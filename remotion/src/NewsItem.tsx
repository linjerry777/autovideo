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
import { NewsItem as NewsItemType, SceneType, LayoutMode } from "./types";
import { Subtitle } from "./Subtitle";
import { FireScene } from "./scenes/FireScene";
import { RaceScene } from "./scenes/RaceScene";
import { SceneInterpreter } from "./scenes/SceneInterpreter";
import { BackgroundLayer } from "./BackgroundLayer";

const PRESET_SCENES = new Set(["fire", "race", "money", "robot", "warning", "trophy", "default"]);

/**
 * Resolve scene:
 * 1. Use explicit item.scene_type if set (from Claude or user edit)
 * 2. Fallback: keyword detection on hook+title+script
 */
function resolveScene(item: NewsItemType): SceneType {
  if (item.scene_type && item.scene_type !== "default") return item.scene_type;
  const txt = `${item.hook} ${item.title} ${item.script}`;
  if (/燃燒|爆炸|攻擊|炸|縱火|火燒|丟擲|襲擊/.test(txt)) return "fire";
  if (/追趕|追上|競賽|競爭|領先|超越|差距|消失|賽跑|並駕|對決|比拼/.test(txt)) return "race";
  if (/融資|估值|億|獲利|投資|股價|市值/.test(txt)) return "money";
  if (/機器人|自動化|AI模型|大模型|LLM/.test(txt)) return "robot";
  if (/爭議|警告|違法|訴訟|風險|隱私/.test(txt)) return "warning";
  if (/突破|獲獎|創紀錄|第一|領先業界/.test(txt)) return "trophy";
  return "default";
}

interface NewsItemProps {
  item: NewsItemType;
  index: number;
  totalFrames: number;
  totalItems: number;
  layout_mode?: LayoutMode;
}

/**
 * Text-driven news segment. Screenshot is an optional bonus thumbnail —
 * composition looks good even when screenshots are missing (many news
 * sites block scraping).
 *
 * Layout (1080x1920):
 *   animated gradient backdrop + drifting glow orbs
 *   top: item counter "01 / 03"
 *   hero: HOOK text (huge, spring bounce-in, gradient fill)
 *   card: title + optional screenshot thumbnail (glass panel)
 *   bottom: source badge + timing-synced subtitle bar
 */

const PALETTES = [
  { bg1: "#1a0033", bg2: "#4a148c", bg3: "#880e4f", accent: "#ff6bcb", glow: "rgba(255,107,203,0.35)" },
  { bg1: "#001e3c", bg2: "#0d47a1", bg3: "#006064", accent: "#4dd0ff", glow: "rgba(77,208,255,0.35)" },
  { bg1: "#1b3300", bg2: "#2e7d32", bg3: "#e65100", accent: "#ffd740", glow: "rgba(255,215,64,0.4)" },
  { bg1: "#3e0a1e", bg2: "#b71c1c", bg3: "#4a148c", accent: "#ff8a65", glow: "rgba(255,138,101,0.35)" },
];

const FONT_CJK = '"Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif';

export const NewsItemComponent: React.FC<NewsItemProps> = ({
  item,
  index,
  totalFrames,
  totalItems,
  layout_mode = "visual",
}) => {
  // Inside <Sequence from=N>, useCurrentFrame() is already shifted to 0 at
  // the sequence start — do NOT subtract startFrame again.
  const localFrame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const palette = PALETTES[index % PALETTES.length];

  const FADE = 9;
  const fadeOpacity = interpolate(
    localFrame,
    [0, FADE, totalFrames - FADE, totalFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // Hook spring bounce
  const hookSpring = spring({
    fps,
    frame: localFrame,
    config: { damping: 10, stiffness: 180, mass: 0.7 },
    durationInFrames: 28,
  });
  const hookScale = interpolate(hookSpring, [0, 0.7, 1], [0.3, 1.08, 1]);
  const hookOpacity = interpolate(hookSpring, [0, 0.3, 1], [0, 1, 1]);
  const hookRotate = interpolate(hookSpring, [0, 0.6, 1], [-8, 2, 0]);

  // Card slide-up (after hook)
  const cardSpring = spring({
    fps,
    frame: Math.max(0, localFrame - 18),
    config: { damping: 15, stiffness: 120, mass: 0.8 },
    durationInFrames: 22,
  });
  const cardY = interpolate(cardSpring, [0, 1], [80, 0]);
  const cardOpacity = interpolate(cardSpring, [0, 1], [0, 1]);

  // Source badge fade
  const sourceProgress = interpolate(localFrame, [32, 46], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Background gradient drift
  const bgAngle = interpolate(localFrame, [0, totalFrames], [135, 165]);
  const bgPulse = Math.sin((localFrame / fps) * 0.6) * 4;

  // Orb drift
  const orb1X = interpolate(localFrame, [0, totalFrames], [80, 200]);
  const orb1Y = interpolate(localFrame, [0, totalFrames], [300, 260]);
  const orb2X = interpolate(localFrame, [0, totalFrames], [900, 820]);
  const orb2Y = interpolate(localFrame, [0, totalFrames], [1400, 1480]);

  const audioSrc = pathToUrl(item.audio);
  const screenshotSrc = pathToUrl(item.screenshot);
  const scene = resolveScene(item);

  // Scene fades in softer when screenshot coexists (atmosphere), bolder otherwise
  const maxSceneOpacity = screenshotSrc ? 0.55 : 0.9;
  const sceneOpacity = interpolate(localFrame, [10, 30], [0, maxSceneOpacity], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ opacity: fadeOpacity, backgroundColor: palette.bg1 }}>
      {audioSrc && <Audio src={audioSrc} startFrom={0} />}

      {layout_mode === "visual" ? (
        <BackgroundLayer
          imgSrc={screenshotSrc}
          totalFrames={totalFrames}
          palette={{ bg1: palette.bg1, bg2: palette.bg2, bg3: palette.bg3, glow: palette.glow }}
        />
      ) : (
        <>
          {/* Text-mode: animated gradient backdrop */}
          <AbsoluteFill
            style={{
              background: `linear-gradient(${bgAngle}deg, ${palette.bg1} 0%, ${palette.bg2} ${50 + bgPulse}%, ${palette.bg3} 100%)`,
            }}
          />

          {/* Text-mode: drifting glow orbs */}
          <div
            style={{
              position: "absolute",
              left: orb1X,
              top: orb1Y,
              width: 600,
              height: 600,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${palette.glow} 0%, transparent 65%)`,
              filter: "blur(40px)",
              pointerEvents: "none",
            }}
          />
          <div
            style={{
              position: "absolute",
              left: orb2X,
              top: orb2Y,
              width: 500,
              height: 500,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${palette.glow} 0%, transparent 65%)`,
              filter: "blur(40px)",
              pointerEvents: "none",
            }}
          />
        </>
      )}

      {/* ── Contextual scene layer (between orbs and text) ── */}
      <div style={{ position: "absolute", inset: 0, opacity: sceneOpacity, zIndex: 3 }}>
        {/* Priority 1: LLM-resolved recipe (free-text scene_type) */}
        {item.scene_recipe && <SceneInterpreter recipe={item.scene_recipe} />}
        {/* Priority 2: preset specific scenes */}
        {!item.scene_recipe && scene === "fire" && <FireScene />}
        {!item.scene_recipe && scene === "race" && <RaceScene />}
      </div>

      {/* Item counter top-right — hidden for single-item (trending) videos */}
      {totalItems > 1 && (
      <div
        style={{
          position: "absolute",
          top: 80,
          right: 60,
          zIndex: 20,
          opacity: sourceProgress,
        }}
      >
        <div
          style={{
            fontFamily: FONT_CJK,
            fontSize: 42,
            fontWeight: 700,
            color: palette.accent,
            backgroundColor: "rgba(0,0,0,0.5)",
            borderRadius: 999,
            padding: "8px 28px",
            letterSpacing: 2,
          }}
        >
          {String(index + 1).padStart(2, "0")} / {String(totalItems).padStart(2, "0")}
        </div>
      </div>
      )}

      {/* HOOK hero */}
      <div
        style={{
          position: "absolute",
          top: 260,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          transform: `scale(${hookScale}) rotate(${hookRotate}deg)`,
          opacity: hookOpacity,
          zIndex: 15,
        }}
      >
        <span
          style={{
            fontFamily: FONT_CJK,
            fontSize: 150,
            fontWeight: 900,
            letterSpacing: 8,
            textAlign: "center",
            padding: "0 40px",
            lineHeight: 1.1,
            background: `linear-gradient(180deg, #ffffff 0%, ${palette.accent} 100%)`,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            filter:
              layout_mode === "visual"
                ? `drop-shadow(0 4px 24px rgba(0,0,0,0.95)) drop-shadow(0 0 30px ${palette.glow})`
                : `drop-shadow(0 0 30px ${palette.glow})`,
          }}
        >
          {item.hook || "AI 快訊"}
        </span>
      </div>

      {/* Info card */}
      <div
        style={{
          position: "absolute",
          top: 720,
          left: 60,
          right: 60,
          opacity: cardOpacity,
          transform: `translateY(${cardY}px)`,
          zIndex: 12,
        }}
      >
        <div
          style={{
            backgroundColor: "rgba(15,15,30,0.65)",
            backdropFilter: "blur(20px)",
            borderRadius: 32,
            padding: 48,
            border: `2px solid ${palette.accent}40`,
            boxShadow: `0 30px 80px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.1)`,
          }}
        >
          <h1
            style={{
              fontFamily: FONT_CJK,
              fontSize: 78,
              fontWeight: 800,
              color: "#ffffff",
              lineHeight: 1.25,
              margin: 0,
              letterSpacing: 1,
              textShadow:
                layout_mode === "visual"
                  ? "0 4px 24px rgba(0,0,0,0.95), 0 2px 8px rgba(0,0,0,0.9)"
                  : "0 4px 20px rgba(0,0,0,0.8)",
            }}
          >
            {item.title}
          </h1>

          {screenshotSrc && layout_mode === "text" && (
            <div
              style={{
                marginTop: 28,
                borderRadius: 20,
                overflow: "hidden",
                boxShadow: `0 20px 50px rgba(0,0,0,0.7), 0 0 0 2px ${palette.accent}30`,
                maxHeight: 420,
              }}
            >
              <Img
                src={screenshotSrc}
                style={{
                  width: "100%",
                  objectFit: "cover",
                  display: "block",
                }}
              />
            </div>
          )}
        </div>
      </div>

      {/* Source badge (sits above subtitle zone) */}
      {item.source && (
        <div
          style={{
            position: "absolute",
            bottom: 260,
            left: 60,
            zIndex: 15,
            opacity: sourceProgress,
          }}
        >
          <div
            style={{
              fontFamily: FONT_CJK,
              fontSize: 32,
              fontWeight: 600,
              color: palette.accent,
              backgroundColor: "rgba(0,0,0,0.55)",
              borderRadius: 999,
              padding: "10px 24px",
              letterSpacing: 1,
              border: `1px solid ${palette.accent}60`,
            }}
          >
            📰 {item.source}
          </div>
        </div>
      )}

      {/* Subtitle bar */}
      <Subtitle timing={item.timing} script={item.script} />
    </AbsoluteFill>
  );
};

function pathToUrl(p: string): string {
  if (!p) return "";
  if (/^(https?:\/\/|file:\/\/|data:)/i.test(p)) return p;
  const normalized = p.replace(/\\/g, "/");
  if (/^[A-Za-z]:\//.test(normalized)) {
    return `file:///${normalized}`;
  }
  return `file://${normalized}`;
}
