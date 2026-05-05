"""One-shot — cancel all Upload-Post queued posts for jobs 138-141.

Match by news.json titles (the queued post `title` field on Upload-Post side
contains the news headline), since the local `request_id` is not the same
as Upload-Post's `job_id`.

Usage:
    python scripts/_cancel_jobs.py 138 139 140 141
"""
import io, json, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv
from upload_post import UploadPostClient

load_dotenv(Path(__file__).parent.parent / ".env")

job_ids = [int(x) for x in sys.argv[1:]] or [138, 139, 140, 141]

# Collect titles from each job's news.json
ROOT = Path(__file__).parent.parent
expected_titles = set()
expected_news_titles = set()
for jid in job_ids:
    for date_dir in (ROOT / "pipeline").iterdir():
        jd = date_dir / f"job_{jid}"
        if not jd.exists():
            continue
        nj = jd / "news.json"
        if nj.exists():
            data = json.loads(nj.read_text(encoding="utf-8"))
            for it in data.get("items", []):
                t = it.get("title", "")
                if t:
                    expected_news_titles.add(t)
        # platform_meta titles too (per-platform overrides)
        pmf = jd / "platform_meta.json"
        if pmf.exists():
            pm = json.loads(pmf.read_text(encoding="utf-8"))
            for plat, info in pm.items():
                if isinstance(info, dict):
                    t = info.get("title")
                    if t:
                        expected_titles.add(t.strip())

print(f"Expected titles: {len(expected_titles)} from platform_meta + {len(expected_news_titles)} from news.json")

c = UploadPostClient(os.getenv("UPLOAD_POST_KEY", ""))
listing = c.list_scheduled()
posts = listing.get("scheduled_posts", [])
print(f"Total scheduled in Upload-Post queue: {len(posts)}")

to_cancel = []
for p in posts:
    pt = (p.get("title") or "").strip()
    # Try also platform_content per-platform titles
    plat_titles = []
    for plat, content in (p.get("platform_content") or {}).items():
        if isinstance(content, dict):
            tt = content.get("title", "")
            if tt: plat_titles.append(tt.strip())

    candidates = {pt} | set(plat_titles)
    matched = False
    for cand in candidates:
        if not cand: continue
        # Exact or substring match against expected
        if cand in expected_titles:
            matched = True; break
        for nt in expected_news_titles:
            if nt and (nt in cand or cand[:30] in nt):
                matched = True; break
        if matched: break
    if matched:
        to_cancel.append(p)

print(f"Matched for cancellation: {len(to_cancel)}")
for p in to_cancel:
    plats = ",".join(p.get("platforms", []))
    print(f"  job_id={p.get('job_id')[:16]}... platforms={plats} title={(p.get('title') or '')[:40]}")

ans = input("\nCancel these? (yes/no): ").strip().lower()
if ans != "yes":
    print("Aborted.")
    sys.exit(0)

cancelled = 0; failed = 0
for p in to_cancel:
    jid = p.get("job_id")
    try:
        r = c.cancel_scheduled(jid)
        cancelled += 1
        print(f"  ✓ cancelled {jid[:16]}...")
    except Exception as e:
        failed += 1
        print(f"  ✗ failed {jid[:16]}...: {e}")

print(f"\nDone. Cancelled: {cancelled}, Failed: {failed}")
