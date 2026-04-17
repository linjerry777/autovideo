import React from "react";
import { AbsoluteFill, Img, interpolate, useCurrentFrame } from "remotion";

export interface BackgroundPalette {
  bg1: string;
  bg2: string;
  bg3: string;
  glow: string;
}

interface Props {
  imgSrc: string;         // data URL or file URL; empty string → gradient fallback
  totalFrames: number;    // sequence duration, used to scale Ken Burns
  palette: BackgroundPalette;
}

/**
 * Full-bleed image with slow Ken Burns zoom + scrim, OR gradient fallback.
 *
 * Ken Burns: scale 1.0 → 1.08 over the sequence + 15px horizontal drift.
 * Scrim: dark gradient at top (10% opacity) and bottom (80% opacity) for text legibility.
 */
export const BackgroundLayer: React.FC<Props> = ({
  imgSrc,
  totalFrames,
  palette,
}) => {
  const frame = useCurrentFrame();

  const scale = interpolate(frame, [0, totalFrames], [1.0, 1.08], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const driftX = interpolate(frame, [0, totalFrames], [0, 15], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  if (!imgSrc) {
    // Gradient fallback (matches "text mode" feel)
    return (
      <AbsoluteFill
        style={{
          background: `linear-gradient(135deg, ${palette.bg1} 0%, ${palette.bg2} 55%, ${palette.bg3} 100%)`,
        }}
      />
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: palette.bg1 }}>
      <Img
        src={imgSrc}
        style={{
          width:           "100%",
          height:          "100%",
          objectFit:       "cover",
          transform:       `scale(${scale}) translateX(${driftX}px)`,
          transformOrigin: "center center",
        }}
      />

      {/* Scrim: top dark + bottom dark gradient for text legibility */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(180deg, " +
            "rgba(0,0,0,0.45) 0%, " +
            "rgba(0,0,0,0.0) 25%, " +
            "rgba(0,0,0,0.0) 55%, " +
            "rgba(0,0,0,0.75) 100%)",
          pointerEvents: "none",
        }}
      />
    </AbsoluteFill>
  );
};
