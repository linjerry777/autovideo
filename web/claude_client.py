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
    # 2026-04-22 新增：教學口吻版本（與 tech 並存，不取代）
    # 用戶可在設定切 autopilot_news_strategy 從 tech 改 tech_tutorial 比較
    "tech_tutorial": {"script_len": "80~110 字",
                      "hook_style": "AI 圈友口吻分享實用 tips（「我昨天才發現...」「這招我實測有效」），"
                                    "每則必須帶 how-to 或 why-you-care 結構，不是新聞播報"},
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
    strat_key = (strategy or "tech").lower()
    preset = _STRATEGY_PRESETS.get(strat_key, _STRATEGY_PRESETS["tech"])

    # tech_tutorial 專屬 override：換掉 hook templates + script 口吻
    # 保留原 tech 完全不受影響
    tutorial_override = ""
    if strat_key == "tech_tutorial":
        tutorial_override = """

⚠️ 此次生成為 **tech_tutorial 教學分享版** — 覆寫上方 hook 規則：
Hook 必須是 AI 圈友口吻（像朋友分享實用 tips，不是新聞主播）：
  1. 實測分享「我昨天用 X 才發現...」「實測這招有效」
  2. 工具推薦「今年必試的 3 個 AI 工具」「這 1 招讓你...」
  3. 學習誘惑「學這招 AI 面試就過」「3 分鐘學會 AI 會議記錄」
  4. 使用場景「開會用這個 AI 超爽」「工作中最好用的 AI」

**禁止**：純新聞播報式 hook（「XX 公司宣布 YY」「Anthropic 推出 Z」）

Script 結構：每則新聞必須含 **how-to（怎麼用）** 或 **why-you-care（跟你有啥關係）**：
- 差：「Anthropic 推 MCP 想一統 AI 代理」（講事件）
- 好：「欸你看…用 Claude 的注意，MCP 出來後免費 credit 可能要變貴了！」（帶 why-you-care）

CTA 語氣：驅動**關注**（權重 8×），不是評論。
- 好：「想學更多 AI 技巧？追蹤 Doro 每天教你一招」
- 好：「跟你分享的 AI 教學，追蹤不錯過」

**多則合輯時（>=2 則）每則 script 的結構**（避免口吻疲勞）：
第 1 則 script_short 開頭放**整體導入句**，然後直接講該則內容：
- 範例：「帶你快速了解今天 3 件 AI 大事。第一件…」
- 範例：「用 60 秒學會這週 3 招 AI 技巧。先看這招…」
第 2、3 則**直接進主題**，禁止再用「欸」「跟你說」這類開場語氣詞：
- 差：「欸…跟你說，AI 股今天狂噴」（重複）
- 好：「第二件，AI 股今天狂噴！旺宏景碩全漲停」（承接）
- 好：「再來這個，AI 害桌機變貴了」（承接）

承接詞庫：第二件／再來這個／還有／接著看／最後這招／另外…
"""

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

hook 必須是 **中文區短影音 hook 格式**（抖音前 3 秒完播權重 40%）。
從以下 6 個**中文觀眾實測有效**模板挑一個：
  1. 疑問式「你知道為什麼...嗎？」「怎麼會...？」
  2. 反轉式「原來不是...而是...」「大家都誤會了」
  3. 數字懸念「3 件事改變了...」「這 1 個細節讓...」
  4. 痛點壓迫「千萬別再...了」「90% 的人都搞錯」「還不知道就慘了」
  5. 利益貪婪「我花了 X 才學會...」「學不會這個就永遠做不到...」
  6. 過程分享（台灣偏好）「我看了一下... 發現...」「點開那一刻我震驚了」
**禁止陳述句**（例：「Token 稅爭議爆發」「JYP 又出王牌」—這些是結果不是鉤子）。
hook_variants 恰好 3 個，從不同模板挑。
{tutorial_override}
bullets 是 3 條**新聞卡片重點**（≤15字/條），會被放在 Remotion 影片裡當文字 overlay。
- 每條要是獨立成立的短金句，不是半句話
- 避免重複 hook/title 的內容；應該是「延伸 / 數據 / 結論」三個不同面向
- 範例：["營收年增 300%", "三大車廠同步跟進", "2026 全面商用"]

script_short 和 script_long 必須是**獨立重寫**的兩份腳本，不是 Long 的截斷版。
Short 適合 TikTok/IG/FB/Threads（節奏快、1 句關鍵）；
Long 適合 YouTube/X/Pinterest/LinkedIn（有鋪陳、有論點）。

**腳本 TTS 優化（關鍵！讓 Fish Audio 有換氣、不要聽起來像機器）**：
- 每 8-15 字加一個「，」（逗號）或「…」（刪節號）製造停頓
- 關鍵詞前加「欸」「等等」「真的」「你聽好」這類語氣詞製造口語感
- 強調詞用「！」或用重複「這…這太誇張了」
- 避免整段無標點的長句（TTS 會念得像機器人）

**腳本口吻：台灣偏好「過程敘事」不是「結果宣告」**（真實感 > 精緻感）
- 差（公告式）：「NMIXX 新歌破 291 萬！JYP 再出王牌」
- 好（過程式）：「我點開 NMIXX 新歌那一刻…完全懂為什麼 291 萬人都瘋了」
- 差（公告式）：「Anthropic 推 MCP 想一統 AI 代理」
- 好（過程式）：「欸，你聽好…Anthropic 想一統 AI 代理，但 Perplexity 直接嗆：Token 稅太貴了！」

**CTA 求評論 / 關注**（小紅書 CES 分數：評論權重 4×、關注 8×，收藏只有 1×）：
腳本結尾要**清楚邀請留言**（口播要清楚、不要念得太擠）：
- 好：「你覺得呢？留言告訴我」「你會用嗎？留言告訴我」
- 好：「想知道更多？留言問 Doro」
- 差：「1 會 2 不會」（實測念太快觀眾來不及理解）
- 差：「你怎麼看？」（太泛，無具體問題）
重點：CTA 只佔一句話，不要把選擇題塞進快節奏旁白。

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

hook 必須是 **curiosity-gap（好奇心缺口）格式** — 2026 短影音前 3 秒留存關鍵。
必須從以下 4 個模板挑一個（不要用直述句陳述事實）：
  1. 疑問式「你知道...嗎？」「為什麼...？」「怎麼會...？」
  2. 反轉式「沒人告訴你...」「原來不是...而是...」「大家都誤會了...」
  3. 數字懸念「3 件事改變了...」「這 1 個細節讓...」「為何 XXX 萬人...」
  4. 強烈主張「我預測...」「這一招...」「別再做...了」
**禁止陳述句**（如「264 萬人瘋搶看」—這已經是結果不是鉤子）。
hook_variants 一樣恰好 3 個，各取不同模板。

bullets 是 3 條**趨勢卡片重點**（≤15字/條），會被放在 Remotion 影片裡當文字 overlay。
- 每條要是獨立成立的短金句，不是半句話
- 避免重複 hook/title 的內容；應該是「數據 / 現象 / 結論」三個不同面向
- 範例：["單日破 200 萬觀看", "全平台瘋傳翻拍", "年輕族群 9 成認同"]

**腳本 TTS 優化（關鍵！）**：
- 每 8-15 字加一個「，」或「…」製造停頓
- 關鍵詞前加「欸」「等等」「真的」「你聽好」這類語氣詞
- 強調用「！」或重複（「這…這太誇張了」）
- 避免整段無標點長句

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
