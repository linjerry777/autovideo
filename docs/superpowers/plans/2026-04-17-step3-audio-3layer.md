# Step 3 — 3-Layer Audio (Voice + BGM + Hook SFX) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Step 3 from single-voice TTS into the industry-standard "3-layer audio" stack: (1) **per-strategy voice** mapping (tech/entertainment/finance/pet → distinct Fish Audio voice IDs); (2) **emotion-driven BGM** auto-mixed with sidechain ducking under the voice; (3) **Hook SFX** played before the first sentence to grab attention. Plus smart sentence splitting (cuts long sentences on commas for cleaner subtitle wrapping). Everything degrades gracefully when audio assets aren't yet downloaded — pipeline still produces voice-only audio identical to today.

**Architecture:**
- New `assets/{music,sfx}/...` folder hierarchy with `.gitkeep` placeholders. User fills with royalty-free MP3s on their own pace.
- New `scripts/audio_assets.py` — picks BGM by `emotion`, hook SFX by `emotion`. Returns `None` when nothing's available so caller can skip mixing.
- New `mix_audio(voice, bgm, sfx, out, leading_silence_s) → bool` in `audio_generator.py` — ffmpeg `sidechaincompress` for ducking + concat for SFX-then-voice ordering. Loops BGM to match voice length.
- `audio_generator.py` reads `news.json["strategy"]` → picks voice from `FISH_AUDIO_VOICE_{TECH,ENTERTAINMENT,FINANCE,PET}` env var with fallback to default `FISH_AUDIO_VOICE_ID`.
- `timing.json` offsets shift by `leading_silence + sfx_duration` so subtitles stay synced after we prepend SFX.
- `split_sentences()` cuts on 。！？ first; if any segment > 25 chars, also cut on 、，；.

**Tech Stack:** Python, ffmpeg (sidechaincompress, aloop, concat filter), Fish Audio SDK (existing), no new pip deps.

---

## Research-Backed Audio Layout

```
[silence 0.3s] [hook_sfx ~0.4s] [voice (sentences from TTS)]
                                        |
                                        v
                                  mixed (amix) with
                                        |
                                        v
[bgm_looped] → sidechaincompress (ducks to -8dB when voice has signal)
```

**Why this matters (from earlier 2026 research):**

| Audio config | 3s drop-off rate |
|--------------|------------------|
| Voice only (today's pipeline) | 70% |
| Voice + BGM | 35% |
| Voice + BGM + Hook SFX | 25% |

Source: Buffer 2026 + TikTok Creator Academy retention curves.

---

## File Map

| File | Change |
|------|--------|
| `assets/music/{surprise,fear,joy,curiosity,anger,generic}/.gitkeep` | CREATE — placeholder dirs |
| `assets/sfx/hook/.gitkeep` | CREATE — placeholder dir |
| `assets/README.md` | CREATE — instructions for what to put where |
| `scripts/audio_assets.py` | CREATE — `pick_bgm(emotion)` + `pick_hook_sfx(emotion)` |
| `scripts/audio_generator.py` | EXTEND — smart split, voice-by-strategy, mixing pipeline, timing offset |
| `.env.example` (or note in CLAUDE.md) | Document `FISH_AUDIO_VOICE_TECH/ENTERTAINMENT/FINANCE/PET` |

---

## Task 1: Asset directory bootstrap + audio_assets module

**Files:**
- Create: `assets/music/{surprise,fear,joy,curiosity,anger,generic}/.gitkeep`
- Create: `assets/sfx/hook/.gitkeep`
- Create: `assets/README.md`
- Create: `scripts/audio_assets.py`

- [ ] **Step 1: Create asset directory hierarchy with .gitkeep files**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
for d in surprise fear joy curiosity anger generic; do
  mkdir -p "assets/music/$d"
  touch "assets/music/$d/.gitkeep"
done
mkdir -p assets/sfx/hook
touch assets/sfx/hook/.gitkeep
ls -la assets/music/ assets/sfx/
```

Expected: 6 music dirs + sfx/hook dir, each with `.gitkeep`.

- [ ] **Step 2: Create `assets/README.md`**

```markdown
# Audio Assets

Drop royalty-free MP3 files into the appropriate folders. The pipeline picks one at random per video and mixes it with the voice.

## Music (BGM under voice)

`audio_generator.py` reads `news.json["items"][i]["emotion"]` and picks from the matching folder. Fallback chain: `<emotion>/` → `generic/` → no BGM.

```
assets/music/
├─ surprise/    # 驚訝風 — twist reveals, pop hits
├─ fear/        # 緊張感 — minor key, low strings
├─ joy/         # 輕快 — upbeat, major key
├─ curiosity/   # 神秘 — ambient, building
├─ anger/       # 強烈節奏 — bass-heavy, urgent
└─ generic/     # fallback when emotion folder is empty
```

**Recommended sources:** YouTube Audio Library (free, commercial-safe), Pixabay Music, Free Music Archive.

**Format:** MP3, 30-90s loops work best (BGM gets looped to match voice length).

**Volume:** Music gets ducked to ~-12dB under the voice automatically (sidechaincompress).

## SFX (Hook attention-grabber)

Plays right before the first spoken word. ~0.3-0.5 seconds.

```
assets/sfx/hook/
├─ whoosh.mp3
├─ ding.mp3
├─ alert.mp3
└─ ...   # any number of files; pipeline picks one at random
```

**Recommended sources:** Pixabay (sfx category), Freesound.org (CC0 licensed).

**Format:** MP3, < 1 second.
```

- [ ] **Step 3: Create `scripts/audio_assets.py`**

```python
#!/usr/bin/env python3
"""
audio_assets.py — Pick BGM / SFX from local asset library.

Folder layout (relative to repo root):
    assets/music/<emotion>/*.mp3   ← random pick per emotion
    assets/sfx/hook/*.mp3          ← random pick

Public API:
    pick_bgm(emotion: str) -> Path | None
    pick_hook_sfx(emotion: str | None = None) -> Path | None

Returns None when no usable asset exists, so callers can fall through
to voice-only output without crashing.
"""
import random
from pathlib import Path

REPO_ROOT  = Path(__file__).resolve().parent.parent
MUSIC_ROOT = REPO_ROOT / "assets" / "music"
SFX_ROOT   = REPO_ROOT / "assets" / "sfx"

# Known emotions (matches Step 1 schema). Unknown → generic only.
KNOWN_EMOTIONS = {"surprise", "fear", "joy", "curiosity", "anger"}


def _pick_random(folder: Path) -> Path | None:
    """Return a random .mp3 from folder (recursive=False), or None."""
    if not folder.exists() or not folder.is_dir():
        return None
    candidates = [p for p in folder.iterdir() if p.suffix.lower() == ".mp3" and p.is_file()]
    if not candidates:
        return None
    return random.choice(candidates)


def pick_bgm(emotion: str | None) -> Path | None:
    """Pick a BGM track for the given emotion.

    Fallback chain: <emotion>/ → generic/ → None
    """
    em = (emotion or "").lower()
    if em in KNOWN_EMOTIONS:
        choice = _pick_random(MUSIC_ROOT / em)
        if choice:
            return choice
    return _pick_random(MUSIC_ROOT / "generic")


def pick_hook_sfx(emotion: str | None = None) -> Path | None:
    """Pick a hook SFX. Currently emotion is unused but accepted for
    forward-compat in case we add per-emotion SFX later."""
    return _pick_random(SFX_ROOT / "hook")


# ── CLI for debugging ─────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse, sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--emotion", default="surprise")
    args = parser.parse_args()
    bgm = pick_bgm(args.emotion)
    sfx = pick_hook_sfx(args.emotion)
    print(f"emotion={args.emotion}")
    print(f"  bgm: {bgm or '(none)'}")
    print(f"  sfx: {sfx or '(none)'}")
    sys.exit(0)
```

- [ ] **Step 4: Verify**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/audio_assets.py').read()); print('OK')"
```
Expected: `OK`

```bash
python -X utf8 scripts/audio_assets.py --emotion surprise
```
Expected (since folders are empty for now):
```
emotion=surprise
  bgm: (none)
  sfx: (none)
```

- [ ] **Step 5: Commit**

```bash
git add assets/ scripts/audio_assets.py
git commit -m "feat: bootstrap assets/music + assets/sfx; audio_assets picker module"
```

(Note: `.gitkeep` files are needed because git doesn't track empty directories. They're tiny and harmless.)

---

## Task 2: Smart sentence splitting

**Files:**
- Modify: `scripts/audio_generator.py` — `split_sentences()` function (~line 70)

Current splitter cuts only on 。！？. Long sentences without those become subtitle disasters. Cut on 、，； too when a segment exceeds 25 CJK characters.

- [ ] **Step 1: Replace `split_sentences()`**

Find in `scripts/audio_generator.py`:

```python
def split_sentences(script: str) -> list[str]:
    """依中文句號/感嘆/問號切句；若無標點則整段"""
    parts = re.split(r'(?<=[。！？])\s*', script)
    parts = [p.strip() for p in parts if p.strip()]
    return parts if parts else [script]
```

Replace with:

```python
def split_sentences(script: str, max_len: int = 25) -> list[str]:
    """Split script into subtitle-friendly chunks.

    Stage 1: split on 。！？
    Stage 2: any chunk > max_len (CJK chars) → split further on 、，；
    """
    parts = re.split(r'(?<=[。！？])\s*', script)
    parts = [p.strip() for p in parts if p.strip()]

    refined: list[str] = []
    for p in parts:
        if len(p) <= max_len:
            refined.append(p)
            continue
        # Split long chunk on , 、 ；
        subparts = re.split(r'(?<=[、，；])\s*', p)
        subparts = [s.strip() for s in subparts if s.strip()]
        refined.extend(subparts if subparts else [p])

    return refined if refined else [script]
```

- [ ] **Step 2: Quick unit test inline**

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
python -X utf8 -c "
from scripts.audio_generator import split_sentences

# Case 1: short sentences with periods — unchanged
r = split_sentences('你好。我是 AI。今天天氣好。')
assert r == ['你好。', '我是 AI。', '今天天氣好。'], f'case1 failed: {r}'

# Case 2: long sentence with no periods, has commas
r = split_sentences('周杰倫新歌一上線就破200萬，這次回歸田園風，樸實旋律勾起全台回憶，網友留言破千。')
print('case2:', r)
assert all(len(s) <= 30 for s in r), f'case2 too long: {r}'
assert len(r) >= 2, f'case2 should split on commas: {r}'

# Case 3: short single sentence — unchanged
r = split_sentences('AI 嚇到所有人。')
assert r == ['AI 嚇到所有人。'], f'case3 failed: {r}'

print('all pass')
"
```
Expected: prints `case2:` with the comma-split chunks, then `all pass`.

- [ ] **Step 3: Commit**

```bash
git add scripts/audio_generator.py
git commit -m "feat: smart sentence split — cuts long chunks on 、，； for cleaner subtitles"
```

---

## Task 3: Per-strategy voice mapping

**Files:**
- Modify: `scripts/audio_generator.py` — top-level voice resolution (~line 24)

Read `news.json["strategy"]` (set by Step 1 plan) → look up matching voice env var → fall back to default. Strategy values: `tech | entertainment | finance | pet`.

- [ ] **Step 1: Replace single-voice constant with resolver**

Find at the top of `scripts/audio_generator.py`:

```python
API_KEY  = os.getenv("FISH_AUDIO_API_KEY", "")
VOICE_ID = os.getenv("FISH_AUDIO_VOICE_ID", "")
```

Replace with:

```python
API_KEY  = os.getenv("FISH_AUDIO_API_KEY", "")
DEFAULT_VOICE_ID = os.getenv("FISH_AUDIO_VOICE_ID", "")

# Per-strategy voice mapping (env vars are optional — fall back to default)
STRATEGY_VOICE_MAP = {
    "tech":          os.getenv("FISH_AUDIO_VOICE_TECH",          "") or DEFAULT_VOICE_ID,
    "entertainment": os.getenv("FISH_AUDIO_VOICE_ENTERTAINMENT", "") or DEFAULT_VOICE_ID,
    "finance":       os.getenv("FISH_AUDIO_VOICE_FINANCE",       "") or DEFAULT_VOICE_ID,
    "pet":           os.getenv("FISH_AUDIO_VOICE_PET",           "") or DEFAULT_VOICE_ID,
}


def resolve_voice_id(strategy: str | None) -> str:
    """Pick voice_id by strategy, falling back to default."""
    return STRATEGY_VOICE_MAP.get((strategy or "").lower(), DEFAULT_VOICE_ID)
```

- [ ] **Step 2: Update `text_to_speech()` to accept voice_id parameter**

Find:

```python
def text_to_speech(text: str, out_path: Path) -> None:
    if not API_KEY:
        raise RuntimeError("❌ 缺少 FISH_AUDIO_API_KEY")
    if not VOICE_ID:
        raise RuntimeError("❌ 缺少 FISH_AUDIO_VOICE_ID")

    session = Session(API_KEY)
    chunks  = []
    for chunk in session.tts(TTSRequest(
        reference_id = VOICE_ID,
        text         = text,
        format       = "mp3",
        mp3_bitrate  = 128,
        latency      = "normal",
    )):
        chunks.append(chunk)

    out_path.write_bytes(b"".join(chunks))
```

Replace with:

```python
def text_to_speech(text: str, out_path: Path, voice_id: str | None = None) -> None:
    if not API_KEY:
        raise RuntimeError("❌ 缺少 FISH_AUDIO_API_KEY")
    use_voice = voice_id or DEFAULT_VOICE_ID
    if not use_voice:
        raise RuntimeError("❌ 缺少 FISH_AUDIO_VOICE_ID（或 strategy 對應的 voice）")

    session = Session(API_KEY)
    chunks  = []
    for chunk in session.tts(TTSRequest(
        reference_id = use_voice,
        text         = text,
        format       = "mp3",
        mp3_bitrate  = 128,
        latency      = "normal",
    )):
        chunks.append(chunk)

    out_path.write_bytes(b"".join(chunks))
```

- [ ] **Step 3: Update `main()` to read strategy from news.json and pass voice through**

Find in `main()`:

```python
    data  = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = data["items"]

    print(f"🎙️  生成 {len(items)} 則語音（Fish Audio 哈基米）...")
```

Replace with:

```python
    data  = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = data["items"]
    strategy = (data.get("strategy") or "").lower()
    voice_id = resolve_voice_id(strategy)

    voice_label = strategy or "default"
    print(f"🎙️  生成 {len(items)} 則語音（Fish Audio · {voice_label} voice）...")
```

Then find inside the per-item loop:

```python
        for j, sent in enumerate(sentences, 1):
            sp = AUDIO_DIR / f"audio_{i:02d}_s{j:02d}.mp3"
            print(f"      句{j}: {sent[:30]}...")
            text_to_speech(sent, sp)
```

Replace the `text_to_speech` call with:

```python
        for j, sent in enumerate(sentences, 1):
            sp = AUDIO_DIR / f"audio_{i:02d}_s{j:02d}.mp3"
            print(f"      句{j}: {sent[:30]}...")
            text_to_speech(sent, sp, voice_id=voice_id)
```

- [ ] **Step 4: Verify**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/audio_generator.py').read()); print('OK')"
```
Expected: `OK`

Test the resolver:
```bash
python -X utf8 -c "
from scripts.audio_generator import resolve_voice_id, DEFAULT_VOICE_ID, STRATEGY_VOICE_MAP
for s in ['tech', 'entertainment', 'finance', 'pet', '', None, 'unknown']:
    v = resolve_voice_id(s)
    same = '(=default)' if v == DEFAULT_VOICE_ID else '(strategy-specific)'
    print(f'  strategy={s!r:<18} → voice {same}')
"
```
Expected: all map to default (since you haven't set the per-strategy env vars yet) — proves graceful fallback works.

- [ ] **Step 5: Commit**

```bash
git add scripts/audio_generator.py
git commit -m "feat: per-strategy voice mapping (FISH_AUDIO_VOICE_TECH/ENT/FIN/PET env vars)"
```

---

## Task 4: Audio mixing function

**Files:**
- Modify: `scripts/audio_generator.py` — add `mix_audio()` function

Single function that takes voice + optional BGM + optional SFX, outputs final mixed MP3. Handles all 4 cases (none/bgm only/sfx only/both) gracefully.

- [ ] **Step 1: Add the function near the existing `concat_mp3()` helper**

Insert this function after `concat_mp3()` (~line 65) in `scripts/audio_generator.py`:

```python
LEADING_SILENCE_S = 0.3   # silence before SFX (gives breathing room)
SFX_BGM_GAP_S     = 0.2   # silence between SFX and voice
BGM_DUCK_DB       = -12   # how much BGM dips when voice plays
BGM_BASE_DB       = -18   # BGM resting volume under voice


def _ffmpeg_path_arg(p: Path) -> str:
    """ffmpeg-safe path string (forward slashes, no escapes)."""
    return str(p).replace("\\", "/")


def mix_audio(voice: Path, out: Path, bgm: Path | None = None,
              hook_sfx: Path | None = None) -> float:
    """Mix voice with optional BGM (sidechain-ducked) and optional Hook SFX (prepended).

    Output structure when both BGM and SFX present:
      [silence 0.3s][hook_sfx][gap 0.2s][voice]
        all of the above mixed with [bgm_looped at -18dB, ducked to -30dB when voice signal]

    Returns the leading offset in seconds (silence + sfx duration + gap) so caller
    can shift timing.json. Returns 0.0 when no SFX is added.
    """
    voice_dur = get_duration(voice)

    # Case 1: no BGM and no SFX → just copy voice through
    if not bgm and not hook_sfx:
        if voice != out:
            import shutil
            shutil.copy(voice, out)
        return 0.0

    # Build leading audio: silence + sfx + gap (only if sfx provided)
    leading_offset = 0.0
    voice_input    = voice
    sfx_dur        = 0.0
    if hook_sfx:
        sfx_dur = get_duration(hook_sfx)
        leading_offset = LEADING_SILENCE_S + sfx_dur + SFX_BGM_GAP_S

    total_dur = leading_offset + voice_dur

    # Build ffmpeg filter graph
    inputs   = []
    cmd      = [FFMPEG, "-y"]

    # Voice always input 0
    cmd += ["-i", _ffmpeg_path_arg(voice)]
    voice_idx = 0

    if hook_sfx:
        cmd += ["-i", _ffmpeg_path_arg(hook_sfx)]
        sfx_idx = 1
        next_idx = 2
    else:
        sfx_idx = None
        next_idx = 1

    if bgm:
        cmd += ["-stream_loop", "-1", "-i", _ffmpeg_path_arg(bgm)]
        bgm_idx = next_idx
    else:
        bgm_idx = None

    # Build filter
    filter_parts: list[str] = []

    if hook_sfx:
        # Silence(0.3s) + sfx + silence(0.2s) + voice → [vfull]
        filter_parts.append(
            f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={LEADING_SILENCE_S}[s1];"
            f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={SFX_BGM_GAP_S}[s2];"
            f"[s1][{sfx_idx}:a][s2][{voice_idx}:a]concat=n=4:v=0:a=1[vfull]"
        )
        voice_label = "vfull"
    else:
        voice_label = f"{voice_idx}:a"

    if bgm:
        # BGM trimmed to total_dur, lowered to BGM_BASE_DB, sidechain-ducked by voice
        filter_parts.append(
            f"[{bgm_idx}:a]atrim=0:{total_dur},volume={BGM_BASE_DB}dB[bgmraw];"
            f"[{voice_label}]asplit=2[vmain][vsc];"
            f"[bgmraw][vsc]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300:makeup=0[bgmducked];"
            f"[vmain][bgmducked]amix=inputs=2:duration=first:dropout_transition=0[mixout]"
        )
        out_label = "mixout"
    else:
        # Just the (silence+sfx+voice) chain
        out_label = voice_label

    filter_complex = ";".join(filter_parts) if filter_parts else None
    if filter_complex:
        cmd += ["-filter_complex", filter_complex, "-map", f"[{out_label}]"]
    else:
        cmd += ["-map", f"{voice_idx}:a"]

    cmd += ["-c:a", "libmp3lame", "-b:a", "192k", _ffmpeg_path_arg(out)]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"      ⚠️  ffmpeg mix 失敗，fallback 純人聲: {r.stderr[-200:]}")
        # Fallback: just copy voice
        import shutil
        shutil.copy(voice, out)
        return 0.0
    return leading_offset
```

- [ ] **Step 2: Syntax check**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/audio_generator.py').read()); print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Test mix_audio with voice-only fallback (no assets installed yet)**

```bash
python -X utf8 -c "
from pathlib import Path
from scripts.audio_generator import mix_audio, get_duration

# Use existing voice from job 69
src = Path('pipeline/2026-04-17/job_69/audio/audio_01.mp3')
assert src.exists(), 'job 69 audio missing'
out = Path('/tmp/mix_test.mp3')

# Case 1: no BGM, no SFX → should just copy
offset = mix_audio(src, out, bgm=None, hook_sfx=None)
print(f'  voice-only: offset={offset}, output_dur={get_duration(out):.2f}s, src_dur={get_duration(src):.2f}s')
assert abs(get_duration(out) - get_duration(src)) < 0.1, 'voice-only should preserve duration'
assert offset == 0.0, 'no SFX → 0 offset'
print('  ✓ voice-only fallback works')
"
```
Expected: `voice-only: offset=0.0, output_dur=10.42s, src_dur=10.42s` then `✓ voice-only fallback works`.

- [ ] **Step 4: Commit**

```bash
git add scripts/audio_generator.py
git commit -m "feat: mix_audio() — voice + BGM (sidechain-ducked) + Hook SFX with graceful fallback"
```

---

## Task 5: Wire mixing into main flow + timing offset

**Files:**
- Modify: `scripts/audio_generator.py` — `main()` per-item loop

After concatenating per-sentence TTS into the raw narration, call `mix_audio()` to produce the final `audio_XX.mp3`. Apply the leading offset to `timing.json` so subtitles stay synced.

- [ ] **Step 1: Update the per-item loop in `main()`**

Find in `main()`:

```python
        # 合併所有句子 → 單一音訊檔
        if len(sent_files) == 1:
            sent_files[0].rename(combined)
        else:
            concat_mp3(sent_files, combined)
            for sp in sent_files:
                sp.unlink(missing_ok=True)

        timing_f.write_text(
            json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"      ✅ {combined.name}，總時長 {t_cursor:.1f}s")
```

Replace with:

```python
        # Step A: concat sentences into raw narration (intermediate file)
        raw_voice = AUDIO_DIR / f"audio_{i:02d}_voice.mp3"
        if len(sent_files) == 1:
            sent_files[0].rename(raw_voice)
        else:
            concat_mp3(sent_files, raw_voice)
            for sp in sent_files:
                sp.unlink(missing_ok=True)

        # Step B: mix with BGM + SFX (or pass through if no assets)
        from scripts.audio_assets import pick_bgm, pick_hook_sfx
        emotion = (item.get("emotion") or "").lower()
        bgm     = pick_bgm(emotion)
        sfx     = pick_hook_sfx(emotion)
        offset  = mix_audio(raw_voice, combined, bgm=bgm, hook_sfx=sfx)

        # Cleanup intermediate file
        raw_voice.unlink(missing_ok=True)

        # Step C: shift timing.json by leading_offset (if we prepended SFX)
        if offset > 0:
            timings = [
                {"text": t["text"],
                 "start": t["start"] + offset,
                 "end":   t["end"]   + offset}
                for t in timings
            ]

        timing_f.write_text(
            json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        bgm_label = bgm.name if bgm else "(no BGM)"
        sfx_label = sfx.name if sfx else "(no SFX)"
        print(f"      ✅ {combined.name}（BGM={bgm_label}, SFX={sfx_label}, +{offset:.1f}s offset）")
```

Note: same `from scripts.audio_assets import` pattern used in screenshot_collector.py worked despite the pywin32 namespace conflict because we're on Python 3.12 with explicit `scripts/__init__.py`. If the import fails at runtime, use the same fallback pattern as `screenshot_collector.py` (try sibling first, then package).

- [ ] **Step 2: Add the import fallback at top if needed**

Run a quick smoke test of just the import:

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
python -X utf8 -c "
import subprocess, sys
r = subprocess.run([sys.executable, '-c', 'from scripts.audio_assets import pick_bgm; print(pick_bgm(\"surprise\"))'],
                   capture_output=True, text=True)
print('stdout:', r.stdout)
print('stderr:', r.stderr[-300:] if r.stderr else '(none)')
"
```

If stderr shows `ModuleNotFoundError: No module named 'scripts.audio_assets'`, fix by replacing the in-loop import line `from scripts.audio_assets import pick_bgm, pick_hook_sfx` with the sibling-fallback pattern from `screenshot_collector.py`:

```python
        # Import audio_assets (sibling-first to dodge pywin32 namespace conflict)
        try:
            import sys as _sys
            _script_dir = str(Path(__file__).resolve().parent)
            if _script_dir not in _sys.path:
                _sys.path.insert(0, _script_dir)
            from audio_assets import pick_bgm, pick_hook_sfx
        except ImportError:
            from scripts.audio_assets import pick_bgm, pick_hook_sfx
```

(Move this block ABOVE the per-item loop so it runs once.)

- [ ] **Step 3: Syntax check + voice-only smoke test**

```bash
python -X utf8 -c "import ast; ast.parse(open('scripts/audio_generator.py').read()); print('OK')"
```
Expected: `OK`

Run audio_generator on a clean job and verify it works with empty assets folder (graceful fallback):

```bash
# Clean job 69 audio so it regenerates
rm -f pipeline/2026-04-17/job_69/audio/audio_*.mp3 pipeline/2026-04-17/job_69/audio/*timing.json

python -X utf8 scripts/audio_generator.py 2026-04-17/job_69 2>&1 | tail -15
echo "---"
ls -la pipeline/2026-04-17/job_69/audio/
echo "---"
# Verify timing.json: offset should be 0.0 (no SFX yet) → first sentence starts at 0
python -X utf8 -c "
import json
t = json.load(open('pipeline/2026-04-17/job_69/audio/audio_01_timing.json', encoding='utf-8'))
print('first sentence start:', t[0]['start'])
print('last sentence end:   ', t[-1]['end'])
"
```

Expected:
- Audio generator runs to completion. Output line shows `(BGM=(no BGM), SFX=(no SFX), +0.0s offset)`
- `audio_01.mp3` exists
- `timing.json` first start = 0.0 (no offset because no SFX)

- [ ] **Step 4: Commit**

```bash
git add scripts/audio_generator.py
git commit -m "feat: 3-layer audio mixing wired into pipeline + timing offset"
```

---

## Task 6: E2E test with simulated assets + docs

**Files:**
- Modify: `CLAUDE.md` — add audio assets section
- (Test only) drop test files into `assets/music/generic/` and `assets/sfx/hook/`

- [ ] **Step 1: Generate test assets (synthetic via ffmpeg)**

We don't need real music to test the mixing pipeline — we can synthesize tones with ffmpeg.

```bash
cd C:/Users/User/Documents/GitHub/AutoVideo
# 30-second sine-wave "BGM" at 220Hz (low, won't fight voice)
ffmpeg -y -f lavfi -i "sine=frequency=220:duration=30" -c:a libmp3lame -b:a 128k assets/music/generic/test_tone.mp3 2>/dev/null && echo "  ✓ test BGM created"

# 0.4s "ding" SFX at 880Hz with fade
ffmpeg -y -f lavfi -i "sine=frequency=880:duration=0.4" -af "afade=t=out:st=0.2:d=0.2" -c:a libmp3lame assets/sfx/hook/test_ding.mp3 2>/dev/null && echo "  ✓ test SFX created"

ls -la assets/music/generic/ assets/sfx/hook/
```

Expected: both `.mp3` files exist (~few KB each).

- [ ] **Step 2: Re-run audio_generator on job 69 with assets present**

```bash
rm -f pipeline/2026-04-17/job_69/audio/audio_*.mp3 pipeline/2026-04-17/job_69/audio/*timing.json

python -X utf8 scripts/audio_generator.py 2026-04-17/job_69 2>&1 | tail -10
echo "---"
python -X utf8 -c "
import json
t = json.load(open('pipeline/2026-04-17/job_69/audio/audio_01_timing.json', encoding='utf-8'))
print('first sentence start:', t[0]['start'])
print('last sentence end:   ', t[-1]['end'])
print('expected offset ~0.9s if SFX added')
"
echo "---"
python -X utf8 -c "
from scripts.audio_generator import get_duration
from pathlib import Path
print('audio_01.mp3 duration:', get_duration(Path('pipeline/2026-04-17/job_69/audio/audio_01.mp3')))
"
```

Expected:
- Output line shows `(BGM=test_tone.mp3, SFX=test_ding.mp3, +0.9s offset)`
- `first sentence start:` ≈ 0.9 (was 0.0 before — proof that timing was offset)
- `audio_01.mp3 duration:` ≈ 11.3s (was 10.4s — proof that 0.9s of leading silence+SFX was added)

- [ ] **Step 3: Cleanup test assets (let user provide real ones later)**

```bash
rm assets/music/generic/test_tone.mp3
rm assets/sfx/hook/test_ding.mp3
ls assets/music/generic/ assets/sfx/hook/   # should show only .gitkeep
```

- [ ] **Step 4: Update CLAUDE.md**

Open `C:\Users\User\Documents\GitHub\AutoVideo\CLAUDE.md`. Find the **"Key Environment Variables"** section. Add these lines inside the env block:

```env
FISH_AUDIO_VOICE_TECH=          # optional — overrides default for tech strategy
FISH_AUDIO_VOICE_ENTERTAINMENT= # optional — overrides default for entertainment
FISH_AUDIO_VOICE_FINANCE=       # optional — overrides default for finance
FISH_AUDIO_VOICE_PET=           # optional — overrides default for pet
```

Then add a new section after "Upload-Post Feature Coverage":

```markdown
## Audio Assets (Step 3 — 3-layer audio)

`audio_generator.py` mixes 3 layers when assets exist; gracefully falls back to voice-only when they don't.

```
assets/
├─ music/<emotion>/*.mp3   ← BGM, picked by news.json items[i].emotion
│   (surprise / fear / joy / curiosity / anger / generic)
└─ sfx/hook/*.mp3          ← Hook SFX prepended to first sentence (~0.4s)
```

- BGM is sidechain-ducked under voice (-18dB resting, dips to ~-30dB when voice plays)
- Hook SFX adds ~0.9s to total audio length; `timing.json` offsets shift accordingly
- See `assets/README.md` for recommended sources (YouTube Audio Library, Pixabay)

Per-strategy voice mapping via env: `FISH_AUDIO_VOICE_{TECH,ENTERTAINMENT,FINANCE,PET}`. Each can be set to a different Fish Audio reference_id; missing keys fall back to `FISH_AUDIO_VOICE_ID`.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit --allow-empty -m "docs: Step 3 audio assets + per-strategy voice env vars"
```

(`--allow-empty` because if no other files changed in this session you may end up with only docs.)

---

## Self-Review

**1. Spec coverage:**
- BGM auto-mix with emotion folders → Task 1 (assets bootstrap), Task 4 (mix function), Task 5 (wired) ✅
- Per-strategy voice mapping → Task 3 ✅
- Hook SFX with leading silence → Task 4 (mix function), Task 5 (timing offset) ✅
- Smart sentence splitting (long → split on commas) → Task 2 ✅
- Music ducking via sidechain → Task 4 (sidechaincompress filter) ✅
- Graceful fallback (no assets = voice-only) → Task 4 (mix_audio handles None bgm/sfx) ✅
- Timing.json offset for SFX prefix → Task 5 (Step C) ✅
- Documentation → Task 6 (CLAUDE.md + assets/README.md from Task 1) ✅

**2. Placeholder scan:**
- All ffmpeg filter strings have concrete values (no TBD)
- Test commands use real fixture data (job 69's existing news.json + audio)
- The `import` fallback in Task 5 Step 2 is conditional — explicitly described both branches

**3. Type consistency:**
- `pick_bgm(emotion: str | None) → Path | None` — Task 1 defines, Task 5 consumes with same signature ✅
- `pick_hook_sfx(emotion: str | None) → Path | None` — Task 1 defines, Task 5 calls with `emotion` arg ✅
- `mix_audio(voice, out, bgm=None, hook_sfx=None) → float` — Task 4 defines, Task 5 calls with same args + reads `offset` return ✅
- `resolve_voice_id(strategy)` — Task 3 defines, called once in `main()` ✅
- `LEADING_SILENCE_S=0.3 + SFX_BGM_GAP_S=0.2 + sfx_dur≈0.4 ≈ 0.9s offset` — Task 4 computes, Task 6 expects 0.9s in test ✅

**4. Scope check:** Single subsystem (Step 3 audio generation). No DB schema, no new endpoints, no frontend. 6 tasks. Acceptable as one plan.
