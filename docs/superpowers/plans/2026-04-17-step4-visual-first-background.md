# Step 4 — Visual-First Background Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `item.screenshot` (the high-quality og:image from Step 2) from small 360×420 decoration to full-bleed 1080×1920 video background with slow Ken Burns zoom. Text elements (hook, title, subtitle) become overlays with reinforced `textShadow` for legibility over any image. New `layout_mode` prop defaults to `"visual"` for new jobs; existing `"text"` mode preserved unchanged for backward compatibility and user choice.

**Architecture:**
- New `NewsVideoProps.layout_mode: "visual" | "text"` — read by `remotion_renderer.py` from `news.json` (defaults to `"visual"` when missing).
- New `BackgroundLayer.tsx` component — takes `imgSrc` + `palette` + `totalFrames`, renders either: (a) `<Img>` full-bleed with Ken Burns zoom + scrim gradient, or (b) gradient fallback matching current backdrop when image missing.
- `NewsItemComponent` branches on `layout_mode`: visual mode replaces the existing "gradient + floating orbs" block with `<BackgroundLayer>` (scene overlay still runs on top), removes the screenshot-inside-info-card (now redundant with bg), and ratchets up `textShadow` on hook/title/subtitle for legibility. Text mode unchanged.
- Scene overlays (FireScene / RaceScene / SceneInterpreter) continue to render in both modes — they sit on the zIndex layer above the background.

**Tech Stack:** Remotion 4.x (existing), React, TypeScript, Python (remotion_renderer bridge).

---

## Visual Comparison

```
TEXT MODE (existing, preserved):      VISUAL MODE (new default):
┌──────────────────────┐              ┌──────────────────────┐
│ [gradient + orbs]    │              │ [IMAGE FULL-BLEED]   │
│                      │              │ [+ Ken Burns 1→1.08] │
│   ✨ HOOK ✨        │              │                      │
│                      │              │  HOOK (on image)     │
│  ┌───────────┐      │              │                      │
│  │ [screenshot]│     │              │  [scrim at bottom]   │
│  └───────────┘      │              │   Title (overlay)    │
│  📰 來源            │              │   📰 來源             │
│  字幕                │              │   字幕 (overlay)      │
└──────────────────────┘              └──────────────────────┘
```

**Text shadow rules (visual mode):**
- Hook: `drop-shadow(0 4px 20px rgba(0,0,0,0.9))` + existing gradient fill
- Title: `textShadow: 0 4px 24px rgba(0,0,0,0.95)` (stronger than current 0.8)
- Subtitle: `textShadow: 0 2px 12px rgba(0,0,0,0.9)` (already strong, bump slightly)
- Counter badge + source badge: unchanged (they have their own bg)

---

## File Map

| File | Change |
|------|--------|
| `remotion/src/types.ts` | Add `layout_mode?: "visual" \| "text"` to `NewsVideoProps` |
| `scripts/remotion_renderer.py` | Read `data.get("layout_mode", "visual")` and pass in props |
| `remotion/src/BackgroundLayer.tsx` | CREATE — image-with-Ken-Burns or gradient fallback |
| `remotion/src/NewsVideo.tsx` | Pass `layout_mode` prop into each `NewsItemComponent` |
| `remotion/src/NewsItem.tsx` | Accept `layout_mode` prop; branch rendering; strengthen textShadow in visual mode; drop nested screenshot from info card in visual mode |

---

## Task 1: Add `layout_mode` to types

**Files:**
- Modify: `remotion/src/types.ts`

Add one optional field to `NewsVideoProps` and a type alias for the two modes. No runtime change yet — this just establishes the contract for later tasks.

- [ ] **Step 1: Add the `LayoutMode` type and the `layout_mode` field**

At the bottom of `remotion/src/types.ts` (just before the closing of `NewsVideoProps`), replace:

```ts
export interface NewsVideoProps extends Record<string, unknown> {
  date: string;
  items: NewsItem[];
}
```

With:

```ts
export type LayoutMode = "visual" | "text";

export interface NewsVideoProps extends Record<string, unknown> {
  date: string;
  items: NewsItem[];
  /** Visual = image full-bleed bg; Text = gradient + orbs. Defaults to "visual" in renderer. */
  layout_mode?: LayoutMode;
}
```

- [ ] **Step 2: Verify types compile**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo/remotion
npx tsc --noEmit
```
Expected: exit 0, no errors.

- [ ] **Step 3: Commit**

```bash
cd ..
git add remotion/src/types.ts
git commit -m "feat: add LayoutMode type + layout_mode to NewsVideoProps"
```

---

## Task 2: Thread `layout_mode` through the renderer

**Files:**
- Modify: `scripts/remotion_renderer.py` — `build_props()` function (~line 120-170)

Read `layout_mode` from `news.json` top-level field (default `"visual"` when missing), pass into props dict consumed by Remotion.

- [ ] **Step 1: Update `build_props()`**

Find `scripts/remotion_renderer.py:build_props()`. Its current return has:

```python
    return {
        "date":  TODAY,
        "items": items_out,
    }
```

Replace with:

```python
    # layout_mode: default "visual" (image full-bleed); accept "text" for legacy look
    layout_mode = (raw.get("layout_mode") or "visual").lower()
    if layout_mode not in ("visual", "text"):
        layout_mode = "visual"

    return {
        "date":        TODAY,
        "items":       items_out,
        "layout_mode": layout_mode,
    }
```

Note: `raw` is the dict produced earlier in the function by `json.loads(news_file.read_text(...))`. Find that line near the top of `build_props()` and confirm the variable name — if it's different (e.g. `news` or `data`), use the matching name.

- [ ] **Step 2: Syntax check**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/remotion_renderer.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Dry-test props shape (no Remotion render)**

```bash
python -X utf8 -c "
import sys
sys.path.insert(0, '.')
from pathlib import Path
from scripts.remotion_renderer import build_props
# Use job 69's news.json
props = build_props(Path('pipeline/2026-04-17/job_69'), Path('pipeline/2026-04-17/job_69/news.json'))
print('layout_mode:', props.get('layout_mode'))
print('items:', len(props.get('items', [])))
assert props.get('layout_mode') == 'visual', 'default must be visual'
print('OK')
"
```

Expected:
```
layout_mode: visual
items: 1
OK
```

- [ ] **Step 4: Commit**

```bash
git add scripts/remotion_renderer.py
git commit -m "feat: remotion_renderer passes layout_mode prop (default visual)"
```

---

## Task 3: Create `BackgroundLayer` component

**Files:**
- Create: `remotion/src/BackgroundLayer.tsx`

Encapsulates the new visual-first backdrop: full-bleed `<Img>` with Ken Burns zoom + scrim gradient, or gradient fallback if image is missing.

- [ ] **Step 1: Create `remotion/src/BackgroundLayer.tsx`**

```tsx
import React from "react";
import { AbsoluteFill, Img, interpolate, useCurrentFrame } from "remotion";

export interface BackgroundPalette {
  bg1: string;
  bg2: string;
  bg3: string;
  glow: string;
}

interface Props {
  imgSrc: string;         // data URL or file URL; empty string → gradient fallback
  totalFrames: number;    // sequence duration, used to scale Ken Burns
  palette: BackgroundPalette;
}

/**
 * Full-bleed image with slow Ken Burns zoom + scrim, OR gradient fallback.
 *
 * Ken Burns: scale 1.0 → 1.08 over the sequence + 15px horizontal drift.
 * Scrim: dark gradient at top (10% opacity) and bottom (80% opacity) for text legibility.
 */
export const BackgroundLayer: React.FC<Props> = ({
  imgSrc,
  totalFrames,
  palette,
}) => {
  const frame = useCurrentFrame();

  const scale = interpolate(frame, [0, totalFrames], [1.0, 1.08], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const driftX = interpolate(frame, [0, totalFrames], [0, 15], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  if (!imgSrc) {
    // Gradient fallback (matches "text mode" feel)
    return (
      <AbsoluteFill
        style={{
          background: `linear-gradient(135deg, ${palette.bg1} 0%, ${palette.bg2} 55%, ${palette.bg3} 100%)`,
        }}
      />
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: palette.bg1 }}>
      <Img
        src={imgSrc}
        style={{
          width:           "100%",
          height:          "100%",
          objectFit:       "cover",
          transform:       `scale(${scale}) translateX(${driftX}px)`,
          transformOrigin: "center center",
        }}
      />

      {/* Scrim: top dark + bottom dark gradient for text legibility */}
      <AbsoluteFill
        style={{
          background:
            "linear-gradient(180deg, " +
            "rgba(0,0,0,0.45) 0%, " +
            "rgba(0,0,0,0.0) 25%, " +
            "rgba(0,0,0,0.0) 55%, " +
            "rgba(0,0,0,0.75) 100%)",
          pointerEvents: "none",
        }}
      />
    </AbsoluteFill>
  );
};
```

- [ ] **Step 2: TypeScript check**

```bash
cd remotion && npx tsc --noEmit
```
Expected: 0 errors. (It's fine if this doesn't USE the component yet — that's Task 4.)

- [ ] **Step 3: Commit**

```bash
cd ..
git add remotion/src/BackgroundLayer.tsx
git commit -m "feat: BackgroundLayer component — full-bleed Img + Ken Burns + scrim or gradient fallback"
```

---

## Task 4: Branch NewsItem rendering on `layout_mode`

**Files:**
- Modify: `remotion/src/NewsVideo.tsx` — pass `layout_mode` down
- Modify: `remotion/src/NewsItem.tsx` — accept prop, branch rendering, strengthen textShadow

### Part A: Pass the prop down

- [ ] **Step 1: Update `NewsVideo.tsx` to forward `layout_mode`**

In `remotion/src/NewsVideo.tsx`, find the component signature:

```tsx
export const NewsVideo: React.FC<NewsVideoProps> = ({ items }) => {
```

Change to:

```tsx
export const NewsVideo: React.FC<NewsVideoProps> = ({ items, layout_mode = "visual" }) => {
```

Then find the `<NewsItemComponent>` JSX and add the prop:

```tsx
          <NewsItemComponent
            item={item}
            index={idx}
            totalFrames={durationFrames}
          />
```

Change to:

```tsx
          <NewsItemComponent
            item={item}
            index={idx}
            totalFrames={durationFrames}
            layout_mode={layout_mode}
          />
```

### Part B: Update `NewsItem.tsx`

- [ ] **Step 2: Import BackgroundLayer + LayoutMode at top of NewsItem.tsx**

Find the existing imports block at top of `remotion/src/NewsItem.tsx`:

```tsx
import { NewsItem as NewsItemType, SceneType } from "./types";
import { Subtitle } from "./Subtitle";
import { FireScene } from "./scenes/FireScene";
import { RaceScene } from "./scenes/RaceScene";
import { SceneInterpreter } from "./scenes/SceneInterpreter";
```

Add these two lines:

```tsx
import { NewsItem as NewsItemType, SceneType, LayoutMode } from "./types";
import { Subtitle } from "./Subtitle";
import { FireScene } from "./scenes/FireScene";
import { RaceScene } from "./scenes/RaceScene";
import { SceneInterpreter } from "./scenes/SceneInterpreter";
import { BackgroundLayer } from "./BackgroundLayer";
```

(The `LayoutMode` is added to the existing types import; `BackgroundLayer` is a new line.)

- [ ] **Step 3: Add `layout_mode` to `NewsItemProps`**

Find:

```tsx
interface NewsItemProps {
  item: NewsItemType;
  index: number;
  totalFrames: number;
}
```

Replace with:

```tsx
interface NewsItemProps {
  item: NewsItemType;
  index: number;
  totalFrames: number;
  layout_mode?: LayoutMode;
}
```

And the component destructure:

```tsx
export const NewsItemComponent: React.FC<NewsItemProps> = ({
  item,
  index,
  totalFrames,
}) => {
```

Change to:

```tsx
export const NewsItemComponent: React.FC<NewsItemProps> = ({
  item,
  index,
  totalFrames,
  layout_mode = "visual",
}) => {
```

- [ ] **Step 4: Replace the gradient + orbs block with a conditional**

Find this block (starting right after `{audioSrc && <Audio .../>}`):

```tsx
      {/* Animated gradient backdrop */}
      <AbsoluteFill
        style={{
          background: `linear-gradient(${bgAngle}deg, ${palette.bg1} 0%, ${palette.bg2} ${50 + bgPulse}%, ${palette.bg3} 100%)`,
        }}
      />

      {/* Drifting glow orbs */}
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
```

Replace with:

```tsx
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
```

- [ ] **Step 5: Strengthen hook text shadow in visual mode**

Find the HOOK hero `<span>` block (around line 220) with this style block:

```tsx
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
            filter: `drop-shadow(0 0 30px ${palette.glow})`,
          }}
        >
```

Replace the `filter` line with a conditional that adds a strong black drop-shadow in visual mode (improves legibility when image is behind):

```tsx
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
```

- [ ] **Step 6: Skip nested screenshot inside info card when visual mode (it's the bg now)**

Find the screenshot render inside the info card (~line 277):

```tsx
          {screenshotSrc && (
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
```

Change the guard to also check layout mode:

```tsx
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
```

- [ ] **Step 7: Strengthen title textShadow in visual mode**

Find the `<h1>` title inside the info card (~line 262):

```tsx
          <h1
            style={{
              fontFamily: FONT_CJK,
              fontSize: 78,
              fontWeight: 800,
              color: "#ffffff",
              lineHeight: 1.25,
              margin: 0,
              letterSpacing: 1,
              textShadow: "0 4px 20px rgba(0,0,0,0.8)",
            }}
          >
            {item.title}
          </h1>
```

Replace the `textShadow` line with:

```tsx
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
```

- [ ] **Step 8: TypeScript check**

```bash
cd remotion && npx tsc --noEmit
```
Expected: 0 errors.

- [ ] **Step 9: Commit**

```bash
cd ..
git add remotion/src/NewsVideo.tsx remotion/src/NewsItem.tsx
git commit -m "feat: NewsItem branches on layout_mode — visual=full-bleed image, text=existing"
```

---

## Task 5: E2E render comparison

**Files:**
- None modified — render + visual inspection.

- [ ] **Step 1: Render job 69 in default (visual) mode**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
# Clean existing output so we get a fresh render
rm -f pipeline/2026-04-17/job_69/output.mp4

python -X utf8 scripts/remotion_renderer.py 2026-04-17/job_69 2>&1 | tail -15
```

Expected: exits cleanly, `output.mp4` generated. No TypeScript or runtime errors from Remotion.

- [ ] **Step 2: Read the `output.mp4` metadata**

```bash
python -X utf8 -c "
import subprocess
r = subprocess.run(['ffprobe','-v','error',
    '-show_entries','format=duration,size:stream=width,height,codec_name',
    '-of','default=noprint_wrappers=1','pipeline/2026-04-17/job_69/output.mp4'],
    capture_output=True, text=True)
print(r.stdout)
"
```

Expected: `width=1080`, `height=1920`, `duration~11` (matches audio_01.mp3 of 10.4s + ~0.3s crossfade tail).

- [ ] **Step 3: Render same job in "text" mode for comparison**

Temporarily patch news.json:

```bash
python -X utf8 -c "
import json
from pathlib import Path
p = Path('pipeline/2026-04-17/job_69/news.json')
data = json.loads(p.read_text(encoding='utf-8'))
data['layout_mode'] = 'text'
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print('patched layout_mode → text')
"

# Save the visual-mode render aside
cp pipeline/2026-04-17/job_69/output.mp4 /tmp/output_visual.mp4

# Re-render in text mode
rm -f pipeline/2026-04-17/job_69/output.mp4
python -X utf8 scripts/remotion_renderer.py 2026-04-17/job_69 2>&1 | tail -5
cp pipeline/2026-04-17/job_69/output.mp4 /tmp/output_text.mp4

# Revert news.json back to visual
python -X utf8 -c "
import json
from pathlib import Path
p = Path('pipeline/2026-04-17/job_69/news.json')
data = json.loads(p.read_text(encoding='utf-8'))
data['layout_mode'] = 'visual'
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print('reverted → visual')
"

# Final render stays as visual
rm -f pipeline/2026-04-17/job_69/output.mp4
python -X utf8 scripts/remotion_renderer.py 2026-04-17/job_69 2>&1 | tail -5

echo ""
echo "Compare:"
ls -la /tmp/output_visual.mp4 /tmp/output_text.mp4 pipeline/2026-04-17/job_69/output.mp4
```

Expected: all 3 files exist, sizes similar (~2-3 MB for 10 second 1080p video). Open both `/tmp/output_visual.mp4` and `/tmp/output_text.mp4` in a media player to visually compare.

**Visual acceptance criteria:**
- `output_visual.mp4`: screenshot fills entire frame with slow zoom; text overlays readable against image (scrim present); no floating orbs
- `output_text.mp4`: gradient background with purple/pink orbs; screenshot as small card in middle; same as before

- [ ] **Step 4: Commit (E2E marker)**

```bash
# Cleanup comparison files
rm -f /tmp/output_visual.mp4 /tmp/output_text.mp4

git commit --allow-empty -m "test: Step 4 visual-first layout E2E — both modes render cleanly"
```

---

## Self-Review

**1. Spec coverage:**
- Full-bleed image background → Task 3 (BackgroundLayer) + Task 4 Step 4 (render in visual mode) ✅
- Ken Burns zoom (scale 1.0 → 1.08) → Task 3 Step 1 `interpolate` ✅
- Scrim gradient for text legibility → Task 3 Step 1 ✅
- Enhanced textShadow (hook + title) in visual mode → Task 4 Steps 5, 7 ✅
- Skip nested screenshot in info card (visual mode) → Task 4 Step 6 ✅
- Text mode preserved exactly → Task 4 Step 4 (the `<>...</>` branch is the ORIGINAL code, untouched) ✅
- Gradient fallback when image missing → Task 3 Step 1 (the `if (!imgSrc)` branch) ✅
- Default to "visual" for new jobs → Task 2 Step 1 `raw.get("layout_mode") or "visual"` ✅
- User can opt back to text mode → Task 5 Step 3 demonstrates by patching news.json ✅

**2. Placeholder scan:** All steps have concrete code. The visual acceptance criteria in Task 5 Step 3 are measurable (check scrim present, no orbs in visual mode).

**3. Type consistency:**
- `LayoutMode = "visual" | "text"` — Task 1 defines, Tasks 2-4 use consistently ✅
- `layout_mode` property name (snake_case) — matches JSON convention in news.json, consistent across types.ts + remotion_renderer + NewsVideo.tsx + NewsItem.tsx ✅
- `BackgroundPalette` interface in BackgroundLayer.tsx (Task 3) matches `palette` prop passed from NewsItem.tsx (Task 4 Step 4) — both use `bg1/bg2/bg3/glow` keys ✅
- `totalFrames` prop on BackgroundLayer matches the same prop already on NewsItem — consistent ✅

**4. Scope check:** Single subsystem — Step 4 (Remotion video composition). 5 tasks, all touching only `remotion/src/*` + `scripts/remotion_renderer.py`. No DB schema, no new endpoints, no frontend (Alpine UI). Acceptable as a single plan.
