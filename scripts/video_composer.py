#!/usr/bin/env python3
"""
Video Composer (Windows版)
風格：截圖居中 + 背景模糊 + 中文字幕 (參考 SnapInsta 風格)

佈局 (1080x1920):
  ┌──────────────────────┐
  │  hook 鉤子文字 (頂)  │ ~120px
  ├──────────────────────┤
  │  模糊背景填滿        │
  │  ┌─────────────────┐ │
  │  │  新聞截圖居中   │ │  主視覺區
  │  │  (1080px寬)     │ │
  │  └─────────────────┘ │
  ├──────────────────────┤
  │  中文字幕大字 (底)   │ ~250px
  └──────────────────────┘
"""
import json, os, re, shutil, subprocess, sys, tempfile, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from datetime import date
from pathlib import Path

TODAY     = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
BASE_DIR  = Path(__file__).parent.parent
PIPE_DIR  = BASE_DIR / "pipeline" / TODAY
NEWS_FILE = PIPE_DIR / "news.json"
SHOTS_DIR = PIPE_DIR / "screenshots"
AUDIO_DIR = PIPE_DIR / "audio"
SEG_DIR   = PIPE_DIR / "segments"
OUTPUT    = PIPE_DIR / "output.mp4"

W, H = 1080, 1920                     # 9:16
FONT_ZH   = r"C:/Windows/Fonts/msjhbd.ttc"   # 微軟正黑體 Bold
FONT_ZH_B = r"C:/Windows/Fonts/msjh.ttc"     # 微軟正黑體 Regular
HOOK_COLOR   = "FFD700"   # 金黃色
SUB_COLOR    = "FFFFFF"   # 白色

# 每則新聞背景色調 (hue 旋轉角度，讓三段視覺有明顯差異)
ITEM_HUE = [0, 130, 220]   # 偏原色、偏綠、偏藍

# assets 路徑
ASSETS_DIR  = BASE_DIR / "assets"
BGM_PATH    = ASSETS_DIR / "music" / "bgm.mp3"     # 背景音樂（可選）
INTRO_PATH  = ASSETS_DIR / "brand" / "intro.mp4"   # 片頭（可選）
OUTRO_PATH  = ASSETS_DIR / "brand" / "outro.mp4"   # 片尾（可選）
BGM_VOLUME  = 0.08   # 背景音樂音量（0.0~1.0，預設 8%）


# ── ffmpeg 路徑偵測 ──────────────────────────────────────────────────

def find_ffmpeg() -> tuple[str, str]:
    """回傳 (ffmpeg路徑, ffprobe路徑)"""
    if shutil.which("ffmpeg"):
        return "ffmpeg", "ffprobe"

    winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / \
        "Microsoft/WinGet/Packages"
    for root, dirs, files in os.walk(winget_base):
        for f in files:
            if f.lower() == "ffmpeg.exe":
                bin_dir = Path(root)
                return str(bin_dir / "ffmpeg.EXE"), str(bin_dir / "ffprobe.EXE")

    raise RuntimeError(
        "找不到 ffmpeg！請執行：winget install Gyan.FFmpeg"
    )


FFMPEG, FFPROBE = find_ffmpeg()


def run(cmd: list, desc: str = "") -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(f"❌ {desc or cmd[0]} 錯誤:\n{result.stderr[-2000:]}", file=sys.stderr)
        raise RuntimeError(f"ffmpeg 失敗: {desc}")
    return result


def get_duration(path: Path) -> float:
    r = subprocess.run([
        FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ], capture_output=True, text=True)
    return float(r.stdout.strip())


# ── 字幕處理 ────────────────────────────────────────────────────────

def wrap_ass(text: str, max_chars: int = 13) -> str:
    """中文換行，用 ASS \\N 硬換行符"""
    lines, buf = [], ""
    for ch in text:
        buf += ch
        if len(buf) >= max_chars:
            lines.append(buf)
            buf = ""
        elif buf and ch in "，。！？、；":
            lines.append(buf)
            buf = ""
    if buf:
        lines.append(buf)
    return r"\N".join(lines)          # ASS hard newline


def split_script(script: str, n_chunks: int = 4) -> list[str]:
    """把腳本按句子斷成 n 段，每段套用 ASS 換行"""
    sents = re.split(r"(?<=[！？。，、])", script)
    sents = [s.strip() for s in sents if s.strip()]
    if not sents:
        sents = [script]

    chunks, buf, target = [], "", len(script) / n_chunks
    for s in sents:
        buf += s
        if len(buf) >= target and len(chunks) < n_chunks - 1:
            chunks.append(wrap_ass(buf))
            buf = ""
    if buf:
        chunks.append(wrap_ass(buf))

    while len(chunks) < n_chunks:
        chunks.append(" ")
    return chunks[:n_chunks]


def make_ass(chunks: list[str], durations: list[tuple[float,float]], out_path: str):
    """產生 ASS 字幕檔（含底部半透明底框 + 多行中文）"""
    def ts(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # BorderStyle=3: opaque box背景; Bold=1; 字大粗體半透明黑底塊風格
        "Style: Main,Microsoft JhengHei,72,&H00FFFFFF,&H000000FF,"
        "&H00000000,&H99000000,1,0,0,0,100,100,2,0,3,0,0,2,60,60,175,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = ""
    for chunk, (start, end) in zip(chunks, durations):
        # \fad(in_ms, out_ms) 淡入200ms、淡出100ms
        events += f"Dialogue: 0,{ts(start)},{ts(end)},Main,,0,0,0,,{{\\fad(200,100)}}{chunk}\n"

    with open(out_path, "w", encoding="utf-8-sig") as f:
        f.write(header + events)


# ── 單一片段合成 ─────────────────────────────────────────────────────

def make_segment(
    screenshot: Path,
    audio: Path,
    hook: str,
    script: str,
    out_path: Path,
    timing: list[dict] | None = None,   # [{text, start, end}, ...]
    hue: int = 0,                        # 背景色調偏移角度
    broll: Path | None = None,           # B-roll 影片（優先於截圖）
):
    audio_dur = get_duration(audio)
    duration  = audio_dur + 0.3
    use_video = broll is not None and broll.exists()

    # ── 字幕分段 ────────────────────────────────────────────────────
    if timing:
        # 用 Fish Audio 逐句時長精確對齊
        chunks    = [wrap_ass(t["text"]) for t in timing]
        sub_times = [(t["start"], min(t["end"], duration)) for t in timing]
    else:
        # fallback：等比切 4 段
        chunks    = split_script(script, 4)
        t1, t2, t3 = duration/4, duration/2, duration*3/4
        sub_times = [(0, t1), (t1, t2), (t2, t3), (t3, duration)]

    tmp_files = []

    try:
        def tf(p: str) -> str:
            """Windows 路徑 → ffmpeg filter 安全路徑"""
            p = p.replace("\\", "/")
            if len(p) >= 2 and p[1] == ":":
                p = p[0] + "\\:" + p[2:]
            return p

        # hook 暫存 txt（單行，不需換行）
        hook_f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        hook_f.write(hook); hook_f.close()
        tmp_files.append(hook_f.name)

        # ASS 字幕檔（取代 drawtext，支援真正多行換行）
        ass_f = tempfile.NamedTemporaryFile(
            suffix=".ass", delete=False
        )
        ass_path = ass_f.name; ass_f.close()
        tmp_files.append(ass_path)
        make_ass(chunks, sub_times, ass_path)

        # ── Video filters ──────────────────────────────────────────
        if use_video:
            # B-roll 模式：影片當背景 + 前景，背景不做 Ken Burns（影片本身有動態）
            bg = (
                f"[0:v]scale=1400:2500:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},"
                f"boxblur=16:3,"
                f"hue=h={hue},"
                f"eq=brightness=-0.25:saturation=0.80[bg]"
            )
            # 前景：等比縮放至 1080px 寬（直向影片填滿；橫向置中）
            fg = f"[0:v]scale={W}:-2[fg]"
        else:
            # 截圖模式：Ken Burns 橫移 + zoom-in（原有行為）
            bg = (
                f"[0:v]scale=1400:2500:force_original_aspect_ratio=increase,"
                f"crop={W}:{H}:x='(iw-{W})/2*(1+sin(t*0.12))/2':y='(ih-{H})/2',"
                f"boxblur=16:3,"
                f"hue=h={hue},"
                f"eq=brightness=-0.25:saturation=0.80[bg]"
            )
            fg = (
                f"[0:v]scale=w='{W}+t*4':h=-2:eval=frame[fgz];"
                f"[fgz]crop={W}:ih:x='(iw-{W})/2'[fg]"
            )
        ovl  = f"[bg][fg]overlay=(W-w)/2:(H-h)/2[ov]"
        # 頂部黑框（加高配合更大 hook 字體）
        tbar = f"[ov]drawbox=x=0:y=0:w={W}:h=170:color=black@0.75:t=fill[tb]"
        # hook 金黃字（drawtext，單行，不需換行）
        hk   = (
            f"[tb]drawtext=fontfile='{tf(FONT_ZH)}':"
            f"textfile='{tf(hook_f.name)}':"
            f"fontsize=56:fontcolor=#{HOOK_COLOR}:"
            f"x=(w-text_w)/2:y=58:"
            f"shadowcolor=black@0.95:shadowx=3:shadowy=3[hk]"
        )
        # ASS 字幕燒入（BorderStyle=3 自帶半透明黑底塊，不需要再 drawbox）
        sub  = (
            f"[hk]subtitles='{tf(ass_path)}':"
            f"fontsdir='{tf('C:/Windows/Fonts')}'[ov2]"
        )

        # fade in/out（影片＋音訊）
        fade_dur = min(0.4, duration / 3)
        fade_v = (
            f"[ov2]fade=t=in:st=0:d={fade_dur:.2f},"
            f"fade=t=out:st={max(0, duration - fade_dur):.2f}:d={fade_dur:.2f}[out]"
        )
        fade_a = (
            f"[1:a]afade=t=in:st=0:d={fade_dur:.2f},"
            f"afade=t=out:st={max(0, duration - fade_dur):.2f}:d={fade_dur:.2f}[aout]"
        )

        filter_complex = ";".join([bg, fg, ovl, tbar, hk, sub, fade_v, fade_a])

        if use_video:
            # B-roll：stream_loop 讓影片循環到音訊結束
            src_args = ["-stream_loop", "-1", "-i", str(broll)]
            mode_label = f"B-roll {out_path.name}"
        else:
            src_args = ["-loop", "1", "-i", str(screenshot)]
            mode_label = f"截圖 {out_path.name}"

        run([
            FFMPEG, "-y",
            *src_args,
            "-i", str(audio),
            "-filter_complex", filter_complex,
            "-map", "[out]", "-map", "[aout]",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            str(out_path),
        ], desc=f"合成片段 ({mode_label})")

    finally:
        for f in tmp_files:
            Path(f).unlink(missing_ok=True)


def concat_segments(segs: list[Path], out: Path):
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for s in segs:
            f.write(f"file '{str(s).replace(chr(92), '/')}'\n")
        list_file = f.name

    run([
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        str(out),
    ], desc="合併片段")
    Path(list_file).unlink(missing_ok=True)


# ── 背景音樂混音 ─────────────────────────────────────────────────────

def mix_bgm(video: Path, bgm: Path, out: Path, vol: float = 0.08):
    """將 BGM loop 混入影片，BGM 音量 vol (0.0~1.0)"""
    vid_dur = get_duration(video)
    run([
        FFMPEG, "-y",
        "-i", str(video),
        "-stream_loop", "-1", "-i", str(bgm),   # BGM 無限循環
        "-filter_complex",
        f"[1:a]volume={vol},afade=t=out:st={max(0, vid_dur-1.5):.2f}:d=1.5[bgm];"
        f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(out),
    ], desc="混入 BGM")


# ── 佔位背景圖 ──────────────────────────────────────────────────────

def make_placeholder(out_path: Path, hue: int = 0):
    """用 ffmpeg 生成漸層佔位截圖（沒有實際截圖時使用）"""
    import colorsys
    r1, g1, b1 = colorsys.hsv_to_rgb(hue / 360, 0.55, 0.22)
    r2, g2, b2 = colorsys.hsv_to_rgb((hue + 30) / 360, 0.35, 0.10)
    c1 = f"0x{int(r1*255):02x}{int(g1*255):02x}{int(b1*255):02x}"
    c2 = f"0x{int(r2*255):02x}{int(g2*255):02x}{int(b2*255):02x}"
    # 用 gradients 濾鏡生成漸層，fallback 到純色
    try:
        run([
            FFMPEG, "-y",
            "-f", "lavfi",
            "-i", (
                f"gradients=s=1080x700:c0={c1}:c2={c2}"
                f":x0=0:y0=0:x1=1080:y1=700:nb_colors=2:speed=0"
            ),
            "-frames:v", "1", str(out_path),
        ], desc=f"生成漸層背景 {out_path.name}")
    except Exception:
        # gradients 濾鏡版本不支援時 fallback 到純色
        run([
            FFMPEG, "-y",
            "-f", "lavfi",
            "-i", f"color=c={c1}:size=1080x700:rate=1",
            "-frames:v", "1", str(out_path),
        ], desc=f"生成純色背景 {out_path.name}")


# ── Remotion 模式 ────────────────────────────────────────────────────

def main_remotion():
    """
    Delegate rendering to the Remotion compositor.
    Called when RENDER_MODE=remotion is set.
    Runs scripts/remotion_renderer.py and exits with its return code.
    """
    remotion_script = BASE_DIR / "scripts" / "remotion_renderer.py"
    if not remotion_script.exists():
        print(f"❌ 找不到 remotion_renderer.py：{remotion_script}", file=sys.stderr)
        sys.exit(1)

    print(f"🎬 RENDER_MODE=remotion — delegating to Remotion compositor...")
    result = subprocess.run(
        [sys.executable, str(remotion_script), TODAY],
        text=True, encoding="utf-8", errors="replace",
    )
    sys.exit(result.returncode)


# ── 主程式 ───────────────────────────────────────────────────────────

def main():
    # ── RENDER_MODE check ──────────────────────────────────────────
    render_mode = os.environ.get("RENDER_MODE", "ffmpeg").lower()
    if render_mode == "remotion":
        main_remotion()
        return  # unreachable (main_remotion calls sys.exit)

    if not NEWS_FILE.exists():
        print(f"❌ 找不到新聞檔：{NEWS_FILE}", file=sys.stderr)
        sys.exit(1)

    data  = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    items = data["items"]

    SEG_DIR.mkdir(parents=True, exist_ok=True)
    BROLL_DIR = PIPE_DIR / "broll"
    seg_files = []

    print(f"🎬 合成 {len(items)} 個片段...")
    for i, item in enumerate(items, 1):
        edited_shot = SHOTS_DIR / f"news_{i:02d}_edited.png"
        orig_shot   = SHOTS_DIR / f"news_{i:02d}.png"
        shot  = Path(item.get("screenshot") or (edited_shot if edited_shot.exists() else orig_shot))
        audio = AUDIO_DIR / f"audio_{i:02d}.mp3"
        seg   = SEG_DIR   / f"seg_{i:02d}.mp4"
        broll = BROLL_DIR / f"broll_{i:02d}.mp4"

        # B-roll 優先；若無則 fallback 截圖 → 佔位圖
        use_broll = broll.exists()
        if not use_broll and not shot.exists():
            print(f"  [{i}] 截圖不存在，自動生成佔位背景...")
            shot.parent.mkdir(parents=True, exist_ok=True)
            make_placeholder(shot, hue=ITEM_HUE[(i - 1) % len(ITEM_HUE)])

        if not audio.exists():
            print(f"❌ 找不到語音：{audio}", file=sys.stderr)
            sys.exit(1)

        if seg.exists():
            print(f"  [{i}] 已存在，跳過")
        else:
            hook     = item.get("hook", "AI 快訊")
            script   = item.get("script") or item.get("summary", "")
            timing_f = AUDIO_DIR / f"audio_{i:02d}_timing.json"
            timing   = json.loads(timing_f.read_text(encoding="utf-8")) if timing_f.exists() else None
            hue      = ITEM_HUE[(i - 1) % len(ITEM_HUE)]
            mode_str = "B-roll" if use_broll else "截圖"
            print(f"  [{i}] {item['title']}... ({mode_str}, hue={hue}°, timing={'精確' if timing else '等比'})")
            make_segment(
                shot, audio, hook, script, seg,
                timing=timing, hue=hue,
                broll=broll if use_broll else None,
            )

        seg_files.append(seg)

    # ── 組合最終清單（片頭 + 片段 + 片尾）───────────────────────────
    final_segs: list[Path] = []
    if INTRO_PATH.exists():
        print(f"  🎬 加入片頭：{INTRO_PATH.name}")
        final_segs.append(INTRO_PATH)
    final_segs.extend(seg_files)
    if OUTRO_PATH.exists():
        print(f"  🎬 加入片尾：{OUTRO_PATH.name}")
        final_segs.append(OUTRO_PATH)

    print("🔗 合併影片...")
    merged = PIPE_DIR / "merged.mp4"
    concat_segments(final_segs, merged)

    # ── 混入背景音樂（如果存在）────────────────────────────────────
    if BGM_PATH.exists():
        print(f"🎵 混入背景音樂（音量 {int(BGM_VOLUME*100)}%）...")
        mix_bgm(merged, BGM_PATH, OUTPUT, BGM_VOLUME)
        merged.unlink(missing_ok=True)
    else:
        merged.rename(OUTPUT)
        print(f"  ℹ️  未找到 BGM（{BGM_PATH}），跳過混音")

    print(f"\n✅ 影片完成：{OUTPUT}")


if __name__ == "__main__":
    main()
