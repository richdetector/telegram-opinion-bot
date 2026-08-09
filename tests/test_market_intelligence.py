import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from auto_publish_engine import should_auto_publish
from deduper import dedupe_news
from editor_selector import select_news_with_ai
from market_scorer import score_market_item
from models import NewsItem


def item(title, summary="", source="CNBC"):
    return NewsItem(
        title=title,
        summary=summary,
        content="",
        link=f"https://example.com/{abs(hash(title))}",
        published="",
        source=source,
    )


class MarketIntelligenceTests(unittest.TestCase):

    def test_low_materiality_crypto_price_move_is_discarded(self):
        news = item("Bitcoin sube 0,4% durante la manana sin catalizador")

        scored = score_market_item(news)

        self.assertEqual(scored.materiality, "LOW")
        self.assertLess(scored.market_impact, 52)

    def test_macro_high_impact_can_reach_selector(self):
        news = item(
            "Federal Reserve unexpectedly signals higher rates",
            "FOMC says inflation risk may require tighter financial conditions and higher yields.",
            source="Federal Reserve - Monetary Policy",
        )

        scored = score_market_item(news)

        self.assertIn(scored.materiality, {"HIGH", "CRITICAL"})
        self.assertIn("BTC", scored.affected_assets)
        self.assertGreaterEqual(scored.market_impact, 72)

    def test_selector_never_returns_more_than_two_without_ai(self):
        items = [
            score_market_item(
                item(
                    f"SEC announces major spot Bitcoin ETF custody rule {i}",
                    "The decision affects institutional access, ETF flows, custody and BTC liquidity.",
                    source="SEC - Press Releases",
                )
            )
            for i in range(4)
        ]

        selected = select_news_with_ai(items, use_ai=False)

        self.assertLessEqual(len(selected), 2)

    def test_same_event_is_grouped(self):
        one = score_market_item(
            item(
                "Fed keeps rates unchanged but signals tighter policy",
                "FOMC decision affects yields, dollar and risk assets.",
                source="Federal Reserve - Monetary Policy",
            )
        )
        two = score_market_item(
            item(
                "Bloomberg reports Fed keeps rates unchanged",
                "The same FOMC decision affects yields, dollar and risk assets.",
                source="Bloomberg",
            )
        )

        grouped = dedupe_news([one, two])

        self.assertEqual(len(grouped), 1)
        self.assertIn("Bloomberg", grouped[0].related_sources)

    def test_reviewer_failure_blocks_auto_publish(self):
        news = score_market_item(
            item(
                "SEC announces major decision on spot Bitcoin ETF",
                "The decision affects institutional access, ETF demand and BTC liquidity.",
                source="SEC - Press Releases",
            )
        )
        news.confidence = "Alta"
        news.verification_status = "CONFIRMED"

        review = {
            "ok": False,
            "errors": ["Rumor presented as fact"],
        }

        self.assertFalse(should_auto_publish(review, [news]))


if __name__ == "__main__":
    unittest.main()
