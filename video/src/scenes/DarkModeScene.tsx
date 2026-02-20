import React from "react";
import { Img, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

const IMAGES = [
  "clips/darkmode-1.png",
  "clips/darkmode-2.png",
  "clips/darkmode-3.png",
];

export const DarkModeScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // Divide scene evenly across images, snap between them
  const framesPerImage = Math.floor(durationInFrames / IMAGES.length);
  const activeIdx = Math.min(
    Math.floor(frame / framesPerImage),
    IMAGES.length - 1,
  );

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <Img
        src={staticFile(IMAGES[activeIdx])}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    </div>
  );
};
