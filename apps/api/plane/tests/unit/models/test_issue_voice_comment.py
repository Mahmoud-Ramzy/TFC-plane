# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta

import pytest

from django.utils import timezone

from plane.db.models import FileAsset, Issue, IssueComment, Project, State, Workspace


@pytest.fixture
def workspace(create_user):
    """Create a test workspace"""
    return Workspace.objects.create(
        name="Voice Test Workspace",
        slug=f"voice-ws-{str(create_user.id)[:8]}",
        owner=create_user,
    )


@pytest.fixture
def project(workspace, create_user):
    """Create a test project"""
    return Project.objects.create(
        name="Voice Test Project",
        identifier=f"VC{str(create_user.id)[:4]}",
        workspace=workspace,
        created_by=create_user,
    )


@pytest.fixture
def state_backlog(project):
    return State.objects.create(name="Todo", project=project, group="backlog", default=True)


@pytest.fixture
def state_done(project):
    return State.objects.create(name="Done", project=project, group="completed")


@pytest.fixture
def issue(workspace, project, state_backlog, create_user):
    return Issue.objects.create(
        name="Voice Issue",
        workspace=workspace,
        project=project,
        state=state_backlog,
        created_by=create_user,
    )


@pytest.fixture
def voice_comment(workspace, project, issue, create_user):
    """Create a voice comment with an uploaded audio asset"""
    comment = IssueComment.objects.create(
        comment_html="<p></p>",
        comment_type="VOICE",
        issue=issue,
        project=project,
        workspace=workspace,
        actor=create_user,
        created_by=create_user,
    )
    FileAsset.objects.create(
        comment=comment,
        issue=issue,
        project=project,
        workspace=workspace,
        asset=f"{workspace.id}/voice-recording.webm",
        entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
        attributes={"name": "voice-recording.webm", "type": "audio/webm", "size": 1024},
        size=1024,
        is_uploaded=True,
    )
    return comment


def complete_issue(issue, state_done):
    """Move the issue into the completed state through a normal save."""
    issue.state = state_done
    issue.save()
    issue.refresh_from_db()
    return issue


@pytest.mark.unit
class TestVoiceCommentExpiryOnCompletion:
    """Retention stamping when a work item becomes completed"""

    @pytest.mark.django_db
    def test_completion_stamps_voice_expiry(self, voice_comment, issue, state_done):
        """Voice comments with existing audio get completed_at + retention"""
        complete_issue(issue, state_done)
        voice_comment.refresh_from_db()
        assert issue.completed_at is not None
        assert voice_comment.voice_expires_at is not None
        assert voice_comment.voice_expires_at - issue.completed_at == timedelta(days=3)

    @pytest.mark.django_db
    def test_completion_does_not_stamp_voice_comment_without_audio(
        self, workspace, project, issue, create_user, state_done
    ):
        """A voice comment whose audio was never uploaded is not stamped"""
        bare_comment = IssueComment.objects.create(
            comment_html="<p></p>",
            comment_type="VOICE",
            issue=issue,
            project=project,
            workspace=workspace,
            actor=create_user,
        )
        complete_issue(issue, state_done)
        bare_comment.refresh_from_db()
        assert bare_comment.voice_expires_at is None

    @pytest.mark.django_db
    def test_text_comments_are_never_stamped(self, workspace, project, issue, create_user, state_done):
        """Text comments never receive a voice expiry"""
        IssueComment.objects.create(
            comment_html="<p>hello</p>",
            issue=issue,
            project=project,
            workspace=workspace,
            actor=create_user,
        )
        complete_issue(issue, state_done)
        text_comment = IssueComment.objects.get(issue=issue, comment_type="TEXT")
        assert text_comment.voice_expires_at is None

    @pytest.mark.django_db
    def test_unrelated_edit_does_not_change_expiry(self, voice_comment, issue, state_done):
        """Edits after completion must not extend or reset the expiry"""
        complete_issue(issue, state_done)
        voice_comment.refresh_from_db()
        original_expiry = voice_comment.voice_expires_at

        issue.name = "Renamed after completion"
        issue.save()

        voice_comment.refresh_from_db()
        assert voice_comment.voice_expires_at == original_expiry

    @pytest.mark.django_db
    def test_reopen_keeps_audio_and_expiry(self, voice_comment, issue, state_done, state_backlog):
        """Reopening before expiry keeps the recording and its existing expiry"""
        complete_issue(issue, state_done)
        voice_comment.refresh_from_db()
        original_expiry = voice_comment.voice_expires_at

        issue.state = state_backlog
        issue.save()
        issue.refresh_from_db()

        assert issue.completed_at is None
        voice_comment.refresh_from_db()
        assert voice_comment.voice_expires_at == original_expiry

    @pytest.mark.django_db
    def test_recompletion_starts_new_window(self, voice_comment, issue, state_done, state_backlog):
        """Re-completing starts a fresh retention window from the new completion"""
        complete_issue(issue, state_done)
        voice_comment.refresh_from_db()
        first_expiry = voice_comment.voice_expires_at

        issue.state = state_backlog
        issue.save()
        issue.state = state_done
        issue.save()
        issue.refresh_from_db()

        voice_comment.refresh_from_db()
        assert voice_comment.voice_expires_at > first_expiry
        assert voice_comment.voice_expires_at - issue.completed_at == timedelta(days=3)

    @pytest.mark.django_db
    def test_recompletion_skips_expired_recordings(
        self, workspace, project, issue, create_user, state_done, state_backlog
    ):
        """Recordings whose audio was already deleted stay expired on re-completion"""
        expired_comment = IssueComment.objects.create(
            comment_html="<p></p>",
            comment_type="VOICE",
            issue=issue,
            project=project,
            workspace=workspace,
            actor=create_user,
        )
        deleted_asset = FileAsset.objects.create(
            comment=expired_comment,
            issue=issue,
            project=project,
            workspace=workspace,
            asset=f"{workspace.id}/deleted-recording.webm",
            entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
            is_uploaded=True,
            is_deleted=True,
            deleted_at=timezone.now(),
        )

        complete_issue(issue, state_done)
        issue.state = state_backlog
        issue.save()
        issue.state = state_done
        issue.save()

        expired_comment.refresh_from_db()
        deleted_asset.refresh_from_db()
        assert expired_comment.voice_expires_at is None
        assert deleted_asset.is_deleted is True

    @pytest.mark.django_db
    def test_voice_comment_created_after_completion(self, issue, state_done, create_user, workspace, project):
        """A voice comment added to an already-completed issue is stamped at creation"""
        complete_issue(issue, state_done)
        late_comment = IssueComment.objects.create(
            comment_html="<p></p>",
            comment_type="VOICE",
            issue=issue,
            project=project,
            workspace=workspace,
            actor=create_user,
        )
        assert late_comment.voice_expires_at is not None
        assert late_comment.voice_expires_at - issue.completed_at == timedelta(days=3)

    @pytest.mark.django_db
    def test_voice_comment_on_long_completed_issue_gets_no_grace_window(
        self, issue, state_done, create_user, workspace, project
    ):
        """No artificial grace window: expiry is anchored to completion, so a
        comment created after the window has passed is born expired"""
        complete_issue(issue, state_done)
        Issue.objects.filter(pk=issue.pk).update(completed_at=timezone.now() - timedelta(days=30))
        issue.refresh_from_db()

        late_comment = IssueComment.objects.create(
            comment_html="<p></p>",
            comment_type="VOICE",
            issue=issue,
            project=project,
            workspace=workspace,
            actor=create_user,
        )
        assert late_comment.voice_expires_at == issue.completed_at + timedelta(days=3)
        assert late_comment.voice_expired is True
