/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useCallback, useEffect, useRef, useState } from "react";
// plane imports
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/ui";
import type { TCommentsOperations } from "@plane/types";
import { EFileAssetType } from "@plane/types";
// services
import { FileService } from "@/services/file.service";

type TVoiceCommentCreateProps = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  activityOperations: Pick<TCommentsOperations, "createComment" | "removeComment">;
  onSubmitCallback?: (commentId: string) => void;
};

// services
const fileService = new FileService();

const MAX_RECORDING_SECONDS = 300; // 5 minutes
const MAX_RECORDING_BYTES = 5 * 1024 * 1024; // 5MB (matches global FILE_SIZE_LIMIT)

// Preferred first: WebM/Opus in Chrome/Firefox, MP4 in Safari, OGG as fallback.
// Every candidate is verified with MediaRecorder.isTypeSupported so we never
// ask the browser for a container it cannot produce.
const PREFERRED_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];

const EXTENSION_BY_MIME: Record<string, string> = {
  "audio/webm": ".webm",
  "audio/mp4": ".mp4",
  "audio/ogg": ".ogg",
};

const pickSupportedMimeType = (): string | null => {
  if (typeof MediaRecorder === "undefined") return null;
  if (typeof MediaRecorder.isTypeSupported !== "function") return ""; // let the browser decide
  return PREFERRED_MIME_TYPES.find((mimeType) => MediaRecorder.isTypeSupported(mimeType)) ?? null;
};

const getBaseMimeType = (mimeType: string) => mimeType.split(";")[0];

const formatElapsed = (seconds: number) => {
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
};

type TVoiceRecorderState = "idle" | "requesting" | "recording" | "preview" | "uploading";

export const VoiceCommentCreate = (props: TVoiceCommentCreateProps) => {
  const { workspaceSlug, projectId, issueId, activityOperations, onSubmitCallback } = props;
  const { t } = useTranslation();
  // states
  const [recorderState, setRecorderState] = useState<TVoiceRecorderState>("idle");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // refs
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedAtRef = useRef(0);
  const isMountedRef = useRef(true);

  const clearRecordingTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const stopMediaTracks = () => {
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
  };

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      clearRecordingTimer();
      stopMediaTracks();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl]
  );

  const resetRecorder = useCallback(() => {
    clearRecordingTimer();
    stopMediaTracks();
    setPreviewUrl((url) => {
      if (url) URL.revokeObjectURL(url);
      return null;
    });
    setAudioBlob(null);
    setElapsedSeconds(0);
    setErrorMessage(null);
  }, []);

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
      try {
        mediaRecorderRef.current.stop();
      } catch {
        // ignore races where the recorder already stopped
      }
    }
  };

  const startRecording = async () => {
    if (recorderState === "requesting" || recorderState === "recording") return;
    setErrorMessage(null);
    setRecorderState("requesting");

    try {
      if (!navigator?.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
        setErrorMessage(t("issue.comments.voice.support_error"));
        setRecorderState("idle");
        return;
      }

      const mimeType = pickSupportedMimeType();
      if (mimeType === null) {
        setErrorMessage(t("issue.comments.voice.support_error"));
        setRecorderState("idle");
        return;
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!isMountedRef.current) {
        // the component unmounted while waiting for permission
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      mediaStreamRef.current = stream;

      const recorderOptions: MediaRecorderOptions = mimeType ? { mimeType } : {};
      let mediaRecorder: MediaRecorder;
      try {
        mediaRecorder = new MediaRecorder(stream, recorderOptions);
      } catch {
        // some browsers reject explicit MIME options — retry with defaults
        mediaRecorder = new MediaRecorder(stream);
      }
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      mediaRecorder.onerror = () => {
        clearRecordingTimer();
        stopMediaTracks();
        resetRecorder();
        setRecorderState("idle");
        setErrorMessage(t("issue.comments.voice.error"));
      };

      mediaRecorder.onstop = () => {
        clearRecordingTimer();
        const type = getBaseMimeType(mediaRecorder.mimeType || mimeType || "audio/webm");
        const blob = new Blob(audioChunksRef.current, { type });
        stopMediaTracks();
        if (!isMountedRef.current) return;
        setAudioBlob(blob);
        setPreviewUrl(URL.createObjectURL(blob));
        setRecorderState("preview");
      };

      mediaRecorder.start(1000);
      startedAtRef.current = Date.now();
      setElapsedSeconds(0);
      setRecorderState("recording");

      timerRef.current = setInterval(() => {
        const seconds = Math.floor((Date.now() - startedAtRef.current) / 1000);
        setElapsedSeconds(seconds);
        if (seconds >= MAX_RECORDING_SECONDS) stopRecording();
      }, 500);
    } catch (error) {
      stopMediaTracks();
      setRecorderState("idle");
      const name = (error as DOMException)?.name;
      if (name === "NotAllowedError" || name === "SecurityError") {
        setErrorMessage(t("issue.comments.voice.permission_denied"));
      } else if (name === "NotFoundError" || name === "NotReadableError" || name === "OverconstrainedError") {
        setErrorMessage(t("issue.comments.voice.mic_unavailable"));
      } else {
        setErrorMessage(t("issue.comments.voice.error"));
      }
    }
  };

  const cancelRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
      try {
        mediaRecorderRef.current.stop();
      } catch {
        // ignore
      }
    }
    resetRecorder();
    setRecorderState("idle");
  };

  const submitVoiceComment = async () => {
    const blob = audioBlob;
    if (!blob || recorderState !== "preview") return;

    if (blob.size > MAX_RECORDING_BYTES) {
      setErrorMessage(t("issue.comments.voice.size_error"));
      return;
    }

    setRecorderState("uploading");
    setErrorMessage(null);

    try {
      // 1. Create and upload the audio asset (presigned POST + confirm)
      const baseType = getBaseMimeType(blob.type || "audio/webm") || "audio/webm";
      const extension = EXTENSION_BY_MIME[baseType] ?? ".webm";
      const file = new File([blob], `voice-comment-${Date.now()}${extension}`, { type: baseType });
      const assetResponse = await fileService.uploadVoiceCommentAsset(
        workspaceSlug,
        projectId,
        {
          entity_type: EFileAssetType.COMMENT_AUDIO,
          entity_identifier: issueId,
        },
        file
      );

      if (!assetResponse?.asset_id) throw new Error("Voice comment asset upload failed");

      // 2. Create the IssueComment and link the asset via voice_asset_id
      const comment = await activityOperations.createComment({
        comment_type: "VOICE",
        comment_html: "",
        voice_asset_id: assetResponse.asset_id,
      });

      if (!comment?.id) throw new Error("Voice comment creation failed");

      if (onSubmitCallback) onSubmitCallback(comment.id);
      resetRecorder();
      setRecorderState("idle");
    } catch {
      // The uploaded asset becomes an orphan and is removed by the
      // delete_orphan_voice_assets background task after the grace period.
      setErrorMessage(t("issue.comments.voice.error"));
      setRecorderState("preview");
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      {recorderState === "idle" && (
        <Button variant="outline-primary" size="sm" onClick={startRecording}>
          <span aria-hidden className="mr-1 inline-block size-1.5 rounded-full bg-accent-primary" />
          {t("issue.comments.voice.record")}
        </Button>
      )}

      {recorderState === "requesting" && (
        <span className="text-caption-sm-regular text-tertiary">{t("issue.comments.voice.requesting")}</span>
      )}

      {recorderState === "recording" && (
        <>
          <span aria-hidden className="inline-block size-1.5 animate-pulse rounded-full bg-danger-primary" />
          <span className="text-caption-sm-medium text-danger-primary">{t("issue.comments.voice.recording")}</span>
          <span className="text-caption-sm-medium text-tertiary tabular-nums">{formatElapsed(elapsedSeconds)}</span>
          <Button variant="outline-primary" size="sm" onClick={stopRecording}>
            {t("issue.comments.voice.stop")}
          </Button>
          <Button variant="neutral-primary" size="sm" onClick={cancelRecording}>
            {t("issue.comments.voice.cancel")}
          </Button>
        </>
      )}

      {(recorderState === "preview" || recorderState === "uploading") && previewUrl && (
        <>
          <audio controls src={previewUrl} className="h-8 w-64" />
          <span className="text-caption-sm-regular text-tertiary tabular-nums">{formatElapsed(elapsedSeconds)}</span>
          {recorderState === "uploading" ? (
            <span className="text-caption-sm-regular text-tertiary">{t("issue.comments.voice.uploading")}</span>
          ) : (
            <>
              <Button variant="primary" size="sm" onClick={submitVoiceComment}>
                {t("issue.comments.voice.submit")}
              </Button>
              <Button variant="neutral-primary" size="sm" onClick={cancelRecording}>
                {t("issue.comments.voice.cancel")}
              </Button>
            </>
          )}
        </>
      )}

      {errorMessage && <span className="text-caption-sm-regular text-danger-primary">{errorMessage}</span>}
    </div>
  );
};
