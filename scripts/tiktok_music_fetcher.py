"""tiktok_music_fetcher.py — Scrape TikTok Creative Center for trending/royalty-free music.

Two data sources (both scraped from server-rendered __NEXT_DATA__ blobs):

  1. POPULAR trend chart  → ads.tiktok.com/business/creativecenter/inspiration/popular/music/pc/en
     Legally usable subset: tracks with ifCml=True (Commercial Music Library)
     → saved to assets/music/hot/popular/<title>.m4a

  2. COMMERCIAL library   → ads.tiktok.com/business/creativecenter/music/pc/en
     All tracks are royalty-free for Creator use on TikTok; audio_assets.pick_bgm
     will pick from hot/ override whenever non-empty.
     → saved to assets/music/hot/commercial/<title>.m4a

A combined metadata JSON is written to assets/music/hot/trends.json so you can
see both lists (including non-CML copyright tracks) for inspiration.

Usage:
    python scripts/tiktok_music_fetcher.py                    # fetch both, download top 10 commercial
    python scripts/tiktok_music_fetcher.py --count 20         # more tracks
    python scripts/tiktok_music_fetcher.py --no-download      # metadata only
    python scripts/tiktok_music_fetcher.py --clean            # wipe hot/ before downloading

Caveats:
  • TikTok's page structure can change — this scraper targets __NEXT_DATA__ which
    is stable but not contracted API. If it breaks, inspect the response and patch.
  • Commercial Library is licensed for TikTok placement. Using these tracks on
    YouTube/IG/FB may still trigger Content ID (check each track's placementAllowed).
  • Files are M4A (audio/mp4), not MP3. ffmpeg + our mix_audio handle M4A fine.
"""
from __future__ import annotations
import argparse, json, re, shutil, sys, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REPO_ROOT = Path(__file__).resolve().parent.parent
HOT_DIR   = REPO_ROOT / "assets" / "music" / "hot"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

URL_POPULAR    = "https://ads.tiktok.com/business/creativecenter/inspiration/popular/music/pc/en"
URL_COMMERCIAL = "https://ads.tiktok.com/business/creativecenter/music/pc/en"


def _fetch_page(url: str, region: str | None = None) -> dict:
    if region:
        url = f"{url}?countryCode={region}"
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=45) as r:
        html = r.read().decode("utf-8", errors="replace")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.S)
    if not m:
        raise RuntimeError(f"no __NEXT_DATA__ found at {url} — page structure changed?")
    return json.loads(m.group(1))


def _slug(title: str) -> str:
    """Filesystem-safe filename."""
    s = re.sub(r"[^\w\s\-\u4e00-\u9fff]", "", title)  # keep CJK + word chars
    s = re.sub(r"\s+", "_", s.strip())
    return s[:60] or "untitled"


def _download(url: str, out: Path, referer: str) -> bool:
    if out.exists():
        return False   # idempotent
    req = Request(url, headers={"User-Agent": UA, "Referer": referer})
    try:
        with urlopen(req, timeout=30) as r:
            out.write_bytes(r.read())
        return True
    except (HTTPError, URLError) as e:
        print(f"    ❌ download failed: {e}", file=sys.stderr)
        return False


def fetch_popular(region: str | None = None) -> dict:
    data = _fetch_page(URL_POPULAR, region)
    pp = data["props"]["pageProps"]["data"]
    return {
        "pagination": pp.get("pagination", {}),
        "sounds": pp.get("soundList", []),
    }


def fetch_commercial(region: str | None = None) -> dict:
    data = _fetch_page(URL_COMMERCIAL, region)
    pp = data["props"]["pageProps"]
    return {
        "pagination": pp.get("pagination", {}),
        "tracks":     pp.get("musicList", []),
        "playlists":  pp.get("playList", []),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10,
                    help="Max commercial tracks to download (default 10)")
    ap.add_argument("--region", default=None,
                    help="Country code (US, TW, JP, ...). Default: TikTok picks")
    ap.add_argument("--no-download", action="store_true",
                    help="Write trends.json only, skip MP3 downloads")
    ap.add_argument("--clean", action="store_true",
                    help="Wipe assets/music/hot/ before downloading")
    args = ap.parse_args()

    if args.clean and HOT_DIR.exists():
        for child in HOT_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            elif child.suffix in (".json", ".m4a", ".mp3"):
                child.unlink()
        print(f"🧹 cleaned {HOT_DIR.relative_to(REPO_ROOT)}/")

    HOT_DIR.mkdir(parents=True, exist_ok=True)

    print("📡 fetching TikTok Creative Center...")
    popular: dict = {"pagination": {}, "sounds": []}
    commercial: dict = {"pagination": {}, "tracks": [], "playlists": []}
    try:
        popular = fetch_popular(args.region)
    except Exception as e:
        print(f"⚠️  popular chart 失敗（{e}）— 略過，commercial 還可繼續", file=sys.stderr)
    try:
        commercial = fetch_commercial(args.region)
    except Exception as e:
        print(f"⚠️  commercial library 失敗（{e}）", file=sys.stderr)
    if not popular["sounds"] and not commercial["tracks"]:
        sys.exit("❌ 兩邊都掛，TikTok 可能在擋請求。稍後再試。")

    sounds_total = popular["pagination"].get("total", 0)
    tracks_total = commercial["pagination"].get("totalCount", 0)
    print(f"   popular chart: {len(popular['sounds'])} shown (chart total {sounds_total})")
    print(f"   commercial lib: {len(commercial['tracks'])} shown (library total {tracks_total})")

    # Write combined trends.json
    trends_file = HOT_DIR / "trends.json"
    trends_file.write_text(json.dumps({
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "region": args.region or "(TikTok default)",
        "popular": [
            {
                "rank":     s.get("rank"),
                "title":    s.get("title"),
                "author":   s.get("author"),
                "duration": s.get("duration"),
                "link":     s.get("link"),
                "ifCml":    s.get("ifCml"),  # True = legally usable via CML
                "musicUrl": s.get("musicUrl"),
                "cover":    s.get("cover"),
            }
            for s in popular["sounds"]
        ],
        "commercial": [
            {
                "title":            t.get("title"),
                "singer":           t.get("singer"),
                "genre":            t.get("genre"),
                "mood":             t.get("mood"),
                "theme":            t.get("theme"),
                "duration":         t.get("duration"),
                "musicUrl":         t.get("musicUrl"),
                "placementAllowed": t.get("placementAllowed"),
            }
            for t in commercial["tracks"]
        ],
        "playlists": commercial["playlists"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 wrote {trends_file.relative_to(REPO_ROOT)}")

    if args.no_download:
        return

    # Download Commercial Library tracks (top N)
    com_dir = HOT_DIR / "commercial"
    com_dir.mkdir(exist_ok=True)
    to_dl = commercial["tracks"][:args.count]
    print(f"\n⬇️  downloading {len(to_dl)} Commercial Library tracks → {com_dir.relative_to(REPO_ROOT)}/")
    ok = 0
    for i, t in enumerate(to_dl, 1):
        url = t.get("musicUrl")
        if not url:
            continue
        title = t.get("title", f"track_{i}")
        out = com_dir / f"{i:02d}_{_slug(title)}.m4a"
        print(f"  [{i}/{len(to_dl)}] {title} ({t.get('genre','?')}/{t.get('mood','?')}, {t.get('duration')}s)")
        if _download(url, out, URL_COMMERCIAL):
            ok += 1
            time.sleep(0.3)   # polite delay

    # Download CML-eligible tracks from the Popular chart (legally OK subset)
    pop_dir = HOT_DIR / "popular"
    pop_dir.mkdir(exist_ok=True)
    cml = [s for s in popular["sounds"] if s.get("ifCml") and s.get("musicUrl")]
    print(f"\n⬇️  downloading {len(cml)} CML-eligible popular tracks → {pop_dir.relative_to(REPO_ROOT)}/")
    for i, s in enumerate(cml, 1):
        title = s.get("title", f"track_{i}")
        out = pop_dir / f"rank{s.get('rank',99):02d}_{_slug(title)}.m4a"
        print(f"  [{i}/{len(cml)}] rank={s.get('rank')} {title} by {s.get('author')}")
        if _download(s["musicUrl"], out, URL_POPULAR):
            ok += 1
            time.sleep(0.3)

    # Warn about non-CML (copyright) tracks found on the chart
    not_cml = [s for s in popular["sounds"] if not s.get("ifCml")]
    if not_cml:
        print(f"\n⚠️  {len(not_cml)} 首熱門曲不在 Commercial Library，未下載（版權問題）：")
        for s in not_cml:
            print(f"     rank={s.get('rank')} {s.get('title')} — {s.get('author')}  ({s.get('link')})")
        print("     → 要用這些風格時，去 Pixabay/Freesound 找類似風格的無版權音樂手動補")

    print(f"\n✅ 完成，{ok} 首新下載")
    print(f"   pipeline 會自動從 {HOT_DIR.relative_to(REPO_ROOT)}/ 挑 BGM（凌駕 emotion-keyed）")


if __name__ == "__main__":
    main()
