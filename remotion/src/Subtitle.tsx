import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
} from "remotion";
import { TimingEntry } from "./types";

interface SubtitleProps {
  timing: TimingEntry[] | null;
  script: string;
  segmentStartFrame: number;  // absolute frame where this segment starts
}

/**
 * Renders animated subtitles synced to timing JSON.
 * Falls back to splitting script into 4 equal chunks if timing is absent.
 */
export const Subtitle: React.FC<SubtitleProps> = ({
  timing,
  script,
  segmentStartFrame,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Convert frame to local seconds within this segment
  const localFrame = frame - segmentStartFrame;
  const localSeconds = localFrame / fps;

  // Build subtitle chunks from timing or equal split
  let chunks: Array<{ text: string; start: number; end: number }>;

  if (timing && timing.length > 0) {
    chunks = timing;
  } else {
    // Split script into ~4 sentences
    const sentences = script
      .split(/(?<=[！？。，、；])/g)
      .map((s) => s.trim())
      .filter(Boolean);
    const parts = sentences.length > 0 ? sentences : [script];
    // Estimate we won't know duration here, use a placeholder approach
    // The parent passes a generous duration via its own durationInFrames
    // Just give each chunk 1/parts fraction of 999s (clamped by parent)
    const chunkDur = 999 / parts.length;
    chunks = parts.map((text, i) => ({
      text,
      start: i * chunkDur,
      end: (i + 1) * chunkDur,
    }));
  }

  // Find active chunk
  const active = chunks.find(
    (c) => localSeconds >= c.start && localSeconds < c.end
  );

  if (!active) return null;

  const chunkDuration = active.end - active.start;
  const progressInChunk = localSeconds - active.start;

  // Fade in first 0.2s, fade out last 0.15s
  const fadeInEnd = Math.min(0.2, chunkDuration * 0.2);
  const fadeOutStart = Math.max(0, chunkDuration - 0.15);

  const opacity = interpolate(
    progressInChunk,
    [0, fadeInEnd, fadeOutStart, chunkDuration],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // Wrap text at ~13 CJK chars
  const wrapped = wrapText(active.text, 13);

  return (
    <div
      style={{
        position: "absolute",
        bottom: 160,
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        opacity,
        zIndex: 20,
        padding: "0 60px",
      }}
    >
      <div
        style={{
          backgroundColor: "rgba(0,0,0,0.6)",
          borderRadius: 12,
          padding: "14px 28px",
          textAlign: "center",
        }}
      >
        {wrapped.map((line, idx) => (
          <div
            key={idx}
            style={{
              fontFamily:
                '"Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif',
              fontSize: 62,
              fontWeight: "bold",
              color: "#FFFFFF",
              lineHeight: 1.35,
              textShadow: "2px 2px 6px rgba(0,0,0,0.9)",
              letterSpacing: 2,
              display: "block",
            }}
          >
            {line}
          </div>
        ))}
      </div>
    </div>
  );
};

function wrapText(text: string, maxChars: number): string[] {
  const lines: string[] = [];
  let buf = "";
  for (const ch of text) {
    buf += ch;
    if (buf.length >= maxChars) {
      lines.push(buf);
      buf = "";
    } else if (buf && /[，。！？、；]/.test(ch)) {
      lines.push(buf);
      buf = "";
    }
  }
  if (buf) lines.push(buf);
  return lines;
}
