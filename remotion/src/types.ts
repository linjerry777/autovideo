export interface TimingEntry {
  text: string;
  start: number;  // seconds
  end: number;    // seconds
}

export type SceneType =
  | "fire"     // 攻擊/爆炸/燃燒
  | "race"     // 競賽/追趕/對決
  | "money"    // 融資/估值/錢
  | "robot"    // AI/機器人/科技
  | "warning"  // 爭議/警告/風險
  | "trophy"   // 突破/獲獎/創紀錄
  | "default"  // 其他
  | string;    // also allow arbitrary free-text (LLM-resolved to recipe)

// ── Scene DSL (dynamic recipes from Claude) ─────────────────────────────────
export type EmojiAnim =
  | { kind: "pulse";  loop?: number; scale?: [number, number] }
  | { kind: "spin";   rpm?: number }
  | { kind: "bounce"; height?: number; speed?: number }
  | { kind: "drift";  dx?: number; dy?: number; speed?: number }
  | { kind: "shake";  intensity?: number }
  | { kind: "none" };

export type ParticlePattern =
  | "rain"              // 從頂部往下掉
  | "drift_up"          // 從底部往上飄
  | "scatter_twinkle"   // 隨機散佈，fade in/out
  | "burst"             // 從中央向外爆散
  | "orbit";            // 環繞中心旋轉

export type SceneLayer =
  | { type: "emoji";     value: string; x: number; y: number; size: number;
      anim?: EmojiAnim; rotate?: number; opacity?: number }
  | { type: "particles"; emoji: string; count: number; pattern: ParticlePattern;
      size?: [number, number]; color?: string; center?: [number, number] }
  | { type: "beam";      color: string; from: [number, number]; to: [number, number];
      opacity?: number; thickness?: number }
  | { type: "text";      value: string; x: number; y: number; size: number;
      color: string; opacity?: number };

export interface SceneRecipe {
  background?:
    | { type: "gradient"; colors: string[]; angle?: number }
    | { type: "solid"; color: string };
  layers: SceneLayer[];
  accent_color?: string;
}

export interface NewsItem {
  hook: string;
  title: string;
  script: string;
  source: string;
  scene_type?: SceneType;        // 原始文字（可編輯）
  scene_recipe?: SceneRecipe | null;   // LLM-resolved 結構
  screenshot: string;
  audio: string;
  timing: TimingEntry[] | null;
  duration: number;
}

export type LayoutMode = "visual" | "text";

export interface NewsVideoProps extends Record<string, unknown> {
  date: string;
  items: NewsItem[];
  /** Visual = image full-bleed bg; Text = gradient + orbs. Defaults to "visual" in renderer. */
  layout_mode?: LayoutMode;
}
