import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { NewsItem as NewsItemType } from "./types";
import { Subtitle } from "./Subtitle";

interface NewsItemProps {
  item: NewsItemType;
  segmentStartFrame: number;
  totalFrames: number;
}

/**
 * Renders one news item as an animated Remotion segment.
 *
 * Layout (1080x1920):
 *   ┌─────────────────────┐
 *   │  Hook text (top)    │  ~170px – gold, spring slide-in from top
 *   ├─────────────────────┤
 *   │  Blurred background │
 *   │  ┌───────────────┐  │
 *   │  │  Screenshot   │  │  Ken Burns zoom-pan
 *   │  │  Ken Burns    │  │
 *   │  └───────────────┘  │
 *   ├─────────────────────┤
 *   │  Subtitles (bottom) │  ~250px – synced fade words
 *   └─────────────────────┘
 */
export const NewsItemComponent: React.FC<NewsItemProps> = ({
  item,
  segmentStartFrame,
  totalFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();

  // Local frame within this segment
  const localFrame = frame - segmentStartFrame;

  // ── Hook text: spring slide from y=-80 to y=0 ──────────────────────
  const hookProgress = spring({
    fps,
    frame: localFrame,
    config: { damping: 18, stiffness: 120, mass: 0.6 },
    durationInFrames: 20,
  });
  const hookY = interpolate(hookProgress, [0, 1], [-80, 0]);
  const hookOpacity = interpolate(hookProgress, [0, 1], [0, 1]);

  // ── Ken Burns: slow zoom-in + horizontal pan ───────────────────────
  // Scale from 1.0 → 1.08 over the segment; pan x from 0% → 1.5%
  const kenBurnsScale = interpolate(
    localFrame,
    [0, totalFrames],
    [1.0, 1.08],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const kenBurnsPanX = interpolate(
    localFrame,
    [0, totalFrames],
    [0, width * 0.015],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // ── Crossfade: fade in first 9 frames, fade out last 9 frames ─────
  const FADE = 9;
  const fadeOpacity = interpolate(
    localFrame,
    [0, FADE, totalFrames - FADE, totalFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // Convert file path to file:// URL if needed
  const screenshotSrc = pathToUrl(item.screenshot);
  const audioSrc = pathToUrl(item.audio);

  return (
    <AbsoluteFill style={{ opacity: fadeOpacity, backgroundColor: "#111" }}>
      {/* ── Audio ── */}
      {audioSrc && <Audio src={audioSrc} startFrom={0} />}

      {/* ── Blurred background (full canvas) ── */}
      {screenshotSrc && (
        <AbsoluteFill style={{ overflow: "hidden" }}>
          <Img
            src={screenshotSrc}
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              width: "130%",
              height: "130%",
              objectFit: "cover",
              transform: `translate(-50%, -50%) scale(${kenBurnsScale}) translateX(${kenBurnsPanX}px)`,
              filter: "blur(20px) brightness(0.45) saturate(0.7)",
            }}
          />
        </AbsoluteFill>
      )}

      {/* ── Foreground screenshot (Ken Burns, centered) ── */}
      {screenshotSrc && (
        <AbsoluteFill
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            // Push down a bit to leave room for hook bar at top
            paddingTop: 170,
            paddingBottom: 250,
            overflow: "hidden",
          }}
        >
          <Img
            src={screenshotSrc}
            style={{
              width: width,
              objectFit: "contain",
              maxHeight: height - 170 - 250,
              transform: `scale(${kenBurnsScale}) translateX(${kenBurnsPanX}px)`,
              transformOrigin: "center center",
              borderRadius: 4,
              boxShadow: "0 8px 40px rgba(0,0,0,0.7)",
            }}
          />
        </AbsoluteFill>
      )}

      {/* ── Top hook bar ── */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 170,
          backgroundColor: "rgba(0,0,0,0.78)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          zIndex: 10,
          transform: `translateY(${hookY}px)`,
          opacity: hookOpacity,
        }}
      >
        <span
          style={{
            fontFamily:
              '"Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif',
            fontSize: 52,
            fontWeight: "bold",
            color: "#FFD700",
            textShadow: "2px 2px 8px rgba(0,0,0,0.95)",
            letterSpacing: 3,
            textAlign: "center",
            padding: "0 40px",
            lineHeight: 1.3,
            display: "block",
          }}
        >
          {item.hook}
        </span>
      </div>

      {/* ── Source badge ── */}
      {item.source && (
        <div
          style={{
            position: "absolute",
            bottom: 120,
            left: 40,
            backgroundColor: "rgba(0,0,0,0.55)",
            borderRadius: 8,
            padding: "6px 16px",
            zIndex: 15,
          }}
        >
          <span
            style={{
              fontFamily:
                '"Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif',
              fontSize: 28,
              color: "rgba(255,255,255,0.75)",
              fontWeight: 500,
            }}
          >
            {item.source}
          </span>
        </div>
      )}

      {/* ── Subtitles ── */}
      <Subtitle
        timing={item.timing}
        script={item.script}
        segmentStartFrame={segmentStartFrame}
      />
    </AbsoluteFill>
  );
};

/**
 * Convert an absolute Windows/POSIX file path to a file:// URL.
 * If the value already starts with http(s):// or file:// leave it as-is.
 */
function pathToUrl(p: string): string {
  if (!p) return "";
  // Already a URL (http/https/file/data) — pass through unchanged
  if (/^https?:\/\//i.test(p) || /^file:\/\//i.test(p) || /^data:/i.test(p)) return p;
  // Windows: C:\path\to\file → file:///C:/path/to/file
  const normalized = p.replace(/\\/g, "/");
  if (/^[A-Za-z]:\//.test(normalized)) {
    return `file:///${normalized}`;
  }
  // Unix absolute path
  return `file://${normalized}`;
}
