import React from "react";
import { Video } from "@remotion/media";
import { staticFile, useVideoConfig } from "remotion";

/**
 * Shows a zoomed-in portion of a captured video.
 * Specify the crop region as fractions (0-1) of the video dimensions.
 *
 * Example: to show the right 40% × bottom 50% of the video:
 *   <ZoomCrop src="clips/voice-picker.webm" x={0.6} y={0.5} w={0.4} h={0.5} />
 */

interface ZoomCropProps {
  src: string;
  x: number; // left edge, 0-1
  y: number; // top edge, 0-1
  w: number; // width fraction, 0-1
  h: number; // height fraction, 0-1
  trimBefore?: number; // frames
  playbackRate?: number;
}

export const ZoomCrop: React.FC<ZoomCropProps> = ({
  src,
  x,
  y,
  w,
  h,
  trimBefore,
  playbackRate,
}) => {
  const { width, height } = useVideoConfig();

  // Scale factor to fill the composition from the crop region
  const scaleX = 1 / w;
  const scaleY = 1 / h;
  const scale = Math.max(scaleX, scaleY);

  // Video dimensions after scaling
  const videoW = width * scale;
  const videoH = height * scale;

  // Offset to position the crop region at the viewport origin
  const offsetX = -x * videoW;
  const offsetY = -y * videoH;

  return (
    <div style={{ width: "100%", height: "100%", overflow: "hidden" }}>
      <Video
        src={staticFile(src)}
        style={{
          width: videoW,
          height: videoH,
          transform: `translate(${offsetX}px, ${offsetY}px)`,
        }}
        trimBefore={trimBefore}
        playbackRate={playbackRate}
        muted
      />
    </div>
  );
};
