import React from "react";
import {
  Audio,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
} from "remotion";
import { THEME_CLASS, type ThemeName } from "../config";
import { fontFamily } from "../fonts";
import voiceManifest from "../../public/clips/showcase/manifest.json";

/**
 * Voice cycling scene — audio-driven.
 * Timing is computed from the voice manifest (durations from actual audio files).
 * Re-generate clips: cd video && make clips
 */

const LANG_LABELS: Record<string, string> = {
  en: "English",
  fr: "Français",
  ja: "日本語",
  es: "Español",
  it: "Italiano",
};

// English subtitles for non-English lines, keyed by voice_id
const SUBTITLES: Record<string, string> = {
  Diego: "In more than fifteen languages.",
  Asuka: "Any article, you can listen to it.",
  Alain: "Voices that sound truly natural.",
  Gianni: "Any document, read aloud.",
};

// Frames of visual lead-in before audio, and gap after
const LEAD_IN = 6;
const GAP_AFTER = 6;
// Spring config for enter/exit
const SPRING_CFG = { damping: 24, stiffness: 120 };

interface VoiceTiming {
  voiceId: string;
  text: string;
  language: string;
  file: string;
  startFrame: number; // visual enters
  audioStart: number; // audio begins
  audioFrames: number;
  endFrame: number; // visual fully exits
}

export function computeVoiceTimings(fps: number): VoiceTiming[] {
  let offset = 0;
  return voiceManifest.map((entry) => {
    const audioFrames = Math.ceil(entry.duration_s * fps);
    const startFrame = offset;
    const audioStart = offset + LEAD_IN;
    const endFrame = audioStart + audioFrames + GAP_AFTER;
    offset = endFrame;
    return {
      voiceId: entry.voice_id,
      text: entry.text,
      language: entry.language,
      file: entry.file,
      startFrame,
      audioStart,
      audioFrames,
      endFrame,
    };
  });
}

export function totalVoiceCycleFrames(fps: number): number {
  const timings = computeVoiceTimings(fps);
  return timings[timings.length - 1].endFrame;
}

export const VoiceCycleA: React.FC<{ theme?: ThemeName }> = ({
  theme = "charcoal",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const voices = computeVoiceTimings(fps);

  return (
    <div
      className={THEME_CLASS[theme]}
      style={{
        width: "100%",
        height: "100%",
        background: "var(--background)",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        fontFamily,
        overflow: "hidden",
      }}
    >
      {/* Audio layers */}
      {voices.map((v, i) => (
        <Sequence key={`audio-${i}`} from={v.audioStart} premountFor={fps}>
          <Audio src={staticFile(`clips/showcase/${v.file}`)} />
        </Sequence>
      ))}

      {/* Visual labels */}
      {voices.map((v, i) => {
        const localFrame = frame - v.startFrame;
        const totalFrames = v.endFrame - v.startFrame;

        if (localFrame < 0 || localFrame >= totalFrames) return null;

        const enterDur = LEAD_IN + 4;
        const exitStart = totalFrames - GAP_AFTER - 2;

        let opacity: number;
        let y: number;

        if (localFrame < enterDur) {
          const p = spring({
            frame: localFrame,
            fps,
            config: SPRING_CFG,
          });
          opacity = p;
          y = interpolate(p, [0, 1], [50, 0]);
        } else if (localFrame < exitStart) {
          opacity = 1;
          y = 0;
        } else {
          const exitFrame = localFrame - exitStart;
          const p = spring({
            frame: exitFrame,
            fps,
            config: SPRING_CFG,
          });
          opacity = 1 - p;
          y = interpolate(p, [0, 1], [0, -50]);
        }

        if (opacity < 0.01) return null;

        return (
          <div
            key={`visual-${i}`}
            style={{
              position: "absolute",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              transform: `translateY(${y}px)`,
              opacity,
            }}
          >
            <div
              style={{
                fontSize: 80,
                fontWeight: 600,
                color: "var(--foreground)",
                letterSpacing: "-0.03em",
              }}
            >
              {v.voiceId}
            </div>
            <div
              style={{
                fontSize: 28,
                fontWeight: 300,
                color: "var(--muted-foreground)",
                marginTop: 16,
                maxWidth: 800,
                textAlign: "center",
                fontStyle: "italic",
              }}
            >
              &ldquo;{v.text}&rdquo;
            </div>
            {SUBTITLES[v.voiceId] && v.language !== "en" && (
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 300,
                  color: "var(--muted-foreground)",
                  marginTop: 8,
                  opacity: 0.6,
                }}
              >
                {SUBTITLES[v.voiceId]}
              </div>
            )}
            <div
              style={{
                fontSize: 16,
                fontWeight: 500,
                color: "var(--primary)",
                marginTop: 12,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              {LANG_LABELS[v.language] ?? v.language}
            </div>
          </div>
        );
      })}
    </div>
  );
};
