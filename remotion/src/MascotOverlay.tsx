import React from "react";
import { Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

interface Props {
  /** Data URL or file URL to the mascot PNG. Empty string → render nothing. */
  src: string;
}

/**
 * Persistent mascot in the bottom-right corner. Gives each video a "presenter
 * is with you" feel without needing lip-sync / per-item animation cost.
 *
 * Motion recipe (all low-amplitude, anime-subtle):
 *  - breathing  : scale 1.0 ↔ 1.035 over 2.0s (0.5 Hz sine)
 *  - head tilt  : rotate ±2.5° over 3.5s (0.28 Hz sine, phase-shifted vs. scale)
 *  - bob        : translateY ±4px over 1.7s (0.58 Hz sine)
 *  - entry      : slides in from below over the first 18 frames, gentle spring
 */
export const MascotOverlay: React.FC<Props> = ({ src }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!src) return null;

  const t = frame / fps;

  const scale      = 1 + Math.sin(t * Math.PI * 1.0) * 0.035;
  const rotateDeg  = Math.sin(t * Math.PI * 0.56) * 2.5;
  const bobY       = Math.sin(t * Math.PI * 1.16) * 4;

  // Entry slide-up over first 18 frames
  const entryY = interpolate(frame, [0, 18], [140, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const entryOpacity = interpolate(frame, [0, 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        right:    40,
        bottom:   260,             // sits above the subtitle bar area
        width:    220,
        height:   280,
        zIndex:   18,              // above background + card, below counter
        pointerEvents: "none",
        transform: `translateY(${entryY + bobY}px) rotate(${rotateDeg}deg) scale(${scale})`,
        transformOrigin: "bottom center",
        opacity: entryOpacity,
        filter: "drop-shadow(0 12px 28px rgba(0,0,0,0.55))",
      }}
    >
      <Img
        src={src}
        style={{
          width:     "100%",
          height:    "100%",
          objectFit: "contain",
        }}
      />
    </div>
  );
};
