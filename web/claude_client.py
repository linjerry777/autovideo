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


def enrich_news_items(raw_items: list[dict], topic: str | None = None) -> list[dict]:
    """
    raw_items: [{title, summary, url, source}, ...]
    回傳: [{hook, title, summary, script, source_url, source_name}, ...]
    """
    lines = "\n".join([
        f"{i+1}. [{it['source']}] {it['title']}\n   URL: {it['url']}\n   {it.get('summary','')[:120]}"
        for i, it in enumerate(raw_items)
    ])
    topic_line = f"主題背景：{topic}\n\n" if topic else ""
    prompt = f"""請使用繁體中文回答。
{topic_line}以下是用戶選定的新聞，請為每則生成短影音所需的內容。

{lines}

每則請用以下 JSON 格式（照順序）：
{{
  "hook": "開場鉤子（5-8字，製造懸念或衝擊）",
  "title": "標題（15字以內，中文）",
  "summary": "摘要（40字以內，中文，口語化）",
  "script": "旁白腳本（60字以內，像在跟朋友說話）",
  "scene_type": "動畫場景類型（從以下擇一，依據新聞主題）：fire（攻擊/爆炸/燃燒）, race（競賽/追趕/對決）, money（融資/估值/賺錢）, robot（AI/機器人/科技突破）, warning（爭議/警告/風險）, trophy（創紀錄/得獎/突破）, default（其他）",
  "source_url": "原始 URL（從列表複製）",
  "source_name": "媒體名稱"
}}

請直接回傳 JSON 陣列，不要加任何其他文字或 markdown。"""

    raw, usage = call_claude(prompt)
    if not raw:
        raise ValueError("Claude 回傳空白內容")
    # 嘗試直接找 JSON 陣列（忽略前後說明文字）
    match = re.search(r"\[[\s\S]*\]", raw)
    if match:
        raw = match.group(0)
    else:
        # fallback: 清除 markdown fence
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw.strip())
    try:
        items = json.loads(raw)
        # Claude 有時對單篇回傳 {} 而非 [{}]
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
