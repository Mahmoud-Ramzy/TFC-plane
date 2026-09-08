# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import logging

from datetime import timedelta

# Django imports
from django.utils import timezone

# Third party imports
from celery import shared_task

# Module imports
from plane.db.models import FileAsset, IssueComment
from plane.settings.storage import S3Storage
from plane.utils.exception_logger import log_exception

logger = logging.getLogger("plane.worker")
BATCH_SIZE = 500
MAX_BATCHES = 20


@shared_task
def delete_expired_voice_comments():
    """Delete audio objects of expired voice comments.

    Only the audio binary is removed — the IssueComment row and its metadata
    remain in PostgreSQL so the thread history is preserved. The FileAsset row
    is soft-deleted (is_deleted=True) only AFTER a successful storage deletion,
    which makes retries safe and idempotent: already-processed assets are never
    picked up again and deleting a missing object is a no-op in S3.
    """
    now = timezone.now()
    storage = S3Storage()
    deleted_assets = 0
    processed_comment_ids: list = []

    try:
        for _ in range(MAX_BATCHES):
            comment_ids = list(
                IssueComment.objects.filter(
                    comment_type="VOICE",
                    voice_expires_at__lte=now,
                    assets__entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
                    assets__is_deleted=False,
                )
                .exclude(id__in=processed_comment_ids)
                .distinct()
                .values_list("id", flat=True)[:BATCH_SIZE]
            )
            if not comment_ids:
                break
            processed_comment_ids.extend(comment_ids)

            assets = list(
                FileAsset.objects.filter(
                    comment_id__in=comment_ids,
                    entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
                    is_deleted=False,
                )
            )
            if not assets:
                continue

            object_keys = [asset.asset.name for asset in assets]
            if storage.delete_files(object_keys):
                deleted_at = timezone.now()
                for asset in assets:
                    asset.is_deleted = True
                    asset.deleted_at = deleted_at
                FileAsset.objects.bulk_update(assets, ["is_deleted", "deleted_at"], batch_size=100)
                deleted_assets += len(assets)

        logger.info(f"Deleted {deleted_assets} expired voice comment audio objects")
        return deleted_assets
    except Exception as e:
        log_exception(e)
        return deleted_assets


@shared_task
def delete_orphan_voice_assets():
    """Delete unlinked uploaded COMMENT_AUDIO assets.

    Voice comments create the audio asset BEFORE the IssueComment row, so an
    uploaded COMMENT_AUDIO asset can legitimately exist with comment_id=NULL
    for a short time. If the comment creation then fails, the binary would
    remain in storage forever. This task removes such orphans, but only after
    a grace period (1 hour) so in-flight recordings are never touched.

    Storage object is deleted FIRST; the row is soft-deleted only AFTER a
    successful storage deletion, which makes retries safe and idempotent.
    """
    now = timezone.now()
    cutoff = now - timedelta(hours=1)
    storage = S3Storage()
    deleted_assets = 0

    try:
        for _ in range(MAX_BATCHES):
            assets = list(
                FileAsset.objects.filter(
                    entity_type=FileAsset.EntityTypeContext.COMMENT_AUDIO,
                    comment_id__isnull=True,
                    is_uploaded=True,
                    is_deleted=False,
                    created_at__lte=cutoff,
                )[:BATCH_SIZE]
            )
            if not assets:
                break

            object_keys = [asset.asset.name for asset in assets]
            if storage.delete_files(object_keys):
                deleted_at = timezone.now()
                for asset in assets:
                    asset.is_deleted = True
                    asset.deleted_at = deleted_at
                FileAsset.objects.bulk_update(assets, ["is_deleted", "deleted_at"], batch_size=100)
                deleted_assets += len(assets)

        logger.info(f"Deleted {deleted_assets} orphan voice comment audio objects")
        return deleted_assets
    except Exception as e:
        log_exception(e)
        return deleted_assets
