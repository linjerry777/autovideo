import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { NewsVideoProps } from "./types";
import { NewsItemComponent } from "./NewsItem";
import { MascotOverlay } from "./MascotOverlay";

const FPS = 30;

/**
 * Main composition: concatenates all news items as non-overlapping Sequences.
 *
 * Each item's audio duration (seconds) is converted to frames.
 * A 0.3s crossfade is applied by having each Sequence start 9 frames
 * before the previous one ends (handled via opacity in NewsItemComponent).
 */
export const NewsVideo: React.FC<NewsVideoProps> = ({ items, layout_mode = "visual", mascot = "" }) => {
  // Build per-item frame ranges
  const FADE_FRAMES = 9; // 0.3s @ 30fps

  const segments = items.map((item) => {
    const durationFrames = Math.round((item.duration + 0.3) * FPS);
    return { item, durationFrames };
  });

  // Compute cumulative start frames (with crossfade overlap)
  let cursor = 0;
  const placed = segments.map(({ item, durationFrames }, idx) => {
    const startFrame = idx === 0 ? 0 : cursor - FADE_FRAMES;
    cursor = startFrame + durationFrames;
    return { item, startFrame, durationFrames };
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {placed.map(({ item, startFrame, durationFrames }, idx) => (
        <Sequence
          key={idx}
          from={startFrame}
          durationInFrames={durationFrames}
          layout="none"
        >
          <NewsItemComponent
            item={item}
            index={idx}
            totalFrames={durationFrames}
            totalItems={placed.length}
            layout_mode={layout_mode}
          />
        </Sequence>
      ))}
      {/* Persistent mascot presenter — outside sequences so it stays on screen across items */}
      <MascotOverlay src={mascot} />
    </AbsoluteFill>
  );
};

/**
 * Calculate total duration in frames for all items combined.
 */
export function calcTotalFrames(items: NewsVideoProps["items"]): number {
  if (!items || items.length === 0) return FPS * 10;
  const FADE_FRAMES = 9;
  let total = 0;
  items.forEach((item, idx) => {
    const dur = Math.round((item.duration + 0.3) * FPS);
    total += idx === 0 ? dur : dur - FADE_FRAMES;
  });
  return total;
}
