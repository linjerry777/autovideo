"""fb_music_trends.py — Query Meta's Music Recommendations API.

Lists currently trending tracks on Facebook Reels so you can manually
source similar royalty-free music and drop them into assets/music/hot/.
The pipeline's audio_assets.pick_bgm() checks hot/ first, so populated
hot/ overrides emotion-keyed BGM automatically.

Usage:
    python scripts/fb_music_trends.py                    # FACEBOOK_POPULAR_MUSIC
    python scripts/fb_music_trends.py --type new         # FACEBOOK_NEW_MUSIC
    python scripts/fb_music_trends.py --type for_you     # FACEBOOK_FOR_YOU
    python scripts/fb_music_trends.py --countries TW,US  # restrict availability
    python scripts/fb_music_trends.py --save             # also write JSON to assets/music/hot/trends.json

Env vars (.env):
    META_PAGE_ACCESS_TOKEN  — Page or User access token with pages_read_engagement scope

Setup: https://developers.facebook.com/docs/video-api/guides/music-recommendations/
  1. Create Meta app → add Instagram Graph API or Pages API product
  2. Generate a Page access token (Graph API Explorer)
  3. Grant pages_read_engagement scope
  4. Put token in .env as META_PAGE_ACCESS_TOKEN

Known limit: the API returns trending metadata ONLY. Meta does not expose
a way to programmatically attach these tracks to uploaded Reels — you must
source royalty-free alternatives yourself.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
API_VERSION = "v25.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}/audio/recommendations"
TYPE_MAP = {
    "popular": "FACEBOOK_POPULAR_MUSIC",
    "new":     "FACEBOOK_NEW_MUSIC",
    "for_you": "FACEBOOK_FOR_YOU",
}


def fetch(trend_type: str, countries: str | None, token: str) -> dict:
    params = {"type": trend_type, "access_token": token}
    if countries:
        params["available_countries"] = countries
    url = f"{BASE_URL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "AutoVideo/1.0"})
    with urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _fmt_track(t: dict) -> str:
    title  = t.get("title")  or t.get("name") or "(untitled)"
    artist = t.get("artist") or t.get("artist_name") or "(unknown)"
    dur    = t.get("duration_seconds") or t.get("duration") or ""
    dur_s  = f"{dur}s" if dur else ""
    return f"  • {title}  —  {artist}  {dur_s}".rstrip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=list(TYPE_MAP), default="popular",
                    help="popular | new | for_you (default: popular)")
    ap.add_argument("--countries", default=None,
                    help="Comma-separated ISO-2 codes (e.g. TW,US)")
    ap.add_argument("--save", action="store_true",
                    help="Write JSON to assets/music/hot/trends.json")
    ap.add_argument("--json", action="store_true",
                    help="Print raw JSON instead of formatted list")
    args = ap.parse_args()

    token = os.getenv("META_PAGE_ACCESS_TOKEN")
    if not token:
        sys.exit(
            "❌ 缺少 META_PAGE_ACCESS_TOKEN\n"
            "   1. 在 https://developers.facebook.com 建 app\n"
            "   2. Graph API Explorer 產 Page access token + pages_read_engagement scope\n"
            "   3. 放進 .env：META_PAGE_ACCESS_TOKEN=xxx"
        )

    trend_type = TYPE_MAP[args.type]
    try:
        data = fetch(trend_type, args.countries, token)
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"❌ Meta API HTTP {e.code}: {body[:500]}")
    except URLError as e:
        sys.exit(f"❌ 網路錯誤: {e}")

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    tracks = data.get("data") or data.get("audio") or []
    print(f"🎵 {args.type.upper()} ({trend_type}) — {len(tracks)} 首")
    if args.countries:
        print(f"   地區: {args.countries}")
    print()
    if not tracks:
        print("  (空清單 — Business Page 可能見得的結果較少，或 token 權限不足)")
    else:
        for t in tracks:
            print(_fmt_track(t))

    if args.save:
        hot_dir = REPO_ROOT / "assets" / "music" / "hot"
        hot_dir.mkdir(parents=True, exist_ok=True)
        out = hot_dir / "trends.json"
        out.write_text(json.dumps({
            "type": trend_type,
            "countries": args.countries,
            "fetched_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "tracks": tracks,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n💾 已存 {out.relative_to(REPO_ROOT)}")

    print("\n下一步：去 Pixabay / Freesound / YouTube Audio Library 找類似風格的無版權音樂，")
    print(f"       下載 .mp3 放進 {(REPO_ROOT / 'assets' / 'music' / 'hot').relative_to(REPO_ROOT)}/")
    print("       pipeline 會自動優先用 hot/ 的音樂（凌駕 emotion-keyed 挑選）。")


if __name__ == "__main__":
    main()
