import React from "react";
import { Composition, Folder } from "remotion";
import { YapitTrailer, TRAILER_DURATION } from "./YapitTrailer";
import { EndCard } from "./scenes/EndCard";
import { CardFanScene } from "./scenes/CardFanScene";
import { DarkModeScene } from "./scenes/DarkModeScene";
import { VoiceCycleA, totalVoiceCycleFrames } from "./scenes/VoiceCycleA";
import { FPS, WIDTH, HEIGHT } from "./config";

const VOICE_CYCLE_FRAMES = totalVoiceCycleFrames(FPS);

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* Full trailer */}
      <Composition
        id="YapitTrailer"
        component={YapitTrailer}
        durationInFrames={TRAILER_DURATION}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
      />

      {/* Individual scenes for fast iteration */}
      <Folder name="Scenes">
        <Composition
          id="CardFanScene"
          component={CardFanScene}
          durationInFrames={Math.round(3.5 * FPS)}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
        <Composition
          id="DarkModeScene"
          component={DarkModeScene}
          durationInFrames={Math.round(5 * FPS)}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
        <Composition
          id="VoiceCycleA"
          component={VoiceCycleA}
          durationInFrames={VOICE_CYCLE_FRAMES}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
        <Composition
          id="VoiceCycleA-Light"
          component={() => <VoiceCycleA theme="light" />}
          durationInFrames={VOICE_CYCLE_FRAMES}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
        <Composition
          id="EndCard"
          component={EndCard}
          durationInFrames={Math.round(4 * FPS)}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
        <Composition
          id="EndCard-Light"
          component={() => <EndCard theme="light" />}
          durationInFrames={Math.round(4 * FPS)}
          fps={FPS}
          width={WIDTH}
          height={HEIGHT}
        />
      </Folder>
    </>
  );
};
