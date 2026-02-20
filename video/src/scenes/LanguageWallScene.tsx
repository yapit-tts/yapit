import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
} from "remotion";
import { THEME_CLASS, type ThemeName } from "../config";
import { fontFamily } from "../fonts";

const LANGUAGES = [
  "English",
  "Español",
  "Français",
  "Deutsch",
  "Italiano",
  "Português",
  "日本語",
  "中文",
  "한국어",
  "Русский",
  "العربية",
  "हिन्दी",
  "Nederlands",
  "Polski",
  "עברית",
];

export const LanguageWallScene: React.FC<{ theme?: ThemeName }> = ({
  theme = "charcoal",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headerProgress = spring({
    frame,
    fps,
    config: { damping: 25, stiffness: 80 },
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
        fontFamily,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          fontSize: 48,
          fontWeight: 600,
          color: "var(--foreground)",
          letterSpacing: "-0.03em",
          opacity: headerProgress,
          transform: `translateY(${(1 - headerProgress) * 30}px)`,
          marginBottom: 12,
        }}
      >
        120+ voices · 15 languages
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: "14px 20px",
          maxWidth: 900,
          marginTop: 40,
        }}
      >
        {LANGUAGES.map((lang, i) => {
          const delay = 6 + i * 2;
          const p = spring({
            frame: frame - delay,
            fps,
            config: { damping: 20, stiffness: 120 },
          });

          return (
            <div
              key={lang}
              style={{
                fontSize: 28,
                fontWeight: 400,
                color: "var(--foreground)",
                opacity: interpolate(p, [0, 1], [0, 0.85]),
                transform: `translateY(${(1 - p) * 20}px)`,
              }}
            >
              {lang}
            </div>
          );
        })}
      </div>
    </div>
  );
};
