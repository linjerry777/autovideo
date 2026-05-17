import unittest

from scripts import figure_quote_collector
from web.routes import jobs
from scripts import publisher


class FigureQuoteAutopilotTest(unittest.TestCase):
    def test_figure_strategies_are_registered_for_publish_metadata(self):
        self.assertEqual(jobs._STRATEGY_LABEL["figure_tech"], "科技大咖解析")
        self.assertEqual(jobs._STRATEGY_LABEL["figure_entertainment"], "娛樂咖解析")
        self.assertEqual(jobs._STRATEGY_CTA_GROUP["figure_tech"], "tech")
        self.assertEqual(jobs._STRATEGY_CTA_GROUP["figure_entertainment"], "entertain")
        self.assertTrue(jobs._IS_AIGC_BY_STRATEGY["figure_tech"])
        self.assertFalse(jobs._IS_AIGC_BY_STRATEGY["figure_entertainment"])
        self.assertIn("黃仁勳", jobs._YOUTUBE_TAGS_BY_STRATEGY["figure_tech"])
        self.assertIn("#科技大咖", publisher._HASHTAGS_BY_STRATEGY["figure_tech"])

    def test_vtt_parser_keeps_timed_text_blocks(self):
        raw = """WEBVTT

00:00:01.000 --> 00:00:03.000
AI is not just a tool.

00:00:03.500 --> 00:00:06.000
It changes how teams work.
"""
        cues = figure_quote_collector.parse_vtt(raw)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["start"], 1.0)
        self.assertEqual(cues[1]["end"], 6.0)
        self.assertIn("teams work", cues[1]["text"])

    def test_transcript_window_uses_context_around_quote(self):
        cues = [
            {"start": 0.0, "end": 5.0, "text": "intro"},
            {"start": 5.0, "end": 10.0, "text": "important quote"},
            {"start": 10.0, "end": 15.0, "text": "explanation"},
        ]
        text = figure_quote_collector.window_text(cues, 4.0, 11.0)
        self.assertIn("[5.0-10.0]", text)
        self.assertIn("important quote", text)


if __name__ == "__main__":
    unittest.main()
