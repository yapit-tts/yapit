import React from "react";
import {
  Img,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
} from "remotion";
import { BRAND } from "../config";
import { fontFamily } from "../fonts";

/**
 * Sequential card fan — screenshots slide in one by one from the right,
 * each overlapping the previous. Like dealing cards left to right.
 *
 * Replace placeholder images in video/public/clips/cards/.
 */

const CARDS = [
  { file: "clips/cards/paper.png" },
  { file: "clips/cards/blog.png" },
  { file: "clips/darkmode-1.png" },
  { file: "clips/darkmode-2.png" },
  { file: "clips/darkmode-3.png" },
];

const CARD_W = 680;
const CARD_H = 420;
const OVERLAP = 420; // heavy overlap — each card shows ~260px of unique area
const STAGGER = 30; // frames between each card appearing (~1s)
const TILT = 1.5; // slight rotation per card (degrees)

export const CardFanScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Total width of the fan
  const fanWidth = CARD_W + (CARDS.length - 1) * (CARD_W - OVERLAP);
  const startX = (1920 - fanWidth) / 2;

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: `linear-gradient(160deg, ${BRAND.cream} 0%, ${BRAND.greenPale} 60%, ${BRAND.cream} 100%)`,
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Title overlay */}
      <div
        style={{
          position: "absolute",
          top: 80,
          width: "100%",
          textAlign: "center",
          zIndex: 10,
          fontFamily,
          opacity: interpolate(frame, [8, 20], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          transform: `translateY(${interpolate(
            spring({ frame: Math.max(0, frame - 8), fps, config: { damping: 30, stiffness: 100 } }),
            [0, 1],
            [20, 0],
          )}px)`,
        }}
      >
        <div
          style={{
            fontSize: 52,
            fontWeight: 600,
            color: BRAND.brown,
            letterSpacing: "-0.03em",
          }}
        >
          Listen to anything!
        </div>
        <div
          style={{
            fontSize: 22,
            fontWeight: 400,
            color: BRAND.brown,
            opacity: 0.6,
            marginTop: 8,
          }}
        >
          Articles · Papers · Books · News · Blogs
        </div>
      </div>

      {CARDS.map((card, i) => {
        const delay = i * STAGGER;
        const p = spring({
          frame: frame - delay,
          fps,
          config: { damping: 22, stiffness: 100 },
        });

        // Each card slides in from the right
        const x = startX + i * (CARD_W - OVERLAP);
        const slideFrom = 1920 + 100;
        const currentX = interpolate(p, [0, 1], [slideFrom, x]);
        // Center vertically with slight upward arc for middle cards
        const baseY = (1080 - CARD_H) / 2;
        const y = baseY + interpolate(p, [0, 1], [40, 0]);
        // Slight tilt — each card a bit more than the previous
        const rotation = interpolate(p, [0, 1], [8, (i - 2) * TILT]);
        const scale = interpolate(p, [0, 1], [0.9, 1]);

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: currentX,
              top: y,
              width: CARD_W,
              height: CARD_H,
              transform: `rotate(${rotation}deg) scale(${scale})`,
              transformOrigin: "center center",
              zIndex: i, // later cards on top (left to right stacking)
              borderRadius: 14,
              boxShadow:
                "0 6px 30px rgba(0,0,0,0.10), 0 2px 8px rgba(0,0,0,0.06)",
              overflow: "hidden",
            }}
          >
            <Img
              src={staticFile(card.file)}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                display: "block",
              }}
            />
          </div>
        );
      })}
    </div>
  );
};
