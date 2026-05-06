# PHASE: Obstructed Screenshot Detection (job 143 regression)

## Problem (2026-05-06)

Job 143 (date 2026-05-06, autopilot_news, strategy=tech) item 1 captured the
**Initium Media paywall** instead of the article body:

> 「免費註冊，立即解鎖本文 / 註冊即可暢讀限定報導 / 領取「總編周記」與「端週報」/
>   收藏喜歡的文章、作者、系列  〔免費註冊〕」

The video (`pipeline/2026-05-06/job_143/short/output.mp4`) was published to
YouTube/Instagram/Facebook/Threads/X/LinkedIn before the obstruction was
spotted. Jerry manually delisted it.

Root cause: `scripts/screenshot_collector.py` Method 1 (Playwright element
screenshot) targets the `<article>` selector first. On Initium Media's page
the registration wall is rendered _inside_ that same `<article>` element, so
`element.screenshot()` faithfully captured the wall as if it were the article.

The existing dismissal logic only matched a few selectors (cookie / generic
modal close buttons) and the existing CSS injection only hid
`[class*='paywall']`-style elements — neither matched the Initium card.

## Fix

Added a post-capture **obstruction gate** that combines a Pillow heuristic
with a Groq Llama-4 Scout vision check, plus stronger pre-capture overlay
removal. When the gate fires, the autopilot publish step is skipped and the
job goes into `manual_review` with a Telegram alert.

### Files

| File | Change |
|------|--------|
| `scripts/screenshot_quality.py` | **NEW.** Two-stage detector: Pillow heuristic (only flags structurally broken images) + Groq vision LLM (semantic obstruction detection). Falls back gracefully when vision is unavailable. |
| `scripts/screenshot_collector.py` | After every capture, runs `check_screenshot()`. If the verdict is "obstructed" the screenshot is deleted and the next capture method is tried (Playwright retry with stronger overlay strip → OG image fetcher → Unsplash). Final per-item verdicts written to `pipeline/<date>/job_<id>/screenshots/quality.json`. The pre-capture CSS strip was extended with paywall/login/gate/wall/register selectors that catch the Initium-style card. |
| `web/job_runner.py` | New gate after `step_screenshot=done`. Reads `quality.json`; if `any_obstructed=True`: marks affected URLs `screenshot_blocked` in `news_cache`, sends a Telegram alert (`_notify_obstruction`), forces the job out of autopilot, and finishes the job with `status=manual_review` instead of `status=done`. The video is still rendered so the operator can preview before approving the upload. |
| `web/telegram_bot.py` | Handles `manual_review` status broadcasts (resets the active-job tracker; does not duplicate the detailed message that `_notify_obstruction` already sent). |
| `scripts/test_screenshot_quality.py` | **NEW.** Fixture-based smoke test. Replays job 143 + job 138 screenshots through `check_screenshot()` and asserts: paywall caught, legit pages NOT flagged. |

### Detection design

* **Stage A — Pillow heuristic.** Only hard-flags structural failures
  (missing file, byte size < 25 KB, dimensions < 200 px, edgeless image).
  Pure pixel statistics (dominant colour coverage, edge density) are recorded
  as advisory signals in `data/screenshot_quality.log` but never set
  `obstructed=true` on their own — earlier prototypes false-positively flagged
  long text-only blog posts that have a similar bottom-half colour
  distribution to a paywall card.
* **Stage B — Groq vision (`meta-llama/llama-4-scout-17b-16e-instruct`).**
  This is the authoritative detector. Sent a structured prompt and the
  base-64 image; expects a one-line JSON verdict.
* **Skip-if-impossible.** If `GROQ_API_KEY` is missing OR the call fails,
  the gate gracefully falls through (no false-positive cascade). The local
  Claude-Code proxy at `:3456` cannot serialize multipart vision requests
  (passes `content` array as `[object Object]`), so it is not used; OpenAI
  is supported as a secondary backend if `OPENAI_API_KEY` is set.

### Configuration

* `GROQ_API_KEY` — primary vision backend (already set in `.env`).
* `OPENAI_API_KEY` — optional secondary backend (not currently set).
* `SCREENSHOT_VISION_MODEL` — override Groq model id.
* `OBSTRUCTION_DETECT=0` — env-var disable for offline debugging.
* DB settings used by Telegram alert: `telegram_bot_token`, `telegram_chat_ids`.

## Test results

```
$ python scripts/test_screenshot_quality.py
  🚫 job 143 / item 1 — Initium Media paywall (regression)
     obstructed=True, kind=paywall, conf=0.9, why=The article body is blocked by a registration wall
  ✅ job 143 / item 2 — TechNews legit body
     obstructed=False, kind=none, conf=0.9
  ✅ job 143 / item 3 — Yahoo legit body
     obstructed=False, kind=none, conf=1.0
  ✅ job 138 / item 1 — TechNews DRAM (legit)
     obstructed=False, kind=none, conf=1.0
  ✅ job 138 / item 2 — TechNews retail AI (legit)
     obstructed=False, kind=none, conf=1.0

✅ all 5 fixtures passed
```

End-to-end test (subprocess: `python scripts/screenshot_collector.py
test_quality_gate`) produces a valid `quality.json` with
`any_obstructed=true, kinds=['paywall']` on the job 143 fixture set.
`data/screenshot_quality.log` accumulates one JSONL row per check.

## Operational notes

* Only `autopilot=True` jobs were subject to silent paywall publish;
  human-review jobs already pause at the screenshot review step where Jerry
  can spot the issue. The gate now adds a second safety net for the
  autopilot path.
* When the gate fires the video still renders — Jerry can preview and either
  approve via the existing UI replace flow (`POST
  /api/jobs/{id}/items/{n}/replace`) or scrap the job entirely.
* `news_cache.screenshot_blocked` is updated on each obstruction, so
  re-pickers naturally avoid the same URL on subsequent runs.
* Cost: ~1 Groq vision call per news item (3 per typical job). Well within
  the free tier; stays inside the existing `GROQ_API_KEY` quota.
