import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

/**
 * 場景：攻擊 / 燃燒 / 爆炸
 * - 房子 🏠 在右下
 * - 多顆燃燒瓶 🔥🧨 從左邊弧形飛向房子（循環）
 * - 爆炸時紅色閃光 + 屏幕震動
 * - 火焰粒子向上漂浮
 */
export const FireScene: React.FC = () => {
  const frame = useCurrentFrame();

  const bombs = [
    { delay: 0,  startX: -150, startY: 900 },
    { delay: 25, startX: -150, startY: 700 },
    { delay: 50, startX: -150, startY: 1050 },
    { delay: 80, startX: -200, startY: 850 },
  ];

  const LOOP = 100; // 100 frames per bomb cycle
  const HOUSE_X = 640;
  const HOUSE_Y = 1200;

  // Red flash timing — when any bomb hits
  const anyImpact = bombs.some(b => ((frame - b.delay) % LOOP) > 55 && ((frame - b.delay) % LOOP) < 62);
  const flashOpacity = anyImpact ? 0.5 : 0;

  // Screen shake on impact
  const shake = anyImpact ? (Math.sin(frame * 3) * 6) : 0;

  return (
    <AbsoluteFill style={{ transform: `translate(${shake}px, 0)`, pointerEvents: "none" }}>
      {/* Red impact flash */}
      <AbsoluteFill
        style={{
          backgroundColor: "rgba(255, 40, 20, 1)",
          opacity: flashOpacity,
          mixBlendMode: "screen",
        }}
      />

      {/* House */}
      <div
        style={{
          position: "absolute",
          left: HOUSE_X,
          top: HOUSE_Y,
          fontSize: 260,
          filter: `drop-shadow(0 10px 30px rgba(0,0,0,0.8)) ${anyImpact ? "brightness(1.4) hue-rotate(-30deg)" : ""}`,
          transform: `rotate(${anyImpact ? -2 : 0}deg)`,
        }}
      >
        🏠
      </div>

      {/* Flying bombs/molotovs */}
      {bombs.map((b, i) => {
        const t = ((frame - b.delay) % LOOP) / LOOP; // 0..1
        const beforeImpact = t < 0.6;
        // Parabolic arc: x linear, y = start + dip - gravity
        const x = interpolate(t, [0, 0.6], [b.startX, HOUSE_X + 20], { extrapolateRight: "clamp" });
        const arc = Math.sin(t * Math.PI / 0.6) * 400;
        const y = beforeImpact ? b.startY - arc : HOUSE_Y;
        const scale = beforeImpact ? 1 : interpolate(t, [0.6, 0.85], [2.5, 0], { extrapolateRight: "clamp" });
        const rot = beforeImpact ? frame * 8 + i * 30 : 0;
        const opacity = beforeImpact ? 1 : interpolate(t, [0.6, 0.85], [1, 0]);

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x,
              top: y,
              fontSize: 110,
              transform: `rotate(${rot}deg) scale(${scale})`,
              opacity,
              filter: "drop-shadow(0 0 20px rgba(255,100,0,0.9))",
            }}
          >
            {beforeImpact ? "🔥" : "💥"}
          </div>
        );
      })}

      {/* Rising fire particles from house */}
      {[0, 1, 2, 3, 4, 5].map(i => {
        const cycle = 60;
        const localT = ((frame + i * 10) % cycle) / cycle;
        const opacity = interpolate(localT, [0, 0.3, 1], [0, 1, 0]);
        const y = HOUSE_Y - localT * 400;
        const x = HOUSE_X + 40 + Math.sin(localT * Math.PI * 2 + i) * 60;
        return (
          <div
            key={`p${i}`}
            style={{
              position: "absolute",
              left: x,
              top: y,
              fontSize: 60 + (i % 3) * 20,
              opacity,
              filter: "drop-shadow(0 0 12px rgba(255,120,0,0.8))",
            }}
          >
            🔥
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
