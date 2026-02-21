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
import { VoiceCycleA, totalVoiceCycleFrames } from "./scenes/VoiceCycleA";
import { LanguageWallScene } from "./scenes/LanguageWallScene";
import { EndCard } from "./scenes/EndCard";
import meta from "../public/clips/meta.json";
import narrationManifest from "../public/clips/narration/manifest.json";

import "./styles/app.css";

// Narration manifest indices:
// 0: Craig — "Articles, papers, books — just paste the link."
// 1: Deborah — "Listen to anything, in any voice you want!"
// 2: Blake — "Try it now, on yapit.md!"

const markers = meta.markers;
const isLight = meta.light_mode === true;
const bg = isLight ? BRAND.cream : "#1c1a17";
const narr = narrationManifest;

// Scene durations
const FLOW_DURATION = Math.round((markers.play_clicked + 3) * FPS);
const CARD_FAN_DURATION = Math.round(6 * FPS);
const VOICE_DURATION = totalVoiceCycleFrames(FPS);
const LANG_WALL_DURATION = Math.round((narr[2].duration_s + 1.5) * FPS); // long enough for Blake CTA
const END_DURATION = Math.round(3 * FPS);

export const YapitTrailer: React.FC = () => {
  const { fps } = useVideoConfig();
  const fadeTiming = linearTiming({ durationInFrames: TRANSITION_FRAMES });

  return (
    <>
    {/* Background music — low volume, plays from start */}
    <Audio src={staticFile("clips/music.mp3")} volume={0.05} />

    <TransitionSeries>
      {/* Scene 1: URL paste flow */}
      <TransitionSeries.Sequence durationInFrames={FLOW_DURATION}>
        <ClipScene videoSrc="clips/playback.webm" background={bg} />
        <Sequence from={Math.round(0.3 * fps)} premountFor={fps}>
          <Audio src={staticFile(`clips/narration/${narr[0].file}`)} />
        </Sequence>
      </TransitionSeries.Sequence>

      {/* Hard cut into cards — the spring-in animation IS the transition */}
      <TransitionSeries.Transition
        timing={linearTiming({ durationInFrames: 1 })}
        presentation={none()}
      />

      {/* Scene 2: Card fan (light + dark mode cards) */}
      <TransitionSeries.Sequence durationInFrames={CARD_FAN_DURATION}>
        <CardFanScene />
        <Sequence from={Math.round(0.8 * fps)} premountFor={fps}>
          <Audio src={staticFile(`clips/narration/${narr[1].file}`)} />
        </Sequence>
      </TransitionSeries.Sequence>

      <TransitionSeries.Transition
        timing={fadeTiming}
        presentation={fade()}
      />

      {/* Scene 3: Multilingual voice showcase */}
      <TransitionSeries.Sequence durationInFrames={VOICE_DURATION}>
        <VoiceCycleA theme={isLight ? "light" : "charcoal"} />
      </TransitionSeries.Sequence>

      <TransitionSeries.Transition
        timing={fadeTiming}
        presentation={fade()}
      />

      {/* Scene 4: Language wall + Blake CTA */}
      <TransitionSeries.Sequence durationInFrames={LANG_WALL_DURATION}>
        <LanguageWallScene theme={isLight ? "light" : "charcoal"} />
        <Sequence from={Math.round(0.8 * fps)} premountFor={fps}>
          <Audio src={staticFile(`clips/narration/${narr[2].file}`)} />
        </Sequence>
      </TransitionSeries.Sequence>

      <TransitionSeries.Transition
        timing={fadeTiming}
        presentation={fade()}
      />

      {/* Scene 5: End card */}
      <TransitionSeries.Sequence durationInFrames={END_DURATION}>
        <EndCard theme={isLight ? "light" : "charcoal"} />
      </TransitionSeries.Sequence>
    </TransitionSeries>
    </>
  );
};

export const TRAILER_DURATION =
  FLOW_DURATION +
  CARD_FAN_DURATION +
  VOICE_DURATION +
  LANG_WALL_DURATION +
  END_DURATION -
  3 * TRANSITION_FRAMES - // cards→voice, voice→langwall, langwall→end
  1; // hard cut (flow→cards)
