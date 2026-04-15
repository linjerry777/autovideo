import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import {
  EmojiAnim,
  ParticlePattern,
  SceneLayer,
  SceneRecipe,
} from "../types";

/**
 * Interprets a SceneRecipe JSON and renders it as a composed scene.
 * Claude generates recipes; this component animates them.
 */
export const SceneInterpreter: React.FC<{ recipe: SceneRecipe }> = ({ recipe }) => {
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* Background */}
      {recipe.background?.type === "gradient" && (
        <AbsoluteFill
          style={{
            background: `linear-gradient(${recipe.background.angle ?? 135}deg, ${recipe.background.colors.join(", ")})`,
          }}
        />
      )}
      {recipe.background?.type === "solid" && (
        <AbsoluteFill style={{ backgroundColor: recipe.background.color }} />
      )}

      {/* Layers */}
      {(recipe.layers ?? []).map((layer, i) => (
        <LayerRenderer key={i} layer={layer} index={i} />
      ))}
    </AbsoluteFill>
  );
};

// ── Dispatch by layer.type ───────────────────────────────────────────────────

const LayerRenderer: React.FC<{ layer: SceneLayer; index: number }> = ({ layer, index }) => {
  if (layer.type === "emoji")     return <EmojiLayer layer={layer} />;
  if (layer.type === "particles") return <ParticlesLayer layer={layer} seed={index} />;
  if (layer.type === "beam")      return <BeamLayer layer={layer} />;
  if (layer.type === "text")      return <TextLayer layer={layer} />;
  return null;
};

// ── Emoji layer ──────────────────────────────────────────────────────────────

const EmojiLayer: React.FC<{ layer: Extract<SceneLayer, { type: "emoji" }> }> = ({ layer }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const { tx, ty, scale, rotate, opacity } = applyAnim(layer.anim, t, frame);
  const finalOpacity = (layer.opacity ?? 1) * opacity;

  return (
    <div
      style={{
        position: "absolute",
        left: layer.x - layer.size / 2 + tx,
        top:  layer.y - layer.size / 2 + ty,
        fontSize: layer.size,
        transform: `scale(${scale}) rotate(${(layer.rotate ?? 0) + rotate}deg)`,
        opacity: finalOpacity,
        lineHeight: 1,
        filter: "drop-shadow(0 8px 24px rgba(0,0,0,0.55))",
      }}
    >
      {layer.value}
    </div>
  );
};

// Resolve animation deltas from an EmojiAnim spec
function applyAnim(anim: EmojiAnim | undefined, t: number, frame: number) {
  const base = { tx: 0, ty: 0, scale: 1, rotate: 0, opacity: 1 };
  if (!anim || anim.kind === "none") return base;

  if (anim.kind === "pulse") {
    const loop = anim.loop ?? 1.2;
    const [lo, hi] = anim.scale ?? [0.9, 1.15];
    const phase = (t % loop) / loop;        // 0..1
    const wave = Math.sin(phase * Math.PI * 2) * 0.5 + 0.5;  // 0..1 smooth
    return { ...base, scale: lo + (hi - lo) * wave };
  }

  if (anim.kind === "spin") {
    const rpm = anim.rpm ?? 20;
    return { ...base, rotate: (t * rpm * 6) % 360 };
  }

  if (anim.kind === "bounce") {
    const height = anim.height ?? 60;
    const speed  = anim.speed ?? 1.5;
    const y = Math.abs(Math.sin(t * Math.PI * speed)) * -height;
    return { ...base, ty: y };
  }

  if (anim.kind === "drift") {
    const dx = anim.dx ?? 20;
    const dy = anim.dy ?? -30;
    const speed = anim.speed ?? 0.5;
    return {
      ...base,
      tx: Math.sin(t * speed * 2) * dx,
      ty: Math.cos(t * speed * 1.3) * dy,
    };
  }

  if (anim.kind === "shake") {
    const intensity = anim.intensity ?? 8;
    return {
      ...base,
      tx: (Math.random() - 0.5) * intensity * 2,  // cheap shake; deterministic per frame below
      ty: (Math.sin(frame * 0.9) * intensity),
      rotate: Math.sin(frame * 0.7) * 3,
    };
  }

  return base;
}

// ── Particles layer ─────────────────────────────────────────────────────────

const ParticlesLayer: React.FC<{
  layer: Extract<SceneLayer, { type: "particles" }>;
  seed: number;
}> = ({ layer, seed }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const items = Array.from({ length: Math.min(layer.count, 60) });
  const [sMin, sMax] = layer.size ?? [50, 120];

  return (
    <>
      {items.map((_, i) => {
        const r = pseudoRand(seed * 1000 + i);
        const size = sMin + r * (sMax - sMin);
        const { x, y, opacity, rotate } = particlePos(layer.pattern, i, items.length, t, r, layer.center);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x - size / 2,
              top:  y - size / 2,
              fontSize: size,
              opacity,
              lineHeight: 1,
              transform: `rotate(${rotate}deg)`,
              pointerEvents: "none",
            }}
          >
            {layer.emoji}
          </div>
        );
      })}
    </>
  );
};

function particlePos(
  pattern: ParticlePattern,
  i: number,
  total: number,
  t: number,
  r: number,
  center?: [number, number],
) {
  const cx = center?.[0] ?? 540;
  const cy = center?.[1] ?? 960;

  if (pattern === "rain") {
    const loop = 3 + r * 2;
    const phase = ((t + i * 0.2) % loop) / loop;
    return {
      x: 60 + pseudoRand(i * 31) * 960,
      y: -100 + phase * 2100,
      opacity: phase < 0.05 ? phase * 20 : phase > 0.9 ? (1 - phase) * 10 : 1,
      rotate: Math.sin((t + i) * 2) * 10,
    };
  }

  if (pattern === "drift_up") {
    const loop = 4 + r * 2;
    const phase = ((t + i * 0.3) % loop) / loop;
    const driftX = Math.sin((t + i) * 1.5) * 60;
    return {
      x: 60 + pseudoRand(i * 17) * 960 + driftX,
      y: 2000 - phase * 2200,
      opacity: phase < 0.15 ? phase / 0.15 : phase > 0.8 ? (1 - phase) / 0.2 : 1,
      rotate: Math.sin((t + i) * 1.2) * 15,
    };
  }

  if (pattern === "scatter_twinkle") {
    const loop = 2.5;
    const phase = ((t + r * loop) % loop) / loop;
    const twinkle = Math.sin(phase * Math.PI * 2) * 0.5 + 0.5;
    return {
      x: 50 + pseudoRand(i * 71) * 980,
      y: 150 + pseudoRand(i * 13) * 1700,
      opacity: 0.3 + twinkle * 0.7,
      rotate: 0,
    };
  }

  if (pattern === "burst") {
    const loop = 2.5;
    const phase = ((t + r * 0.3) % loop) / loop;
    const angle = (i / total) * Math.PI * 2;
    const dist = phase * 900;
    return {
      x: cx + Math.cos(angle) * dist,
      y: cy + Math.sin(angle) * dist,
      opacity: phase < 0.1 ? phase * 10 : (1 - phase),
      rotate: angle * 57.3,
    };
  }

  if (pattern === "orbit") {
    const radius = 350 + r * 150;
    const speed  = 0.3 + r * 0.2;
    const angle  = t * speed + (i / total) * Math.PI * 2;
    return {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
      opacity: 0.8,
      rotate: angle * 57.3,
    };
  }

  return { x: cx, y: cy, opacity: 1, rotate: 0 };
}

// Deterministic cheap pseudo-random [0..1]
function pseudoRand(seed: number): number {
  const x = Math.sin(seed * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

// ── Beam layer ───────────────────────────────────────────────────────────────

const BeamLayer: React.FC<{ layer: Extract<SceneLayer, { type: "beam" }> }> = ({ layer }) => {
  const frame = useCurrentFrame();
  const pulse = interpolate(frame % 60, [0, 30, 60], [0.6, 1, 0.6]);
  const [x1, y1] = layer.from;
  const [x2, y2] = layer.to;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const length = Math.sqrt(dx * dx + dy * dy);
  const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
  const thickness = layer.thickness ?? 8;

  return (
    <div
      style={{
        position: "absolute",
        left: x1,
        top: y1 - thickness / 2,
        width: length,
        height: thickness,
        transformOrigin: "0 50%",
        transform: `rotate(${angle}deg)`,
        background: `linear-gradient(90deg, transparent 0%, ${layer.color} 50%, transparent 100%)`,
        opacity: (layer.opacity ?? 0.6) * pulse,
        filter: "blur(2px)",
      }}
    />
  );
};

// ── Text layer ──────────────────────────────────────────────────────────────

const TextLayer: React.FC<{ layer: Extract<SceneLayer, { type: "text" }> }> = ({ layer }) => (
  <div
    style={{
      position: "absolute",
      left: layer.x,
      top: layer.y,
      fontSize: layer.size,
      color: layer.color,
      opacity: layer.opacity ?? 1,
      fontWeight: 800,
      fontFamily: '"Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif',
      textShadow: "0 4px 20px rgba(0,0,0,0.7)",
      whiteSpace: "nowrap",
    }}
  >
    {layer.value}
  </div>
);
