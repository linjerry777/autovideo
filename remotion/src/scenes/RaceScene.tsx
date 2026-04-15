import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

/**
 * 場景：競賽 / 追趕 / 競爭
 * - 兩個 🏃 並排奔跑（左邊較快，右邊追上）
 * - 底下地面 + 速度線條
 * - 國旗 🇨🇳🇺🇸 跟在各自上方
 * - 跑步動作用 y 震盪模擬腳步
 */
export const RaceScene: React.FC = () => {
  const frame = useCurrentFrame();

  // Ground scroll
  const groundOffset = (frame * 14) % 80;

  // Runner bounce (foot strike simulation)
  const bounceA = Math.abs(Math.sin(frame * 0.45)) * 24;
  const bounceB = Math.abs(Math.sin(frame * 0.48 + 0.3)) * 24;

  // A starts behind, catches up and overtakes by the end
  const RACE_FRAMES = 120;
  const t = (frame % RACE_FRAMES) / RACE_FRAMES;
  const runnerAX = interpolate(t, [0, 1], [140, 460]);
  const runnerBX = interpolate(t, [0, 1], [560, 620]);

  const GROUND_Y = 1500;
  const RUNNER_SIZE = 240;

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* Motion speed lines */}
      {[0, 1, 2, 3, 4].map(i => {
        const speedT = ((frame * 22 + i * 80) % 1200) / 1200;
        const y = 1050 + i * 90;
        const x = interpolate(speedT, [0, 1], [1100, -300]);
        return (
          <div
            key={`line${i}`}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: 160,
              height: 6,
              backgroundColor: "rgba(255,255,255,0.35)",
              borderRadius: 3,
              transform: "skewX(-15deg)",
              filter: "blur(1px)",
            }}
          />
        );
      })}

      {/* Ground line */}
      <div
        style={{
          position: "absolute",
          top: GROUND_Y + RUNNER_SIZE - 30,
          left: -groundOffset,
          width: 1400,
          height: 14,
          background:
            "repeating-linear-gradient(90deg, rgba(255,255,255,0.7) 0 40px, transparent 40px 80px)",
        }}
      />

      {/* Dust trail A */}
      {[0, 1, 2].map(i => {
        const dustT = ((frame + i * 12) % 30) / 30;
        return (
          <div
            key={`dustA${i}`}
            style={{
              position: "absolute",
              left: runnerAX - 30 - i * 25,
              top: GROUND_Y + RUNNER_SIZE - 50,
              fontSize: 50 + i * 10,
              opacity: interpolate(dustT, [0, 1], [0.8, 0]),
            }}
          >
            💨
          </div>
        );
      })}

      {/* Dust trail B */}
      {[0, 1, 2].map(i => {
        const dustT = ((frame + i * 12 + 6) % 30) / 30;
        return (
          <div
            key={`dustB${i}`}
            style={{
              position: "absolute",
              left: runnerBX - 30 - i * 25,
              top: GROUND_Y + RUNNER_SIZE - 50,
              fontSize: 50 + i * 10,
              opacity: interpolate(dustT, [0, 1], [0.8, 0]),
            }}
          >
            💨
          </div>
        );
      })}

      {/* Runner A (left — China) */}
      <div
        style={{
          position: "absolute",
          left: runnerAX,
          top: GROUND_Y - bounceA,
          fontSize: RUNNER_SIZE,
          filter: "drop-shadow(0 10px 20px rgba(0,0,0,0.6))",
          transform: "scaleX(1)",
        }}
      >
        🏃
      </div>
      <div
        style={{
          position: "absolute",
          left: runnerAX + 20,
          top: GROUND_Y - 120 - bounceA,
          fontSize: 120,
        }}
      >
        🇨🇳
      </div>

      {/* Runner B (right — USA) */}
      <div
        style={{
          position: "absolute",
          left: runnerBX,
          top: GROUND_Y - bounceB,
          fontSize: RUNNER_SIZE,
          filter: "drop-shadow(0 10px 20px rgba(0,0,0,0.6))",
        }}
      >
        🏃
      </div>
      <div
        style={{
          position: "absolute",
          left: runnerBX + 20,
          top: GROUND_Y - 120 - bounceB,
          fontSize: 120,
        }}
      >
        🇺🇸
      </div>
    </AbsoluteFill>
  );
};
