import React from "react";
import { useCurrentFrame, interpolate, spring, useVideoConfig } from "remotion";
import { BRAND, THEME_CLASS } from "../config";
import { fontFamily } from "../fonts";

export const HookScene: React.FC<{ theme?: keyof typeof THEME_CLASS }> = ({
  theme = "charcoal",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const line1Opacity = interpolate(frame, [8, 28], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const line1Y =
    spring({ frame: frame - 8, fps, config: { damping: 30, stiffness: 120 } }) *
      40 -
    40;

  const line2Opacity = interpolate(frame, [30, 50], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const line2Y =
    spring({ frame: frame - 30, fps, config: { damping: 30, stiffness: 120 } }) *
      40 -
    40;

  const lineWidth = interpolate(frame, [55, 80], [0, 120], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const sceneOpacity = interpolate(frame, [75, 90], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

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
        opacity: sceneOpacity,
        fontFamily,
      }}
    >
      <div
        style={{
          opacity: line1Opacity,
          transform: `translateY(${line1Y}px)`,
          fontSize: 54,
          fontWeight: 300,
          color: "var(--muted-foreground)",
          letterSpacing: "-0.025em",
        }}
      >
        What if your papers
      </div>
      <div
        style={{
          opacity: line2Opacity,
          transform: `translateY(${line2Y}px)`,
          fontSize: 54,
          fontWeight: 600,
          color: "var(--foreground)",
          letterSpacing: "-0.025em",
          marginTop: 4,
        }}
      >
        could read themselves?
      </div>

      <div
        style={{
          width: lineWidth,
          height: 3,
          background: BRAND.green,
          borderRadius: 2,
          marginTop: 28,
          opacity: line2Opacity,
        }}
      />
    </div>
  );
};
