import React from "react";
import { AbsoluteFill } from "remotion";

/**
 * Wraps content in a device-like frame with frosted glass chrome.
 * For showing captured app UI floating on a gradient background.
 *
 * Use with <Video> or any content that should look like it's
 * displayed on a device/monitor.
 */

interface DeviceFrameProps {
  children: React.ReactNode;
  background?: string;
  padding?: number;
  borderRadius?: number;
  shadow?: boolean;
}

export const DeviceFrame: React.FC<DeviceFrameProps> = ({
  children,
  background = "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
  padding = 40,
  borderRadius = 16,
  shadow = true,
}) => {
  return (
    <AbsoluteFill
      style={{
        background,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        padding,
      }}
    >
      <div
        style={{
          width: `calc(100% - ${padding * 2}px)`,
          height: `calc(100% - ${padding * 2}px)`,
          borderRadius,
          overflow: "hidden",
          position: "relative",
          boxShadow: shadow
            ? "0 25px 50px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(255, 255, 255, 0.1)"
            : undefined,
        }}
      >
        {children}
      </div>
    </AbsoluteFill>
  );
};
