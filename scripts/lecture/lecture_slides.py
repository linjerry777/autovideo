#!/usr/bin/env python3
"""
Lecture slide renderer.

Reads <lesson>.segments.json, renders a 1920×1080 PNG for each segment via
Playwright. Brand colour brand-500 = #f97316 (orange).

Outputs to: data/lecture-work/<lesson_id>/slides/seg_NNN.png

Each slide is a self-contained HTML page styled with inline CSS, taken at
1920×1080 with default scale.
"""
import argparse
import base64
import html
import io
import json
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

# Local import — same dir
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from url_screenshot import capture_urls_batch  # noqa: E402

WIDTH, HEIGHT = 1920, 1080
BRAND = "#f97316"
BRAND_DARK = "#c2410c"
BRAND_LIGHT = "#fed7aa"
INK = "#0f172a"          # slate-900 (text)
SUB = "#475569"          # slate-600
BG = "#fffbf5"           # warm cream background
PANEL = "#ffffff"
WARN_BG = "#fee2e2"
WARN_BORDER = "#dc2626"
TIP_BG = "#fef3c7"
TIP_BORDER = "#d97706"
CODE_BG = "#0f172a"
CODE_FG = "#f8fafc"
CLAUDE_BG = "#1c1917"
CLAUDE_BORDER = BRAND


CSS_BASE = f"""
*, *::before, *::after {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; width: {WIDTH}px; height: {HEIGHT}px;
              font-family: 'Microsoft JhengHei','PingFang TC','Noto Sans TC',
                           'Segoe UI', sans-serif;
              background: {BG}; color: {INK};
              -webkit-font-smoothing: antialiased;
              text-rendering: optimizeLegibility; }}
.slide {{ width: 100%; height: 100%; padding: 80px 100px; display: flex;
          flex-direction: column; position: relative; }}
.brand-rule {{ position: absolute; top: 0; left: 0; width: 100%; height: 14px;
                background: {BRAND}; }}
.footer {{ position: absolute; bottom: 36px; left: 100px; right: 100px;
            display: flex; justify-content: space-between;
            color: {SUB}; font-size: 22px; }}
.lesson-tag {{ color: {BRAND_DARK}; font-weight: 700; letter-spacing: 0.06em; }}
"""


def _esc(s: str) -> str:
    return html.escape(s or "")


def _render_html(body_html: str, footer_left: str = "", footer_right: str = "",
                 extra_css: str = "") -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{CSS_BASE}{extra_css}</style></head>
<body><div class="slide"><div class="brand-rule"></div>
{body_html}
<div class="footer"><span class="lesson-tag">{_esc(footer_left)}</span>
<span>{_esc(footer_right)}</span></div></div></body></html>"""


# ── Per-kind templates ────────────────────────────────────────────────────────
def html_title(seg: dict) -> str:
    course_title = _esc(seg.get("course_title", ""))
    lesson_id = _esc(seg.get("lesson_id", "").upper())
    lesson_title = _esc(seg.get("lesson_title", ""))
    duration = _esc(seg.get("lesson_duration", ""))
    body = f"""
<div style="margin:auto 0; padding-top: 80px;">
  <div style="font-size:48px; color:{BRAND}; font-weight:700; letter-spacing:0.08em;">
    {course_title}
  </div>
  <div style="margin-top: 60px; font-size:120px; color:{BRAND}; font-weight:900; letter-spacing:0.04em;">
    {lesson_id}
  </div>
  <div style="margin-top: 30px; font-size:84px; font-weight:900; line-height:1.15;">
    {lesson_title}
  </div>
  <div style="margin-top: 50px; font-size:36px; color:{SUB}; font-weight:500;">
    {duration}
  </div>
</div>"""
    return _render_html(body, footer_left="Claude Code 實戰工作流", footer_right="ai-lesson")


def html_intro(seg: dict) -> str:
    title = _esc(seg.get("lesson_title", ""))
    desc = seg.get("description", "") or ""
    # Render description preserving paragraphs
    paragraphs = [p.strip() for p in desc.split("\n\n") if p.strip()]
    desc_html = "".join(f'<p style="margin: 0 0 24px; line-height:1.6;">{_esc(p)}</p>' for p in paragraphs)

    points = seg.get("key_points", []) or []
    points_html = ""
    if points:
        items = "".join(
            f'<li style="margin: 0 0 18px; padding-left: 18px;">{_esc(p)}</li>'
            for p in points
        )
        points_html = f"""
<div style="margin-top: 48px;">
  <div style="font-size:32px; color:{BRAND_DARK}; font-weight:700; margin-bottom: 16px;">
    這一章的重點
  </div>
  <ul style="font-size:30px; line-height:1.4; padding-left: 24px; margin:0;">
    {items}
  </ul>
</div>"""
    body = f"""
<div style="margin: 30px 0 0;">
  <div style="font-size:60px; font-weight:900; color:{INK}; margin-bottom:36px;">{title}</div>
  <div style="font-size:32px; color:{INK}; max-width: 1500px;">{desc_html}</div>
  {points_html}
</div>"""
    return _render_html(body, footer_left=f"INTRO", footer_right="ai-lesson")


def html_step_title(seg: dict) -> str:
    idx = seg.get("step_index", 0)
    total = seg.get("step_total", 0)
    title = _esc(seg.get("step_title", ""))
    body = f"""
<div style="margin:auto 0; padding-top: 60px;">
  <div style="font-size:48px; color:{BRAND}; font-weight:700; letter-spacing:0.06em;">
    STEP {idx} / {total}
  </div>
  <div style="margin-top: 30px; font-size:96px; font-weight:900; line-height:1.15;
              color:{INK}; max-width: 1600px;">
    {title}
  </div>
  <div style="margin-top: 40px; width: 240px; height: 8px; background:{BRAND};"></div>
</div>"""
    return _render_html(body, footer_left=f"STEP {idx:02d}", footer_right="ai-lesson")


def html_step_body(seg: dict) -> str:
    idx = seg.get("step_index", 0)
    title = _esc(seg.get("step_title", ""))
    body_text = seg.get("body", "") or ""
    paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
    body_html = "".join(
        f'<p style="margin: 0 0 28px; line-height:1.55;">{_esc(p)}</p>'
        for p in paragraphs
    )
    body = f"""
<div style="margin: 0;">
  <div style="font-size:32px; color:{BRAND_DARK}; font-weight:700; letter-spacing:0.04em;">
    STEP {idx:02d}
  </div>
  <div style="font-size:54px; font-weight:900; color:{INK}; margin: 12px 0 36px;
              line-height:1.2;">
    {title}
  </div>
  <div style="font-size:34px; color:{INK}; max-width: 1700px;">
    {body_html}
  </div>
</div>"""
    return _render_html(body, footer_left=f"STEP {idx:02d}", footer_right="ai-lesson")


def _highlight_url(text: str) -> str:
    """Wrap http(s) URLs in a brand-coloured span."""
    out = _esc(text)
    out = re.sub(
        r"(https?://[^\s'\"<>]+)",
        rf'<span style="color:{BRAND}; text-decoration:underline;">\1</span>',
        out,
    )
    return out


# ── Syntax-aware highlighting for terminal mockup ─────────────────────────────
# Colours roughly inspired by JetBrains "One Dark"-ish palette.
TERM_BG = "#1e1e1e"
TERM_HEADER = "#2d2d2d"
TERM_FG = "#e6e6e6"
TERM_PROMPT = "#7ec699"      # green prompt
TERM_COMMENT = "#7a8290"     # gray comment
TERM_STRING = "#d4d27a"      # yellow string
TERM_KEYWORD = "#c678dd"     # purple keyword (sql)
TERM_FLAG = "#61afef"        # blue for --flags
TERM_PATH = "#e5c07b"        # orange path

_BASH_BUILTINS = {
    "cd", "ls", "pwd", "cat", "echo", "mkdir", "rm", "mv", "cp", "touch",
    "chmod", "chown", "export", "source", "git", "npm", "npx", "node",
    "python", "python3", "pip", "pip3", "winget", "scoop", "brew", "stripe",
    "vercel", "supabase", "claude", "ffmpeg", "curl", "wget", "ssh", "scp",
}
_SQL_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "INSERT", "INTO", "VALUES", "UPDATE", "SET",
    "DELETE", "CREATE", "TABLE", "DROP", "ALTER", "ADD", "COLUMN", "INDEX",
    "PRIMARY", "KEY", "FOREIGN", "REFERENCES", "JOIN", "INNER", "LEFT", "RIGHT",
    "OUTER", "ON", "AS", "AND", "OR", "NOT", "NULL", "IS", "IN", "BETWEEN",
    "LIKE", "ORDER", "BY", "GROUP", "HAVING", "LIMIT", "OFFSET", "UNION", "ALL",
    "DISTINCT", "TRUE", "FALSE", "DEFAULT", "UNIQUE", "CONSTRAINT", "RETURNING",
}


def _hl_bash_line(line: str) -> str:
    """Tokenise a single bash/text line and wrap with colour spans."""
    if not line:
        return ""
    # Comment line wins outright.
    stripped = line.lstrip()
    leading_ws = line[: len(line) - len(stripped)]
    if stripped.startswith("#"):
        return f'<span style="color:{TERM_COMMENT};">{_esc(line)}</span>'

    out: list[str] = [_esc(leading_ws)]
    # Tokenise on whitespace but keep order.
    tokens = re.findall(r"\S+|\s+", stripped)
    is_first = True
    for tok in tokens:
        if tok.isspace():
            out.append(_esc(tok))
            continue
        # Strings (unbalanced ok)
        if (tok.startswith('"') and tok.endswith('"')) or \
           (tok.startswith("'") and tok.endswith("'")):
            out.append(f'<span style="color:{TERM_STRING};">{_esc(tok)}</span>')
        elif tok.startswith("--") or tok.startswith("-"):
            out.append(f'<span style="color:{TERM_FLAG};">{_esc(tok)}</span>')
        elif is_first and tok in _BASH_BUILTINS:
            out.append(f'<span style="color:{TERM_KEYWORD}; font-weight:600;">'
                       f'{_esc(tok)}</span>')
        elif "/" in tok and not tok.startswith("http"):
            out.append(f'<span style="color:{TERM_PATH};">{_esc(tok)}</span>')
        elif tok.startswith("http"):
            out.append(f'<span style="color:{BRAND}; text-decoration:underline;">'
                       f'{_esc(tok)}</span>')
        else:
            out.append(_esc(tok))
        is_first = False
    return "".join(out)


def _hl_sql_line(line: str) -> str:
    """Highlight a single SQL line: keywords bold uppercase, strings yellow."""
    if not line:
        return ""
    stripped = line.lstrip()
    if stripped.startswith("--"):
        return f'<span style="color:{TERM_COMMENT};">{_esc(line)}</span>'

    # Tokenise; keep delimiters.
    parts = re.split(r"(\s+|[,;()])", line)
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        upper = p.upper()
        if upper in _SQL_KEYWORDS:
            out.append(f'<span style="color:{TERM_KEYWORD}; font-weight:700;">'
                       f'{_esc(upper)}</span>')
        elif p.startswith("'") and p.endswith("'") and len(p) >= 2:
            out.append(f'<span style="color:{TERM_STRING};">{_esc(p)}</span>')
        else:
            out.append(_esc(p))
    return "".join(out)


def _highlight_terminal(content: str, lang: str) -> tuple[str, str]:
    """Return (highlighted_html, header_title) for the terminal block.

    Splits commands from "fake" execution output. Heuristic: a line that begins
    with a known builtin, "winget", "scoop", "git" etc. is treated as a command
    and prefixed with a green prompt. Comment-only lines are left as comments.
    SQL is highlighted token-wise without prompt prefix.
    """
    lang_l = (lang or "").lower()
    lines = content.splitlines() or [""]
    out_lines: list[str] = []

    if lang_l == "sql":
        title = "psql"
        for ln in lines:
            out_lines.append(_hl_sql_line(ln))
        return "\n".join(out_lines), title

    # Default: bash/shell/text — prompt-prefixed for commands.
    if lang_l in ("bash", "shell", "sh", "zsh", "powershell", "ps", "cmd"):
        title = "claude — zsh"
    else:
        title = "claude — zsh"

    for ln in lines:
        stripped = ln.lstrip()
        if not stripped:
            out_lines.append("")
            continue
        leading_ws = ln[: len(ln) - len(stripped)]
        is_comment = stripped.startswith("#") or stripped.startswith("//")
        first_tok = stripped.split()[0] if stripped.split() else ""
        # Heuristic: command-ish line gets prompt prefix. We deliberately do
        # NOT treat plain "/word" tokens as commands — those are typically
        # Claude slash-skills (e.g. /simplify), not shell paths.
        looks_like_command = (
            first_tok in _BASH_BUILTINS
            or first_tok.startswith("./")
        )
        if is_comment or not looks_like_command:
            out_lines.append(_hl_bash_line(ln))
        else:
            prompt = (f'<span style="color:{TERM_PROMPT}; '
                      f'font-weight:700;">❯ </span>')
            out_lines.append(_esc(leading_ws) + prompt
                             + _hl_bash_line(stripped))

    return "\n".join(out_lines), title


def _terminal_window(content_html: str, header_title: str,
                     extra_min_height: int = 0) -> str:
    """A macOS-style terminal window wrapping pre-highlighted HTML."""
    return f"""
<div style="background:{TERM_BG}; border-radius: 16px;
            box-shadow: 0 30px 60px -20px rgba(0,0,0,0.5),
                        0 0 0 1px rgba(255,255,255,0.04);
            overflow: hidden; flex:1; display:flex; flex-direction:column;
            min-height:{extra_min_height}px;">
  <div style="background:{TERM_HEADER}; padding: 14px 20px;
              display:flex; align-items:center; gap:14px;
              border-bottom: 1px solid rgba(255,255,255,0.06);">
    <div style="display:flex; gap:9px;">
      <span style="width:14px; height:14px; border-radius:50%;
                   background:#ff5f57; display:inline-block;"></span>
      <span style="width:14px; height:14px; border-radius:50%;
                   background:#febc2e; display:inline-block;"></span>
      <span style="width:14px; height:14px; border-radius:50%;
                   background:#28c840; display:inline-block;"></span>
    </div>
    <div style="flex:1; text-align:center; color:#a8a8a8;
                font-family:'JetBrains Mono','Menlo','Cascadia Code',monospace;
                font-size: 22px; letter-spacing: 0.02em;">
      {_esc(header_title)}
    </div>
    <div style="width:60px;"></div>
  </div>
  <div style="flex:1; padding: 36px 44px; overflow:hidden;">
    <pre style="margin:0; font-family:'JetBrains Mono','Menlo','Cascadia Code',
                'Consolas',monospace;
                font-size:30px; line-height:1.55; color:{TERM_FG};
                white-space: pre-wrap; word-break: break-word;">{content_html}</pre>
  </div>
</div>"""


def html_code(seg: dict) -> str:
    idx = seg.get("step_index", 0)
    title = _esc(seg.get("step_title", ""))
    lang = (seg.get("code_lang") or "").lower()
    content = seg.get("code_content") or ""
    badge = (lang or "code").upper() if lang else "CODE"
    content_html, header_title = _highlight_terminal(content, lang)

    body = f"""
<div style="margin: 0; height: 100%; display:flex; flex-direction:column;">
  <div style="font-size:28px; color:{BRAND_DARK}; font-weight:700; letter-spacing:0.04em;">
    STEP {idx:02d} · {title}
  </div>
  <div style="margin-top: 14px; display:flex; align-items:center; gap:14px;">
    <div style="background:{BRAND}; color:white; padding: 6px 18px; font-size:24px;
                font-weight:700; border-radius: 6px;">{badge}</div>
    <div style="font-size:22px; color:{SUB};">→ 終端機 / Terminal</div>
  </div>
  <div style="margin-top: 22px; flex:1; display:flex; flex-direction:column;">
    {_terminal_window(content_html, header_title)}
  </div>
</div>"""
    return _render_html(body, footer_left=f"STEP {idx:02d} · CODE", footer_right="ai-lesson")


# ── Claude conversation mockup ────────────────────────────────────────────────
CLAUDE_PAGE_BG = "#f5f4ed"        # claude.ai cream background
CLAUDE_PANEL = "#ffffff"
CLAUDE_USER_BUBBLE = "#f0eee5"    # user message: warm beige
CLAUDE_INK = "#1f1f1d"
CLAUDE_SUB = "#7a7468"
CLAUDE_ACCENT = "#DA7756"         # claude.ai signature orange


def _claude_logo_svg(size: int = 28) -> str:
    """Inline SVG of Claude's signature asterisk-style mark."""
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}"
     viewBox="0 0 32 32" fill="none">
  <path fill="{CLAUDE_ACCENT}"
    d="M16 2 L18.2 13.8 L30 16 L18.2 18.2 L16 30 L13.8 18.2 L2 16 L13.8 13.8 Z"/>
</svg>"""


def html_claude(seg: dict) -> str:
    idx = seg.get("step_index", 0)
    title = _esc(seg.get("step_title", ""))
    prompt = seg.get("prompt") or ""
    # Render prompt with newlines preserved + URL highlight.
    prompt_html = _highlight_url(prompt)

    # Truncated faux Claude response — keeps slide feeling like a real chat
    # without putting words in Claude's mouth that might not match narration.
    response_placeholder = (
        '<span style="opacity:0.55;">正在思考…</span>'
    )

    body = f"""
<div style="margin: 0; height: 100%; display:flex; flex-direction:column;">
  <div style="font-size:28px; color:{BRAND_DARK}; font-weight:700; letter-spacing:0.04em;">
    STEP {idx:02d} · {title}
  </div>
  <div style="margin-top: 14px; display:flex; align-items:center; gap:14px;">
    <div style="background:{BRAND}; color:white; padding: 6px 18px; font-size:24px;
                font-weight:700; border-radius: 6px;">貼給 CLAUDE</div>
    <div style="font-size:22px; color:{SUB};">→ Claude Code Desktop</div>
  </div>

  <div style="margin-top: 22px; flex:1; background:{CLAUDE_PAGE_BG};
              border-radius: 18px; overflow:hidden; display:flex;
              flex-direction:column;
              box-shadow: 0 30px 60px -20px rgba(15,23,42,0.35),
                          0 0 0 1px rgba(15,23,42,0.06);">
    <!-- Top bar -->
    <div style="display:flex; align-items:center; gap:14px;
                padding: 16px 24px;
                background:{CLAUDE_PANEL};
                border-bottom: 1px solid rgba(15,23,42,0.06);">
      {_claude_logo_svg(28)}
      <div style="font-size:22px; font-weight:700; color:{CLAUDE_INK};
                  letter-spacing:0.01em;">Claude</div>
      <div style="flex:1;"></div>
      <div style="display:flex; align-items:center; gap:8px;
                  padding: 6px 14px; border:1px solid rgba(15,23,42,0.08);
                  border-radius: 999px; font-size:18px; color:{CLAUDE_SUB};
                  background:#fafaf7;">
        Claude Sonnet 4.5 ▾
      </div>
    </div>

    <!-- Conversation area -->
    <div style="flex:1; padding: 32px 60px; display:flex; flex-direction:column;
                gap: 22px; overflow:hidden;">
      <!-- User bubble -->
      <div style="display:flex; justify-content:flex-end;">
        <div style="background:{CLAUDE_USER_BUBBLE};
                    color:{CLAUDE_INK};
                    padding: 22px 28px; border-radius: 22px 22px 6px 22px;
                    max-width: 1300px; font-size:28px; line-height:1.5;
                    box-shadow: 0 4px 12px -4px rgba(15,23,42,0.08);">
          <pre style="margin:0; font-family: inherit;
                      white-space: pre-wrap; word-break: break-word;">{prompt_html}</pre>
        </div>
      </div>

      <!-- Claude reply bubble -->
      <div style="display:flex; align-items:flex-start; gap:14px;">
        <div style="width:42px; height:42px; border-radius:50%;
                    background:{CLAUDE_PANEL};
                    border:1px solid rgba(15,23,42,0.08);
                    display:flex; align-items:center; justify-content:center;
                    flex-shrink:0;">
          {_claude_logo_svg(22)}
        </div>
        <div style="background:{CLAUDE_PANEL}; color:{CLAUDE_INK};
                    padding: 18px 24px; border-radius: 6px 22px 22px 22px;
                    font-size:24px; line-height:1.5;
                    border: 1px solid rgba(15,23,42,0.06);">
          {response_placeholder}
        </div>
      </div>
    </div>

    <!-- Input box mockup -->
    <div style="padding: 18px 32px 24px;">
      <div style="background:{CLAUDE_PANEL};
                  border:1px solid rgba(15,23,42,0.10);
                  border-radius: 18px;
                  padding: 18px 22px;
                  display:flex; align-items:center; gap:14px;
                  box-shadow: 0 8px 20px -10px rgba(15,23,42,0.18);">
        <span style="font-size:22px; color:{CLAUDE_SUB};">＋</span>
        <span style="flex:1; font-size:22px; color:#b8b1a4;">
          Reply to Claude…
        </span>
        <span style="background:{CLAUDE_ACCENT}; color:white;
                     width:38px; height:38px; border-radius:50%;
                     display:inline-flex; align-items:center;
                     justify-content:center; font-size:22px;
                     font-weight:700;">↑</span>
      </div>
    </div>
  </div>
</div>"""
    return _render_html(body, footer_left=f"STEP {idx:02d} · CLAUDE", footer_right="ai-lesson")


def html_warning(seg: dict) -> str:
    idx = seg.get("step_index", 0)
    title = _esc(seg.get("step_title", ""))
    text = seg.get("warning") or ""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    body_html = "".join(
        f'<p style="margin: 0 0 22px; line-height:1.55;">{_esc(p)}</p>'
        for p in paragraphs
    )
    body = f"""
<div style="margin: 0; height: 100%; display:flex; flex-direction:column;">
  <div style="font-size:28px; color:{BRAND_DARK}; font-weight:700; letter-spacing:0.04em;">
    STEP {idx:02d} · {title}
  </div>
  <div style="margin-top: 18px; display:flex; align-items:center; gap:16px;">
    <div style="background:{WARN_BORDER}; color:white; padding: 6px 18px; font-size:24px;
                font-weight:700; border-radius: 6px;">⚠ 注意</div>
  </div>
  <div style="flex:1; margin-top: 24px; background:{WARN_BG};
              border: 4px solid {WARN_BORDER}; border-radius: 16px;
              padding: 48px 56px;
              display:flex; flex-direction:column; overflow:hidden;">
    <div style="font-size:34px; color:#7f1d1d; line-height:1.55;">
      {body_html}
    </div>
  </div>
</div>"""
    return _render_html(body, footer_left=f"STEP {idx:02d} · WARNING", footer_right="ai-lesson")


def html_tip(seg: dict) -> str:
    idx = seg.get("step_index", 0)
    title = _esc(seg.get("step_title", ""))
    text = seg.get("tip") or ""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    body_html = "".join(
        f'<p style="margin: 0 0 22px; line-height:1.55;">{_esc(p)}</p>'
        for p in paragraphs
    )
    body = f"""
<div style="margin: 0; height: 100%; display:flex; flex-direction:column;">
  <div style="font-size:28px; color:{BRAND_DARK}; font-weight:700; letter-spacing:0.04em;">
    STEP {idx:02d} · {title}
  </div>
  <div style="margin-top: 18px; display:flex; align-items:center; gap:16px;">
    <div style="background:{TIP_BORDER}; color:white; padding: 6px 18px; font-size:24px;
                font-weight:700; border-radius: 6px;">💡 提示</div>
  </div>
  <div style="flex:1; margin-top: 24px; background:{TIP_BG};
              border: 4px solid {TIP_BORDER}; border-radius: 16px;
              padding: 48px 56px;
              display:flex; flex-direction:column; overflow:hidden;">
    <div style="font-size:34px; color:#78350f; line-height:1.55;">
      {body_html}
    </div>
  </div>
</div>"""
    return _render_html(body, footer_left=f"STEP {idx:02d} · TIP", footer_right="ai-lesson")


def _png_to_data_uri(png_path: Path) -> str:
    """Inline a local PNG as a base64 data: URI so set_content() can show it
    without needing a file:// route (which set_content does not provide)."""
    raw = png_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _mock_browser_html(url: str, screenshot_data_uri: str) -> str:
    """A minimal Chrome-style browser frame wrapping a screenshot."""
    safe_url = _esc(url)
    return f"""
<div style="background: #e6e9ef; border-radius: 16px; padding: 0;
            box-shadow: 0 30px 60px -20px rgba(15,23,42,0.35);
            overflow: hidden; width: 1400px; max-width: 100%;
            margin: 0 auto; border: 1px solid rgba(15,23,42,0.1);">
  <div style="display:flex; align-items:center; gap: 16px; padding: 16px 22px;
              background: linear-gradient(#f4f5f8,#e6e9ef);
              border-bottom: 1px solid rgba(15,23,42,0.08);">
    <div style="display:flex; gap:10px;">
      <span style="width:16px; height:16px; border-radius:50%; background:#ff5f57; display:inline-block;"></span>
      <span style="width:16px; height:16px; border-radius:50%; background:#febc2e; display:inline-block;"></span>
      <span style="width:16px; height:16px; border-radius:50%; background:#28c840; display:inline-block;"></span>
    </div>
    <div style="flex:1; background:white; border-radius: 999px;
                padding: 10px 22px; font-size: 22px;
                font-family:'Cascadia Code','Consolas','Courier New',monospace;
                color:{INK}; border:1px solid rgba(15,23,42,0.08);
                white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
      <span style="color:#16a34a; margin-right: 8px;">🔒</span>{safe_url}
    </div>
  </div>
  <div style="background:white; line-height:0;">
    <img src="{screenshot_data_uri}" style="width:100%; display:block;" />
  </div>
</div>"""


def html_link(seg: dict) -> str:
    idx = seg.get("step_index", 0)
    title = _esc(seg.get("step_title", ""))
    link_text = _esc(seg.get("link_text", ""))
    link_url = seg.get("link_url", "") or ""
    link_url_safe = _esc(link_url)
    shot_path_str = seg.get("_url_screenshot")

    # Real-screenshot path
    if shot_path_str:
        shot_path = Path(shot_path_str)
        if shot_path.exists():
            data_uri = _png_to_data_uri(shot_path)
            mock = _mock_browser_html(link_url, data_uri)
            body = f"""
<div style="margin: 0; height: 100%; display:flex; flex-direction:column;">
  <div style="font-size:28px; color:{BRAND_DARK}; font-weight:700; letter-spacing:0.04em;">
    STEP {idx:02d} · {title}
  </div>
  <div style="margin-top: 8px; display:flex; align-items:baseline; gap: 22px; flex-wrap: wrap;">
    <div style="font-size:48px; font-weight:900; color:{INK}; line-height:1.15;">
      {link_text}
    </div>
    <div style="font-size:24px; color:{SUB}; font-family:'Cascadia Code','Consolas',monospace;">
      打開這個網址
    </div>
  </div>
  <div style="flex:1; margin-top: 24px; display:flex; align-items:center;
              justify-content:center;">
    {mock}
  </div>
</div>"""
            return _render_html(body, footer_left=f"STEP {idx:02d} · LINK",
                                footer_right="ai-lesson")

    # Fallback: original URL-pill design (unchanged)
    body = f"""
<div style="margin: 0; height: 100%; display:flex; flex-direction:column;">
  <div style="font-size:28px; color:{BRAND_DARK}; font-weight:700; letter-spacing:0.04em;">
    STEP {idx:02d} · {title}
  </div>
  <div style="margin: auto 0; padding: 60px 0;">
    <div style="font-size:32px; color:{SUB}; margin-bottom: 16px;">打開這個網址</div>
    <div style="font-size:64px; font-weight:900; color:{INK}; margin-bottom: 36px;">
      {link_text}
    </div>
    <div style="display:inline-block; background:{PANEL}; border:3px solid {BRAND};
                border-radius: 14px; padding: 24px 40px;
                font-family:'Cascadia Code','Consolas','Courier New',monospace;
                font-size:38px; color:{BRAND_DARK}; font-weight:700;
                box-shadow: 0 16px 40px -16px rgba(249,115,22,0.4);">
      {link_url_safe}
    </div>
  </div>
</div>"""
    return _render_html(body, footer_left=f"STEP {idx:02d} · LINK", footer_right="ai-lesson")


def html_outro(seg: dict) -> str:
    lesson_id = _esc((seg.get("lesson_id") or "").upper())
    next_id = (seg.get("next_lesson_id") or "")
    next_title = (seg.get("next_lesson_title") or "")
    if next_id:
        next_html = f"""
<div style="margin-top: 80px; padding: 40px 60px; background: white;
            border-left: 14px solid {BRAND}; border-radius: 16px;
            box-shadow: 0 30px 60px -20px rgba(249,115,22,0.25);">
  <div style="font-size:30px; color:{SUB}; font-weight:600; letter-spacing:0.08em;">
    下一章
  </div>
  <div style="margin-top: 14px; font-size:48px; color:{BRAND}; font-weight:900;">
    {_esc(next_id.upper())}
  </div>
  <div style="margin-top: 8px; font-size:54px; color:{INK}; font-weight:700; line-height:1.2;">
    {_esc(next_title)}
  </div>
</div>"""
    else:
        next_html = f"""
<div style="margin-top: 80px; font-size:48px; color:{BRAND_DARK}; font-weight:700;">
  恭喜你完成這堂課。
</div>"""
    body = f"""
<div style="margin: auto 0;">
  <div style="font-size:36px; color:{SUB}; font-weight:600; letter-spacing:0.08em;">
    {lesson_id} · 完
  </div>
  <div style="margin-top: 24px; font-size:96px; color:{INK}; font-weight:900;
              line-height:1.15;">
    感謝收看
  </div>
  {next_html}
</div>"""
    return _render_html(body, footer_left="OUTRO", footer_right="ai-lesson")


KIND_TO_FN = {
    "title":      html_title,
    "intro":      html_intro,
    "step_title": html_step_title,
    "step_body":  html_step_body,
    "code":       html_code,
    "claude":     html_claude,
    "warning":    html_warning,
    "tip":        html_tip,
    "link":       html_link,
    "outro":      html_outro,
}


def render(segments_path: Path, out_dir: Path):
    data = json.loads(segments_path.read_text(encoding="utf-8"))
    segments = data["segments"]
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pre-capture URL screenshots for `link` segments. Cache lives one level up
    # so different lessons can share screenshots of the same URL.
    link_urls = []
    seen = set()
    for seg in segments:
        if seg.get("kind") == "link":
            u = (seg.get("link_url") or "").strip()
            if u and u not in seen:
                seen.add(u)
                link_urls.append(u)
    if link_urls:
        shot_cache = out_dir.parent / "screenshots"
        print(f"Capturing {len(link_urls)} URL screenshot(s) → {shot_cache}")
        url_to_path = capture_urls_batch(link_urls, shot_cache)
        for seg in segments:
            if seg.get("kind") != "link":
                continue
            u = (seg.get("link_url") or "").strip()
            shot = url_to_path.get(u)
            seg["_url_screenshot"] = str(shot) if shot else None
        ok_n = sum(1 for v in url_to_path.values() if v)
        print(f"  → {ok_n}/{len(link_urls)} captured "
              f"({len(link_urls)-ok_n} fallbacks to URL pill)")

    print(f"Rendering {len(segments)} slides → {out_dir}")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=1,
        )
        page = context.new_page()

        for i, seg in enumerate(segments):
            kind = seg["kind"]
            fn = KIND_TO_FN.get(kind)
            if not fn:
                print(f"  [{i:03d}] WARN: no template for kind={kind}, using step_body")
                fn = html_step_body
            html_doc = fn(seg)
            out_path = out_dir / f"seg_{i:03d}.png"
            page.set_content(html_doc, wait_until="networkidle")
            page.screenshot(path=str(out_path), clip={"x": 0, "y": 0,
                                                       "width": WIDTH, "height": HEIGHT},
                            omit_background=False)
            seg["_slide_png"] = str(out_path)
            print(f"  [{i:03d}] {kind:<11} → {out_path.name}")

        context.close()
        browser.close()

    # Persist enriched segments back
    enriched_path = out_dir.parent / f"{data['lesson_id']}.segments.with_slides.json"
    enriched_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    print(f"✅ Slides ready, manifest: {enriched_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    render(Path(args.segments), Path(args.out_dir))


if __name__ == "__main__":
    main()
