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
const BAR_Y       = 1540;
const BAR_HEIGHT  = 6;
const BAR_MARGIN  = 80;        // horizontal padding from frame edge
const CANVAS_W    = 1080;
const BAR_WIDTH   = CANVAS_W - BAR_MARGIN * 2;
const MASCOT_W    = 90;
const MASCOT_H    = 105;       // matches ~0.85 aspect of 848×993 source

const ACCENT      = "#ff6bcb";  // fallback; ideally read from palette but NewsVideo doesn't expose per-item palette up here
const TRACK_BG    = "rgba(255,255,255,0.22)";

export const MascotOverlay: React.FC<Props> = ({ src }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  if (!src) return null;

  // Progress 0..1 across the whole video. Clamp so trailing/leading overshoot doesn't move mascot off-screen.
  const progress = Math.max(0, Math.min(1, frame / Math.max(1, durationInFrames - 1)));

  // Where the mascot's horizontal centre sits
  const mascotCenterX = BAR_MARGIN + BAR_WIDTH * progress;
  const mascotLeft    = mascotCenterX - MASCOT_W / 2;
  // Mascot sits on top of the bar — its feet line up with the bar
  const mascotTop     = BAR_Y - MASCOT_H + 8;

  // Life micro-motion while walking
  const t           = frame / fps;
  const bob         = Math.sin(t * Math.PI * 1.6) * 3;         // ±3px vertical wobble (~0.8 Hz)
  const rotate      = Math.sin(t * Math.PI * 1.1) * 2;         // ±2° tilt
  const entryFade   = interpolate(frame, [0, 14], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <>
      {/* Background track */}
      <div
        style={{
          position: "absolute",
          left:  BAR_MARGIN,
          top:   BAR_Y,
          width: BAR_WIDTH,
          height: BAR_HEIGHT,
          borderRadius: 999,
          background: TRACK_BG,
          zIndex: 17,
          opacity: entryFade,
        }}
      />
      {/* Filled portion behind the mascot */}
      <div
        style={{
          position: "absolute",
          left:  BAR_MARGIN,
          top:   BAR_Y,
          width: Math.max(0, mascotCenterX - BAR_MARGIN),
          height: BAR_HEIGHT,
          borderRadius: 999,
          background: `linear-gradient(90deg, ${ACCENT} 0%, #ffffff 100%)`,
          boxShadow: `0 0 18px ${ACCENT}`,
          zIndex: 17,
          opacity: entryFade,
        }}
      />
      {/* Mascot sliding along the bar */}
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
    </>
  );
};
