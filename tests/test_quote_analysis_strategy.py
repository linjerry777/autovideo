import unittest

from web.claude_client import _STRATEGY_PRESETS
from web.routes import jobs
from web.routes import schedule
from scripts import publisher


class QuoteAnalysisStrategyTest(unittest.TestCase):
    def test_quote_analysis_is_registered_across_pipeline_maps(self):
        self.assertIn("quote_analysis", _STRATEGY_PRESETS)
        self.assertEqual(jobs._STRATEGY_LABEL["quote_analysis"], "名人語錄解析")
        self.assertEqual(schedule._STRATEGY_LABEL["quote_analysis"], "語錄解析")
        self.assertTrue(jobs._IS_AIGC_BY_STRATEGY["quote_analysis"])
        self.assertEqual(jobs._STRATEGY_CTA_GROUP["quote_analysis"], "tech")
        self.assertEqual(jobs._FB_PAGE_BY_STRATEGY["quote_analysis"], "1100141579843223")
        self.assertIn("名人語錄", jobs._YOUTUBE_TAGS_BY_STRATEGY["quote_analysis"])
        self.assertIn("#名人語錄", jobs._HASHTAGS["instagram"]["quote_analysis"])
        self.assertIn("#名人語錄", publisher._HASHTAGS_BY_STRATEGY["quote_analysis"])


if __name__ == "__main__":
    unittest.main()
