# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from django.utils import timezone

from plane.db.models import FileAsset, IssueComment
from plane.bgtasks.voice_comment_task import delete_expired_voice_comments, delete_orphan_voice_assets


@pytest.mark.unit
class TestDeleteExpiredVoiceComments:
    """Idempotent audio-object cleanup for expired voice comments"""

    @pytest.fixture
    def workspace(self, create_user):
        from plane.db.models import Workspace

        return Workspace.objects.create(
            name="Cleanup WS",
            slug=f"vc-clean-{str(create_user.id)[:8]}",
            owner=create_user,
        )

    @pytest.fixture
    def project(self, workspace, create_user):
        from plane.db.models import Project

        return Project.objects.create(
            name="Cleanup Project",
            identifier=f"CL{str(create_user.id)[:4]}",
            workspace=workspace,
            created_by=create_user,
        )

    @pytest.fixture
    def issue(self, workspace, project, create_user):
        from plane.db.models import Issue, State
        state = State.objects.create(name="Done", project=project, group="completed")
        return Issue.objects.create(
            name="Cleanup Issue",
            workspace=workspace,
            project=project,
            state=state,
            created_by=create_user,
        )

    @pytest.fixture
    def expired_comment(self, workspace, project, issue, create_user):
        """Voice comment whose retention window has passed, with uploaded audio"""
        comment = IssueComment.objects.create(
            comment_html="<p></p>",
            comment_type="VOICE",
            issue=issue,
            project=project,
            workspace=workspace,
            actor=create_user,
            voice_expires_at=timezone.now() - timedelta(hours=1),
        )
        FileAsset.objects.create(
            comment=comment,
            project=project,
            workspace=workspace,
            asset=f"{workspace.id}/expired-audio.webm",
            entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
            is_uploaded=True,
        )
        return comment

    @pytest.mark.django_db
    @patch("plane.bgtasks.voice_comment_task.S3Storage")
    def test_deletes_expired_audio_and_marks_asset(self, mock_storage, expired_comment):
        """Storage object is deleted first, then the asset row is soft-deleted"""
        mock_storage.return_value = MagicMock()
        mock_storage.return_value.delete_files.return_value = True

        asset = expired_comment.assets.first()
        keys = [asset.asset.name]

        result = delete_expired_voice_comments()

        mock_storage.return_value.delete_files.assert_called_once_with(keys)
        asset.refresh_from_db()
        assert asset.is_deleted is True
        assert asset.deleted_at is not None
        assert result == 1

    @pytest.mark.django_db
    @patch("plane.bgtasks.voice_comment_task.S3Storage")
    def test_storage_failure_leaves_asset_active(self, mock_storage, expired_comment):
        """If storage deletion fails, the asset stays active for the next run"""
        mock_storage.return_value = MagicMock()
        mock_storage.return_value.delete_files.return_value = False

        result = delete_expired_voice_comments()

        assert result == 0
        asset = expired_comment.assets.first()
        asset.refresh_from_db()
        assert asset.is_deleted is False
        assert asset.deleted_at is None

    @pytest.mark.django_db
    @patch("plane.bgtasks.voice_comment_task.S3Storage")
    def test_non_expired_comments_are_untouched(self, mock_storage, workspace, project, issue, create_user):
        """Comments inside their retention window are never processed"""
        IssueComment.objects.create(
            comment_html="<p></p>",
            comment_type="VOICE",
            issue=issue,
            project=project,
            workspace=workspace,
            actor=create_user,
            voice_expires_at=timezone.now() + timedelta(days=2),
        )

        result = delete_expired_voice_comments()

        assert result == 0
        mock_storage.return_value.delete_files.assert_not_called()

    @pytest.mark.django_db
    @patch("plane.bgtasks.voice_comment_task.S3Storage")
    def test_already_deleted_assets_are_skipped(self, mock_storage, workspace, project, issue, create_user):
        """Soft-deleted assets are never selected again (idempotency)"""
        comment = IssueComment.objects.create(
            comment_html="<p></p>",
            comment_type="VOICE",
            issue=issue,
            project=project,
            workspace=workspace,
            actor=create_user,
            voice_expires_at=timezone.now() - timedelta(hours=2),
        )
        FileAsset.objects.create(
            comment=comment,
            project=project,
            workspace=workspace,
            asset=f"{workspace.id}/already-deleted.webm",
            entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
            is_uploaded=True,
            is_deleted=True,
        )

        result = delete_expired_voice_comments()

        assert result == 0
        mock_storage.return_value.delete_files.assert_not_called()

    @pytest.mark.django_db
    @patch("plane.bgtasks.voice_comment_task.S3Storage")
    def test_missing_object_is_still_marked(self, mock_storage, expired_comment):
        """Deleting a missing object is a no-op; the row is still marked (retry-safe)"""
        mock_storage.return_value = MagicMock()
        mock_storage.return_value.delete_files.return_value = True

        asset = expired_comment.assets.first()
        delete_expired_voice_comments()

        asset.refresh_from_db()
        assert asset.is_deleted is True

@pytest.mark.unit
class TestDeleteOrphanVoiceAssets:
    """Cleanup of uploaded COMMENT_AUDIO assets that were never linked to a comment"""

    @pytest.fixture
    def workspace(self, create_user):
        from plane.db.models import Workspace

        return Workspace.objects.create(
            name="Orphan WS",
            slug=f"orphan-ws-{str(create_user.id)[:8]}",
            owner=create_user,
        )

    @pytest.fixture
    def project(self, workspace, create_user):
        from plane.db.models import Project

        return Project.objects.create(
            name="Orphan Project",
            identifier=f"OR{str(create_user.id)[:4]}",
            workspace=workspace,
            created_by=create_user,
        )

    @pytest.fixture
    def orphan_asset(self, workspace, project):
        """Uploaded, unlinked COMMENT_AUDIO asset older than the grace period"""
        from django.utils import timezone
        from datetime import timedelta

        asset = FileAsset.objects.create(
            project=project,
            workspace=workspace,
            asset=f"{workspace.id}/orphan-audio.webm",
            entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
            is_uploaded=True,
        )
        FileAsset.objects.filter(pk=asset.pk).update(created_at=timezone.now() - timedelta(hours=2))
        return FileAsset.objects.get(pk=asset.pk)

    @pytest.mark.django_db
    @patch("plane.bgtasks.voice_comment_task.S3Storage")
    def test_deletes_old_orphan(self, mock_storage, orphan_asset):
        mock_storage.return_value = MagicMock()
        mock_storage.return_value.delete_files.return_value = True

        result = delete_orphan_voice_assets()

        assert result == 1
        mock_storage.return_value.delete_files.assert_called_once_with([orphan_asset.asset.name])
        orphan_asset.refresh_from_db()
        assert orphan_asset.is_deleted is True
        assert orphan_asset.deleted_at is not None

    @pytest.mark.django_db
    @patch("plane.bgtasks.voice_comment_task.S3Storage")
    def test_recent_orphan_is_not_deleted(self, mock_storage, workspace, project):
        """In-flight uploads (younger than 1 hour) are never touched"""
        FileAsset.objects.create(
            project=project,
            workspace=workspace,
            asset=f"{workspace.id}/fresh-orphan.webm",
            entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
            is_uploaded=True,
        )

        result = delete_orphan_voice_assets()

        assert result == 0
        mock_storage.return_value.delete_files.assert_not_called()

    @pytest.mark.django_db
    @patch("plane.bgtasks.voice_comment_task.S3Storage")
    def test_linked_assets_are_never_deleted(self, mock_storage, workspace, project, create_user):
        """Assets linked to a real comment are never considered orphans"""
        from datetime import timedelta
        from django.utils import timezone
        from plane.db.models import Issue, IssueComment, State

        state = State.objects.create(name="Todo", project=project, group="backlog", default=True)
        issue = Issue.objects.create(name="Linked Issue", workspace=workspace, project=project, state=state)
        comment = IssueComment.objects.create(
            comment_html="<p></p>",
            comment_type="VOICE",
            issue=issue,
            project=project,
            workspace=workspace,
            actor=create_user,
            voice_expires_at=timezone.now() + timedelta(days=3),
        )
        asset = FileAsset.objects.create(
            comment=comment,
            project=project,
            workspace=workspace,
            asset=f"{workspace.id}/linked-audio.webm",
            entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
            is_uploaded=True,
        )
        FileAsset.objects.filter(pk=asset.pk).update(created_at=timezone.now() - timedelta(hours=2))

        result = delete_orphan_voice_assets()

        assert result == 0
        mock_storage.return_value.delete_files.assert_not_called()
        asset.refresh_from_db()
        assert asset.is_deleted is False

    @pytest.mark.django_db
    @patch("plane.bgtasks.voice_comment_task.S3Storage")
    def test_storage_failure_leaves_orphan_active(self, mock_storage, orphan_asset):
        """Storage deletion failure does NOT soft-delete the asset (retry-safe)"""
        mock_storage.return_value = MagicMock()
        mock_storage.return_value.delete_files.return_value = False

        result = delete_orphan_voice_assets()

        assert result == 0
        orphan_asset.refresh_from_db()
        assert orphan_asset.is_deleted is False
        assert orphan_asset.deleted_at is None
