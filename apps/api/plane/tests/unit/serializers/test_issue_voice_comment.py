# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.app.serializers import IssueCommentSerializer
from plane.db.models import FileAsset, IssueComment


@pytest.mark.unit
class TestVoiceCommentSerializer:
    """Voice comment creation and derived playback fields"""

    @pytest.fixture
    def workspace(self, create_user):
        from plane.db.models import Workspace

        return Workspace.objects.create(
            name="Serializer WS",
            slug=f"vc-ser-{str(create_user.id)[:8]}",
            owner=create_user,
        )

    @pytest.fixture
    def project(self, workspace, create_user):
        from plane.db.models import Project

        return Project.objects.create(
            name="Serializer Project",
            identifier=f"SV{str(create_user.id)[:4]}",
            workspace=workspace,
            created_by=create_user,
        )

    @pytest.fixture
    def issue(self, workspace, project, create_user):
        from plane.db.models import Issue

        return Issue.objects.create(
            name="Serializer Issue",
            workspace=workspace,
            project=project,
            created_by=create_user,
        )

    @pytest.mark.django_db
    def test_voice_comment_accepts_empty_html(self, workspace, project, issue, create_user):
        """A VOICE comment is valid with empty HTML content"""
        serializer = IssueCommentSerializer(
            data={"comment_html": "", "comment_type": "VOICE"},
        )
        assert serializer.is_valid(), serializer.errors
        comment = serializer.save(project_id=project.id, issue_id=issue.id, actor=create_user)
        comment.refresh_from_db()
        assert comment.comment_type == "VOICE"
        assert comment.voice_asset_id is None
        assert comment.voice_expired is True
        data = IssueCommentSerializer(comment).data
        assert data["voice_asset_id"] is None
        assert data["voice_expired"] is True

    @pytest.mark.django_db
    def test_voice_comment_creation_links_voice_asset(self, workspace, project, issue, create_user):
        """Passing voice_asset_id at creation associates the FileAsset and hydrates the response"""
        asset = FileAsset.objects.create(
            issue=issue,
            project=project,
            workspace=workspace,
            asset=f"{workspace.id}/initial.webm",
            entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
            is_uploaded=True,
        )
        serializer = IssueCommentSerializer(
            data={"comment_html": "", "comment_type": "VOICE", "voice_asset_id": str(asset.id)},
        )
        assert serializer.is_valid(), serializer.errors
        comment = serializer.save(project_id=project.id, issue_id=issue.id, actor=create_user)
        assert serializer.data["voice_asset_id"] == str(asset.id)
        assert serializer.data["voice_expired"] is False
        asset.refresh_from_db()
        assert asset.comment_id == comment.id

    @pytest.mark.django_db
    def test_voice_asset_fields_with_active_audio(self, workspace, project, issue, create_user):
        """An uploaded, non-deleted audio asset is exposed and not expired"""
        comment = IssueComment.objects.create(
            comment_html="<p></p>",
            comment_type="VOICE",
            project=project,
            issue=issue,
            workspace=workspace,
            actor=create_user,
        )
        asset = FileAsset.objects.create(
            comment=comment,
            project=project,
            workspace=workspace,
            asset=f"{workspace.id}/active.webm",
            entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
            is_uploaded=True,
        )
        data = IssueCommentSerializer(comment).data
        assert data["voice_asset_id"] == str(asset.id)
        assert data["voice_expired"] is False
        assert data["comment_type"] == "VOICE"

    @pytest.mark.django_db
    def test_voice_expired_when_audio_deleted(self, workspace, project, issue, create_user):
        """A deleted audio asset marks the recording as expired"""
        comment = IssueComment.objects.create(
            comment_html="<p></p>",
            comment_type="VOICE",
            project=project,
            issue=issue,
            workspace=workspace,
            actor=create_user,
        )
        FileAsset.objects.create(
            comment=comment,
            project=project,
            workspace=workspace,
            asset=f"{workspace.id}/deleted.webm",
            entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
            is_uploaded=True,
            is_deleted=True,
        )
        data = IssueCommentSerializer(comment).data
        assert data["voice_asset_id"] is None
        assert data["voice_expired"] is True

    @pytest.mark.django_db
    def test_text_comment_has_no_voice_fields(self, workspace, project, issue, create_user):
        """Text comments report empty/expired-neutral voice fields"""
        comment = IssueComment.objects.create(
            comment_html="<p>text</p>",
            project=project,
            issue=issue,
            workspace=workspace,
            actor=create_user,
        )
        data = IssueCommentSerializer(comment).data
        assert data["comment_type"] == "TEXT"
        assert data["voice_asset_id"] is None
        assert data["voice_expired"] is False

    @pytest.mark.django_db
    def test_voice_asset_from_other_issue_is_not_linked(self, workspace, project, create_user):
        """A COMMENT_AUDIO asset anchored to a different issue is never linked"""
        from plane.db.models import Issue, State

        state = State.objects.create(name="Todo", project=project, group="backlog", default=True)
        other_issue = Issue.objects.create(name="Other", workspace=workspace, project=project, state=state)
        issue = Issue.objects.create(name="Mine", workspace=workspace, project=project, state=state)

        asset = FileAsset.objects.create(
            issue=other_issue,
            project=project,
            workspace=workspace,
            asset=f"{workspace.id}/other-issue.webm",
            entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
            is_uploaded=True,
        )
        serializer = IssueCommentSerializer(
            data={"comment_html": "", "comment_type": "VOICE", "voice_asset_id": str(asset.id)},
        )
        assert serializer.is_valid(), serializer.errors
        comment = serializer.save(project_id=project.id, issue_id=issue.id, actor=create_user)
        data = IssueCommentSerializer(comment).data
        assert data["voice_asset_id"] is None
        assert data["voice_expired"] is True
        asset.refresh_from_db()
        assert asset.comment_id is None

    @pytest.mark.django_db
    def test_non_audio_asset_is_not_linked(self, workspace, project, issue, create_user):
        """A non-COMMENT_AUDIO asset can never be attached as a voice comment"""
        asset = FileAsset.objects.create(
            issue=issue,
            project=project,
            workspace=workspace,
            asset=f"{workspace.id}/not-audio.png",
            entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
            is_uploaded=True,
        )
        serializer = IssueCommentSerializer(
            data={"comment_html": "", "comment_type": "VOICE", "voice_asset_id": str(asset.id)},
        )
        assert serializer.is_valid(), serializer.errors
        comment = serializer.save(project_id=project.id, issue_id=issue.id, actor=create_user)
        data = IssueCommentSerializer(comment).data
        assert data["voice_asset_id"] is None
        asset.refresh_from_db()
        assert asset.comment_id is None
