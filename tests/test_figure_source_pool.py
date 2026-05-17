import tempfile
import unittest
from pathlib import Path

from scripts import figure_quote_collector
from scripts import figure_segment_pool
from scripts import figure_source_pool
from scripts import figure_transcript_cache
from web import db


def _cues(count=12):
    return [
        {"start": float(i), "end": float(i + 1), "text": f"cue {i}"}
        for i in range(count)
    ]


class FigureSourcePoolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "dashboard.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.old_db_path
        self.tmp.cleanup()

    def test_pick_figure_candidate_skips_used_and_low_caption_sources(self):
        db.upsert_figure_source_candidate(
            {
                "group_name": "tech",
                "figure_name": "Used Person",
                "topic": "AI strategy",
                "url": "https://www.youtube.com/watch?v=used",
                "title": "Used source",
                "channel": "Channel",
                "duration_seconds": 600,
                "caption_count": 80,
                "status": "available",
            }
        )
        db.upsert_figure_source_candidate(
            {
                "group_name": "tech",
                "figure_name": "Weak Person",
                "topic": "AI strategy",
                "url": "https://www.youtube.com/watch?v=weak",
                "title": "Weak source",
                "channel": "Channel",
                "duration_seconds": 600,
                "caption_count": 3,
                "status": "available",
            }
        )
        db.upsert_figure_source_candidate(
            {
                "group_name": "tech",
                "figure_name": "Fresh Person",
                "topic": "AI future",
                "url": "https://www.youtube.com/watch?v=fresh",
                "title": "Fresh source",
                "channel": "Channel",
                "duration_seconds": 900,
                "caption_count": 120,
                "status": "available",
            }
        )

        picked = db.pick_figure_source_candidate(
            "tech",
            used_urls={"https://www.youtube.com/watch?v=used"},
            min_caption_count=8,
        )

        self.assertIsNotNone(picked)
        self.assertEqual(picked["url"], "https://www.youtube.com/watch?v=fresh")
        self.assertEqual(picked["topic"], "AI future")

    def test_collector_prefers_pool_candidate_before_live_youtube_search(self):
        db.upsert_figure_source_candidate(
            {
                "group_name": "tech",
                "figure_name": "Fresh Person",
                "topic": "AI future",
                "url": "https://www.youtube.com/watch?v=fresh",
                "title": "Fresh source",
                "channel": "Channel",
                "duration_seconds": 900,
                "caption_count": 120,
                "status": "available",
            }
        )

        old_used = figure_quote_collector._used_urls
        old_download = figure_quote_collector._download_captions
        old_search = figure_quote_collector._search_youtube
        try:
            figure_quote_collector._used_urls = lambda: set()
            figure_quote_collector._download_captions = lambda _url, _tmp: _cues(12)
            figure_quote_collector._search_youtube = lambda _query, _limit: self.fail(
                "pool candidate should be tried before live search"
            )

            video, cues = figure_quote_collector._choose_candidate("tech")
        finally:
            figure_quote_collector._used_urls = old_used
            figure_quote_collector._download_captions = old_download
            figure_quote_collector._search_youtube = old_search

        self.assertEqual(video["url"], "https://www.youtube.com/watch?v=fresh")
        self.assertEqual(video["figure_name"], "Fresh Person")
        self.assertEqual(len(cues), 12)

    def test_collector_prefers_quote_segment_before_source_candidate(self):
        source_id = db.upsert_figure_source_candidate(
            {
                "group_name": "tech",
                "figure_name": "Segment Person",
                "topic": "AI future",
                "url": "https://www.youtube.com/watch?v=segment-source",
                "title": "Segment source",
                "channel": "Channel",
                "duration_seconds": 900,
                "caption_count": 120,
                "status": "available",
            }
        )
        segment_id = db.upsert_figure_quote_segment(
            {
                "source_candidate_id": source_id,
                "group_name": "tech",
                "figure_name": "Segment Person",
                "topic": "AI future",
                "source_url": "https://www.youtube.com/watch?v=segment-source",
                "source_title": "Segment source",
                "source_channel": "Channel",
                "start_seconds": 20,
                "end_seconds": 50,
                "quote_original": "original",
                "quote_zh": "中文金句",
                "hook": "先看這句",
                "title": "片段標題",
                "summary": "片段摘要",
                "script_short": "短解析",
                "script_long": "完整解析文案",
                "virality_score": 8,
                "transcript_window": "[20-50] original",
                "status": "available",
            }
        )

        video, cues, analysis, picked_id = figure_quote_collector._pool_segment("tech")

        self.assertEqual(picked_id, segment_id)
        self.assertEqual(video["url"], "https://www.youtube.com/watch?v=segment-source")
        self.assertEqual(cues[0]["text"], "original")
        self.assertEqual(analysis["quote_zh"], "中文金句")
        self.assertEqual(analysis["start_seconds"], 20.0)

    def test_source_pool_infers_topic_from_title_and_query(self):
        self.assertEqual(
            figure_source_pool.infer_topic("NVIDIA AI agents keynote", "Jensen Huang keynote"),
            "AI agents",
        )
        self.assertEqual(
            figure_source_pool.infer_topic("AMD GPU and data center interview", "Lisa Su AI"),
            "chips/GPU",
        )
        self.assertEqual(
            figure_source_pool.infer_topic("The future of work with Microsoft CEO", "Satya Nadella"),
            "future of work",
        )

    def test_quote_segment_pool_picks_unused_segment_before_used_one(self):
        source_id = db.upsert_figure_source_candidate(
            {
                "group_name": "tech",
                "figure_name": "Fresh Person",
                "topic": "AI future",
                "url": "https://www.youtube.com/watch?v=source",
                "title": "Fresh source",
                "channel": "Channel",
                "duration_seconds": 900,
                "caption_count": 120,
                "status": "available",
            }
        )
        first_id = db.upsert_figure_quote_segment(
            {
                "source_candidate_id": source_id,
                "group_name": "tech",
                "figure_name": "Fresh Person",
                "topic": "AI future",
                "source_url": "https://www.youtube.com/watch?v=source",
                "source_title": "Fresh source",
                "source_channel": "Channel",
                "start_seconds": 10,
                "end_seconds": 35,
                "quote_zh": "第一段",
                "script_long": "第一段解析",
                "virality_score": 9,
                "transcript_window": "first window",
                "status": "available",
            }
        )
        db.upsert_figure_quote_segment(
            {
                "source_candidate_id": source_id,
                "group_name": "tech",
                "figure_name": "Fresh Person",
                "topic": "AI future",
                "source_url": "https://www.youtube.com/watch?v=source",
                "source_title": "Fresh source",
                "source_channel": "Channel",
                "start_seconds": 60,
                "end_seconds": 88,
                "quote_zh": "第二段",
                "script_long": "第二段解析",
                "virality_score": 7,
                "transcript_window": "second window",
                "status": "available",
            }
        )
        db.mark_figure_quote_segment_used(first_id)

        picked = db.pick_figure_quote_segment("tech")

        self.assertIsNotNone(picked)
        self.assertEqual(picked["quote_zh"], "第二段")
        self.assertEqual(picked["source_url"], "https://www.youtube.com/watch?v=source")
        self.assertEqual(picked["start_seconds"], 60.0)

    def test_segment_pool_normalizes_and_filters_llm_segments(self):
        cues = [
            {"start": 95.0, "end": 101.0, "text": "before"},
            {"start": 102.0, "end": 120.0, "text": "useful quote"},
            {"start": 125.0, "end": 140.0, "text": "after"},
        ]
        raw = [
            {
                "quote_original": "Useful quote",
                "quote_zh": "有用金句",
                "start_seconds": 100,
                "end_seconds": 130,
                "hook": "別錯過",
                "title": "好片段",
                "summary": "摘要",
                "bullets": ["一", "二"],
                "script_short": "短解析",
                "script_long": "這是一段夠長的完整解析，說明這句話為什麼適合拆成短影音。",
                "scene_type": "robot",
                "emotion": "curiosity",
                "virality_score": 8,
                "virality_reason": "有觀點",
            },
            {"quote_zh": "太短", "start_seconds": 200, "end_seconds": 205},
        ]

        segments = figure_segment_pool.normalize_segments(raw, cues)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["quote_zh"], "有用金句")
        self.assertEqual(segments[0]["start_seconds"], 100.0)
        self.assertEqual(segments[0]["end_seconds"], 130.0)
        self.assertIn("useful quote", segments[0]["transcript_window"])

    def test_transcript_cache_saves_and_loads_cues_by_video_id(self):
        old_dir = figure_transcript_cache.TRANSCRIPT_DIR
        figure_transcript_cache.TRANSCRIPT_DIR = Path(self.tmp.name) / "transcripts"
        try:
            video = {
                "id": "abc123",
                "url": "https://www.youtube.com/watch?v=abc123",
                "title": "Test interview",
            }
            figure_transcript_cache.save_transcript(
                video,
                _cues(9),
                source="local_whisper",
                model_name="base",
                language="en",
            )

            loaded = figure_transcript_cache.load_transcript(video)
        finally:
            figure_transcript_cache.TRANSCRIPT_DIR = old_dir

        self.assertEqual(len(loaded), 9)
        self.assertEqual(loaded[0]["text"], "cue 0")


if __name__ == "__main__":
    unittest.main()
