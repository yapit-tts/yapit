import React from "react";
import {
  Audio,
  Sequence,
  staticFile,
  useVideoConfig,
} from "remotion";
import { linearTiming, TransitionSeries } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { none } from "@remotion/transitions/none";
import { FPS, TRANSITION_FRAMES, BRAND } from "./config";
import { ClipScene } from "./scenes/ClipScene";
import { CardFanScene } from "./scenes/CardFanScene";
import { DarkModeScene } from "./scenes/DarkModeScene";
import { VoiceCycleA, totalVoiceCycleFrames } from "./scenes/VoiceCycleA";
import { EndCard } from "./scenes/EndCard";
import meta from "../public/clips/meta.json";
import narrationManifest from "../public/clips/narration/manifest.json";

import "./styles/app.css";

// Narration manifest indices:
// 0: Craig — "Articles, papers, books — just paste the link."
// 1: Deborah — "Listen to anything, in any voice you want!"
// 2: Hana — "Make it yours."
// 3: Blake — "Try it now, on yapit.md!"

const markers = meta.markers;
const isLight = meta.light_mode === true;
const bg = isLight ? BRAND.cream : "#1c1a17";
const narr = narrationManifest;

// Padding after voice showcase so Heitor's text is visible before end card
const SHOWCASE_PADDING = Math.round(1.5 * FPS);

// Scene durations
const FLOW_DURATION = Math.round((markers.play_clicked + 0.5) * FPS);
const CARD_FAN_DURATION = Math.round(5 * FPS);
const DARK_MODE_DURATION = Math.round(5 * FPS);
const VOICE_DURATION = totalVoiceCycleFrames(FPS) + SHOWCASE_PADDING;
const END_DURATION = Math.round((narr[3].duration_s + 1.5) * FPS);

export const YapitTrailer: React.FC = () => {
  const { fps } = useVideoConfig();
  const fadeTiming = linearTiming({ durationInFrames: TRANSITION_FRAMES });

  return (
    <TransitionSeries>
      {/* Scene 1: URL paste flow */}
      <TransitionSeries.Sequence durationInFrames={FLOW_DURATION}>
        <ClipScene videoSrc="clips/playback.webm" background={bg} />
        <Sequence from={Math.round(0.3 * fps)} premountFor={fps}>
          <Audio src={staticFile(`clips/narration/${narr[0].file}`)} />
        </Sequence>
      </TransitionSeries.Sequence>

      <TransitionSeries.Transition
        timing={fadeTiming}
        presentation={fade()}
      />

      {/* Scene 2: Card fan */}
      <TransitionSeries.Sequence durationInFrames={CARD_FAN_DURATION}>
        <CardFanScene />
        <Sequence from={Math.round(0.3 * fps)} premountFor={fps}>
          <Audio src={staticFile(`clips/narration/${narr[1].file}`)} />
        </Sequence>
      </TransitionSeries.Sequence>

      {/* Hard cut from cards → dark mode */}
      <TransitionSeries.Transition
        timing={linearTiming({ durationInFrames: 1 })}
        presentation={none()}
      />

      {/* Scene 3: Dark mode cycling (screenshots) */}
      <TransitionSeries.Sequence durationInFrames={DARK_MODE_DURATION}>
        <DarkModeScene />
        <Sequence from={Math.round(0.3 * fps)} premountFor={fps}>
          <Audio src={staticFile(`clips/narration/${narr[2].file}`)} />
        </Sequence>
      </TransitionSeries.Sequence>

      <TransitionSeries.Transition
        timing={fadeTiming}
        presentation={fade()}
      />

      {/* Scene 4: Multilingual voice showcase */}
      <TransitionSeries.Sequence durationInFrames={VOICE_DURATION}>
        <VoiceCycleA theme={isLight ? "light" : "charcoal"} />
      </TransitionSeries.Sequence>

      <TransitionSeries.Transition
        timing={fadeTiming}
        presentation={fade()}
      />

      {/* Scene 5: End card */}
      <TransitionSeries.Sequence durationInFrames={END_DURATION}>
        <EndCard theme={isLight ? "light" : "charcoal"} />
        <Sequence from={Math.round(0.5 * fps)} premountFor={fps}>
          <Audio src={staticFile(`clips/narration/${narr[3].file}`)} />
        </Sequence>
      </TransitionSeries.Sequence>
    </TransitionSeries>
  );
};

export const TRAILER_DURATION =
  FLOW_DURATION +
  CARD_FAN_DURATION +
  DARK_MODE_DURATION +
  VOICE_DURATION +
  END_DURATION -
  3 * TRANSITION_FRAMES -
  1; // hard cut
