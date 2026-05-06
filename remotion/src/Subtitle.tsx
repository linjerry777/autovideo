import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
} from "remotion";
import { TimingEntry } from "./types";

interface SubtitleProps {
  timing: TimingEntry[] | null;
  script: string;
  /** Accent color used for power-word emphasis. Defaults to punchy yellow. */
  accent?: string;
}

// Power-word regex — numbers, percentages, Chinese emphasis words.
// Matches are rendered in accent color with a glow, mimicking Submagic's
// per-word highlight style. Designed for 60%+ muted viewers who read captions.
const POWER_REGEX =
  /(\d+[.,]?\d*[%％萬億千百倍]?|破|爆|首|最|第一|竟然|居然|直接|全網|瞬間|秒殺|顛覆|崩壞|封神|全平台|狂漲|暴漲|暴跌|翻倍|上線|震撼|驚|真的|絕對|完全|史上|一次|瞬間|正式)/g;

function renderColoredText(text: string, accent: string) {
  const nodes: React.ReactNode[] = [];
  const re = new RegExp(POWER_REGEX.source, "g");
  let lastIdx = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > lastIdx) {
      nodes.push(
        <span key={`t${lastIdx}`}>{text.slice(lastIdx, m.index)}</span>,
      );
    }
    nodes.push(
      <span
        key={`e${m.index}`}
        style={{
          color: accent,
          textShadow: `0 0 14px ${accent}aa, 0 3px 8px rgba(0,0,0,0.95)`,
          fontWeight: 900,
        }}
      >
        {m[0]}
      </span>,
    );
    lastIdx = m.index + m[0].length;
  }
  if (lastIdx < text.length) {
    nodes.push(<span key={`t${lastIdx}`}>{text.slice(lastIdx)}</span>);
  }
  return nodes.length > 0 ? nodes : [<span key="all">{text}</span>];
}

/**
 * Animated subtitles synced to timing JSON. Falls back to equal-split chunks
 * if timing is absent.
 *
 * Submagic-style: each chunk enters with a scale-in spring bounce, power words
 * highlighted in accent color with glow, larger/bolder text than the old plain
 * white subtitle.
 */
export const Subtitle: React.FC<SubtitleProps> = ({
  timing,
  script,
  accent = "#ffd740",
}) => {
  const localFrame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const localSeconds = localFrame / fps;

  let chunks: Array<{ text: string; start: number; end: number }>;

  if (timing && timing.length > 0) {
    chunks = timing;
  } else {
    const sentences = script
      .split(/(?<=[！？。，、；])/g)
      .map((s) => s.trim())
      .filter(Boolean);
    const parts = sentences.length > 0 ? sentences : [script];
    const chunkDur = 999 / parts.length;
    chunks = parts.map((text, i) => ({
      text,
      start: i * chunkDur,
      end: (i + 1) * chunkDur,
    }));
  }

  const active = chunks.find(
    (c) => localSeconds >= c.start && localSeconds < c.end,
  );
  if (!active) return null;

  const chunkStartFrame = active.start * fps;
  const framesIntoChunk = localFrame - chunkStartFrame;
  const chunkDuration = active.end - active.start;
  const progressInChunk = localSeconds - active.start;

  // Scale spring: 0.85 → 1.0 over 10 frames at chunk start
  const scaleSpring = spring({
    fps,
    frame: framesIntoChunk,
    config: { damping: 14, stiffness: 180, mass: 0.6 },
    durationInFrames: 12,
  });
  const scale = interpolate(scaleSpring, [0, 1], [0.85, 1]);

  // Fade in 0.12s, fade out last 0.12s
  // Cap fade length at 1/3 of the chunk so the inputRange stays strictly
  // monotonically increasing for very short chunks (e.g. hook stickers like
  // 「欸，」 produce ~0.235s clips, where a fixed 0.12s fade would make
  // chunkDuration - 0.12 = 0.115 < 0.12 and crash interpolate()).
  const fadeDur = Math.min(0.12, chunkDuration / 3);
  const fadeInEnd  = Math.min(fadeDur, chunkDuration / 2);
  const fadeOutStart = Math.max(fadeInEnd + 1e-4, chunkDuration - fadeDur);
  const opacity = interpolate(
    progressInChunk,
    [0, fadeInEnd, fadeOutStart, chunkDuration],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  const wrapped = wrapText(active.text, 12);

  return (
    <div
      style={{
        position: "absolute",
        // 280px from bottom keeps subtitle clear of TikTok/IG/YT-Shorts UI
        // overlay zone (like buttons + comments take ~250-350px on mobile).
        // Wife flagged previous 60px as "too low" — covered on phones.
        bottom: 280,
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        opacity,
        zIndex: 20,
        padding: "0 40px",
        transform: `scale(${scale})`,
        transformOrigin: "center bottom",
      }}
    >
      <div
        style={{
          backgroundColor: "rgba(0,0,0,0.82)",
          borderRadius: 16,
          padding: "14px 28px",
          textAlign: "center",
          maxWidth: "94%",
          border: `2px solid ${accent}55`,
          boxShadow: `0 12px 32px rgba(0,0,0,0.7), 0 0 28px ${accent}30`,
        }}
      >
        {wrapped.map((line, idx) => (
          <div
            key={idx}
            style={{
              fontFamily:
                '"Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif',
              fontSize: 60,
              fontWeight: 900,
              color: "#FFFFFF",
              lineHeight: 1.25,
              textShadow:
                "0 3px 10px rgba(0,0,0,0.95), 0 0 18px rgba(0,0,0,0.8)",
              letterSpacing: 2,
              display: "block",
            }}
          >
            {renderColoredText(line, accent)}
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
