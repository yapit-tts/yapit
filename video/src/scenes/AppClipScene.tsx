import React from "react";
import meta from "../../public/clips/meta.json";
import { ClipScene } from "./ClipScene";
import type { ClipAudioBlock } from "./ClipScene";
import { BRAND } from "../config";

/**
 * The "money shot": real app playback with highlighting and TTS audio.
 * Wraps ClipScene with the current capture metadata.
 *
 * Trim point uses the capture markers — skip past home page and input,
 * start at the document view with playback.
 */

const audioBlocks: ClipAudioBlock[] = meta.audio.map((block) => ({
  idx: block.idx,
  file: `clips/audio/block-${String(block.idx).padStart(3, "0")}.mp3`,
  durationS: block.duration_s,
}));

const markers = (meta as Record<string, unknown>).markers as
  | Record<string, number>
  | undefined;

// Trim to just after document loads — shows the document view, not the input flow
const TRIM_BEFORE_S = markers?.document_loaded ?? 2.2;

const isLight = (meta as Record<string, unknown>).light_mode === true;

export const AppClipScene: React.FC = () => {
  return (
    <ClipScene
      videoSrc="clips/playback.webm"
      audioBlocks={audioBlocks}
      trimBeforeS={TRIM_BEFORE_S}
      muteAudio
      background={isLight ? BRAND.cream : "#1c1a17"}
    />
  );
};
