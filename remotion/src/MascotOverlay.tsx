import React from "react";
import { Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

interface Props {
  /** Data URL or file URL to the (background-removed) mascot PNG. Empty string → nothing renders. */
  src: string;
}

/**
 * Mascot-on-a-progress-bar overlay. As the composition plays, the mascot slides from
 * the left edge to the right edge, riding a thin track that fills in behind it with
 * the accent color. Subtle bob + rotate gives it life while it moves.
 *
 * Layout (1080×1920):
 *   track  : y ≈ 1540, centred ~960px wide, 6px tall
 *   mascot : 90px wide, sits on top of the track (tail end at progress position)
 *
 * Placement sits *above* the subtitle bar (~1660+) and *below* the info card
 * (~720..1460), using the otherwise-empty gap at y ~1480-1620.
 */
// Canvas is 1080×1920. Mascot slides along the very bottom edge, no visible track.
const FRAME_H     = 1920;
const BAR_MARGIN  = 60;                          // horizontal padding so mascot never clips
const CANVAS_W    = 1080;
const BAR_WIDTH   = CANVAS_W - BAR_MARGIN * 2;
const MASCOT_W    = 110;                         // slightly bigger since it's now the sole character anchor
const MASCOT_H    = 129;                         // ~0.85 aspect of 848×993 source
const MASCOT_BOTTOM_PAD = 8;                     // distance from mascot feet to absolute bottom

export const MascotOverlay: React.FC<Props> = ({ src }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  if (!src) return null;

  // Progress 0..1 across the whole video. Clamp so trailing/leading overshoot doesn't move mascot off-screen.
  const progress = Math.max(0, Math.min(1, frame / Math.max(1, durationInFrames - 1)));

  // Where the mascot's horizontal centre sits
  const mascotCenterX = BAR_MARGIN + BAR_WIDTH * progress;
  const mascotLeft    = mascotCenterX - MASCOT_W / 2;
  // Mascot's feet sit at the very bottom edge of the video
  const mascotTop     = FRAME_H - MASCOT_H - MASCOT_BOTTOM_PAD;

  // Life micro-motion while walking (subtle — no visible track means the
  // wobble is the only cue that something is "moving forward")
  const t           = frame / fps;
  const bob         = Math.sin(t * Math.PI * 1.6) * 3;         // ±3px vertical wobble
  const rotate      = Math.sin(t * Math.PI * 1.1) * 2;         // ±2° tilt
  const entryFade   = interpolate(frame, [0, 14], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        left:  mascotLeft,
        top:   mascotTop + bob,
        width: MASCOT_W,
        height: MASCOT_H,
        zIndex: 19,
        pointerEvents: "none",
        opacity: entryFade,
        transform: `rotate(${rotate}deg)`,
        transformOrigin: "bottom center",
        filter: "drop-shadow(0 6px 14px rgba(0,0,0,0.55))",
      }}
    >
      <Img src={src} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
    </div>
  );
};
