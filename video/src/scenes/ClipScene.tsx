import React from "react";
import { Audio, Video } from "@remotion/media";
import { Sequence, staticFile, useVideoConfig } from "remotion";

/**
 * Generic scene that plays a captured WebM clip with optional sequenced audio.
 * Used as the building block for all scenes sourced from Playwright captures.
 */

export interface ClipAudioBlock {
  idx: number;
  file: string; // e.g. "clips/audio/block-000.mp3"
  durationS: number;
}

interface ClipSceneProps {
  videoSrc: string; // staticFile path, e.g. "clips/playback.webm"
  audioBlocks?: ClipAudioBlock[];
  trimBeforeS?: number; // seconds to skip at start of video
  playbackRate?: number;
  muteVideo?: boolean;
  muteAudio?: boolean;
  background?: string;
}

export const ClipScene: React.FC<ClipSceneProps> = ({
  videoSrc,
  audioBlocks = [],
  trimBeforeS = 0,
  playbackRate = 1,
  muteVideo = true,
  muteAudio = false,
  background = "#1c1a17",
}) => {
  const { fps } = useVideoConfig();

  const trimBefore = Math.round(trimBeforeS * fps);
  let audioOffset = 0;

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background,
        position: "relative",
      }}
    >
      <Video
        src={staticFile(videoSrc)}
        style={{ width: "100%", height: "100%" }}
        trimBefore={trimBefore || undefined}
        playbackRate={playbackRate}
        muted={muteVideo}
      />

      {!muteAudio &&
        audioBlocks.map((block) => {
          const from = audioOffset;
          audioOffset += Math.round(block.durationS * fps);
          return (
            <Sequence key={block.idx} from={from} premountFor={fps}>
              <Audio src={staticFile(block.file)} />
            </Sequence>
          );
        })}
    </div>
  );
};
