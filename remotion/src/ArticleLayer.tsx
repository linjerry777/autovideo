import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type ArticleVariant =
  | "magazine"    // hero image left, bullets right, clean editorial layout
  | "breaking"    // red top banner "突發", big stacked bullets, tabloid energy
  | "flashcard";  // one bullet at a time, full-screen, swiped through

const FONT_CJK = '"Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif';

export interface ArticleLayerProps {
  variant: ArticleVariant;
  hook: string;
  title: string;
  bullets: string[];
  heroImage?: string;          // data-URL or file URL; optional
  fallbackImage?: string;      // screenshot fallback if hero missing
  source?: string;
  byline?: string;
  pubDate?: string;
  accent: string;              // palette.accent
  glow: string;                // palette.glow (rgba)
  totalFrames: number;
}

/**
 * Hook-slam intro (v2, 2026-05) — replaces the previous black-flash pattern
 * interrupt. Reasoning: prior version wasted frames 0-9 on chrome (黑→白→
 * text bounce) before showing actual content. 3s-retention measurements
 * showed viewers swiping during the loading animation.
 *
 * New design:
 *   frame 0   — hook text already on screen at near-final size, full-bleed
 *   0-3       — radial flash of `accent` color burst (single beat for SFX sync)
 *   3-30      — text scales 0.92 → 1.0, gold glow pulse (1s hold)
 *   30-45     — text scales 1.0 → 0.55 + slides to top edge, fades to bg variant
 *
 * Key differences from old version:
 *   - No black/white screen flicker (no "loading style" frames)
 *   - Hook text visible from frame 0 (no waiting for spring)
 *   - Holds full-screen for ~1s instead of 0.3s — gives viewer time to *read*
 *   - Smooth dissolve into Magazine/Breaking/Flashcard variant layout
 */
const HookSlamIntro: React.FC<{ hook: string; accent: string }> = ({ hook, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Total intro length: 45 frames (1.5s @ 30fps). After that the variant takes over.
  if (frame >= 45) return null;

  // Color burst flash: frames 0-3, single saturated wash
  const burstOp = interpolate(frame, [0, 1, 3], [1, 0.85, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  // Text: visible at frame 0 (no spring runup), gentle settle to 1.0
  const textSpring = spring({
    fps, frame, config: { damping: 14, stiffness: 200, mass: 0.7 },
    durationInFrames: 12,
  });
  const settleScale = interpolate(textSpring, [0, 1], [0.92, 1.0]);

  // Exit transition: 30-45 = scale down + fade
  const exitT = Math.max(0, frame - 30) / 15;   // 0 → 1 across last 15 frames
  const exitScale = interpolate(exitT, [0, 1], [1.0, 0.55]);
  const exitY     = interpolate(exitT, [0, 1], [0, -380]);
  const exitOp    = interpolate(exitT, [0, 1], [1, 0]);

  const scale = settleScale * exitScale;

  // Background: dimmed-overlay so viewer focuses on text. Fades out for exit.
  const bgOp = interpolate(frame, [0, 30, 45], [0.92, 0.88, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ zIndex: 100, pointerEvents: "none" }}>
      {/* Dim backdrop so text reads even over hero image */}
      <div
        style={{
          position: "absolute", inset: 0,
          background: `radial-gradient(ellipse at center, rgba(8,12,28,0.96) 0%, rgba(8,12,28,0.82) 70%, rgba(8,12,28,0.55) 100%)`,
          opacity: bgOp,
        }}
      />
      {/* Color-burst flash — single beat for SFX sync */}
      <div
        style={{
          position: "absolute", inset: 0,
          background: `radial-gradient(circle at center, ${accent}cc 0%, ${accent}55 40%, transparent 70%)`,
          opacity: burstOp,
          mixBlendMode: "screen",
        }}
      />
      {/* Hook text — full bleed, frame 0 visible */}
      <div
        style={{
          position: "absolute", inset: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          padding: "0 60px",
          opacity: exitOp,
          transform: `translate(0, ${exitY}px) scale(${scale})`,
          transformOrigin: "center center",
        }}
      >
        <div
          style={{
            fontFamily: FONT_CJK,
            fontSize: 220,
            fontWeight: 900,
            color: "#fff",
            textAlign: "center",
            letterSpacing: 6,
            lineHeight: 1.0,
            textShadow: `0 0 50px ${accent}cc, 0 0 100px ${accent}55, 0 8px 24px rgba(0,0,0,0.9)`,
            // Gold-tinted text gradient on the accent color word
            background: `linear-gradient(180deg, #ffffff 0%, ${accent} 100%)`,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            filter: `drop-shadow(0 4px 12px ${accent}77)`,
          }}
        >
          {(hook || "").slice(0, 12)}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/**
 * Loop-back outro — final 15 frames fade back to hook text, creating a
 * pseudo-loop that makes viewers linger + algo reads as high completion.
 */
const LoopBackOutro: React.FC<{ hook: string; accent: string; totalFrames: number }> = ({
  hook, accent, totalFrames,
}) => {
  const frame = useCurrentFrame();
  const outroStart = totalFrames - 15;
  if (frame < outroStart) return null;

  const t = frame - outroStart;
  const op = interpolate(t, [0, 6, 15], [0, 1, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const scale = interpolate(t, [0, 10], [1.1, 1.0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        zIndex: 99,
        backgroundColor: "rgba(0,0,0,0.88)",
        opacity: op,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
      }}
    >
      <div
        style={{
          fontFamily: FONT_CJK, fontSize: 40, fontWeight: 700,
          color: "#ffffff99", letterSpacing: 4, marginBottom: 20,
        }}
      >
        ↻ 再看一次
      </div>
      <div
        style={{
          fontFamily: FONT_CJK, fontSize: 140, fontWeight: 900,
          color: accent, letterSpacing: 6, textAlign: "center",
          padding: "0 40px", lineHeight: 1.1, transform: `scale(${scale})`,
          textShadow: `0 0 36px ${accent}aa, 0 4px 16px rgba(0,0,0,0.9)`,
        }}
      >
        {(hook || "").slice(0, 12)}
      </div>
    </AbsoluteFill>
  );
};

export const ArticleLayer: React.FC<ArticleLayerProps> = (props) => {
  const { variant } = props;
  const variantEl =
    variant === "magazine"  ? <MagazineLayout  {...props} /> :
    variant === "breaking"  ? <BreakingLayout  {...props} /> :
                              <FlashcardLayout {...props} />;
  return (
    <>
      {variantEl}
      <HookSlamIntro hook={props.hook} accent={props.accent} />
      <LoopBackOutro hook={props.hook} accent={props.accent} totalFrames={props.totalFrames} />
    </>
  );
};

// ── Magazine: hero image top, title, 3 bullets stacked with numbered pills ──
const MagazineLayout: React.FC<ArticleLayerProps> = ({
  hook, title, bullets, heroImage, fallbackImage, source, byline,
  accent, glow, totalFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const imgSrc = heroImage || fallbackImage || "";

  // Rapid punch-in: 1.22 → 1.02 over first 18 frames (0.6s), then slow drift
  // Silent-muted viewers get motion in the first half-second — 2026 data shows
  // this beats static by 2.5× on 3s-retention.
  const punchIn = interpolate(frame, [0, 18], [1.22, 1.02], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const drift = interpolate(frame, [18, totalFrames], [0, 0.04], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const heroScale = punchIn + drift;

  // Title fade-in
  const titleOp = interpolate(frame, [6, 22], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "#0b0f1a" }}>
      {/* Hero image (top 45% of frame) */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 880, overflow: "hidden" }}>
        {imgSrc ? (
          <Img
            src={imgSrc}
            style={{
              width: "100%", height: "100%", objectFit: "cover",
              transform: `scale(${heroScale})`, transformOrigin: "center center",
            }}
          />
        ) : (
          <div style={{ width: "100%", height: "100%", background: `linear-gradient(135deg, ${accent}50, #000)` }} />
        )}
        {/* Bottom fade into dark card area */}
        <AbsoluteFill
          style={{
            background: "linear-gradient(180deg, rgba(0,0,0,0.2) 0%, rgba(0,0,0,0.0) 40%, rgba(11,15,26,1) 100%)",
            pointerEvents: "none",
          }}
        />
        {/* Red "NEWS" ribbon top-left */}
        <div
          style={{
            position: "absolute", top: 60, left: 60,
            fontFamily: FONT_CJK, fontSize: 36, fontWeight: 900, letterSpacing: 4,
            color: "#fff", backgroundColor: "#d32f2f",
            padding: "10px 28px", borderRadius: 6,
            boxShadow: "0 6px 20px rgba(0,0,0,0.55)",
          }}
        >
          📰 NEWS
        </div>
        {/* Hook pill top-right */}
        {hook && (
          <div
            style={{
              position: "absolute", top: 60, right: 60,
              fontFamily: FONT_CJK, fontSize: 42, fontWeight: 800,
              color: "#000", backgroundColor: accent,
              padding: "12px 32px", borderRadius: 999,
              boxShadow: `0 8px 24px ${glow}`,
            }}
          >
            {hook}
          </div>
        )}
      </div>

      {/* Byline + source under the hero */}
      {(source || byline) && (
        <div
          style={{
            position: "absolute", top: 810, left: 60, right: 60,
            display: "flex", gap: 16, alignItems: "center",
            fontFamily: FONT_CJK, fontSize: 30, color: "#cdd5e0",
            opacity: titleOp,
          }}
        >
          {source && <span style={{ color: accent, fontWeight: 700 }}>{source}</span>}
          {byline && <span>· {byline}</span>}
        </div>
      )}

      {/* Title */}
      <div
        style={{
          position: "absolute", top: 900, left: 60, right: 60,
          opacity: titleOp,
        }}
      >
        <h1
          style={{
            fontFamily: FONT_CJK, fontSize: 86, fontWeight: 900,
            color: "#fff", lineHeight: 1.18, margin: 0,
            letterSpacing: 1,
            textShadow: "0 4px 18px rgba(0,0,0,0.8)",
          }}
        >
          {title}
        </h1>
      </div>

      {/* 3 numbered bullet rows */}
      <div
        style={{
          position: "absolute", top: 1180, left: 60, right: 60,
          display: "flex", flexDirection: "column", gap: 24,
        }}
      >
        {bullets.slice(0, 3).map((b, i) => {
          const enterFrame = 22 + i * 10;
          const rowSpring = spring({
            fps,
            frame: Math.max(0, frame - enterFrame),
            config: { damping: 14, stiffness: 130, mass: 0.8 },
            durationInFrames: 24,
          });
          const rowX = interpolate(rowSpring, [0, 1], [-60, 0]);
          const rowOp = interpolate(rowSpring, [0, 1], [0, 1]);
          // v3 visual beat: number pill flashes white for ~5 frames on entry
          // per 2026 data — visual change every 3-5s boosts watch time +18%.
          const sinceEnter = frame - enterFrame;
          const flash = sinceEnter >= 0 && sinceEnter < 5 ? (1 - sinceEnter / 5) : 0;
          return (
            <div
              key={i}
              style={{
                display: "flex", alignItems: "center", gap: 28,
                opacity: rowOp, transform: `translateX(${rowX}px)`,
              }}
            >
              <div
                style={{
                  width: 78, height: 78, minWidth: 78,
                  borderRadius: 20,
                  backgroundColor: flash > 0 ? `rgba(255,255,255,${0.3 + flash*0.7})` : accent,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontFamily: FONT_CJK, fontSize: 52, fontWeight: 900, color: "#000",
                  boxShadow: `0 8px 22px ${glow}, 0 0 ${flash*40}px rgba(255,255,255,${flash*0.8})`,
                  transform: flash > 0 ? `scale(${1 + flash * 0.15})` : "none",
                }}
              >
                {i + 1}
              </div>
              <div
                style={{
                  fontFamily: FONT_CJK, fontSize: 56, fontWeight: 700,
                  color: "#fff", letterSpacing: 1,
                  textShadow: "0 3px 12px rgba(0,0,0,0.7)",
                  flex: 1,
                }}
              >
                {b}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ── Breaking: red top banner, big stacked bullets over image bg ──
const BreakingLayout: React.FC<ArticleLayerProps> = ({
  hook, title, bullets, heroImage, fallbackImage, source,
  accent, glow, totalFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const imgSrc = heroImage || fallbackImage || "";

  // Banner strobe
  const bannerPulse = 0.88 + Math.sin((frame / fps) * 4) * 0.12;

  // Title drop-in
  const titleSpring = spring({
    fps, frame, config: { damping: 12, stiffness: 150, mass: 0.7 },
    durationInFrames: 22,
  });
  const titleY = interpolate(titleSpring, [0, 1], [-80, 0]);
  const titleOp = interpolate(titleSpring, [0, 1], [0, 1]);

  return (
    <AbsoluteFill style={{ backgroundColor: "#0a0a0a" }}>
      {/* Full-bleed image dimmed with rapid punch-in (1.25 → 1.03 over 18f) */}
      {imgSrc ? (
        <Img
          src={imgSrc}
          style={{
            width: "100%", height: "100%", objectFit: "cover",
            filter: "brightness(0.45) contrast(1.1)",
            transform: `scale(${interpolate(frame, [0, 18, totalFrames], [1.25, 1.03, 1.06], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })})`,
            transformOrigin: "center center",
          }}
        />
      ) : (
        <div style={{ width: "100%", height: "100%", background: "linear-gradient(135deg,#3e0a1e,#b71c1c,#4a148c)" }} />
      )}
      {/* Diagonal red wash */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(135deg, rgba(211,47,47,0.35) 0%, rgba(0,0,0,0.0) 50%, rgba(0,0,0,0.85) 100%)",
          pointerEvents: "none",
        }}
      />

      {/* Top banner "突發 / BREAKING" */}
      <div
        style={{
          position: "absolute", top: 0, left: 0, right: 0, height: 150,
          backgroundColor: "#d32f2f",
          display: "flex", alignItems: "center", justifyContent: "center",
          opacity: bannerPulse,
          boxShadow: "0 10px 30px rgba(211,47,47,0.55)",
          borderBottom: "6px solid #fff",
        }}
      >
        <span
          style={{
            fontFamily: FONT_CJK, fontSize: 76, fontWeight: 900,
            color: "#fff", letterSpacing: 12,
            textShadow: "0 3px 10px rgba(0,0,0,0.6)",
          }}
        >
          ⚡ 突發快訊 BREAKING
        </span>
      </div>

      {/* Hook — huge top under banner */}
      {hook && (
        <div
          style={{
            position: "absolute", top: 210, left: 0, right: 0,
            display: "flex", justifyContent: "center",
            opacity: titleOp,
          }}
        >
          <span
            style={{
              fontFamily: FONT_CJK, fontSize: 180, fontWeight: 900,
              color: "#ffeb3b",
              letterSpacing: 6, lineHeight: 1.05,
              textShadow: "0 6px 28px rgba(0,0,0,0.9), 0 0 40px rgba(255,235,59,0.6)",
              padding: "0 40px", textAlign: "center",
            }}
          >
            {hook}
          </span>
        </div>
      )}

      {/* Title */}
      <div
        style={{
          position: "absolute", top: 480, left: 60, right: 60,
          opacity: titleOp, transform: `translateY(${titleY}px)`,
        }}
      >
        <h1
          style={{
            fontFamily: FONT_CJK, fontSize: 78, fontWeight: 900,
            color: "#fff", lineHeight: 1.2, margin: 0,
            letterSpacing: 1,
            textShadow: "0 5px 20px rgba(0,0,0,0.95)",
          }}
        >
          {title}
        </h1>
      </div>

      {/* 3 bullets as stacked red-bar cards */}
      <div
        style={{
          position: "absolute", top: 820, left: 60, right: 60,
          display: "flex", flexDirection: "column", gap: 28,
        }}
      >
        {bullets.slice(0, 3).map((b, i) => {
          const rowSpring = spring({
            fps,
            frame: Math.max(0, frame - (28 + i * 12)),
            config: { damping: 13, stiffness: 140, mass: 0.75 },
            durationInFrames: 22,
          });
          const rowX = interpolate(rowSpring, [0, 1], [-200, 0]);
          const rowOp = interpolate(rowSpring, [0, 1], [0, 1]);
          return (
            <div
              key={i}
              style={{
                display: "flex", alignItems: "stretch",
                opacity: rowOp, transform: `translateX(${rowX}px)`,
                backgroundColor: "rgba(0,0,0,0.7)",
                borderLeft: `12px solid ${accent}`,
                borderRadius: 8,
                padding: "22px 32px",
                boxShadow: "0 12px 30px rgba(0,0,0,0.6)",
              }}
            >
              <div
                style={{
                  fontFamily: FONT_CJK, fontSize: 62, fontWeight: 900,
                  color: accent,
                  marginRight: 24,
                  minWidth: 80,
                }}
              >
                {`0${i + 1}`}
              </div>
              <div
                style={{
                  fontFamily: FONT_CJK, fontSize: 58, fontWeight: 800,
                  color: "#fff", letterSpacing: 1,
                  flex: 1,
                  alignSelf: "center",
                }}
              >
                {b}
              </div>
            </div>
          );
        })}
      </div>

      {/* Source pin bottom */}
      {source && (
        <div
          style={{
            position: "absolute", bottom: 260, left: 60,
            fontFamily: FONT_CJK, fontSize: 30, fontWeight: 700,
            color: "#fff", backgroundColor: "rgba(211,47,47,0.85)",
            padding: "10px 24px", borderRadius: 4,
            letterSpacing: 2,
          }}
        >
          來源：{source}
        </div>
      )}
    </AbsoluteFill>
  );
};

// ── Flashcard: one bullet at a time, full-screen, swipes through timeline ──
const FlashcardLayout: React.FC<ArticleLayerProps> = ({
  hook, title, bullets, heroImage, fallbackImage, source,
  accent, glow, totalFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const imgSrc = heroImage || fallbackImage || "";

  // Intro card (title) holds for ~25% of duration, then 3 bullets each ~25%
  const slots = 4; // 0=title, 1-3=bullets
  const slotLen = Math.max(30, Math.floor(totalFrames / slots));
  const slotIdx = Math.min(slots - 1, Math.floor(frame / slotLen));
  const inSlotFrame = frame - slotIdx * slotLen;

  // Per-slot swipe: 0..1 fade/scale over first 12 frames of slot
  const slotProgress = interpolate(inSlotFrame, [0, 12], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  const isTitle = slotIdx === 0;
  const currentBullet = !isTitle ? (bullets[slotIdx - 1] || "") : "";

  // Index label
  const slotLabel = isTitle ? "重點整理" : `0${slotIdx} / 0${Math.min(3, bullets.length)}`;

  return (
    <AbsoluteFill style={{ backgroundColor: "#0a0a0a" }}>
      {/* Full-bleed dimmed hero with rapid zoom-in (1.3 → 1.08 over 18f) */}
      {imgSrc ? (
        <Img
          src={imgSrc}
          style={{
            width: "100%", height: "100%", objectFit: "cover",
            filter: "brightness(0.3) blur(6px)",
            transform: `scale(${interpolate(frame, [0, 18, totalFrames], [1.3, 1.08, 1.12], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })})`,
          }}
        />
      ) : (
        <div style={{ width: "100%", height: "100%", background: `linear-gradient(135deg, ${accent}40, #000)` }} />
      )}
      <AbsoluteFill style={{ background: "rgba(0,0,0,0.35)", pointerEvents: "none" }} />

      {/* Progress dots top */}
      <div
        style={{
          position: "absolute", top: 100, left: 0, right: 0,
          display: "flex", justifyContent: "center", gap: 20,
        }}
      >
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            style={{
              width: i === slotIdx ? 80 : 24,
              height: 12,
              borderRadius: 999,
              backgroundColor: i === slotIdx ? accent : "rgba(255,255,255,0.35)",
              transition: "none",
              boxShadow: i === slotIdx ? `0 0 20px ${glow}` : "none",
            }}
          />
        ))}
      </div>

      {/* Slot label */}
      <div
        style={{
          position: "absolute", top: 170, left: 0, right: 0,
          fontFamily: FONT_CJK, fontSize: 38, fontWeight: 700,
          color: accent, textAlign: "center", letterSpacing: 6,
          opacity: slotProgress,
        }}
      >
        {slotLabel}
      </div>

      {/* Center content: title slide vs bullet slide */}
      <div
        style={{
          position: "absolute", top: 0, left: 60, right: 60, bottom: 0,
          display: "flex", flexDirection: "column", justifyContent: "center",
          alignItems: "center", textAlign: "center",
          opacity: slotProgress,
          transform: `translateY(${interpolate(slotProgress, [0, 1], [30, 0])}px)`,
        }}
      >
        {isTitle ? (
          <>
            {hook && (
              <div
                style={{
                  fontFamily: FONT_CJK, fontSize: 130, fontWeight: 900,
                  color: accent, letterSpacing: 6, lineHeight: 1.08,
                  marginBottom: 40,
                  textShadow: `0 6px 30px rgba(0,0,0,0.85), 0 0 40px ${glow}`,
                }}
              >
                {hook}
              </div>
            )}
            <h1
              style={{
                fontFamily: FONT_CJK, fontSize: 86, fontWeight: 900,
                color: "#fff", lineHeight: 1.2, margin: 0,
                letterSpacing: 1, maxWidth: "100%",
                textShadow: "0 5px 22px rgba(0,0,0,0.92)",
              }}
            >
              {title}
            </h1>
          </>
        ) : (
          <div
            style={{
              fontFamily: FONT_CJK,
              fontSize: currentBullet.length > 12 ? 128 : 160,
              fontWeight: 900,
              color: "#fff", lineHeight: 1.15,
              letterSpacing: 4,
              textShadow: `0 8px 32px rgba(0,0,0,0.95), 0 0 50px ${glow}`,
              padding: "0 20px",
            }}
          >
            {currentBullet}
          </div>
        )}
      </div>

      {/* Source bottom */}
      {source && (
        <div
          style={{
            position: "absolute", bottom: 260, left: 0, right: 0,
            textAlign: "center",
            fontFamily: FONT_CJK, fontSize: 28, fontWeight: 600,
            color: "#cdd5e0", letterSpacing: 2,
          }}
        >
          📰 {source}
        </div>
      )}
    </AbsoluteFill>
  );
};
