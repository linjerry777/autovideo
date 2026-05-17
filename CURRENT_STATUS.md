# AutoVideo Current Status

Last updated: 2026-05-13

## Session Handoff

AutoVideo is the short-video autopilot project. New sessions should first read workspace
`C:\Users\User\Documents\GitHub\PROJECT_STATUS.md`, then `CLAUDE.md`, this file,
and finally run `git status --short` and recent `git log` before changing code.

## Current Role

- Generates and publishes short videos.
- Tech account: `_doro1998ai`.
- Entertainment account: `_doro1998`.
- TikTok autopilot is intentionally disabled because the account is in shadow-ban recovery.
- Main current issue is reach drop / lower view rate; do not assume the pipeline is "done" just because publishing works.

## Recently Completed

- Active FastAPI static UI analytics page updated in `web/static/index.html` (served at `http://localhost:9000/ui/`) as a per-video performance recovery workbench.
- `web/routes/analytics.py` now enriches completed jobs with generated title/hook/thumbnail, platform stats, engagement rate, baseline comparison, best platform, and performance labels.
- `scripts/analytics_fetcher.py` now uses stricter platform matching: no "latest video" fallback, Facebook matches by per-job page id + title/hook + scheduled window, and YouTube prefers Upload-Post `request_id` status to resolve the exact video id before calling YouTube Data API stats.
- Analytics fetcher supports `--all` for all done jobs, and `/api/analytics/refresh?all_done=true` triggers a background full refresh from the active UI.
- Old false Facebook duplicate pollution was confirmed (same platform video id on many jobs). The analytics UI excludes duplicate platform video ids; strict re-fetch can reclaim a matched video id for the correct job.
- Note: the old `frontend/` Next/Vercel dashboard is not the active local UI. Earlier experimental analytics edits there are unused unless explicitly revived or cleaned up.
- TikTok removed from autopilot.
- Tech and entertainment schedules offset by 4 hours to reduce Meta cross-account spam risk.
- Caption / CTA / hashtag randomization added with deterministic seeds.
- ManyChat keyword alignment moved toward the shared 6-keyword Hub flow, especially `日報`.
- LinkedIn added to fan-out for tech profile.
- Hook visuals improved: frame 0 starts with full-screen large text + voice instead of a black/white chrome flash.
- Retry button and publisher schedule log MERGE added so failed platforms can be retried without reposting successful ones.
- Publisher retry and timeout handling improved.
- IG/YT custom cover support added via imgbb-hosted JPEG.
- `sync_doro_palace_videos.py` exists to sync video entries into doro-palace `/from-ig`.
- Upload / publisher path has been adjusted recently to support upload-post quirks such as YouTube language format (`zh-TW`, not `zh-Hant`) and R2 pre-upload style used by related projects.
- Added `quote_analysis` strategy for tech-line 名人語錄解析: scripts frame news/trending inputs as a founder/AI leader viewpoint, avoid fabricated direct quotes, route metadata/FB page/voice/Upload-Post profile through the tech account, and expose it in the active FastAPI UI strategy picker.
- Corrected the quote-analysis direction into a new YouTube source-video autopilot lane: `figure_tech` and `figure_entertainment`. `scripts/figure_quote_collector.py` searches configured figures, pulls captions, asks the LLM to select a quote, downloads the source clip into `broll_01.mp4`, and writes `news.json` for the existing audio/composer/publisher path. Autopilot now queues tech figure + entertainment figure jobs in addition to the existing news/trending jobs when `autopilot_figure_enabled` is true.
- Per user request, figure autopilot is currently disabled (`autopilot_figure_enabled=false`) until previews are reviewed. A local tech-figure preview was generated at `pipeline/2026-05-13/figure_preview_tech/output.mp4` from Sam Altman's TED2025 interview, using source clip + Doro analysis narration only; it was not uploaded.

## Current Known Issues

- Active UI is the FastAPI static dashboard at port 9000. Do not assume `frontend/` is the current surface.
- The analytics page shows completed videos immediately, but true per-platform ranking depends on trustworthy `video_stats` rows from the analytics fetch/sync path. YouTube rows now work through Upload-Post request status when the post is already published; scheduled future posts still show as pending until Upload-Post exposes a post URL/id.
- Full analytics refresh on 2026-05-13 fetched 86 platform rows: YouTube 41 rows / 15,996 views, Facebook 45 rows / 11,617 views, with no duplicate platform video ids after cleanup.
- Views/reach are down and need continued testing.
- TikTok recovery is manual for now; do not turn TikTok autopilot back on without explicit approval.
- LinkedIn Chinese-to-English video description step is still lower priority.
- Entertainment line ManyChat funnel and blog mapping are not ready.
- `sync_doro_palace_videos.py` is not fully automated from publisher success hook yet.
- The project has generated assets, schedules, logs, and local DB state; do not clean or reset without explicit approval.

## Current Optimization Direction

The next meaningful improvement is not more automation. It is higher first-frame and mid-video retention.

Use Image2 selectively in the short-video flow:

1. **First-frame hook image**: strong visual conflict in the first second.
2. **Custom cover / thumbnail**: clearer platform-native click reason.
3. **Mid-video visual event**: one generated insert that breaks monotony.
4. **Doro / meme reaction beat**: especially for tech explanations that feel too dry.

Do not try to regenerate entire short videos with Image2 yet. Start with the hook, cover, and 1-2 visual inserts because these have the best speed-to-impact ratio.

## Next Priorities

1. Expand `scripts/analytics_fetcher.py` beyond current YouTube/Facebook coverage so IG/Reels/Threads/X/LinkedIn rows also land in local SQLite `video_stats`.
2. Add Image2-assisted hook/cover experiments for tech-line videos and record `cover_type` / `hook_type` for later analytics comparison.
3. Observe reach trend after latest hook/publisher changes.
4. Keep tech-line video comments aligned to shared ManyChat keywords.
5. Run the new `figure_tech` / `figure_entertainment` collector on real YouTube sources and verify caption quality, clip timing, and upload result before turning dry-run off.
6. Test figure-source videos against normal tech/news quick videos; compare cover CTR, first 3 seconds, and per-video views in analytics.
7. Automate successful video sync to doro-palace when stable.
8. Revisit entertainment line funnel only after the tech flow is stable.

## Do Not Do

- Do not re-enable TikTok autopilot casually.
- Do not delete or reset current generated assets / music / data folders.
- Do not replace the existing publisher path unless upload-post becomes a blocker.
- Do not turn every video into a full Image2 pipeline before proving hook/cover impact.
