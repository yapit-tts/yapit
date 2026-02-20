import React from "react";
import { useCurrentFrame, interpolate, spring, useVideoConfig } from "remotion";
import { BRAND, THEME_CLASS } from "../config";
import { fontFamily } from "../fonts";

export const EndCard: React.FC<{ theme?: keyof typeof THEME_CLASS }> = ({
  theme = "charcoal",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const logoScale = spring({
    frame,
    fps,
    config: { damping: 25, stiffness: 80 },
  });
  const logoOpacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const taglineOpacity = interpolate(frame, [20, 40], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const taglineY = spring({
    frame: frame - 20,
    fps,
    config: { damping: 30, stiffness: 100 },
  });

  const urlOpacity = interpolate(frame, [45, 60], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const lineWidth = interpolate(frame, [10, 35], [0, 80], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const fadeOut = interpolate(frame, [100, 120], [1, 0], {
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
        opacity: fadeOut,
        fontFamily,
      }}
    >
      <div
        style={{
          fontSize: 72,
          fontWeight: 700,
          color: "var(--foreground)",
          letterSpacing: "-0.04em",
          opacity: logoOpacity,
          transform: `scale(${0.9 + logoScale * 0.1})`,
        }}
      >
        yapit
      </div>

      <div
        style={{
          width: lineWidth,
          height: 3,
          background: BRAND.green,
          borderRadius: 2,
          marginTop: 16,
          marginBottom: 20,
        }}
      />

      <div
        style={{
          fontSize: 22,
          fontWeight: 400,
          color: "var(--muted-foreground)",
          opacity: taglineOpacity,
          transform: `translateY(${(1 - taglineY) * 20}px)`,
          letterSpacing: "-0.01em",
        }}
      >
        Open source text-to-speech for documents
      </div>

      <div
        style={{
          fontSize: 15,
          color: "var(--muted-foreground)",
          opacity: urlOpacity,
          marginTop: 28,
          fontWeight: 400,
          letterSpacing: "0.01em",
        }}
      >
        65 voices · 15 languages · and counting
      </div>

      <div
        style={{
          fontSize: 16,
          color: "var(--primary)",
          opacity: urlOpacity,
          marginTop: 16,
          fontWeight: 500,
        }}
      >
        yapit.md
      </div>
    </div>
  );
};
