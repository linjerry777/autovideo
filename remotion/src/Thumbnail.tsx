import React from "react";
import { AbsoluteFill, Img } from "remotion";

const FONT_CJK = '"Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif';

export interface ThumbnailProps extends Record<string, unknown> {
  hook:       string;
  title:      string;
  screenshot: string;   // data URL or http URL
  variant?:   "figure_quote" | string;
  figure?:    string;
  logo?:      string;
  palette?:   { bg1: string; bg2: string; bg3: string; accent: string; glow: string };
}

const DEFAULT_PALETTE = {
  bg1: "#1a0033", bg2: "#4a148c", bg3: "#880e4f",
  accent: "#ff6bcb", glow: "rgba(255,107,203,0.5)",
};

export const Thumbnail: React.FC<ThumbnailProps> = (props) => {
  const { hook, title, screenshot, palette } = props;
  const p = palette ?? DEFAULT_PALETTE;

  if (props.variant === "figure_quote") {
    return (
      <AbsoluteFill style={{ backgroundColor: "#050505", overflow: "hidden" }}>
        {screenshot && (
          <>
            <Img
              src={screenshot}
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                objectFit: "cover",
                filter: "blur(28px) brightness(0.42) saturate(0.85)",
                transform: "scale(1.08)",
              }}
            />
            <Img
              src={screenshot}
              style={{
                position: "absolute",
                left: 86,
                top: 470,
                width: 908,
                height: 760,
                objectFit: "cover",
                borderRadius: 24,
                boxShadow: "0 42px 120px rgba(0,0,0,0.82), 0 0 0 4px rgba(255,210,52,0.86)",
              }}
            />
          </>
        )}

        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "linear-gradient(180deg, rgba(0,0,0,0.82) 0%, rgba(0,0,0,0.08) 43%, rgba(0,0,0,0.90) 100%)",
          }}
        />

        <div
          style={{
            position: "absolute",
            left: 70,
            top: 74,
            display: "flex",
            alignItems: "center",
            gap: 20,
          }}
        >
          {props.logo && <Img src={props.logo} style={{ width: 112, height: 112, borderRadius: 24 }} />}
        </div>

        <div
          style={{
            position: "absolute",
            left: 58,
            right: 58,
            top: 170,
            fontFamily: FONT_CJK,
            fontSize: hook.length > 5 ? 142 : 176,
            fontWeight: 950,
            lineHeight: 1.02,
            color: "#fff03a",
            textShadow: "0 8px 0 #000, 0 22px 50px rgba(0,0,0,0.85)",
          }}
        >
          {hook || "這句值得聽"}
        </div>

        <div
          style={{
            position: "absolute",
            left: 70,
            right: 70,
            bottom: 150,
            fontFamily: FONT_CJK,
            fontSize: title.length > 16 ? 66 : 78,
            fontWeight: 900,
            lineHeight: 1.18,
            color: "#ffffff",
            textShadow: "0 6px 28px rgba(0,0,0,1)",
          }}
        >
          {title}
        </div>

        {props.figure && (
          <div
            style={{
              position: "absolute",
              left: 72,
              bottom: 90,
              fontFamily: FONT_CJK,
              fontSize: 34,
              fontWeight: 800,
              color: "#111111",
              backgroundColor: "#fff03a",
              padding: "8px 18px",
              borderRadius: 12,
            }}
          >
            名人金句解析
          </div>
        )}
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(150deg, ${p.bg1} 0%, ${p.bg2} 55%, ${p.bg3} 100%)`,
      }}
    >
      {/* Corner glow */}
      <div
        style={{
          position: "absolute",
          left: -200, top: 200,
          width: 900, height: 900,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${p.glow} 0%, transparent 65%)`,
          filter: "blur(60px)",
        }}
      />

      {/* HOOK — huge, gradient text, top third */}
      <div
        style={{
          position: "absolute",
          top: 180,
          left: 0, right: 0,
          display: "flex", justifyContent: "center",
        }}
      >
        <span
          style={{
            fontFamily: FONT_CJK,
            fontSize: 220,
            fontWeight: 900,
            letterSpacing: 12,
            textAlign: "center",
            padding: "0 60px",
            lineHeight: 1.05,
            background: `linear-gradient(180deg, #ffffff 0%, ${p.accent} 100%)`,
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            filter: `drop-shadow(0 0 40px ${p.glow})`,
          }}
        >
          {hook || "AI快訊"}
        </span>
      </div>

      {/* Screenshot — middle, rounded */}
      {screenshot && (
        <div
          style={{
            position: "absolute",
            left: 80, right: 80,
            top: 720,
            height: 700,
            borderRadius: 40,
            overflow: "hidden",
            boxShadow: `0 40px 100px rgba(0,0,0,0.7), 0 0 0 4px ${p.accent}60`,
          }}
        >
          <Img src={screenshot} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </div>
      )}

      {/* Title badge — bottom */}
      <div
        style={{
          position: "absolute",
          bottom: 140,
          left: 60, right: 60,
          textAlign: "center",
        }}
      >
        <span
          style={{
            fontFamily: FONT_CJK,
            fontSize: 64,
            fontWeight: 800,
            color: "#ffffff",
            backgroundColor: "rgba(0,0,0,0.65)",
            borderRadius: 28,
            padding: "20px 40px",
            letterSpacing: 2,
            display: "inline-block",
            maxWidth: 960,
            lineHeight: 1.25,
            whiteSpace: "normal",
            wordBreak: "break-word",
            textShadow: "0 4px 20px rgba(0,0,0,0.9)",
            border: `2px solid ${p.accent}80`,
          }}
        >
          {title}
        </span>
      </div>
    </AbsoluteFill>
  );
};
