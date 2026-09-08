/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { useTranslation } from "@plane/i18n";
import type { TIssueComment } from "@plane/types";
import { getFileURL } from "@plane/utils";

type TVoiceCommentDisplayProps = {
  comment: TIssueComment;
  workspaceSlug?: string;
  projectId?: string;
};

export const VoiceCommentDisplay = (props: TVoiceCommentDisplayProps) => {
  const { comment, workspaceSlug: propWorkspaceSlug, projectId: propProjectId } = props;
  const { t } = useTranslation();

  const activeAssetId = comment.voice_asset_id;
  const isExpired = Boolean(comment.voice_expired) || !activeAssetId;

  // The audio object is streamed through the existing project-asset download
  // endpoint with disposition=inline, which performs the permission check and
  // redirects to a fresh temporary presigned URL. No presigned URL is ever persisted.
  const workspaceSlug = propWorkspaceSlug || comment.workspace_detail?.slug;
  const projectId = propProjectId || comment.project;
  const audioSrc =
    !isExpired && workspaceSlug && projectId
      ? getFileURL(
          `/api/assets/v2/workspaces/${workspaceSlug}/projects/${projectId}/download/${activeAssetId}/?disposition=inline`
        )
      : null;

  if (isExpired) {
    return (
      <div className="flex flex-col gap-0.5 rounded-sm border border-subtle bg-surface-2 px-3 py-2 text-caption-sm-regular text-tertiary">
        <span className="font-medium">{t("issue.comments.voice.expired")}</span>
        <span>{t("issue.comments.voice.expired_description")}</span>
      </div>
    );
  }

  return <audio controls src={audioSrc ?? undefined} className="h-8 w-64" />;
};
