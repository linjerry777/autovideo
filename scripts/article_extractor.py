"""article_extractor.py — pull structured article data from a news URL.

Outputs (written into news.json item dict):
  hero_image_url    : best single image (og:image → article first big img → None)
  hero_image_b64    : data URL (base64) ready for Remotion
  all_images        : list of {url, width, height} for in-article images ≥ 400px wide
  body_text         : cleaned article body, plain text
  byline            : author line if detectable
  pub_date          : published date (ISO) if detectable

Claude's enrich_* prompts then read body_text to distill 3 bullet-point '金句'.

Usage inside pipeline (called from job_runner after screenshot_collector):
    python scripts/article_extractor.py 2026-04-19/job_99
"""
from __future__ import annotations
import base64, io, json, re, sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

# Force UTF-8 stdout on Windows (cp950 chokes on emojis / CJK)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_DIR  = Path(__file__).resolve().parent.parent
UA        = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
MIN_W     = 400
MIN_H     = 200
MAX_BODY  = 3000       # truncate body so Claude prompt stays bounded


def _http_get(url: str, timeout: int = 15) -> requests.Response:
    return requests.get(url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=timeout)


def _parse_int(val, default=0):
    try:
        return int(re.sub(r"[^0-9]", "", str(val))) if val else default
    except Exception:
        return default


def extract_hero(soup: BeautifulSoup, base_url: str) -> str | None:
    """og:image → twitter:image → first <article><img> ≥ MIN_W. Returns absolute URL."""
    for prop in ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src"):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            return urljoin(base_url, tag["content"].strip())
    root = soup.find("article") or soup.find(attrs={"role": "main"}) or soup.find("main") or soup
    for img in root.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src or src.startswith("data:"):
            continue
        w = _parse_int(img.get("width"))
        if w and w < MIN_W:
            continue
        return urljoin(base_url, src)
    return None


def extract_all_images(soup: BeautifulSoup, base_url: str, max_n: int = 8) -> list[dict]:
    """All in-article images ≥ MIN_W. Returns [{url, width, height}, ...]."""
    root = soup.find("article") or soup.find(attrs={"role": "main"}) or soup.find("main") or soup
    found, seen = [], set()
    for img in root.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src or src.startswith("data:"):
            continue
        abs_url = urljoin(base_url, src)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        w = _parse_int(img.get("width"))
        h = _parse_int(img.get("height"))
        if w and w < MIN_W:
            continue
        found.append({"url": abs_url, "width": w, "height": h, "alt": (img.get("alt") or "")[:80]})
        if len(found) >= max_n:
            break
    return found


def extract_body(soup: BeautifulSoup) -> str:
    """Concatenate <p> tags within <article>/<main>. Strip scripts/styles."""
    root = soup.find("article") or soup.find(attrs={"role": "main"}) or soup.find("main")
    if not root:
        return ""
    for junk in root.find_all(["script", "style", "aside", "nav", "footer", "figure"]):
        junk.decompose()
    paras = []
    for p in root.find_all(["p", "h2", "h3"]):
        txt = p.get_text(" ", strip=True)
        if len(txt) >= 20:
            paras.append(txt)
    joined = "\n\n".join(paras)
    return joined[:MAX_BODY]


def extract_byline(soup: BeautifulSoup) -> str:
    for sel in [
        ('meta', {'property': 'article:author'}),
        ('meta', {'name': 'author'}),
        ('meta', {'name': 'byl'}),
    ]:
        tag = soup.find(*sel)
        if tag and tag.get("content"):
            return tag["content"].strip()[:60]
    # fallback: try common byline classes
    for cls in ["byline", "author", "writer", "article-author"]:
        tag = soup.find(attrs={"class": re.compile(cls, re.I)})
        if tag:
            txt = tag.get_text(" ", strip=True)
            if 2 <= len(txt) <= 60:
                return txt
    return ""


def extract_pub_date(soup: BeautifulSoup) -> str:
    for attrs in [
        {'property': 'article:published_time'},
        {'name': 'pubdate'},
        {'itemprop': 'datePublished'},
    ]:
        tag = soup.find('meta', attrs=attrs)
        if tag and tag.get('content'):
            return tag['content'][:10]
    t = soup.find('time')
    if t and t.get('datetime'):
        return t['datetime'][:10]
    return ""


def download_as_data_url(url: str, max_dim: int = 1600) -> str | None:
    """Fetch image, scale down if bigger than max_dim, return data URL. None on failure."""
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Referer": url}, timeout=20)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        print(f"  [download_as_data_url] {e}", file=sys.stderr)
        return None


def extract_article(url: str) -> dict:
    """Main entry — returns the dict to merge into a news.json item."""
    try:
        r = _http_get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  [extract] fetch failed {url}: {e}", file=sys.stderr)
        return {}

    hero_url = extract_hero(soup, url)
    all_imgs = extract_all_images(soup, url)
    body     = extract_body(soup)
    byline   = extract_byline(soup)
    pub_date = extract_pub_date(soup)

    hero_b64 = download_as_data_url(hero_url) if hero_url else None

    return {
        "hero_image_url": hero_url or "",
        "hero_image_b64": hero_b64 or "",
        "all_images":     all_imgs,
        "body_text":      body,
        "byline":         byline,
        "pub_date":       pub_date,
    }


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: article_extractor.py <job_key>  e.g. 2026-04-19/job_99")
    job_key   = sys.argv[1]
    pipe_dir  = BASE_DIR / "pipeline" / job_key
    news_file = pipe_dir / "news.json"
    if not news_file.exists():
        sys.exit(f"❌ {news_file} 不存在")
    data  = json.loads(news_file.read_text(encoding="utf-8"))
    items = data.get("items", [])
    print(f"📖 extracting article data for {len(items)} item(s)...")
    for i, it in enumerate(items, 1):
        url = it.get("source_url") or it.get("url") or ""
        if not url:
            continue
        print(f"  [{i}] {url[:70]}")
        extracted = extract_article(url)
        for k, v in extracted.items():
            # Don't clobber if item already has (e.g. user-edited)
            if not it.get(k):
                it[k] = v
        ni = len(extracted.get("all_images", []))
        nb = len(extracted.get("body_text", ""))
        print(f"       hero={'✓' if extracted.get('hero_image_url') else '✗'}"
              f"  imgs={ni}"
              f"  body={nb}字"
              f"  byline={extracted.get('byline') or '-'}")
    news_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ updated {news_file}")


if __name__ == "__main__":
    main()
