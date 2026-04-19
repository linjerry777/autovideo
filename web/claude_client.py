"""
web/claude_client.py — 共用 LLM API 呼叫
支援 Claude proxy (localhost:3456) 或 Ollama (localhost:11434)
切換方式：.env 設定 CLAUDE_PROXY_URL 與 LLM_MODEL
"""
import json, os, re, requests

# 預設用 Claude proxy；改成 Ollama 只需 .env 改兩行
_DEFAULT_PROXY = "http://localhost:3456"
_DEFAULT_MODEL = "claude-sonnet-4-6"


def _get_llm_config() -> tuple[str, str]:
    """讀取 LLM 設定：DB 設定優先，其次 .env，最後預設值"""
    try:
        from web.db import get_setting
        db_url      = get_setting("llm_proxy_url", "")
        db_model    = get_setting("llm_model", "")
        db_provider = get_setting("llm_provider", "claude")
        proxy_url   = db_url or os.getenv("CLAUDE_PROXY_URL", _DEFAULT_PROXY)
        if db_model:
            model = db_model
        elif db_provider == "ollama" or "11434" in proxy_url:
            # Ollama 但沒指定模型 → 自動抓第一個可用模型
            try:
                import requests as _r
                tags = _r.get(f"{proxy_url}/api/tags", timeout=3).json()
                model = tags["models"][0]["name"] if tags.get("models") else "qwen2.5:14b"
                print(f"[llm_config] Ollama 自動選用模型：{model}")
            except Exception:
                model = "qwen2.5:14b"
        else:
            model = os.getenv("LLM_MODEL", _DEFAULT_MODEL)
    except Exception:
        proxy_url = os.getenv("CLAUDE_PROXY_URL", _DEFAULT_PROXY)
        model     = os.getenv("LLM_MODEL", _DEFAULT_MODEL)
    return proxy_url, model


def call_claude(prompt: str, timeout: int = 180) -> tuple[str, dict]:
    """回傳 (content, usage)，usage = {prompt_tokens, completion_tokens, total_tokens}"""
    proxy_url, model = _get_llm_config()
    r = requests.post(
        f"{proxy_url}/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4000,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    usage   = data.get("usage", {})
    if content is None:
        print(f"[llm_client] WARNING: content is None, full response: {data}")
        return "", usage
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    backend = "ollama" if "11434" in proxy_url else "claude"
    print(f"[llm_client:{backend}/{model}] tokens: prompt={pt}, completion={ct}, total={pt+ct}")
    return content.strip(), usage


_STRATEGY_PRESETS = {
    "tech":          {"script_len": "80~110 字",
                      "hook_style": "先說結論（1 秒內拋出核心賣點），適合技術解說"},
    "entertainment": {"script_len": "30~50 字",
                      "hook_style": "情緒衝擊（驚喜/反轉/搞笑），開頭必須在 1 秒內抓住注意力"},
    "finance":       {"script_len": "80~110 字",
                      "hook_style": "數字衝擊（先報關鍵數字再解釋），語氣專業"},
    "pet":           {"script_len": "40~60 字",
                      "hook_style": "可愛/互動（特寫情緒，用問句或感嘆引發共鳴）"},
}


def enrich_news_items(raw_items: list[dict], topic: str | None = None,
                     strategy: str | None = None) -> list[dict]:
    """
    raw_items: [{title, summary, url, source}, ...]
    strategy:  tech | entertainment | finance | pet   (None → 預設科技風格)
    回傳: [{hook, title, summary, script, scene_type, source_url, source_name}, ...]
    """
    preset = _STRATEGY_PRESETS.get((strategy or "tech").lower(), _STRATEGY_PRESETS["tech"])
    lines = "\n".join([
        f"{i+1}. [{it['source']}] {it['title']}\n   URL: {it['url']}\n   {it.get('summary','')[:120]}"
        for i, it in enumerate(raw_items)
    ])
    topic_line = f"主題背景：{topic}\n\n" if topic else ""
    prompt = f"""請使用繁體中文回答。
{topic_line}以下是用戶選定的新聞，請為每則生成短影音所需的內容。

內容策略：
- 腳本長度：{preset['script_len']}
- Hook 風格：{preset['hook_style']}

{lines}

每則請用以下 JSON 格式（照順序）：
{{
  "hook": "主要開場鉤子（5-8字，從 hook_variants 中選最強的）",
  "hook_variants": ["懸念式", "打臉式", "提問式"],
  "title": "標題（15字以內，中文）",
  "summary": "摘要（40字以內，中文，口語化）",
  "bullets": ["金句1（≤15字）", "金句2（≤15字）", "金句3（≤15字）"],
  "script_short": "短版旁白（30-40 字，獨立重寫 — 不是 long 的截斷版，一句話講完核心）",
  "script_long":  "長版旁白（60-80 字，獨立重寫 — 含鋪陳+結論，為長平台而寫）",
  "script":       "= script_long (legacy field, backward compat)",
  "scene_type": "動畫場景（擇一）：fire, race, money, robot, warning, trophy, default",
  "virality_score": 1-10 整數，預測這則在短影音爆的潛力,
  "virality_reason": "一句話說明分數理由",
  "emotion": "主導情緒：surprise | anger | joy | curiosity | fear 擇一",
  "source_url": "原始 URL（從列表複製）",
  "source_name": "媒體名稱"
}}

hook_variants 必須恰好 3 個不同風格：
- 風格 A：懸念式（「破千萬的秘密」）
- 風格 B：打臉式（「1188 萬人搞錯了」）
- 風格 C：提問式（「為什麼全網都...？」）

bullets 是 3 條**新聞卡片重點**（≤15字/條），會被放在 Remotion 影片裡當文字 overlay。
- 每條要是獨立成立的短金句，不是半句話
- 避免重複 hook/title 的內容；應該是「延伸 / 數據 / 結論」三個不同面向
- 範例：["營收年增 300%", "三大車廠同步跟進", "2026 全面商用"]

script_short 和 script_long 必須是**獨立重寫**的兩份腳本，不是 Long 的截斷版。
Short 適合 TikTok/IG/FB/Threads（節奏快、1 句關鍵）；
Long 適合 YouTube/X/Pinterest/LinkedIn（有鋪陳、有論點）。

請直接回傳 JSON 陣列，不要加任何其他文字或 markdown。"""

    raw, usage = call_claude(prompt)
    if not raw:
        raise ValueError("Claude 回傳空白內容")
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        raw = match.group(0)
    else:
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw.strip())
    try:
        items = json.loads(raw)
        if isinstance(items, dict):
            items = [items]
        _last_usage.update(usage)
        return items
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude 回傳無效 JSON：{e}\n原始內容：{raw[:300]}")


def enrich_trending_items(raw_items: list[dict]) -> list[dict]:
    """
    raw_items: [{title, summary, url, source, source_type}, ...]
    回傳: [{format, category, hook, title, script, scene_type,
            source_url, source_name, account_suggestion}, ...]

    format: top5 | explainer | reaction | story
    category: tech | entertainment | finance
    """
    def _fmt_stats(it: dict) -> str:
        """Raw stats become a hint line so Claude can write a punchy stat_badge."""
        parts = []
        v = it.get("view_count")
        if v: parts.append(f"view_count={v}")
        c = it.get("comment_count")
        if c: parts.append(f"comment_count={c}")
        return f"   stats: {', '.join(parts)}" if parts else ""

    lines = "\n".join([
        f"{i+1}. [{it.get('source','')}] {it['title']}\n   URL: {it.get('url','')}\n   {it.get('summary','')[:120]}"
        + (("\n" + _fmt_stats(it)) if _fmt_stats(it) else "")
        for i, it in enumerate(raw_items)
    ])

    prompt = f"""請使用繁體中文回答。
以下是從社群平台抓取的熱門話題，請為每則選擇最適合的短影音格式，並生成對應腳本。

{lines}

格式說明：
- top5：排名揭曉節奏「第5是...第1竟然是...」（適合列舉、比較類話題）
- explainer：教育科普節奏「你知道嗎？X其實是...背後原因是...」（適合知識、解釋類）
- reaction：反應評論節奏「全網都在討論X，但沒人告訴你...」（適合爭議、驚訝類）
- story：敘事案例節奏「他靠這個方法...結果...」（適合人物、事件類）

分類說明：
- tech：AI、科技、軟體、遊戲、電腦相關
- entertainment：影視、音樂、運動、迷因、名人、奇聞
- finance：投資、市場、創業、經濟、公司

每則請用以下 JSON 格式（照順序）：
{{
  "format": "top5 | explainer | reaction | story 擇一",
  "category": "tech | entertainment | finance 擇一",
  "hook": "主要開場鉤子（5-8字，從 hook_variants 選最強的）",
  "hook_variants": ["懸念式", "打臉式", "提問式"],
  "title": "標題（15字以內，中文）",
  "bullets": ["金句1（≤15字）", "金句2（≤15字）", "金句3（≤15字）"],
  "script_short": "短版旁白（40-50 字，獨立重寫 — 不是 long 的截斷版，一句話講完核心）",
  "script_long":  "長版旁白（100-130 字，獨立重寫 — 含鋪陳+結論，為長平台而寫）",
  "script":       "= script_long (legacy field, backward compat)",
  "scene_type": "動畫場景：fire/race/money/robot/warning/trophy/default 擇一",
  "virality_score": 1-10 整數,
  "virality_reason": "一句話說明分數理由",
  "emotion": "surprise | anger | joy | curiosity | fear 擇一",
  "stat_badge": "從 stats 或 title 抽出最衝擊的數字當 overlay（例：'2,000,000 觀看'、'+500%'、'破億播放'、'24小時榜首'）。沒可用數字就留空字串。",
  "account_suggestion": "科技帳號 | 娛樂帳號 | 財經帳號 擇一",
  "source_url": "原始 URL",
  "source_name": "來源名稱"
}}

hook_variants 必須恰好 3 個不同風格：懸念式 / 打臉式 / 提問式。

bullets 是 3 條**趨勢卡片重點**（≤15字/條），會被放在 Remotion 影片裡當文字 overlay。
- 每條要是獨立成立的短金句，不是半句話
- 避免重複 hook/title 的內容；應該是「數據 / 現象 / 結論」三個不同面向
- 範例：["單日破 200 萬觀看", "全平台瘋傳翻拍", "年輕族群 9 成認同"]

stat_badge 必須是**短且視覺強**的 overlay 字串（<12 字），會被放大在影片中間。
- 若提示的 stats 有 view_count，格式化為「X萬觀看」或「X百萬觀看」（中文讀數優先）
- 若 title 本身含「兩百萬人朝聖」這種修辭數字，直接採用
- 找不到就填 ""，前端會隱藏 badge

script_short 和 script_long 必須是**獨立重寫**的兩份腳本，不是 Long 的截斷版。
Short 適合 TikTok/IG/FB/Threads（節奏快、1 句關鍵）；
Long 適合 YouTube/X/Pinterest/LinkedIn（有鋪陳、有論點）。

請直接回傳 JSON 陣列，不要加任何其他文字或 markdown。"""

    raw, usage = call_claude(prompt)
    if not raw:
        raise ValueError("Claude 回傳空白內容")
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        raw = match.group(0)
    else:
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw.strip())
    try:
        items = json.loads(raw)
        if isinstance(items, dict):
            items = [items]
        _last_usage.update(usage)
        return items
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude 回傳無效 JSON：{e}\n原始內容：{raw[:300]}")


# 供 job_runner 讀取最後一次 Claude 的 token 用量
_last_usage: dict = {}


# ── Scene DSL resolver ─────────────────────────────────────────────────────────

PRESET_SCENE_KEYS = {"fire", "race", "money", "robot", "warning", "trophy", "default", ""}

def resolve_scene_recipe(description: str, context_title: str = "") -> dict | None:
    """
    Given a free-text scene description (e.g. "跳動的愛心 跟情緒"),
    ask Claude to return a SceneRecipe JSON for Remotion to render.
    Returns None on failure (caller should fall back to default scene).
    """
    if not description or description in PRESET_SCENE_KEYS:
        return None

    prompt = f"""你是短影音動畫設計師。根據以下場景描述，為 1080x1920 直向短影片產生一個 JSON 場景配方。

場景描述：「{description}」
{f'新聞標題：「{context_title}」' if context_title else ''}

要求：
- 挑 2-5 個最能代表這個主題的 emoji
- 組合成一個有層次的畫面：背景漸層 + 2-4 個 layer（主 emoji + 粒子 + 可選 beam）
- 顏色要符合情緒（愛心用粉紅、駭客用綠/黑、速度用藍/青）
- 座標範圍：x=0-1080, y=0-1920
- emoji 大小：主角 300-500，粒子 60-180
- 每個 emoji layer 要選一個動畫讓它動起來

嚴格回傳以下 JSON 格式（不要 markdown、不要其他文字）：
{{
  "background": {{
    "type": "gradient",
    "colors": ["#hex", "#hex", "#hex"],
    "angle": 135
  }},
  "layers": [
    {{
      "type": "emoji",
      "value": "💗",
      "x": 540, "y": 960, "size": 420,
      "anim": {{ "kind": "pulse", "loop": 1.2, "scale": [0.9, 1.2] }}
    }},
    {{
      "type": "particles",
      "emoji": "💖",
      "count": 20,
      "pattern": "drift_up",
      "size": [80, 140]
    }},
    {{
      "type": "particles",
      "emoji": "✨",
      "count": 30,
      "pattern": "scatter_twinkle",
      "size": [50, 90]
    }}
  ],
  "accent_color": "#ff6bcb"
}}

可用的 emoji anim.kind：pulse, spin, bounce, drift, shake, none
可用的 particles.pattern：rain, drift_up, scatter_twinkle, burst, orbit
"""
    try:
        raw, usage = call_claude(prompt, timeout=60)
        if not raw:
            return None
        # Strip markdown fence if present
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw.strip())
        # Pull the first {...} block
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            raw = m.group(0)
        recipe = json.loads(raw)
        # Minimal validation
        if not isinstance(recipe, dict) or "layers" not in recipe:
            return None
        return recipe
    except Exception as e:
        print(f"[scene_resolver] failed for {description!r}: {e}")
        return None
