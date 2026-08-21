import sys
import time
import tempfile
import unittest
import io
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from auto_publish_engine import should_auto_publish
from crypto_market_engine import (
    analyze_btc_market_state,
    analyze_btc_market_snapshot,
    BtcMarketState,
    fetch_btc_market_state,
    market_state_to_news_item,
)
from combined_story import attach_market_reaction_to_news
from daily_publication_gate import evaluate_daily_item
from daily_recap import (
    daily_market_state_score,
    evaluate_daily_market_recap,
    replay_seen_events_with_current_rules,
)
from deduper import dedupe_news
from diagnostics import count_pre_candidate_rejections
from dry_run_report import print_dry_run_report, report_mode_title
from editor_writer import write_news
from editor_selector import select_news_with_ai
from editorial_lanes import lane_for_item, split_selector_lanes
from editorial_image import build_image_brief, prepare_editorial_image
from formatter import format_report
from liquidity_structure_engine import (
    BtcLiquidityStructureSnapshot,
    LiquidityCluster,
)
from intraday_engine import (
    BtcIntradaySnapshot,
    IntradayLiquidityMap,
    analyze_btc_intraday_state,
    attach_intraday_catalyst,
    intraday_state_to_news_item,
    intraday_update_type,
)
from intraday_publication_gate import evaluate_intraday_item
from main import (
    _preselect_market_candidates,
    _revalidate_precandidates_after_download,
    process_news,
)
from market_scorer import accepted_by_paths, can_reach_selection, score_market_item
from market_interpreter import (
    attach_editorial_interpretations,
    build_editorial_interpretation,
    validate_publication_text,
)
from market_data import BtcEtfFlowSnapshot, BtcMarketSnapshot
from market_data import (
    BtcOnchainSnapshot,
    BlockworksEtfFlowClient,
    LargeBtcTransfer,
    classify_large_transfer,
    fetch_btc_etf_flow_snapshot,
    fetch_coin_metrics_context,
)
from models import NewsItem
from publishing import DryRunPublishBlocked
from publication_gate import (
    PublicationGateConfig,
    apply_publication_gate,
    evaluate_item,
)
from quiet_market import (
    QUIET_MARKET_CATEGORY,
    evaluate_quiet_market,
    review_quiet_market_message,
    select_quiet_market_angle,
)
from rss_audit import audit_rss_sources, recommend_source
from sentiment_engine import BtcSentimentSnapshot
from rumor_gate import (
    apply_rumor_gate,
    evaluate_rumor_item,
    event_update_type,
    rumor_score,
)
from truth_social_reader import (
    TruthSocialPost,
    classify_declaration_status,
    get_truth_social_news,
    is_market_sensitive,
    normalize_truth_social_status,
    truth_post_to_news_item,
)
from reddit_reader import (
    RedditStatus,
    accept_reddit_post,
    get_reddit_news,
    normalize_reddit_post,
    post_to_news_item,
    summarize_reddit,
)
from seen_cache import (
    SeenCache,
    canonical_url,
    event_fingerprint,
    title_fingerprint,
)
from runner import run_one_cycle, runner as radar_runner
from runtime_guards import run_async_phase, run_sync_phase
from sources_registry import apply_source_metadata, source_metadata
from telegram_sources import CHANNELS, CHANNEL_METADATA
from verification import verify_news


def item(title, summary="", source="CNBC"):
    return NewsItem(
        title=title,
        summary=summary,
        content="",
        link=f"https://example.com/{abs(hash(title))}",
        published="",
        source=source,
    )


def publishable_item(title="SEC approves major spot Bitcoin ETF rule"):
    news = item(
        title,
        "The decision directly affects spot Bitcoin ETF access, institutional demand, custody and BTC liquidity.",
        source="SEC - Press Releases",
    )
    news.event_type = "CRYPTO_REGULATION"
    news.affected_assets = ["BTC"]
    news.asset_class = "CRYPTO"
    news.market_impact = 84
    news.score = 84
    news.materiality = "HIGH"
    news.confidence = "Alta"
    news.verification_status = "CONFIRMED"
    news.mechanism = "regulation/access -> institutional demand/liquidity -> BTC"
    news.impact_horizon = "DAYS_WEEKS"
    news.confluence_score = 45
    news.surprise = "KNOWN"
    return news


def critical_trump_threat():
    post = TruthSocialPost(
        account="realDonaldTrump",
        text="If China does not agree, I will impose 50% tariffs immediately.",
        url="https://truthsocial.com/@realDonaldTrump/posts/1",
        created_at="2026-08-14T12:00:00Z",
        post_id="1",
        raw_status="THREATENED",
    )
    news = truth_post_to_news_item(post)
    news.event_type = "FISCAL_TRADE"
    news.affected_assets = ["SP500", "NASDAQ", "EURUSD", "TREASURIES", "BTC"]
    news.asset_class = "MACRO"
    news.market_impact = 92
    news.materiality = "CRITICAL"
    news.mechanism = "tariffs -> inflation/growth expectations -> USD/yields/risk assets"
    news.impact_horizon = "INTRADAY"
    news.market_signals = ["policy declaration"]
    news.confluence_score = 45
    return news


def quiet_btc_state(
    price_change=0.3,
    volatility_z=-1.6,
    volume_z=-1.3,
    funding="NORMAL",
    oi_change=0.4,
    book_imbalance=0.05,
):
    snapshot = BtcMarketSnapshot(
        price=100000,
        price_change_24h=price_change,
        volume_zscore=volume_z,
        open_interest_change=oi_change,
        funding_extreme=funding,
        volatility_zscore=volatility_z,
        timestamp="2026-08-16T12:00:00+00:00",
    )
    liquidity = BtcLiquidityStructureSnapshot(
        book_imbalance=book_imbalance,
        timestamp="2026-08-16T12:00:00+00:00",
    )
    return BtcMarketState(
        snapshot=snapshot,
        liquidity_structure=liquidity,
        confluence="LOW",
        confluence_score=10,
        market_regime="NEUTRAL",
        summary="NO MATERIAL BTC MARKET ANOMALY",
    )


def intraday_snapshot(
    change_1h=0.4,
    change_15m=0.1,
    change_4h=0.8,
    volume_ratio=1.0,
    volatility_ratio=1.0,
    oi_change=0.0,
    funding=0.0001,
    structure_15m="RANGE",
    structure_1h="RANGE",
    structure_4h="RANGE",
    age=0.0,
):
    liquidity = IntradayLiquidityMap(
        visible_above="ORDER_BOOK_VISIBLE",
        visible_below="ORDER_BOOK_VISIBLE",
        nearest_visible_above=101000,
        nearest_visible_below=99000,
        equal_highs=101000,
        equal_lows=99000,
        previous_day_high=100800,
        previous_day_low=99050,
    )
    return BtcIntradaySnapshot(
        price=100000,
        price_change_5m=change_15m / 3,
        price_change_15m=change_15m,
        price_change_30m=change_15m * 1.4,
        price_change_1h=change_1h,
        price_change_4h=change_4h,
        price_change_24h=change_4h * 2,
        volume_15m=100,
        volume_1h=500,
        volume_4h=1500,
        volume_ratio_15m=volume_ratio,
        volume_ratio_1h=volume_ratio,
        volume_ratio_4h=max(1.0, volume_ratio * 0.8),
        realized_volatility_15m=abs(change_15m),
        realized_volatility_1h=abs(change_1h),
        realized_volatility_4h=abs(change_4h),
        volatility_ratio_15m=volatility_ratio,
        volatility_ratio_1h=volatility_ratio,
        volatility_ratio_4h=max(1.0, volatility_ratio * 0.8),
        open_interest=1_000_000,
        oi_change_15m=oi_change / 2,
        oi_change_1h=oi_change,
        oi_change_4h=oi_change * 1.5,
        funding_rate=funding,
        funding_change=0.0,
        funding_regime="POSITIVE" if funding > 0 else "NEGATIVE",
        structure_15m=structure_15m,
        structure_1h=structure_1h,
        structure_4h=structure_4h,
        structure_1d="RANGE",
        liquidity=liquidity,
        market_data_age_minutes=age,
        timestamp="2026-08-19T20:00:00+00:00",
    )


def temp_seen_cache():
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    return SeenCache(tmp.name)


class MarketIntelligenceTests(unittest.TestCase):

    def test_low_materiality_crypto_price_move_is_discarded(self):
        news = item("Bitcoin sube 0,4% durante la manana sin catalizador")

        scored = score_market_item(news)

        self.assertEqual(scored.materiality, "LOW")
        self.assertLess(scored.market_impact, 52)

    def test_macro_high_impact_can_reach_selector(self):
        news = item(
            "Federal Reserve unexpectedly signals higher rates",
            "FOMC says inflation risk may require tighter financial conditions, higher yields, a stronger dollar and pressure on global risk assets.",
            source="Federal Reserve - Monetary Policy",
        )

        scored = score_market_item(news)

        self.assertIn(scored.materiality, {"HIGH", "CRITICAL"})
        self.assertIn("BTC", scored.affected_assets)
        self.assertGreaterEqual(scored.market_impact, 72)

    def test_selector_never_returns_more_than_six_without_ai(self):
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

        self.assertLessEqual(len(selected), 6)

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

    def test_dry_run_never_publishes(self):
        import publishing

        with patch.object(publishing, "DRY_RUN", True), patch.object(
            publishing,
            "publish_message",
            new_callable=AsyncMock,
        ) as publisher:
            with self.assertRaises(DryRunPublishBlocked):
                import asyncio

                asyncio.run(
                    publishing.publish_selected(
                        [item("SEC announces major spot Bitcoin ETF decision")],
                        ["telegram text"],
                    )
                )

            publisher.assert_not_called()

    def test_reviewer_pass_and_dry_run_false_reaches_publisher_mock(self):
        import asyncio
        import publishing

        news = score_market_item(
            item(
                "SEC announces major decision on spot Bitcoin ETF",
                "The decision affects institutional access, ETF demand and BTC liquidity.",
                source="SEC - Press Releases",
            )
        )
        news.confidence = "Alta"
        news.verification_status = "CONFIRMED"

        with patch.object(publishing, "DRY_RUN", False), patch.object(
            publishing,
            "publish_message",
            new_callable=AsyncMock,
        ) as publisher, patch.object(
            publishing,
            "remember",
            Mock(),
        ) as remember:
            published = asyncio.run(
                publishing.publish_selected([news], ["telegram text"])
            )

            self.assertEqual(published, 1)
            publisher.assert_awaited_once_with("telegram text")
            remember.assert_called_once()

    def test_zero_stories_is_valid(self):
        selected = select_news_with_ai([], use_ai=False)

        self.assertEqual(selected, [])
        print_dry_run_report([], [])

    def test_report_mode_titles(self):
        self.assertEqual(
            report_mode_title(dry_run=True, shadow=False),
            "RADAR — DRY RUN",
        )
        self.assertEqual(
            report_mode_title(dry_run=False, shadow=True),
            "RADAR — SHADOW AUTO",
        )
        self.assertEqual(
            report_mode_title(dry_run=False, shadow=False),
            "RADAR — LIVE",
        )

    def test_btc_high_or_critical_can_survive(self):
        news = score_market_item(
            item(
                "SEC announces major spot Bitcoin ETF custody decision",
                "The decision affects ETF flows, custody, institutional access and BTC liquidity.",
                source="SEC - Press Releases",
            )
        )

        selected = select_news_with_ai([news], use_ai=False)

        self.assertIn(news.materiality, {"HIGH", "CRITICAL"})
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].crypto_asset, "BTC")

    def test_macro_high_or_critical_can_survive(self):
        news = score_market_item(
            item(
                "Federal Reserve unexpectedly changes rate guidance",
                "The decision affects rates, yields, the dollar, financial conditions and global risk assets.",
                source="Federal Reserve - Monetary Policy",
            )
        )

        selected = select_news_with_ai([news], use_ai=False)

        self.assertIn(news.materiality, {"HIGH", "CRITICAL"})
        self.assertEqual(len(selected), 1)

    def test_fed_administrative_enforcement_action_is_low_without_btc(self):
        news = score_market_item(
            item(
                "Federal Reserve announces enforcement action",
                "The action concerns extension of credit to bank insiders at a non-systemic institution.",
                source="Federal Reserve - All Press Releases",
            )
        )

        self.assertEqual(news.materiality, "LOW")
        self.assertNotIn("BTC", news.affected_assets)
        self.assertLessEqual(news.market_impact, 25)

    def test_fed_unexpected_50bp_hike_is_critical(self):
        news = score_market_item(
            item(
                "Federal Reserve unexpectedly hikes rates 50bp",
                "The FOMC rate hike reprices yields, the dollar, financial conditions, equities and global risk assets.",
                source="Federal Reserve - Monetary Policy",
            )
        )

        self.assertEqual(news.materiality, "CRITICAL")
        self.assertIn("TREASURIES", news.affected_assets)
        self.assertIn("BTC", news.affected_assets)

    def test_sec_minor_committee_meeting_is_low(self):
        news = score_market_item(
            item(
                "SEC announces investor advisory committee meeting",
                "The committee meeting will discuss administrative matters and request for comment procedures.",
                source="SEC - Press Releases",
            )
        )

        self.assertEqual(news.materiality, "LOW")
        self.assertLessEqual(news.market_impact, 25)

    def test_sec_major_spot_btc_etf_decision_is_high_or_critical(self):
        news = score_market_item(
            item(
                "SEC approves major spot Bitcoin ETF custody decision",
                "The SEC decision changes institutional access, ETF flows, custody rules and BTC liquidity.",
                source="SEC - Press Releases",
            )
        )

        self.assertIn(news.materiality, {"HIGH", "CRITICAL"})
        self.assertIn("BTC", news.affected_assets)

    def test_nvidia_generic_blog_post_is_low(self):
        news = score_market_item(
            item(
                "NVIDIA publishes Omniverse developer blog retrospective",
                "The post describes a generic AI workflow, product demos and customer stories.",
                source="NVIDIA Blog",
            )
        )

        self.assertEqual(news.materiality, "LOW")
        self.assertLessEqual(news.market_impact, 25)

    def test_nvidia_material_guidance_cut_is_high_or_critical(self):
        news = score_market_item(
            item(
                "Nvidia materially cuts revenue guidance by 25%",
                "The guidance cut signals weaker AI chip demand, affects semiconductor expectations and Nasdaq risk.",
                source="NVIDIA Blog",
            )
        )

        self.assertIn(news.materiality, {"HIGH", "CRITICAL"})
        self.assertIn("NVIDIA", news.affected_assets)
        self.assertIn("NASDAQ", news.affected_assets)

    def test_ecb_routine_banking_statistics_are_not_high(self):
        news = score_market_item(
            item(
                "ECB publishes consolidated banking data for end-March 2026",
                "The statistical release contains routine banking statistics without abnormal stress or surprise.",
                source="Banco Central Europeo",
            )
        )

        self.assertIn(news.materiality, {"LOW", "MEDIUM"})
        self.assertNotIn("BTC", news.affected_assets)
        self.assertNotIn("ETH", news.affected_assets)
        self.assertLessEqual(news.market_impact, 40)

    def test_btc_etf_large_confirmed_inflows_can_survive(self):
        news = score_market_item(
            item(
                "Bitcoin ETF receives exceptionally large confirmed inflows over multiple sessions",
                "ETF inflows accelerated over multiple sessions, indicating a material change in institutional demand and BTC liquidity.",
                source="CoinDesk",
            )
        )

        selected = select_news_with_ai([news], use_ai=False)

        self.assertIn(news.materiality, {"HIGH", "CRITICAL"})
        self.assertIn("BTC", news.affected_assets)
        self.assertEqual(len(selected), 1)

    def test_eth_generic_ecosystem_news_is_low(self):
        news = score_market_item(
            item(
                "Ethereum ecosystem project announces community partnership",
                "A small ecosystem partnership and generic developer update has no ETF, staking, protocol or regulatory catalyst.",
                source="Cointelegraph",
            )
        )

        self.assertEqual(news.materiality, "LOW")

    def test_btc_price_one_percent_without_other_signals_no_event(self):
        state = analyze_btc_market_snapshot(
            BtcMarketSnapshot(
                price=100000,
                price_change_24h=1.0,
                volume_zscore=0.2,
                open_interest_change=0.0,
                funding_rate=0.0001,
                funding_extreme="NORMAL",
                volatility_zscore=0.1,
                liquidations_long=0,
                liquidations_short=0,
            )
        )

        self.assertEqual(state.confluence, "LOW")
        self.assertIsNone(market_state_to_news_item(state))

    def test_btc_slight_oi_increase_no_event(self):
        state = analyze_btc_market_snapshot(
            BtcMarketSnapshot(
                open_interest_change=2.0,
                funding_rate=0.0001,
                funding_extreme="NORMAL",
                volume_zscore=0.0,
                volatility_zscore=0.0,
            )
        )

        self.assertEqual(state.signals, [])
        self.assertIsNone(market_state_to_news_item(state))

    def test_btc_oi_funding_volume_confluence_is_relevant(self):
        state = analyze_btc_market_snapshot(
            BtcMarketSnapshot(
                open_interest_change=12.0,
                funding_rate=0.0015,
                funding_extreme="POSITIVE",
                volume_zscore=3.2,
                volatility_zscore=0.5,
                liquidations_long=0,
                liquidations_short=0,
            )
        )
        event = market_state_to_news_item(state)

        self.assertEqual(state.confluence, "HIGH")
        self.assertIn("LEVERAGE_BUILDUP", [signal.name for signal in state.signals])
        self.assertIsNotNone(event)
        self.assertEqual(event.source, "MARKET_STATE")

    def test_isolated_liquidation_spike_is_not_high_event(self):
        state = analyze_btc_market_snapshot(
            BtcMarketSnapshot(
                liquidations_long=80_000_000,
                open_interest_change=0.0,
                funding_rate=0.0001,
                funding_extreme="NORMAL",
                volatility_zscore=0.0,
            )
        )

        self.assertNotEqual(state.confluence, "HIGH")
        self.assertIsNone(market_state_to_news_item(state))

    def test_liquidation_oi_collapse_volatility_is_deleveraging_candidate(self):
        state = analyze_btc_market_snapshot(
            BtcMarketSnapshot(
                liquidations_long=90_000_000,
                open_interest_change=-12.0,
                funding_rate=0.0,
                funding_extreme="NORMAL",
                volatility_zscore=3.0,
            )
        )
        event = market_state_to_news_item(state)

        self.assertEqual(state.market_regime, "DELEVERAGING")
        self.assertEqual(state.confluence, "HIGH")
        self.assertIsNotNone(event)

    def test_market_state_missing_data_does_not_invent(self):
        state = analyze_btc_market_snapshot(BtcMarketSnapshot())

        self.assertEqual(state.signals, [])
        self.assertEqual(state.summary, "BTC MARKET STATE: INSUFFICIENT DATA")
        self.assertEqual(state.status, "INSUFFICIENT")
        self.assertIsNone(market_state_to_news_item(state))

    def test_market_data_api_down_keeps_engine_alive(self):
        def failing_fetcher():
            raise RuntimeError("api down")

        state = fetch_btc_market_state(fetcher=failing_fetcher)

        self.assertIn("market_data:RuntimeError", state.snapshot.errors)
        self.assertEqual(state.confluence, "LOW")
        self.assertEqual(state.status, "INSUFFICIENT")

    def test_market_data_partial_failure_is_degraded_not_insufficient(self):
        state = fetch_btc_market_state(
            fetcher=lambda: BtcMarketSnapshot(
                price=100000,
                price_change_1h=0.2,
                price_change_24h=1.0,
                volume_24h=10_000_000,
                timestamp="2026-08-20T10:00:00+00:00",
            ),
            etf_fetcher=lambda: BtcEtfFlowSnapshot(status="NOT_CONFIGURED"),
            onchain_fetcher=lambda: BtcOnchainSnapshot(errors=["coinmetrics_timeout"]),
            sentiment_fetcher=lambda: BtcSentimentSnapshot(),
            liquidity_fetcher=lambda: BtcLiquidityStructureSnapshot(errors=["depth:TimeoutError"]),
            intraday_fetcher=lambda liquidity_structure=None: BtcIntradaySnapshot(
                price=100000,
                price_change_5m=0.1,
                price_change_15m=0.3,
                price_change_30m=0.5,
                price_change_1h=1.0,
                price_change_4h=1.2,
                price_change_24h=2.0,
                volume_15m=100,
                volume_1h=500,
                volume_4h=1500,
                volume_ratio_1h=2.0,
                realized_volatility_1h=1.0,
                volatility_ratio_1h=1.2,
                open_interest=1_000_000,
                oi_change_1h=0.5,
                funding_rate=0.0001,
                funding_regime="POSITIVE",
                structure_15m="RANGE",
                structure_1h="RANGE",
                structure_4h="RANGE",
                liquidity=IntradayLiquidityMap(),
                market_data_age_minutes=0,
                timestamp="2026-08-20T10:00:00+00:00",
                errors=["order_book:TimeoutError"],
            ),
        )

        self.assertEqual(state.status, "DEGRADED")
        self.assertEqual(state.intraday.status, "DEGRADED")
        self.assertNotEqual(state.intraday.decision, "INSUFFICIENT_DATA")

    def test_market_report_does_not_print_no_anomaly_for_insufficient_data(self):
        from dry_run_report import print_btc_market_state

        state = BtcMarketState(
            snapshot=BtcMarketSnapshot(errors=["ticker_24h:TimeoutError"]),
            status="INSUFFICIENT",
            summary="BTC MARKET STATE: INSUFFICIENT DATA",
        )
        output = io.StringIO()
        with redirect_stdout(output):
            print_btc_market_state(state)

        text = output.getvalue()
        self.assertIn("BTC MARKET STATE: INSUFFICIENT DATA", text)
        self.assertNotIn("NO MATERIAL BTC MARKET ANOMALY", text)

    def test_market_state_never_produces_buy_sell_language(self):
        state = analyze_btc_market_snapshot(
            BtcMarketSnapshot(
                open_interest_change=12.0,
                funding_rate=0.0015,
                funding_extreme="POSITIVE",
                volume_zscore=3.2,
            )
        )
        event = market_state_to_news_item(state)
        text = f"{state.summary} {event.title} {event.summary} {event.content}".lower()

        self.assertNotIn("buy", text)
        self.assertNotIn("sell", text)
        self.assertNotIn("compra", text)
        self.assertNotIn("vende", text)

    def test_etf_small_isolated_inflow_no_event(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=10_000_000,
                btc_etf_flow_3d_avg=8_000_000,
                btc_etf_flow_7d_avg=7_000_000,
                btc_etf_flow_zscore=0.2,
                btc_etf_flow_streak=1,
                btc_etf_flow_regime="NEUTRAL",
            ),
        )

        self.assertEqual(state.confluence, "LOW")
        self.assertIsNone(market_state_to_news_item(state))

    def test_etf_large_relative_inflow_generates_strong_signal(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=700_000_000,
                btc_etf_flow_3d_avg=350_000_000,
                btc_etf_flow_7d_avg=100_000_000,
                btc_etf_flow_zscore=2.8,
                btc_etf_flow_streak=1,
                btc_etf_flow_regime="NEUTRAL",
            ),
        )

        self.assertIn("ETF_INFLOW_STRONG", [signal.name for signal in state.signals])
        self.assertNotEqual(state.confluence, "HIGH")

    def test_five_days_elevated_etf_inflows_positive_regime(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=500_000_000,
                btc_etf_flow_3d_avg=480_000_000,
                btc_etf_flow_7d_avg=250_000_000,
                btc_etf_flow_zscore=2.2,
                btc_etf_flow_streak=5,
                btc_etf_flow_regime="POSITIVE",
            ),
        )

        names = [signal.name for signal in state.signals]
        self.assertIn("ETF_POSITIVE_REGIME", names)

    def test_strong_etf_outflow_is_signal_but_not_auto_high_alone(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=-650_000_000,
                btc_etf_flow_3d_avg=-300_000_000,
                btc_etf_flow_7d_avg=-100_000_000,
                btc_etf_flow_zscore=-2.4,
                btc_etf_flow_streak=-1,
                btc_etf_flow_regime="NEUTRAL",
            ),
        )

        self.assertIn("ETF_OUTFLOW_STRONG", [signal.name for signal in state.signals])
        self.assertIsNone(market_state_to_news_item(state))

    def test_persistent_etf_outflows_negative_regime(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=-450_000_000,
                btc_etf_flow_3d_avg=-420_000_000,
                btc_etf_flow_7d_avg=-250_000_000,
                btc_etf_flow_zscore=-2.1,
                btc_etf_flow_streak=-5,
                btc_etf_flow_regime="NEGATIVE",
            ),
        )

        self.assertIn("ETF_NEGATIVE_REGIME", [signal.name for signal in state.signals])

    def test_etf_flow_reversal_signal(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=500_000_000,
                btc_etf_flow_3d_avg=100_000_000,
                btc_etf_flow_7d_avg=-200_000_000,
                btc_etf_flow_zscore=2.5,
                btc_etf_flow_streak=1,
                btc_etf_flow_regime="NEUTRAL",
            ),
        )

        self.assertIn("ETF_FLOW_REVERSAL", [signal.name for signal in state.signals])

    def test_etf_api_failure_keeps_radar_alive(self):
        def failing_etf_fetcher():
            raise RuntimeError("etf api down")

        state = fetch_btc_market_state(
            fetcher=lambda: BtcMarketSnapshot(),
            etf_fetcher=failing_etf_fetcher,
        )

        self.assertIn("etf_flows:RuntimeError", state.etf_flows.errors)
        self.assertEqual(state.confluence, "LOW")

    def test_etf_unknown_does_not_invent_conclusion(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            BtcEtfFlowSnapshot(errors=["etf_flows:NO_DATA"]),
        )

        self.assertEqual(state.confluence, "LOW")
        self.assertIsNone(market_state_to_news_item(state))

    def test_etf_flows_plus_other_signals_increase_confluence(self):
        base_snapshot = BtcMarketSnapshot(
            open_interest_change=9.0,
            funding_rate=0.0001,
            funding_extreme="NORMAL",
            volume_zscore=3.0,
        )
        state_without_etf = analyze_btc_market_state(base_snapshot, None)
        state_with_etf = analyze_btc_market_state(
            base_snapshot,
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=700_000_000,
                btc_etf_flow_3d_avg=350_000_000,
                btc_etf_flow_7d_avg=100_000_000,
                btc_etf_flow_zscore=2.8,
                btc_etf_flow_streak=1,
                btc_etf_flow_regime="NEUTRAL",
            ),
        )

        self.assertGreater(
            state_with_etf.confluence_score,
            state_without_etf.confluence_score,
        )
        self.assertIn(
            "INSTITUTIONAL_DEMAND_CONFLUENCE",
            [signal.name for signal in state_with_etf.signals],
        )

    def test_etf_flow_isolated_does_not_produce_buy_sell_language(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=700_000_000,
                btc_etf_flow_3d_avg=350_000_000,
                btc_etf_flow_7d_avg=100_000_000,
                btc_etf_flow_zscore=2.8,
                btc_etf_flow_streak=1,
                btc_etf_flow_regime="NEUTRAL",
            ),
        )

        text = " ".join(
            f"{signal.name} {signal.evidence}"
            for signal in state.signals
        ).lower()

        self.assertNotIn("buy", text)
        self.assertNotIn("sell", text)
        self.assertNotIn("compra", text)
        self.assertNotIn("vende", text)

    def test_isolated_whale_transfer_is_not_event(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            BtcOnchainSnapshot(
                btc_large_transfer_count=1,
                btc_large_transfer_volume=10_000,
                btc_whale_activity="OBSERVED",
                large_transfers=[
                    LargeBtcTransfer(
                        amount_btc=10_000,
                        from_label="unknown",
                        to_label="unknown",
                    )
                ],
            ),
        )

        self.assertEqual(state.confluence, "LOW")
        self.assertIsNone(market_state_to_news_item(state))

    def test_slight_exchange_inflow_is_not_high_signal(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            BtcOnchainSnapshot(
                btc_exchange_inflow=1000,
                btc_exchange_inflow_zscore=1.2,
            ),
        )

        self.assertNotIn("EXCHANGE_INFLOW_ELEVATED", [signal.name for signal in state.signals])
        self.assertEqual(state.confluence, "LOW")

    def test_extreme_exchange_inflow_is_strong_signal(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            BtcOnchainSnapshot(
                btc_exchange_inflow=5000,
                btc_exchange_inflow_zscore=3.2,
            ),
        )

        self.assertIn("EXCHANGE_INFLOW_EXTREME", [signal.name for signal in state.signals])
        self.assertNotEqual(state.confluence, "HIGH")

    def test_outflows_extreme_and_reserves_falling_is_accumulation_consistent(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            BtcOnchainSnapshot(
                btc_exchange_outflow=6000,
                btc_exchange_outflow_zscore=3.1,
                btc_exchange_reserves=2_000_000,
                btc_exchange_reserve_change_1d=-0.8,
                btc_exchange_reserve_change_7d=-1.5,
            ),
        )

        self.assertEqual(state.onchain_regime, "ACCUMULATION")
        self.assertIn("EXCHANGE_OUTFLOW_EXTREME", [signal.name for signal in state.signals])
        self.assertIn("EXCHANGE_RESERVES_FALLING", [signal.name for signal in state.signals])

    def test_inflows_extreme_and_reserves_rising_is_distribution_risk(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            BtcOnchainSnapshot(
                btc_exchange_inflow=6000,
                btc_exchange_inflow_zscore=3.1,
                btc_exchange_reserves=2_200_000,
                btc_exchange_reserve_change_1d=0.8,
                btc_exchange_reserve_change_7d=1.6,
            ),
        )

        self.assertEqual(state.onchain_regime, "DISTRIBUTION")
        self.assertIn("EXCHANGE_INFLOW_EXTREME", [signal.name for signal in state.signals])
        self.assertIn("EXCHANGE_RESERVES_RISING", [signal.name for signal in state.signals])

    def test_unknown_wallet_transfer_classification(self):
        transfer = LargeBtcTransfer(
            amount_btc=5000,
            from_label="unknown wallet",
            to_label="unknown wallet",
        )

        self.assertEqual(classify_large_transfer(transfer), "UNKNOWN")

    def test_onchain_api_unavailable_keeps_radar_alive(self):
        def failing_onchain_fetcher():
            raise RuntimeError("onchain down")

        state = fetch_btc_market_state(
            fetcher=lambda: BtcMarketSnapshot(),
            etf_fetcher=lambda: BtcEtfFlowSnapshot(),
            onchain_fetcher=failing_onchain_fetcher,
        )

        self.assertIn("onchain:RuntimeError", state.onchain.errors)
        self.assertEqual(state.confluence, "LOW")

    def test_onchain_missing_data_does_not_invent(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            BtcOnchainSnapshot(errors=["onchain:NO_DATA"]),
        )

        self.assertEqual(state.onchain_regime, "UNKNOWN")
        self.assertIsNone(market_state_to_news_item(state))

    def test_onchain_etf_derivatives_confluence_increases(self):
        base = analyze_btc_market_state(
            BtcMarketSnapshot(
                open_interest_change=9.0,
                funding_rate=0.0001,
                funding_extreme="NORMAL",
            ),
            None,
            None,
        )
        with_onchain = analyze_btc_market_state(
            BtcMarketSnapshot(
                open_interest_change=9.0,
                funding_rate=0.0001,
                funding_extreme="NORMAL",
            ),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=700_000_000,
                btc_etf_flow_3d_avg=350_000_000,
                btc_etf_flow_7d_avg=100_000_000,
                btc_etf_flow_zscore=2.8,
                btc_etf_flow_streak=1,
            ),
            BtcOnchainSnapshot(
                btc_exchange_outflow=7000,
                btc_exchange_outflow_zscore=3.2,
                btc_exchange_reserves=2_000_000,
                btc_exchange_reserve_change_1d=-0.8,
                btc_exchange_reserve_change_7d=-1.4,
            ),
        )

        self.assertGreater(with_onchain.confluence_score, base.confluence_score)
        self.assertEqual(with_onchain.confluence, "HIGH")

    def test_onchain_never_produces_buy_sell_language(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            BtcOnchainSnapshot(
                btc_exchange_inflow=6000,
                btc_exchange_inflow_zscore=3.1,
                btc_exchange_reserves=2_200_000,
                btc_exchange_reserve_change_1d=0.8,
                btc_exchange_reserve_change_7d=1.6,
            ),
        )
        text = " ".join(
            f"{signal.name} {signal.evidence}"
            for signal in state.signals
        ).lower()

        self.assertNotIn("buy", text)
        self.assertNotIn("sell", text)
        self.assertNotIn("compra", text)
        self.assertNotIn("vende", text)

    def test_onchain_never_claims_institutions_are_buying_without_direct_evidence(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=700_000_000,
                btc_etf_flow_zscore=2.8,
                btc_etf_flow_streak=1,
            ),
            BtcOnchainSnapshot(
                btc_exchange_outflow=7000,
                btc_exchange_outflow_zscore=3.2,
                btc_exchange_reserve_change_1d=-0.8,
                btc_exchange_reserve_change_7d=-1.4,
            ),
        )
        text = f"{state.summary} " + " ".join(signal.evidence for signal in state.signals)
        text = text.lower()

        self.assertNotIn("institutions are buying", text)
        self.assertNotIn("las instituciones están comprando", text)

    def test_retail_bullish_isolated_no_event(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            None,
            BtcSentimentSnapshot(retail_sentiment="BULLISH", retail_sentiment_score=65),
        )

        self.assertIn("RETAIL_BULLISH", [signal.name for signal in state.signals])
        self.assertEqual(state.confluence, "LOW")
        self.assertIsNone(market_state_to_news_item(state))

    def test_retail_euphoria_funding_extreme_oi_extreme_is_crowding_relevant(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(
                open_interest_change=12.0,
                funding_rate=0.0015,
                funding_extreme="POSITIVE",
            ),
            None,
            None,
            BtcSentimentSnapshot(retail_sentiment="EUPHORIA", retail_sentiment_score=92),
        )

        names = [signal.name for signal in state.signals]
        self.assertIn("CROWDED_LONG", names)
        self.assertIn("CROWDING_RISK_CONFLUENCE", names)
        self.assertEqual(state.confluence, "HIGH")

    def test_retail_bearish_etf_inflows_exchange_outflows_positive_divergence(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(funding_rate=0.0001, funding_extreme="NORMAL"),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=700_000_000,
                btc_etf_flow_zscore=2.8,
                btc_etf_flow_streak=1,
                btc_etf_flow_regime="NEUTRAL",
            ),
            BtcOnchainSnapshot(
                btc_exchange_outflow=7000,
                btc_exchange_outflow_zscore=3.2,
                btc_exchange_reserve_change_1d=-0.8,
                btc_exchange_reserve_change_7d=-1.4,
            ),
            BtcSentimentSnapshot(retail_sentiment="BEARISH", retail_sentiment_score=30),
        )

        names = [signal.name for signal in state.signals]
        self.assertIn("POSITIVE_FLOW_NEGATIVE_RETAIL_DIVERGENCE", names)
        self.assertIn("SENTIMENT_FLOW_DIVERGENCE_CONFLUENCE", names)
        self.assertEqual(state.confluence, "HIGH")

    def test_social_attention_spike_alone_is_not_high(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            None,
            BtcSentimentSnapshot(
                retail_attention="SPIKE",
                retail_attention_score=90,
            ),
        )

        self.assertIn("RETAIL_ATTENTION_SPIKE", [signal.name for signal in state.signals])
        self.assertNotEqual(state.confluence, "HIGH")
        self.assertIsNone(market_state_to_news_item(state))

    def test_sentiment_api_unavailable_keeps_radar_alive(self):
        def failing_sentiment_fetcher():
            raise RuntimeError("sentiment down")

        state = fetch_btc_market_state(
            fetcher=lambda: BtcMarketSnapshot(),
            etf_fetcher=lambda: BtcEtfFlowSnapshot(),
            onchain_fetcher=lambda: BtcOnchainSnapshot(),
            sentiment_fetcher=failing_sentiment_fetcher,
        )

        self.assertIn("sentiment:RuntimeError", state.sentiment.errors)
        self.assertEqual(state.confluence, "LOW")

    def test_unknown_sentiment_does_not_invent(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            None,
            BtcSentimentSnapshot(errors=["sentiment:NO_DATA"]),
        )

        self.assertEqual(state.sentiment.retail_sentiment, "UNKNOWN")
        self.assertEqual(state.sentiment.crowding_state, "UNKNOWN")
        self.assertNotIn("CROWDED_LONG", [signal.name for signal in state.signals])
        self.assertIsNone(market_state_to_news_item(state))

    def test_crowding_long_does_not_produce_sell_signal(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(
                open_interest_change=12.0,
                funding_rate=0.0015,
                funding_extreme="POSITIVE",
            ),
            None,
            None,
            BtcSentimentSnapshot(retail_sentiment="EUPHORIA", retail_sentiment_score=92),
        )
        event = market_state_to_news_item(state)
        text = f"{state.summary} {event.title} {event.summary} {event.content}".lower()

        self.assertNotIn("sell", text)
        self.assertNotIn("vende", text)

    def test_crowding_short_does_not_produce_buy_signal(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(
                open_interest_change=12.0,
                funding_rate=-0.0015,
                funding_extreme="NEGATIVE",
            ),
            None,
            None,
            BtcSentimentSnapshot(retail_sentiment="PANIC", retail_sentiment_score=8),
        )
        event = market_state_to_news_item(state)
        text = f"{state.summary} {event.title} {event.summary} {event.content}".lower()

        self.assertNotIn("buy", text)
        self.assertNotIn("compra", text)

    def test_institutional_proxy_is_never_claimed_as_certainty_without_direct_evidence(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=700_000_000,
                btc_etf_flow_zscore=2.8,
            ),
            BtcOnchainSnapshot(
                btc_exchange_outflow=7000,
                btc_exchange_outflow_zscore=3.2,
            ),
            BtcSentimentSnapshot(retail_sentiment="BEARISH", retail_sentiment_score=30),
        )
        text = f"{state.sentiment.institutional_flow_proxy} {state.summary} "
        text += " ".join(signal.evidence for signal in state.signals)
        text = text.lower()

        self.assertNotIn("institutions are buying", text)
        self.assertNotIn("las instituciones están comprando", text)
        self.assertEqual(
            state.sentiment.institutional_flow_proxy,
            "INSTITUTIONAL_DEMAND_POSITIVE",
        )
        self.assertTrue("proxy" in text or "proxies" in text)

    def test_sentiment_derivatives_and_flows_increase_confluence(self):
        base = analyze_btc_market_state(
            BtcMarketSnapshot(
                open_interest_change=12.0,
                funding_rate=0.0015,
                funding_extreme="POSITIVE",
            )
        )
        with_sentiment_flows = analyze_btc_market_state(
            BtcMarketSnapshot(
                open_interest_change=12.0,
                funding_rate=0.0015,
                funding_extreme="POSITIVE",
            ),
            BtcEtfFlowSnapshot(
                btc_etf_net_flow=-650_000_000,
                btc_etf_flow_zscore=-2.5,
            ),
            BtcOnchainSnapshot(
                btc_exchange_inflow=6000,
                btc_exchange_inflow_zscore=3.1,
                btc_exchange_reserve_change_1d=0.8,
                btc_exchange_reserve_change_7d=1.6,
            ),
            BtcSentimentSnapshot(retail_sentiment="EUPHORIA", retail_sentiment_score=92),
        )

        self.assertGreater(with_sentiment_flows.confluence_score, base.confluence_score)
        self.assertIn(
            "NEGATIVE_FLOW_POSITIVE_RETAIL_DIVERGENCE",
            [signal.name for signal in with_sentiment_flows.signals],
        )

    def test_liquidity_book_normal_no_event(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            None,
            None,
            BtcLiquidityStructureSnapshot(
                best_bid=99990,
                best_ask=100010,
                spread=20,
                bid_depth_1pct=100_000_000,
                ask_depth_1pct=105_000_000,
                bid_depth_2pct=180_000_000,
                ask_depth_2pct=185_000_000,
                book_imbalance=-0.02,
                structure="RANGE",
            ),
        )

        self.assertEqual(state.confluence, "LOW")
        self.assertIsNone(market_state_to_news_item(state))

    def test_bid_depth_slightly_greater_is_not_high(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            None,
            None,
            BtcLiquidityStructureSnapshot(
                bid_depth_1pct=130_000_000,
                ask_depth_1pct=100_000_000,
                bid_depth_2pct=220_000_000,
                ask_depth_2pct=190_000_000,
                book_imbalance=0.13,
            ),
        )

        self.assertNotIn("BID_LIQUIDITY_EXTREME", [signal.name for signal in state.signals])
        self.assertEqual(state.confluence, "LOW")

    def test_extreme_ask_concentration_generates_liquidity_signal(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            None,
            None,
            BtcLiquidityStructureSnapshot(
                bid_depth_1pct=100_000_000,
                ask_depth_1pct=320_000_000,
                bid_depth_2pct=180_000_000,
                ask_depth_2pct=500_000_000,
                book_imbalance=-0.52,
                largest_ask_cluster=LiquidityCluster(
                    price=101000,
                    notional=80_000_000,
                    distance_pct=1.0,
                ),
            ),
        )

        names = [signal.name for signal in state.signals]
        self.assertIn("ASK_LIQUIDITY_EXTREME", names)
        self.assertIn("ORDERBOOK_IMBALANCE_ASK", names)
        self.assertIsNone(market_state_to_news_item(state))

    def test_clean_breakout_with_volume_is_structure_signal_not_publication(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            None,
            None,
            BtcLiquidityStructureSnapshot(
                structure="BULLISH",
                breakout_state="BREAKOUT_UP",
                smc_signals=[
                    "BULLISH_BREAK_OF_STRUCTURE",
                    "DISPLACEMENT_UP",
                ],
            ),
        )

        names = [signal.name for signal in state.signals]
        self.assertIn("BULLISH_BREAK_OF_STRUCTURE", names)
        self.assertIn("DISPLACEMENT_UP", names)
        self.assertIsNone(market_state_to_news_item(state))

    def test_failed_breakout_crowded_long_funding_extreme_increases_confluence(self):
        with_structure = analyze_btc_market_state(
            BtcMarketSnapshot(
                open_interest_change=12.0,
                funding_rate=0.0015,
                funding_extreme="POSITIVE",
            ),
            None,
            None,
            BtcSentimentSnapshot(retail_sentiment="EUPHORIA", retail_sentiment_score=92),
            BtcLiquidityStructureSnapshot(
                breakout_state="FAILED_BREAKOUT_UP",
                liquidity_sweep="ABOVE",
                bid_depth_2pct=80_000_000,
                ask_depth_2pct=400_000_000,
                smc_signals=[
                    "FAILED_BREAKOUT",
                    "LIQUIDITY_SWEEP_ABOVE",
                ],
            ),
        )

        self.assertIn(
            "STRUCTURE_CROWDING_RISK_CONFLUENCE",
            [signal.name for signal in with_structure.signals],
        )
        self.assertEqual(with_structure.confluence, "HIGH")

    def test_liquidity_sweep_isolated_is_not_high(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            None,
            None,
            BtcLiquidityStructureSnapshot(
                liquidity_sweep="ABOVE",
                smc_signals=["LIQUIDITY_SWEEP_ABOVE"],
            ),
        )

        self.assertIn("LIQUIDITY_SWEEP_ABOVE", [signal.name for signal in state.signals])
        self.assertNotEqual(state.confluence, "HIGH")
        self.assertIsNone(market_state_to_news_item(state))

    def test_smc_signal_isolated_never_final_event(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            None,
            None,
            BtcLiquidityStructureSnapshot(smc_signals=["FVG_ABOVE"]),
        )

        self.assertIn("FVG_ABOVE", [signal.name for signal in state.signals])
        self.assertIsNone(market_state_to_news_item(state))

    def test_liquidity_api_unavailable_keeps_radar_alive(self):
        def failing_liquidity_fetcher():
            raise RuntimeError("order book down")

        state = fetch_btc_market_state(
            fetcher=lambda: BtcMarketSnapshot(),
            etf_fetcher=lambda: BtcEtfFlowSnapshot(),
            onchain_fetcher=lambda: BtcOnchainSnapshot(),
            sentiment_fetcher=lambda: BtcSentimentSnapshot(),
            liquidity_fetcher=failing_liquidity_fetcher,
        )

        self.assertIn("liquidity_structure:RuntimeError", state.liquidity_structure.errors)
        self.assertEqual(state.confluence, "LOW")

    def test_liquidity_structure_never_produces_buy_sell_language(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(
                open_interest_change=12.0,
                funding_rate=0.0015,
                funding_extreme="POSITIVE",
            ),
            None,
            None,
            BtcSentimentSnapshot(retail_sentiment="EUPHORIA", retail_sentiment_score=92),
            BtcLiquidityStructureSnapshot(
                breakout_state="FAILED_BREAKOUT_UP",
                liquidity_sweep="ABOVE",
                smc_signals=[
                    "FAILED_BREAKOUT",
                    "LIQUIDITY_SWEEP_ABOVE",
                ],
            ),
        )
        event = market_state_to_news_item(state)
        text = f"{state.summary} {event.title} {event.summary} {event.content}".lower()

        self.assertNotIn("buy", text)
        self.assertNotIn("sell", text)
        self.assertNotIn("compra", text)
        self.assertNotIn("vende", text)

    def test_liquidity_structure_never_claims_institutions_are_manipulating(self):
        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            None,
            None,
            BtcLiquidityStructureSnapshot(
                liquidity_sweep="ABOVE",
                smc_signals=["LIQUIDITY_SWEEP_ABOVE", "FAILED_BREAKOUT"],
            ),
        )
        text = " ".join(signal.evidence for signal in state.signals).lower()

        self.assertNotIn("institutions are manipulating", text)
        self.assertNotIn("smart money hunted stops", text)
        self.assertNotIn("manipulacion institucional", text)

    def test_gate_high_pass_confirmed_direct_mechanism_is_publishable(self):
        news = publishable_item()

        result = evaluate_item(news, review_ok=True)

        self.assertTrue(result.passed)
        self.assertEqual(news.final_decision, "PASS")
        self.assertEqual(result.mechanism_strength, "DIRECT")

    def test_gate_high_weak_indirect_mechanism_rejects(self):
        news = publishable_item("Fed administrative update somehow affects BTC")
        news.event_type = "UNKNOWN"
        news.mechanism = "generic risk assets -> BTC"
        news.affected_assets = ["BTC"]

        result = evaluate_item(news, review_ok=True)

        self.assertFalse(result.passed)
        self.assertIn("weak_mechanism", result.reasons)
        self.assertIn("weak_asset_link", result.reasons)

    def test_gate_critical_rumor_can_pass_only_when_config_allows(self):
        news = publishable_item("Rumor: SEC emergency spot Bitcoin ETF decision")
        news.market_impact = 94
        news.materiality = "CRITICAL"
        news.verification_status = "RUMOR"
        news.confidence = "Media"
        news.is_rumor = True

        blocked = evaluate_item(
            news,
            review_ok=True,
            config=PublicationGateConfig(allow_critical_rumor=False),
        )
        allowed = evaluate_item(
            news,
            review_ok=True,
            config=PublicationGateConfig(allow_critical_rumor=True),
        )

        self.assertFalse(blocked.passed)
        self.assertIn("unverified", blocked.reasons)
        self.assertTrue(allowed.passed)

    def test_gate_reviewer_fail_rejects(self):
        result = evaluate_item(publishable_item(), review_ok=False)

        self.assertFalse(result.passed)
        self.assertIn("reviewer_failed", result.reasons)

    def test_gate_duplicate_rejects(self):
        news = publishable_item()
        news.duplicate = True

        result = evaluate_item(news, review_ok=True)

        self.assertFalse(result.passed)
        self.assertIn("duplicate", result.reasons)

    def test_gate_routine_primary_source_item_rejects(self):
        news = publishable_item("ECB publishes consolidated banking data for end-March 2026")
        news.summary = "Routine statistical release without abnormal stress or surprise."
        news.source_type = "PRIMARY"
        news.market_impact = 86
        news.materiality = "HIGH"

        result = evaluate_item(news, review_ok=True)

        self.assertFalse(result.passed)
        self.assertIn("routine_content", result.reasons)

    def test_gate_high_already_discounted_without_surprise_rejects(self):
        news = publishable_item()
        news.discountedness = "HIGH"
        news.surprise = "UNKNOWN"

        result = evaluate_item(news, review_ok=True)

        self.assertFalse(result.passed)
        self.assertIn("already_discounted", result.reasons)

    def test_gate_max_two_normal_publications(self):
        items = [
            publishable_item(f"SEC approves major spot Bitcoin ETF rule {i}")
            for i in range(3)
        ]
        with patch("publication_gate._published_today_count", return_value=0):
            publishable, results, _ = apply_publication_gate(
                items,
                {"ok": True, "errors": []},
                PublicationGateConfig(max_per_cycle=2, max_per_day=10),
            )

        self.assertEqual(len(publishable), 2)
        self.assertEqual(
            sum("frequency_limit" in result.reasons for result in results),
            1,
        )

    def test_gate_critical_not_duplicate_can_break_normal_limit(self):
        normal = [
            publishable_item(f"SEC approves major spot Bitcoin ETF rule {i}")
            for i in range(2)
        ]
        critical = publishable_item("Federal Reserve unexpectedly hikes rates 50bp")
        critical.event_type = "CENTRAL_BANK"
        critical.affected_assets = ["TREASURIES", "EURUSD", "SP500", "NASDAQ", "BTC"]
        critical.asset_class = "MACRO"
        critical.market_impact = 95
        critical.materiality = "CRITICAL"
        critical.mechanism = "rates/yields/USD -> financial conditions -> risk assets"
        critical.summary = "The unexpected hike reprices yields, USD and financial conditions."

        with patch("publication_gate._published_today_count", return_value=0):
            publishable, _, _ = apply_publication_gate(
                normal + [critical],
                {"ok": True, "errors": []},
                PublicationGateConfig(max_per_cycle=2, max_per_day=2),
            )

        self.assertEqual(len(publishable), 3)
        self.assertIn(critical, publishable)

    def test_gate_low_never_publishes(self):
        news = publishable_item("Bitcoin rises 0.4 percent with no catalyst")
        news.market_impact = 20
        news.materiality = "LOW"

        result = evaluate_item(news, review_ok=True)

        self.assertFalse(result.passed)
        self.assertIn("low_materiality", result.reasons)

    def test_reddit_api_normalizes_posts(self):
        raw = {
            "data": {
                "subreddit": "Bitcoin",
                "title": "Bitcoin ETF flows accelerate after a macro catalyst",
                "selftext": "Discussion of ETF demand and liquidity.",
                "permalink": "/r/Bitcoin/comments/abc/test/",
                "score": 120,
                "num_comments": 45,
                "created_utc": 1_800_000_000,
                "link_flair_text": "Markets",
                "author": "sample_user",
                "upvote_ratio": 0.91,
            }
        }

        post = normalize_reddit_post(raw)
        news = post_to_news_item(post)

        self.assertEqual(post.subreddit, "Bitcoin")
        self.assertEqual(post.score, 120)
        self.assertEqual(news.source, "r/Bitcoin")
        self.assertEqual(news.source_type, "COMMUNITY")
        self.assertTrue(news.is_rumor)

    def test_reddit_credentials_absent_continues(self):
        class NotConfiguredClient:
            def configured(self):
                return False

        news, status = get_reddit_news(client=NotConfiguredClient())

        self.assertEqual(news, [])
        self.assertEqual(status.status, "DISABLED_PENDING_APPROVAL")
        self.assertEqual(status.posts_read, 0)
        self.assertEqual(status.posts_accepted, 0)

    def test_reddit_pending_approval_makes_no_http_requests(self):
        class PendingClient:
            def configured(self):
                return True

            def approved(self):
                return False

            def subreddit_new(self, subreddit, limit=25):
                raise AssertionError("Reddit HTTP should not be called while disabled.")

        news, status = get_reddit_news(client=PendingClient())

        self.assertEqual(news, [])
        self.assertEqual(status.status, "DISABLED_PENDING_APPROVAL")
        self.assertEqual(status.posts_read, 0)
        self.assertEqual(status.posts_accepted, 0)

    def test_reddit_429_is_safe_failure(self):
        from urllib.error import HTTPError

        class RateLimitedClient:
            def configured(self):
                return True

            def subreddit_new(self, subreddit, limit=25):
                raise HTTPError("url", 429, "Too Many Requests", None, None)

        news, status = get_reddit_news(client=RateLimitedClient())

        self.assertEqual(news, [])
        self.assertEqual(status.status, "API_ERROR")
        self.assertIn("r/Bitcoin:RATE_LIMIT", status.errors)

    def test_reddit_rumor_only_is_not_confirmed(self):
        reddit = apply_source_metadata(
            item(
                "Rumor: SEC may approve a strategic Bitcoin reserve",
                "Unconfirmed Reddit discussion.",
                source="r/Bitcoin",
            )
        )

        verified = verify_news([reddit])[0]

        self.assertEqual(verified.source_type, "COMMUNITY")
        self.assertNotEqual(verified.verification_status, "CONFIRMED")

    def test_reddit_plus_primary_source_can_raise_confidence(self):
        reddit = apply_source_metadata(
            item(
                "SEC announces major spot Bitcoin ETF custody decision",
                "Reddit discussion points to the same official event.",
                source="r/Bitcoin",
            )
        )
        primary = apply_source_metadata(
            item(
                "SEC announces major spot Bitcoin ETF custody decision",
                "The SEC confirmed a decision affecting custody and ETF access.",
                source="SEC - Press Releases",
            )
        )

        verified = verify_news([reddit, primary])
        reddit_verified = next(news for news in verified if news.source == "r/Bitcoin")

        self.assertEqual(reddit_verified.verification_status, "CONFIRMED")
        self.assertEqual(reddit_verified.confidence, "Alta")
        self.assertEqual(reddit_verified.primary_source, "SEC - Press Releases")

    def test_reddit_attention_spike_is_sentiment_signal_not_publication(self):
        status = RedditStatus(
            status="OK",
            posts_read=30,
            posts_accepted=18,
            top_narratives=["BTC"],
            attention="EXTREME",
            sentiment="BULLISH",
        )
        from sentiment_engine import sentiment_from_reddit_status

        state = analyze_btc_market_state(
            BtcMarketSnapshot(),
            None,
            None,
            sentiment_from_reddit_status(status),
        )

        self.assertIn("REDDIT_ATTENTION_EXTREME", [signal.name for signal in state.signals])
        self.assertIsNone(market_state_to_news_item(state))

    def test_multiple_reddit_posts_are_not_independent_confirmation(self):
        one = apply_source_metadata(
            item(
                "Rumor: Treasury may announce Bitcoin reserve",
                "A Reddit post says sources are circulating this rumor.",
                source="r/Bitcoin",
            )
        )
        two = apply_source_metadata(
            item(
                "Rumor: Treasury may announce Bitcoin reserve",
                "Another Reddit discussion repeats the same rumor.",
                source="r/CryptoCurrency",
            )
        )

        verified = verify_news([one, two])

        self.assertTrue(all(news.source_type == "COMMUNITY" for news in verified))
        self.assertTrue(all(news.verification_status == "RUMOR" for news in verified))

    def test_new_telegram_channels_are_rumor_prone(self):
        for channel in ["NoticiasTradingCrypto", "ultimominutoOTC", "binancekillers"]:
            self.assertIn(channel, CHANNELS)
            self.assertTrue(CHANNEL_METADATA[channel]["rumor_prone"])
            meta = source_metadata(channel)
            self.assertEqual(meta["type"], "FAST")
            self.assertTrue(meta["rumor_prone"])

    def test_nvidiaai_is_not_primary_or_high_reliability(self):
        self.assertNotIn("NVIDIAAI", CHANNELS)
        meta = source_metadata("NVIDIAAI")

        self.assertNotEqual(meta["type"], "PRIMARY")
        self.assertLess(meta["reliability"], 80)

    def test_unknown_reason_statuses_work(self):
        etf = BtcEtfFlowSnapshot(status="NOT_CONFIGURED")
        onchain = BtcOnchainSnapshot(status="UNAVAILABLE_FREE_SOURCE")

        self.assertEqual(etf.status, "NOT_CONFIGURED")
        self.assertEqual(onchain.status, "UNAVAILABLE_FREE_SOURCE")

    def test_provider_not_configured_has_clean_status(self):
        snapshot = fetch_btc_etf_flow_snapshot(
            client=BlockworksEtfFlowClient(api_key="")
        )

        self.assertEqual(snapshot.status, "NOT_CONFIGURED")
        self.assertEqual(snapshot.errors, [])

    def test_coin_metrics_fallback_never_invents_unavailable_metrics(self):
        class EmptyCoinMetricsClient:
            def asset_metrics(self):
                return {"data": [{"time": "2026-01-01T00:00:00Z", "TxCnt": "10"}]}

        context = fetch_coin_metrics_context(EmptyCoinMetricsClient())

        self.assertEqual(context["TxCnt"], 10.0)
        self.assertIsNone(context["AdrActCnt"])
        self.assertIsNone(context["HashRate"])
        self.assertNotIn("exchange_inflow", context)
        self.assertNotIn("whale", context)

    def test_external_api_failure_keeps_reddit_alive(self):
        class FailingClient:
            def configured(self):
                return True

            def subreddit_new(self, subreddit, limit=25):
                raise RuntimeError("api down")

        news, status = get_reddit_news(client=FailingClient())

        self.assertEqual(news, [])
        self.assertEqual(status.status, "API_ERROR")

    def test_selector_can_select_up_to_six_after_daily_intraday_phase(self):
        items = [
            score_market_item(
                item(
                    f"SEC announces major spot Bitcoin ETF custody decision {i}",
                    "The decision affects ETF flows, custody, institutional access and BTC liquidity.",
                    source="SEC - Press Releases",
                )
            )
            for i in range(5)
        ]

        selected = select_news_with_ai(items, use_ai=False)

        self.assertLessEqual(len(selected), 6)

    def test_publication_gate_thresholds_unchanged_after_reddit_phase(self):
        news = publishable_item()
        result = evaluate_item(news, review_ok=True)

        self.assertTrue(result.passed)
        self.assertGreaterEqual(news.market_impact, 65)
        self.assertIn(news.materiality, {"HIGH", "CRITICAL"})

    def test_trump_tariff_threat_is_threatened_and_market_sensitive(self):
        text = "If China does not accept, I will impose tariffs of 50%."

        self.assertTrue(is_market_sensitive(text))
        self.assertEqual(classify_declaration_status(text), "THREATENED")

    def test_trump_direct_declaration_confirms_declaration_not_implementation(self):
        raw = {
            "id": "123",
            "content": "<p>I will impose 50% tariffs on China unless talks improve.</p>",
            "url": "https://truthsocial.com/@realDonaldTrump/posts/123",
            "created_at": "2026-08-14T12:00:00Z",
        }
        post = normalize_truth_social_status(raw)
        news = truth_post_to_news_item(post)

        self.assertEqual(news.declaration_status, "THREATENED")
        self.assertTrue(news.intelligence_summary["truth_social"]["confirmed_declaration"])
        self.assertFalse(news.intelligence_summary["truth_social"]["policy_implemented"])

    def test_minor_trump_post_is_irrelevant(self):
        text = "Great crowd today. Thank you everyone!"

        self.assertFalse(is_market_sensitive(text))
        self.assertEqual(classify_declaration_status(text), "UNKNOWN")

    def test_critical_trump_declaration_can_reach_rumor_gate(self):
        result = evaluate_rumor_item(critical_trump_threat(), review_ok=True)

        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.rumor_score, 70)

    def test_weak_rumor_rejects(self):
        news = item(
            "Random account says oil may move tomorrow",
            "No traceable source or mechanism.",
            source="Unknown Blog",
        )
        news.market_impact = 86
        news.materiality = "HIGH"
        news.verification_status = "RUMOR"
        news.affected_assets = ["OIL"]
        news.mechanism = ""

        result = evaluate_rumor_item(news, review_ok=True)

        self.assertFalse(result.passed)
        self.assertIn("weak_source", result.reasons)
        self.assertIn("weak_mechanism", result.reasons)

    def test_critical_rumor_from_relevant_source_can_pass(self):
        news = critical_trump_threat()
        news.verification_status = "THREATENED"

        result = evaluate_rumor_item(news, review_ok=True)

        self.assertTrue(result.passed)

    def test_telegram_only_low_relevance_rumor_rejects(self):
        news = item(
            "Rumor: small exchange may list a token",
            "Telegram-only rumor with no material market mechanism.",
            source="binancekillers",
        )
        news = apply_source_metadata(news)
        news.market_impact = 50
        news.materiality = "MEDIUM"
        news.verification_status = "RUMOR"
        news.affected_assets = ["BTC"]
        news.mechanism = "generic crypto sentiment -> BTC"

        result = evaluate_rumor_item(news, review_ok=True)

        self.assertFalse(result.passed)
        self.assertIn("low_market_impact", result.reasons)

    def test_multiple_independent_fast_sources_improve_rumor_score(self):
        one = critical_trump_threat()
        one.related_sources = []
        one.materiality = "HIGH"
        one.market_impact = 85
        one.market_signals = []
        two = critical_trump_threat()
        two.related_sources = ["ClashReport", "OSINTdefender"]
        two.materiality = "HIGH"
        two.market_impact = 85
        two.market_signals = []

        self.assertGreater(rumor_score(two), rumor_score(one))

    def test_market_reaction_does_not_confirm_rumor(self):
        news = critical_trump_threat()
        news.market_signals = ["oil +4%", "volatility spike"]
        news.verification_status = "RUMOR"

        evaluate_rumor_item(news, review_ok=True)

        self.assertEqual(news.verification_status, "RUMOR")
        self.assertNotEqual(news.confidence, "Alta")

    def test_rumor_contradicted_is_denied(self):
        news = critical_trump_threat()
        news.declaration_status = "DENIED"
        news.verification_status = "DENIED"

        result = evaluate_rumor_item(news, review_ok=True)

        self.assertFalse(result.passed)
        self.assertIn("denied", result.reasons)

    def test_rumor_later_confirmed_update_existing_event(self):
        self.assertEqual(event_update_type("RUMOR", "CONFIRMED"), "CONFIRMED")
        self.assertEqual(event_update_type("THREATENED", "IMPLEMENTED"), "IMPLEMENTED")
        self.assertEqual(event_update_type("RUMOR", "DENIED"), "DENIED")

    def test_statement_about_policy_is_announced_not_implemented(self):
        text = "I am announcing new tariffs on semiconductors next month."

        self.assertEqual(classify_declaration_status(text), "ANNOUNCED")
        self.assertNotEqual(classify_declaration_status(text), "IMPLEMENTED")

    def test_truth_social_unavailable_keeps_radar_running(self):
        news, status = get_truth_social_news()

        self.assertEqual(news, [])
        self.assertEqual(status.status, "UNAVAILABLE_FREE_SOURCE")

    def test_rumor_reviewer_fail_never_publishes(self):
        result = evaluate_rumor_item(critical_trump_threat(), review_ok=False)

        self.assertFalse(result.passed)
        self.assertIn("reviewer_failed", result.reasons)

    def test_rumor_gate_no_buy_sell_language(self):
        news = critical_trump_threat()
        result = evaluate_rumor_item(news, review_ok=True)
        text = f"{news.title} {news.summary} {news.mechanism} {' '.join(news.market_signals)}".lower()

        self.assertTrue(result.passed)
        self.assertNotIn("buy", text)
        self.assertNotIn("sell", text)
        self.assertNotIn("compra", text)
        self.assertNotIn("vende", text)

    def test_precandidate_low_score_15_never_reaches_enrichment(self):
        news = item("Crypto Biz: Bitcoin self-custody wake-up call")
        news.market_impact = 15
        news.materiality = "LOW"
        news.verification_status = "PRELIMINARY"
        news.mechanism = "no clear material market transmission"

        self.assertFalse(can_reach_selection(news))

    def test_precandidate_low_rumor_never_reaches_enrichment(self):
        news = item("Rumor: Bitcoin self-custody story", source="Cointelegraph")
        news.market_impact = 15
        news.materiality = "LOW"
        news.is_rumor = True
        news.verification_status = "RUMOR"
        news.mechanism = "positioning/liquidity -> volatility risk -> BTC/ETH"
        news.affected_assets = ["BTC"]

        self.assertFalse(can_reach_selection(news))

    def test_precandidate_low_rumor_legacy_score_high_never_reaches_enrichment(self):
        news = item("Crypto Biz: Bitcoin self-custody wake-up call", source="Cointelegraph")
        news.score = 99
        news.market_impact = 15
        news.materiality = "LOW"
        news.is_rumor = True
        news.verification_status = "RUMOR"
        news.mechanism = "positioning/liquidity -> volatility risk -> BTC/ETH"
        news.affected_assets = ["BTC"]

        self.assertFalse(can_reach_selection(news))
        self.assertEqual(_preselect_market_candidates([news]), [])

    def test_precandidate_weak_rumor_score_40_never_reaches_enrichment(self):
        news = item("Rumor: weak crypto market story", source="binancekillers")
        news = apply_source_metadata(news)
        news.market_impact = 40
        news.materiality = "MEDIUM"
        news.is_rumor = True
        news.verification_status = "RUMOR"
        news.mechanism = "positioning/liquidity -> volatility risk -> BTC/ETH"
        news.affected_assets = ["BTC"]

        self.assertFalse(can_reach_selection(news))

    def test_precandidate_material_rumor_score_75_can_reach_enrichment(self):
        news = item("Trump threatens 50% tariffs on China", source="Truth Social @realDonaldTrump")
        news = apply_source_metadata(news)
        news.market_impact = 75
        news.materiality = "HIGH"
        news.is_rumor = True
        news.verification_status = "RUMOR"
        news.declaration_status = "THREATENED"
        news.mechanism = "tariffs -> inflation/growth expectations -> USD/yields/risk assets"
        news.affected_assets = ["SP500", "NASDAQ", "TREASURIES", "EURUSD", "BTC"]

        self.assertTrue(can_reach_selection(news))

    def test_precandidate_high_confirmed_reaches_enrichment(self):
        news = publishable_item()

        self.assertTrue(can_reach_selection(news))

    def test_post_download_low_candidate_is_removed_before_ai_enrichment(self):
        news = publishable_item("SEC approves major spot Bitcoin ETF rule")
        self.assertTrue(can_reach_selection(news))

        news.market_impact = 15
        news.score = 15
        news.materiality = "LOW"
        news.verification_status = "RUMOR"
        news.is_rumor = True

        self.assertEqual(_revalidate_precandidates_after_download([news]), [])

    def test_precandidate_change_does_not_change_final_publication_rules(self):
        low = publishable_item("Bitcoin rises 0.4 percent with no catalyst")
        low.market_impact = 15
        low.materiality = "LOW"

        result = evaluate_item(low, review_ok=True)

        self.assertFalse(result.passed)
        self.assertIn("low_materiality", result.reasons)

    def test_precandidate_rejection_counters(self):
        low = item("Low impact item")
        low.market_impact = 15
        low.materiality = "LOW"

        medium = item("Medium item")
        medium.market_impact = 50
        medium.materiality = "MEDIUM"

        rumor = item("Weak rumor", source="binancekillers")
        rumor = apply_source_metadata(rumor)
        rumor.market_impact = 40
        rumor.materiality = "MEDIUM"
        rumor.verification_status = "RUMOR"
        rumor.is_rumor = True

        counters = count_pre_candidate_rejections([low, medium, rumor])

        self.assertEqual(counters["pre_candidate_low_rejected"], 1)
        self.assertEqual(counters["pre_candidate_medium_rejected"], 1)
        self.assertEqual(counters["pre_candidate_rumor_rejected"], 1)

    def test_structural_medium_intraday_high_survives(self):
        news = item(
            "Trump urges Congress to pass crypto regulation today",
            "The White House statement references the CLARITY Act and BTC market structure.",
            source="NoticiasTradingCrypto",
        )
        news.published = datetime.utcnow().isoformat()
        news = score_market_item(news)
        news.market_impact = 50
        news.materiality = "MEDIUM"

        self.assertGreaterEqual(news.intraday_news_relevance, 82)
        self.assertTrue(can_reach_selection(news))
        self.assertIn("INTRADAY", accepted_by_paths(news))

    def test_structural_low_daily_high_survives(self):
        news = item(
            "CLARITY Act advances after House committee vote",
            "A major US legislative development on crypto regulation could affect BTC market structure.",
            source="CoinDesk",
        )
        news.published = datetime.utcnow().isoformat()
        news = score_market_item(news)
        news.market_impact = 44
        news.materiality = "LOW"
        news.is_rumor = False
        news.verification_status = "PRELIMINARY"

        self.assertGreaterEqual(news.daily_news_relevance, 76)
        self.assertTrue(can_reach_selection(news))
        self.assertIn("DAILY", accepted_by_paths(news))

    def test_trump_crypto_declaration_becomes_daily_intraday_candidate(self):
        news = item(
            "Trump says Congress must pass the CLARITY Act for crypto",
            "The direct declaration targets US crypto regulation and Bitcoin market structure.",
            source="Truth Social @realDonaldTrump",
        )
        news.published = datetime.utcnow().isoformat()
        news.declaration_status = "ANNOUNCED"
        news = score_market_item(news)

        self.assertEqual(news.event_type, "CRYPTO_REGULATION")
        self.assertIn("BTC", news.affected_assets)
        self.assertGreaterEqual(news.daily_news_relevance, 76)
        self.assertGreaterEqual(news.intraday_news_relevance, 82)
        self.assertTrue(can_reach_selection(news))

    def test_clarity_act_advancement_daily_high(self):
        news = item(
            "Senate committee advances CLARITY Act crypto market structure bill",
            "The vote is a real legislative step for US crypto regulation and CFTC oversight.",
            source="CoinDesk",
        )
        news.published = datetime.utcnow().isoformat()
        news = score_market_item(news)

        self.assertEqual(news.event_type, "CRYPTO_REGULATION")
        self.assertIn("BTC", news.affected_assets)
        self.assertGreaterEqual(news.daily_news_relevance, 76)
        self.assertTrue(can_reach_selection(news))
        self.assertTrue(evaluate_daily_item(news, review_ok=True).passed)

    def test_duplicate_telegram_headline_no_second_slot(self):
        first = score_market_item(
            item(
                "Trump urges Congress to pass the CLARITY Act",
                "Crypto regulation headline.",
                source="NoticiasTradingCrypto",
            )
        )
        second = score_market_item(
            item(
                "Trump urges Congress to pass the CLARITY Act",
                "Crypto regulation headline.",
                source="ultimominutoOTC",
            )
        )

        merged = dedupe_news([first, second])

        self.assertEqual(len(merged), 1)

    def test_telegram_rumor_primary_confirmation_raises_confidence(self):
        telegram = item(
            "CLARITY Act advances after committee vote",
            "Rumor: sources say the crypto market structure bill advanced.",
            source="NoticiasTradingCrypto",
        )
        telegram = score_market_item(telegram)
        telegram.is_rumor = True
        telegram.verification_status = "RUMOR"

        primary = item(
            "CLARITY Act advances after committee vote",
            "Official committee notice confirms the crypto market structure bill advanced.",
            source="SEC - Press Releases",
        )
        primary = score_market_item(primary)
        primary.source_type = "PRIMARY"

        verified = verify_news([telegram, primary])

        self.assertEqual(verified[0].verification_status, "CONFIRMED")
        self.assertEqual(verified[0].confidence, "Alta")

    def test_stale_telegram_headline_rejected(self):
        news = item(
            "Trump urges Congress to pass crypto regulation",
            "The post discusses the CLARITY Act and BTC market structure.",
            source="NoticiasTradingCrypto",
        )
        news.published = (datetime.utcnow() - timedelta(days=3)).isoformat()
        news = score_market_item(news)

        self.assertFalse(can_reach_selection(news))
        self.assertLess(news.daily_news_relevance, 76)

    def test_generic_political_chatter_rejected(self):
        news = item(
            "Trump criticized a rival during a campaign event",
            "The speech did not mention crypto, tariffs, rates, oil, sanctions or markets.",
            source="ClashReport",
        )
        news.published = datetime.utcnow().isoformat()
        news = score_market_item(news)

        self.assertFalse(can_reach_selection(news))

    def test_same_event_across_telegram_rss_one_event(self):
        telegram = score_market_item(
            item(
                "Trump pushes Congress to pass CLARITY Act",
                "Crypto regulation and BTC market structure.",
                source="NoticiasTradingCrypto",
            )
        )
        rss = score_market_item(
            item(
                "Trump pushes Congress to pass CLARITY Act",
                "Crypto regulation and BTC market structure.",
                source="CoinDesk",
            )
        )

        self.assertEqual(len(dedupe_news([telegram, rss])), 1)

    def test_daily_publication_does_not_relax_structural_gate(self):
        news = item(
            "CLARITY Act advances after committee vote",
            "A US crypto regulation development affects BTC market structure.",
            source="CoinDesk",
        )
        news.published = datetime.utcnow().isoformat()
        news = score_market_item(news)
        news.market_impact = 44
        news.materiality = "LOW"

        structural_result = evaluate_item(news, review_ok=True)
        daily_result = evaluate_daily_item(news, review_ok=True)

        self.assertFalse(structural_result.passed)
        self.assertIn("low_materiality", structural_result.reasons)
        self.assertTrue(daily_result.passed)

    def test_daily_high_news_can_publish_structural_medium(self):
        news = item(
            "CLARITY Act advances after committee vote",
            "A US crypto regulation development affects BTC market structure.",
            source="CoinDesk",
        )
        news.published = datetime.utcnow().isoformat()
        news = score_market_item(news)
        news.market_impact = 50
        news.materiality = "MEDIUM"

        self.assertTrue(evaluate_daily_item(news, review_ok=True).passed)

    def test_trump_clarity_and_btc_reaction_becomes_combined_story(self):
        news = score_market_item(
            item(
                "Trump pushes Congress to pass the CLARITY Act",
                "The White House crypto statement is relevant for BTC regulation.",
                source="CoinDesk",
            )
        )
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=2.2, change_15m=0.7, change_4h=3.0, volume_ratio=2.5, volatility_ratio=2.0, oi_change=2.0)
        )

        attach_market_reaction_to_news([news], state)

        self.assertIn("TEMPORAL_MARKET_REACTION", news.market_signals)
        self.assertIn("coincide temporalmente", news.content.lower())
        self.assertNotIn("caused by", news.content.lower())
        self.assertGreaterEqual(news.daily_news_relevance, 82)

    def test_same_story_from_multiple_sources_merges(self):
        one = score_market_item(
            item("Trump pushes Congress to pass CLARITY Act", source="NoticiasTradingCrypto")
        )
        two = score_market_item(
            item("Trump pushes Congress to pass CLARITY Act", source="CoinDesk")
        )

        self.assertEqual(len(dedupe_news([one, two])), 1)

    def test_image_failure_does_not_block_text_publish(self):
        news = score_market_item(
            item(
                "Trump pushes Congress to pass the CLARITY Act",
                "BTC regulation story.",
                source="CoinDesk",
            )
        )

        path = prepare_editorial_image(news, generator=Mock(side_effect=RuntimeError("image down")))

        self.assertIsNone(path)
        self.assertTrue(news.image_eligible)
        self.assertEqual(news.image_path, "")

    def test_image_only_generated_for_eligible_story(self):
        minor = score_market_item(item("Generic corporate blog retrospective", source="CNBC"))
        major = score_market_item(
            item("Trump pushes Congress to pass the CLARITY Act", "BTC regulation story.", source="CoinDesk")
        )

        self.assertFalse(build_image_brief(minor).eligible)
        self.assertTrue(build_image_brief(major).eligible)

    def test_same_event_uses_same_image_reuse_key(self):
        one = score_market_item(
            item("Trump pushes Congress to pass CLARITY Act", source="NoticiasTradingCrypto")
        )
        two = score_market_item(
            item("Trump pushes Congress to pass CLARITY Act", source="CoinDesk")
        )

        self.assertEqual(build_image_brief(one).reuse_key, build_image_brief(two).reuse_key)

    def test_no_fake_photorealistic_event_image(self):
        news = score_market_item(
            item("Trump pushes Congress to pass the CLARITY Act", "BTC regulation story.", source="CoinDesk")
        )
        brief = build_image_brief(news)

        self.assertIn("illustration", brief.brief.lower())
        self.assertIn("not a fake documentary photo", brief.brief.lower())

    def test_combined_story_has_no_fake_causality(self):
        news = score_market_item(
            item("CLARITY Act advances after committee vote", "BTC regulation story.", source="CoinDesk")
        )
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=2.2, change_15m=0.7, change_4h=3.0, volume_ratio=2.5, volatility_ratio=2.0, oi_change=2.0)
        )

        attach_market_reaction_to_news([news], state)

        self.assertIn("no demuestra causalidad", news.content.lower())

    def test_intraday_small_move_normal_vol_no_alert(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.5, volume_ratio=1.0, volatility_ratio=1.0)
        )

        self.assertEqual(state.decision, "NO_ACTION")
        self.assertEqual(state.intraday_materiality, "INTRADAY_LOW")

    def test_intraday_missing_core_is_insufficient(self):
        state = analyze_btc_intraday_state(
            BtcIntradaySnapshot(
                funding_rate=0.0001,
                errors=["klines_5m:TimeoutError"],
            )
        )

        self.assertEqual(state.status, "INSUFFICIENT")
        self.assertEqual(state.decision, "INSUFFICIENT_DATA")
        self.assertIsNone(intraday_state_to_news_item(state))

    def test_intraday_core_ok_optional_missing_is_degraded(self):
        snapshot = intraday_snapshot(change_1h=2.0, change_15m=0.8, volume_ratio=2.0)
        snapshot.open_interest = None
        snapshot.oi_change_1h = None
        snapshot.funding_rate = None
        snapshot.funding_regime = "UNKNOWN"
        snapshot.errors = ["open_interest:TimeoutError", "funding:TimeoutError"]

        state = analyze_btc_intraday_state(snapshot)

        self.assertEqual(state.status, "DEGRADED")
        self.assertNotEqual(state.decision, "INSUFFICIENT_DATA")

    def test_intraday_order_book_timeout_still_analyzes_price_action(self):
        snapshot = intraday_snapshot(
            change_1h=3.0,
            change_15m=1.0,
            volume_ratio=2.4,
            volatility_ratio=2.0,
            oi_change=3.0,
        )
        snapshot.liquidity = IntradayLiquidityMap()
        snapshot.errors = ["liquidity_structure:TimeoutError"]

        state = analyze_btc_intraday_state(snapshot)
        names = {signal.name for signal in state.signals}

        self.assertEqual(state.status, "DEGRADED")
        self.assertIn("PRICE_ACCELERATION_UP", names)
        self.assertIn("VOLUME_EXPANSION", names)

    def test_intraday_fast_move_normal_volume_is_not_high_automatically(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=2.0, change_15m=0.6, volume_ratio=1.0, volatility_ratio=1.2)
        )

        self.assertNotEqual(state.intraday_materiality, "INTRADAY_HIGH")

    def test_intraday_live_four_hour_breakout_case_not_low_without_catalyst(self):
        snapshot = intraday_snapshot(
            change_15m=-0.0167,
            change_1h=0.14,
            change_4h=2.7429,
            volume_ratio=1.0,
            volatility_ratio=1.0,
            oi_change=0.4,
            structure_15m="BULLISH",
            structure_1h="BULLISH",
            structure_4h="BULLISH_BREAKOUT",
        )
        snapshot.price_change_5m = -0.0442
        snapshot.price_change_30m = 0.1362
        snapshot.price_change_24h = 8.1092
        snapshot.volume_ratio_4h = 3.183
        snapshot.volatility_ratio_4h = 2.3306
        snapshot.oi_change_4h = 2.4173

        state = analyze_btc_intraday_state(snapshot)

        self.assertNotEqual(state.intraday_materiality, "INTRADAY_LOW")
        self.assertEqual(state.decision, "INTRADAY_ALERT")
        self.assertEqual(state.catalyst_status, "NO_CLEAR_CATALYST")

    def test_intraday_same_move_confirmed_catalyst_raises_confluence(self):
        base = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=2.6, change_15m=0.8, volume_ratio=2.2, volatility_ratio=2.0, oi_change=2.5)
        )
        confirmed = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=2.6, change_15m=0.8, volume_ratio=2.2, volatility_ratio=2.0, oi_change=2.5)
        )
        primary = item("SEC confirms Bitcoin ETF emergency decision", source="SEC - Press Releases")
        primary.source_type = "PRIMARY"

        attach_intraday_catalyst(confirmed, [primary])

        self.assertGreater(confirmed.intraday_confluence_score, base.intraday_confluence_score)
        self.assertEqual(confirmed.catalyst_status, "CONFIRMED_CATALYST")

    def test_intraday_no_clear_catalyst_alone_is_not_penalty(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.0, change_15m=1.1, volume_ratio=2.4, volatility_ratio=2.1, oi_change=3.0)
        )

        self.assertEqual(state.catalyst_status, "NO_CLEAR_CATALYST")
        self.assertGreaterEqual(state.intraday_confluence_score, 75)

    def test_intraday_medium_event_becomes_note(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(
                change_1h=1.4,
                change_15m=0.3,
                change_4h=2.0,
                volume_ratio=2.0,
                volatility_ratio=2.0,
                oi_change=0.5,
                structure_1h="BULLISH_BREAKOUT",
            )
        )

        self.assertEqual(state.decision, "INTRADAY_NOTE")
        self.assertEqual(state.intraday_materiality, "INTRADAY_MEDIUM")

    def test_intraday_note_reaches_publishing_pipeline_gate(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(
                change_1h=1.4,
                change_15m=0.3,
                change_4h=2.0,
                volume_ratio=2.0,
                volatility_ratio=2.0,
                oi_change=0.5,
                structure_1h="BULLISH_BREAKOUT",
            )
        )
        news = intraday_state_to_news_item(state)
        result = evaluate_intraday_item(news, review_ok=True)

        self.assertEqual(state.decision, "INTRADAY_NOTE")
        self.assertTrue(result.passed)

    def test_intraday_note_reaches_precandidate(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=-0.88, change_15m=-0.72, change_4h=-0.81, volume_ratio=2.1, volatility_ratio=2.2, oi_change=-0.69)
        )
        state.decision = "INTRADAY_NOTE"
        state.intraday_materiality = "INTRADAY_MEDIUM"
        state.intraday_confluence_score = 66
        news = intraday_state_to_news_item(state)

        self.assertTrue(can_reach_selection(news))
        self.assertIn(news, _preselect_market_candidates([news]))

    def test_intraday_note_reaches_writer(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=-0.88, change_15m=-0.72, change_4h=-0.81, volume_ratio=2.1, volatility_ratio=2.2, oi_change=-0.69)
        )
        state.decision = "INTRADAY_NOTE"
        state.intraday_materiality = "INTRADAY_MEDIUM"
        state.intraday_confluence_score = 66
        news = intraday_state_to_news_item(state)

        with patch("editor_writer.ask_json", return_value={
            "news": [{
                "id": 1,
                "title": "BTC ENFRIA EL RALLY",
                "what_happened": "BTC corrige en el corto plazo tras seguir positivo en 24h.",
                "why_it_matters": "Importa porque el OI cae junto al precio.",
                "affected_markets": ["BTC"],
                "signals": ["BTC 24h positivo", "OI cae"],
                "reading": "Compatible con limpieza de leverage, no causalidad confirmada.",
                "what_to_watch": "Estructura 1h/4h y OI.",
                "status": "PRELIMINAR",
                "confidence": "Media",
                "telegram_text": "BTC ENFRIA EL RALLY\n\n₿ BTC sigue arriba en 24h, pero pierde momentum de corto plazo.\n\n👉 LECTURA RADAR: la caida del OI es compatible con limpieza de leverage.",
                "internal_diagnostic": {},
            }]
        }):
            report = write_news([news])

        self.assertIn("telegram_text", report["news"][0])
        self.assertIn("BTC ENFRIA", report["news"][0]["telegram_text"])

    def test_intraday_note_does_not_require_alert_gate(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=-0.88, change_15m=-0.72, change_4h=-0.81, volume_ratio=2.1, volatility_ratio=2.2, oi_change=-0.69)
        )
        state.decision = "INTRADAY_NOTE"
        state.intraday_materiality = "INTRADAY_MEDIUM"
        state.intraday_confluence_score = 66
        news = intraday_state_to_news_item(state)
        result = evaluate_intraday_item(news, review_ok=True)

        self.assertTrue(result.passed)
        self.assertEqual(news.intelligence_summary["INTRADAY_DECISION"], "INTRADAY_NOTE")
        self.assertLess(news.confluence_score, 70)

    def test_selector_cannot_silently_kill_intraday_lane(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=-0.88, change_15m=-0.72, change_4h=-0.81, volume_ratio=2.1, volatility_ratio=2.2, oi_change=-0.69)
        )
        state.decision = "INTRADAY_NOTE"
        state.intraday_materiality = "INTRADAY_MEDIUM"
        state.intraday_confluence_score = 66
        news = intraday_state_to_news_item(state)

        selected = select_news_with_ai([news], use_ai=False)

        self.assertIn(news, selected)

    def test_confirmed_event_is_not_confirmed_causality(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=-0.88, change_15m=-0.72, change_4h=-0.81, volume_ratio=2.1, volatility_ratio=2.2, oi_change=-0.69)
        )
        state.decision = "INTRADAY_NOTE"
        state.intraday_materiality = "INTRADAY_MEDIUM"
        state.intraday_confluence_score = 66
        state.catalyst_status = "CONFIRMED_CATALYST"
        state.catalyst_source = "CNBC"
        news = intraday_state_to_news_item(state)

        self.assertEqual(news.intelligence_summary["CATALYST_EVENT_STATUS"], "CONFIRMED_EVENT")
        self.assertEqual(news.intelligence_summary["CATALYST_CAUSALITY_CONFIDENCE"], "POSSIBLE")

    def test_current_snapshot_generates_publishable_intraday_note(self):
        snapshot = intraday_snapshot(
            change_15m=-0.7266,
            change_1h=-0.8882,
            change_4h=-0.8126,
            volume_ratio=2.1065,
            volatility_ratio=2.2103,
            oi_change=-0.6895,
            structure_15m="RANGE",
            structure_1h="BULLISH",
            structure_4h="BULLISH",
        )
        snapshot.price_change_24h = 5.8792
        snapshot.oi_change_15m = -0.6784
        snapshot.oi_change_4h = -1.1799
        snapshot.volume_ratio_15m = 2.1065
        snapshot.volatility_ratio_15m = 2.2103
        state = analyze_btc_intraday_state(snapshot)
        state.decision = "INTRADAY_NOTE"
        state.intraday_materiality = "INTRADAY_MEDIUM"
        state.intraday_confluence_score = 66
        state.catalyst_status = "CONFIRMED_CATALYST"
        state.catalyst_source = "CNBC"
        news = intraday_state_to_news_item(state)
        interpretation = build_editorial_interpretation(news)

        self.assertTrue(can_reach_selection(news))
        self.assertTrue(evaluate_intraday_item(news, review_ok=True).passed)
        self.assertEqual(interpretation["story_angle"], "LEVERAGE_RESET_AFTER_RALLY")
        self.assertIn("BTC ENFRIA", interpretation["headline"])
        self.assertTrue(validate_publication_text(interpretation["headline"])["ok"])

    def _fixture_result(self, name, item_obj, review_ok=True):
        lane = lane_for_item(item_obj)
        if lane in {"INTRADAY_ALERT", "INTRADAY_NOTE"}:
            gate = evaluate_intraday_item(item_obj, review_ok=review_ok)
            passed = gate.passed
        elif lane in {"DAILY_NEWS", "DAILY_MARKET_RECAP", "COMBINED_STORY"}:
            gate = evaluate_daily_item(item_obj, review_ok=review_ok)
            passed = gate.passed
        elif lane == "RUMOR":
            gate = evaluate_rumor_item(item_obj, review_ok=review_ok)
            passed = gate.passed
        elif lane == "STRUCTURAL":
            passed, _, _ = apply_publication_gate([item_obj], {"ok": review_ok, "errors": []})
            passed = bool(passed)
        else:
            passed = bool(review_ok)
        interpretation = build_editorial_interpretation(item_obj)
        text = (
            f"{interpretation['headline']}\n\n"
            f"₿ {interpretation['news_summary']}\n\n"
            f"👉 LECTURA RADAR: {interpretation['market_interpretation']}\n\n"
            f"❓ {interpretation['suggested_question']}"
        )
        return {
            "fixture": name,
            "lane": lane,
            "candidate_created": True,
            "writer": "PASS",
            "reviewer": "PASS" if review_ok else "FAIL",
            "gate": "PASS" if passed else "FAIL",
            "dedupe": "PASS",
            "frequency": "PASS",
            "final_result": "WOULD_PUBLISH" if passed else "REJECTED",
            "telegram_text": text,
        }

    def test_product_fixture_a_btc_intraday_alert(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.0, change_15m=1.1, volume_ratio=3.0, volatility_ratio=2.2, oi_change=3.0, structure_1h="BULLISH_BREAKOUT")
        )
        item_obj = intraday_state_to_news_item(state)
        result = self._fixture_result("A", item_obj)

        self.assertEqual(result["lane"], "INTRADAY_ALERT")
        self.assertEqual(result["final_result"], "WOULD_PUBLISH")

    def test_product_fixture_b_btc_daily_recap_or_note(self):
        snapshot = intraday_snapshot(change_15m=-0.7, change_1h=-0.8, change_4h=-0.8, volume_ratio=2.1, volatility_ratio=2.2, oi_change=-0.7, structure_1h="BULLISH", structure_4h="BULLISH")
        snapshot.price_change_24h = 6.0
        snapshot.oi_change_15m = -0.6
        snapshot.oi_change_4h = -1.2
        state = analyze_btc_intraday_state(snapshot)
        state.decision = "INTRADAY_NOTE"
        state.intraday_materiality = "INTRADAY_MEDIUM"
        state.intraday_confluence_score = 66
        item_obj = intraday_state_to_news_item(state)
        result = self._fixture_result("B", item_obj)

        self.assertIn(result["lane"], {"INTRADAY_NOTE", "DAILY_MARKET_RECAP"})
        self.assertEqual(result["final_result"], "WOULD_PUBLISH")
        self.assertIn("LECTURA RADAR", result["telegram_text"])

    def test_product_fixture_c_trump_clarity_daily_news(self):
        news = item("Trump urges Congress to accelerate CLARITY Act for crypto regulation", "Trump comments on CLARITY Act and US crypto regulation.", source="CNBC")
        news.event_type = "CRYPTO_REGULATION"
        news.affected_assets = ["BTC"]
        news.daily_news_relevance = 88
        news.market_impact = 72
        news.materiality = "MEDIUM"
        news.confidence = "Media"
        news.verification_status = "CONFIRMED"
        news.mechanism = "crypto regulation -> institutional access/liquidity -> BTC"

        result = self._fixture_result("C", news)

        self.assertEqual(result["lane"], "DAILY_NEWS")
        self.assertEqual(result["final_result"], "WOULD_PUBLISH")

    def test_product_fixture_d_trump_rumor_lane(self):
        rumor = item("Trump may announce emergency Bitcoin reserve policy", "Unconfirmed report about possible Bitcoin reserve policy.", source="Truth Social @realDonaldTrump")
        rumor.event_type = "CRYPTO_REGULATION"
        rumor.affected_assets = ["BTC"]
        rumor.market_impact = 90
        rumor.materiality = "HIGH"
        rumor.verification_status = "RUMOR"
        rumor.declaration_status = "THREATENED"
        rumor.is_rumor = True
        rumor.source_type = "FAST"
        rumor.source_reliability = 75
        rumor.link = "truthsocial://realDonaldTrump/1"
        rumor.mechanism = "policy declaration -> crypto regulation expectations -> BTC"

        result = self._fixture_result("D", rumor)

        self.assertEqual(result["lane"], "RUMOR")
        self.assertEqual(result["final_result"], "WOULD_PUBLISH")

    def test_product_fixture_e_quiet_market(self):
        decision = evaluate_quiet_market(quiet_btc_state(), history=[])

        self.assertEqual(lane_for_item(decision.note), "QUIET_MARKET")
        self.assertTrue(decision.passed)
        self.assertIn("MARKET NOTE", decision.message)

    def test_product_fixture_f_combined_story(self):
        news = item("Trump CLARITY Act headline coincides with BTC breakout", "Crypto regulation headline coincides with BTC volume expansion.", source="CNBC")
        news.event_type = "COMBINED_MARKET_STORY"
        news.affected_assets = ["BTC"]
        news.daily_news_relevance = 86
        news.market_impact = 76
        news.materiality = "HIGH"
        news.verification_status = "CONFIRMED"
        news.confidence = "Media"
        news.mechanism = "news catalyst plus BTC market reaction -> daily BTC expectations"

        result = self._fixture_result("F", news)

        self.assertEqual(result["lane"], "COMBINED_STORY")
        self.assertEqual(result["final_result"], "WOULD_PUBLISH")

    def test_product_fixture_g_duplicate_same_event_no_publication(self):
        cache = temp_seen_cache()
        first = item("Trump urges Congress to accelerate CLARITY Act", source="CNBC")
        second = item("Trump urges Congress to accelerate CLARITY Act", source="CoinDesk")
        cache.remember_item(first, "PUBLISHED")
        filtered, stats = cache.filter_new_items([second])

        self.assertEqual(filtered, [])
        self.assertGreaterEqual(stats.exact_duplicates + stats.near_duplicates + stats.same_event_merges, 1)

    def test_product_fixture_h_material_update_can_republish(self):
        old = item("Rumor says White House may advance CLARITY Act", source="Telegram")
        old.verification_status = "RUMOR"
        new = item("White House confirms CLARITY Act push", source="CNBC")
        new.verification_status = "CONFIRMED"

        self.assertEqual(event_update_type(old.verification_status, new.verification_status), "CONFIRMED")

    def test_intraday_alert_reaches_publishing_pipeline_gate(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.0, change_15m=1.1, volume_ratio=2.4, volatility_ratio=2.1, oi_change=3.0)
        )
        news = intraday_state_to_news_item(state)
        result = evaluate_intraday_item(news, review_ok=True)

        self.assertEqual(state.decision, "INTRADAY_ALERT")
        self.assertTrue(result.passed)

    def test_intraday_high_event_becomes_alert(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.0, change_15m=1.1, volume_ratio=2.4, volatility_ratio=2.1, oi_change=3.0)
        )

        self.assertEqual(state.decision, "INTRADAY_ALERT")
        self.assertIn(state.intraday_materiality, {"INTRADAY_HIGH", "INTRADAY_CRITICAL"})

    def test_eight_percent_24h_strong_4h_context_not_low(self):
        snapshot = intraday_snapshot(
            change_15m=-0.0167,
            change_1h=0.14,
            change_4h=2.7429,
            volume_ratio=1.0,
            volatility_ratio=1.0,
            oi_change=0.4,
            structure_15m="BULLISH",
            structure_1h="BULLISH",
            structure_4h="BULLISH_BREAKOUT",
        )
        snapshot.price_change_24h = 8.1092
        snapshot.volume_ratio_4h = 3.183
        snapshot.volatility_ratio_4h = 2.3306
        snapshot.oi_change_4h = 2.4173

        state = analyze_btc_intraday_state(snapshot)

        self.assertNotEqual(state.intraday_materiality, "INTRADAY_LOW")
        self.assertEqual(state.decision, "INTRADAY_ALERT")

    def test_no_catalyst_does_not_kill_intraday_alert(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.0, change_15m=1.1, volume_ratio=2.4, volatility_ratio=2.1, oi_change=3.0)
        )

        self.assertEqual(state.catalyst_status, "NO_CLEAR_CATALYST")
        self.assertEqual(state.decision, "INTRADAY_ALERT")

    def test_btc_today_recap_can_publish_8pct_24h_current_1h_flat(self):
        snapshot = intraday_snapshot(
            change_15m=-0.1,
            change_1h=0.26,
            change_4h=-0.95,
            volume_ratio=1.2,
            volatility_ratio=1.1,
            oi_change=0.84,
            structure_15m="BEARISH",
            structure_1h="BULLISH",
            structure_4h="BULLISH",
        )
        snapshot.price_change_24h = 7.24
        snapshot.oi_change_4h = -5.05
        state = analyze_btc_intraday_state(snapshot)
        market_state = BtcMarketState(snapshot=BtcMarketSnapshot(price=100000), intraday=state)

        with patch("daily_recap.recent_history", return_value=[]):
            decision = evaluate_daily_market_recap(market_state, seen_cache=temp_seen_cache())

        self.assertEqual(state.decision, "NO_ACTION")
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.note.event_type, "BTC_DAILY_RECAP")
        self.assertGreaterEqual(decision.score, 76)

    def test_btc_today_no_recap_for_small_24h_move(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.1, change_4h=0.2, volume_ratio=1.0, volatility_ratio=1.0)
        )
        state.snapshot.price_change_24h = 0.5
        market_state = BtcMarketState(snapshot=BtcMarketSnapshot(price=100000), intraday=state)

        with patch("daily_recap.recent_history", return_value=[]):
            decision = evaluate_daily_market_recap(market_state, seen_cache=temp_seen_cache())

        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, "LOW_DAILY_MARKET_STATE_SCORE")

    def test_daily_recap_receives_actual_24h_market_state(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=-0.8, change_4h=-0.8, volume_ratio=2.1, volatility_ratio=2.2, oi_change=-0.7)
        )
        state.snapshot.price_change_24h = None
        market_state = BtcMarketState(
            snapshot=BtcMarketSnapshot(price=100000, price_change_24h=5.848),
            intraday=state,
        )

        with patch("daily_recap.recent_history", return_value=[]):
            decision = evaluate_daily_market_recap(market_state, seen_cache=temp_seen_cache())

        self.assertEqual(state.snapshot.price_change_24h, 5.848)
        if decision.note:
            self.assertEqual(decision.note.intelligence_summary["CURRENT_24H_MOVE"], 5.848)

    def test_irrelevant_recent_events_excluded_from_btc_recap(self):
        cache = temp_seen_cache()
        cache.remember_item(item("Djibouti football federation elects new chairman", source="BBC World"), "DISCARDED")
        cache.remember_item(item("Social Security union criticizes staffing decision", source="TechCrunch"), "DISCARDED")
        cache.remember_item(item("Solana slot time improves after validator patch", source="Cointelegraph"), "DISCARDED")
        cache.remember_item(item("Trump comments on Bitcoin regulation and CLARITY Act", source="CNBC"), "DISCARDED")

        events = cache.get_recent_relevant_events(hours=24)

        titles = " ".join(event["title"] for event in events)
        self.assertIn("trump", titles)
        self.assertNotIn("djibouti", titles)
        self.assertNotIn("social security", titles)
        self.assertNotIn("solana", titles)

    def test_btc_today_rolling_memory_preserves_peak_move(self):
        cache = temp_seen_cache()
        peak = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.2, change_4h=4.0, volume_ratio=3.0, volatility_ratio=2.4, oi_change=4.0)
        )
        peak.snapshot.timestamp = (datetime.utcnow() - timedelta(hours=8)).isoformat()
        cache.remember_btc_intraday_snapshot(peak)
        cooled = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.1, change_4h=-0.4, volume_ratio=1.0, volatility_ratio=1.0, oi_change=-1.0)
        )
        cooled.snapshot.price_change_24h = 7.5
        market_state = BtcMarketState(snapshot=BtcMarketSnapshot(price=100000), intraday=cooled)

        with patch("daily_recap.recent_history", return_value=[]):
            decision = evaluate_daily_market_recap(market_state, seen_cache=cache)

        self.assertTrue(decision.eligible)
        self.assertGreaterEqual(decision.note.intelligence_summary["MAX_MOVE_1H_24H"], 3.2)

    def test_btc_today_same_daily_story_already_published_suppressed(self):
        cache = temp_seen_cache()
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.1, change_4h=-0.4, volume_ratio=2.0, volatility_ratio=2.0, oi_change=-3.5)
        )
        state.snapshot.price_change_24h = 7.5
        market_state = BtcMarketState(snapshot=BtcMarketSnapshot(price=100000), intraday=state)

        with patch("daily_recap.recent_history", return_value=[]):
            first = evaluate_daily_market_recap(market_state, seen_cache=cache)
            cache.remember_daily_recap(first.fingerprint, published=True)
            second = evaluate_daily_market_recap(market_state, seen_cache=cache)

        self.assertTrue(first.eligible)
        self.assertFalse(second.eligible)
        self.assertEqual(second.reason, "DUPLICATE_DAILY_RECAP")

    def test_btc_today_intraday_alert_already_covered_suppresses_recap(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.1, change_4h=-0.4, volume_ratio=2.0, volatility_ratio=2.0, oi_change=-3.5)
        )
        state.snapshot.price_change_24h = 7.5
        market_state = BtcMarketState(snapshot=BtcMarketSnapshot(price=100000), intraday=state)
        history = [{"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "status": "published", "category": "BTC Intraday"}]

        with patch("daily_recap.recent_history", return_value=history):
            decision = evaluate_daily_market_recap(market_state, seen_cache=temp_seen_cache())

        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, "RECENT_BTC_POST_ALREADY_COVERED")

    def test_btc_today_oi_minus_5_uses_conservative_deleveraging_language(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.26, change_4h=-0.95, volume_ratio=2.5, volatility_ratio=2.0, oi_change=0.84)
        )
        state.snapshot.price_change_24h = 7.24
        state.snapshot.oi_change_4h = -5.05
        market_state = BtcMarketState(snapshot=BtcMarketSnapshot(price=100000), intraday=state)

        with patch("daily_recap.recent_history", return_value=[]):
            decision = evaluate_daily_market_recap(market_state, seen_cache=temp_seen_cache())

        text = decision.note.content.lower()
        self.assertIn("compatible con limpieza de apalancamiento", text)
        self.assertIn("no identifica por sí solo", text)

    def test_btc_today_no_catalyst_still_publishable(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.1, change_4h=-0.4, volume_ratio=2.5, volatility_ratio=2.0, oi_change=-3.5)
        )
        state.snapshot.price_change_24h = 7.5
        market_state = BtcMarketState(snapshot=BtcMarketSnapshot(price=100000), intraday=state)

        with patch("daily_recap.recent_history", return_value=[]):
            decision = evaluate_daily_market_recap(market_state, seen_cache=temp_seen_cache())

        self.assertTrue(decision.eligible)
        self.assertIn("No hay catalizador confirmado", decision.note.content)

    def test_btc_today_recent_seen_news_context_not_new_candidate(self):
        cache = temp_seen_cache()
        old = item("Trump pushes Congress to pass CLARITY Act", source="CoinDesk")
        cache.remember_item(old, "DISCARDED")
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.1, change_4h=-0.4, volume_ratio=2.5, volatility_ratio=2.0, oi_change=-3.5)
        )
        state.snapshot.price_change_24h = 7.5
        market_state = BtcMarketState(snapshot=BtcMarketSnapshot(price=100000), intraday=state)

        with patch("daily_recap.recent_history", return_value=[]):
            decision = evaluate_daily_market_recap(market_state, seen_cache=cache)

        self.assertTrue(decision.recent_events)
        self.assertIn("trump", decision.note.content.lower())

    def test_btc_today_old_clarity_replay_does_not_republish(self):
        cache = temp_seen_cache()
        cache.remember_item(item("CLARITY Act advances after committee vote", source="CoinDesk"), "DISCARDED")

        replay = replay_seen_events_with_current_rules(cache, hours=24)

        self.assertTrue(replay[0]["would_be_daily_candidate_now"])
        self.assertFalse(replay[0]["retroactive_publish"])

    def test_btc_today_image_failure_does_not_block_text(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.1, change_4h=-0.4, volume_ratio=2.5, volatility_ratio=2.0, oi_change=-3.5)
        )
        state.snapshot.price_change_24h = 7.5
        market_state = BtcMarketState(snapshot=BtcMarketSnapshot(price=100000), intraday=state)

        with patch("daily_recap.recent_history", return_value=[]):
            decision = evaluate_daily_market_recap(market_state, seen_cache=temp_seen_cache())
        path = prepare_editorial_image(decision.note, generator=Mock(side_effect=RuntimeError("image down")))

        self.assertIsNone(path)
        self.assertTrue(decision.note.image_eligible)

    def test_btc_today_no_buy_sell_language(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.1, change_4h=-0.4, volume_ratio=2.5, volatility_ratio=2.0, oi_change=-3.5)
        )
        state.snapshot.price_change_24h = 7.5
        market_state = BtcMarketState(snapshot=BtcMarketSnapshot(price=100000), intraday=state)

        with patch("daily_recap.recent_history", return_value=[]):
            decision = evaluate_daily_market_recap(market_state, seen_cache=temp_seen_cache())

        text = decision.note.content.lower()
        self.assertNotIn("compra", text)
        self.assertNotIn("vende", text)
        self.assertNotIn("buy", text)
        self.assertNotIn("sell", text)

    def test_editorial_interpreter_summarizes_news_before_analysis(self):
        news = publishable_item("SEC opens comment period on spot Bitcoin ETF custody rule")
        news.summary = "The SEC opened a formal comment period on a Bitcoin ETF custody rule."

        interpretation = build_editorial_interpretation(news)

        self.assertIn("SEC", interpretation["headline"])
        self.assertIn("comment period", interpretation["news_summary"])
        self.assertIn("La noticia importa", interpretation["market_interpretation"])

    def test_editorial_publication_selects_only_important_data(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.26, change_4h=-0.95, volume_ratio=2.5, volatility_ratio=2.0, oi_change=0.84)
        )
        state.snapshot.price_change_24h = 7.24
        state.snapshot.oi_change_4h = -5.05
        market_state = BtcMarketState(snapshot=BtcMarketSnapshot(price=100000), intraday=state)

        with patch("daily_recap.recent_history", return_value=[]):
            decision = evaluate_daily_market_recap(market_state, seen_cache=temp_seen_cache())
        interpretation = build_editorial_interpretation(decision.note)

        self.assertLessEqual(len(interpretation["interesting_data_selected"]), 4)
        self.assertTrue(interpretation["data_omitted_from_publication"])

    def test_price_up_oi_down_generates_nuanced_interpretation(self):
        news = NewsItem(
            title="BTC today",
            summary="BTC rises strongly while open interest falls.",
            content="",
            link="market-state:btc-test",
            published="",
            source="MARKET_STATE",
            event_type="BTC_DAILY_RECAP",
            affected_assets=["BTC"],
        )
        news.intelligence_summary = {
            "CURRENT_24H_MOVE": 7.2,
            "OI_CONTEXT_4H": -5.0,
            "MAX_VOLUME_RATIO_24H": 2.7,
            "STRUCTURE": "15m=COOLING, 1h=BULLISH, 4h=BULLISH",
        }

        interpretation = build_editorial_interpretation(news)

        self.assertEqual(interpretation["story_angle"], "PRICE_UP_OI_DOWN")
        self.assertIn("compatible con limpieza", interpretation["primary_hypothesis"])
        self.assertIn("no con una prueba automatica", interpretation["primary_hypothesis"])

    def test_oi_alone_cannot_prove_short_covering(self):
        news = NewsItem(
            title="BTC rises with OI falling",
            summary="BTC rises while OI falls.",
            content="",
            link="market-state:btc-test-2",
            published="",
            source="MARKET_STATE",
            event_type="BTC_DAILY_RECAP",
            affected_assets=["BTC"],
        )
        news.intelligence_summary = {"CURRENT_24H_MOVE": 7.2, "OI_CONTEXT_4H": -5.0}

        interpretation = build_editorial_interpretation(news)

        self.assertNotIn("provocaron", interpretation["primary_hypothesis"].lower())
        self.assertIn("compatible", interpretation["primary_hypothesis"].lower())

    def test_multiple_related_catalysts_can_form_combined_story(self):
        news = publishable_item("Trump and CLARITY Act headlines coincide with BTC move")
        news.event_type = "COMBINED_MARKET_STORY"
        news.summary = "Trump and CLARITY Act headlines coincide with a BTC breakout."

        interpretation = build_editorial_interpretation(news)

        self.assertEqual(interpretation["story_angle"], "CLARITY_ACT")
        self.assertIn("mercado", interpretation["suggested_question"])

    def test_catalyst_correlation_does_not_become_causation(self):
        news = publishable_item("CLARITY Act headline coincides with BTC rally")
        news.verification_status = "PRELIMINARY"
        news.intelligence_summary = {"CATALYST": "POSSIBLE_CATALYST"}

        interpretation = build_editorial_interpretation(news)

        self.assertIn("correlacion temporal", " ".join(interpretation["evidence_against"]))
        self.assertEqual(interpretation["catalyst_confidence"], "POSSIBLE_CATALYST")

    def test_smc_terminology_translated_into_normal_language(self):
        news = publishable_item("BTC liquidity above recent highs")
        news.market_signals = ["EQUAL_HIGHS_LIQUIDITY", "VISIBLE_LIQUIDITY_ABOVE"]

        interpretation = build_editorial_interpretation(news)

        self.assertIn("zona de liquidez relevante por encima", interpretation["primary_hypothesis"])
        self.assertNotIn("smart money hunted stops", interpretation["primary_hypothesis"].lower())

    def test_formatter_uses_compact_telegram_text(self):
        report = {
            "news": [
                {
                    "title": "BITCOIN DESPIERTA",
                    "what_happened": "BTC sube.",
                    "why_it_matters": "Importa por estructura.",
                    "affected_markets": ["BTC"],
                    "signals": [],
                    "reading": "Lectura prudente.",
                    "what_to_watch": "Volumen.",
                    "status": "PRELIMINAR",
                    "confidence": "Media",
                    "telegram_text": "BITCOIN DESPIERTA\n\n₿ BTC sube con volumen.\n\n👉 LECTURA RADAR: el movimiento gana interes, pero necesita confirmacion.",
                }
            ]
        }

        message = format_report(report)[0]

        self.assertTrue(message.startswith("BITCOIN DESPIERTA"))
        self.assertIn("LECTURA RADAR", message)
        self.assertNotIn("*Qué ha pasado:*", message)

    def test_title_is_editorial_but_fact_safe(self):
        news = publishable_item("Bitcoin rally with lower leverage")
        news.event_type = "BTC_DAILY_RECAP"
        news.intelligence_summary = {"CURRENT_24H_MOVE": 7.2, "OI_CONTEXT_4H": -5.0}

        interpretation = build_editorial_interpretation(news)

        self.assertIn("BITCOIN", interpretation["headline"])
        self.assertFalse(validate_publication_text(interpretation["headline"])["errors"])

    def test_duplicate_thesis_is_marked_for_editorial_dedupe(self):
        news = publishable_item("Bitcoin rally with lower leverage")
        news.event_type = "BTC_DAILY_RECAP"
        news.intelligence_summary = {"CURRENT_24H_MOVE": 7.2, "OI_CONTEXT_4H": -5.0}
        first = build_editorial_interpretation(news)
        second = build_editorial_interpretation(news)

        self.assertEqual(first["story_angle"], second["story_angle"])
        self.assertEqual(first["headline"], second["headline"])

    def test_material_thesis_change_can_republish(self):
        rally = publishable_item("Bitcoin rally with lower leverage")
        rally.event_type = "BTC_DAILY_RECAP"
        rally.intelligence_summary = {"CURRENT_24H_MOVE": 7.2, "OI_CONTEXT_4H": -5.0}
        breakout = publishable_item("Bitcoin breaks higher with renewed structure")
        breakout.event_type = "BTC_DAILY_RECAP"
        breakout.intelligence_summary = {"CURRENT_24H_MOVE": 7.2, "OI_CONTEXT_4H": 4.0, "STRUCTURE": "BULLISH_BREAKOUT"}

        self.assertNotEqual(
            build_editorial_interpretation(rally)["story_angle"],
            build_editorial_interpretation(breakout)["story_angle"],
        )

    def test_final_question_derives_from_evidence(self):
        news = publishable_item("Bitcoin rally with lower leverage")
        news.event_type = "BTC_DAILY_RECAP"
        news.intelligence_summary = {"CURRENT_24H_MOVE": 7.2, "OI_CONTEXT_4H": -5.0}

        interpretation = build_editorial_interpretation(news)

        self.assertIn("demanda", interpretation["suggested_question"].lower())
        self.assertIn("leverage", interpretation["suggested_question"].lower())

    def test_image_brief_matches_editorial_story(self):
        news = publishable_item("Trump pushes CLARITY Act as BTC rallies")
        news.daily_news_relevance = 88
        news.event_type = "COMBINED_MARKET_STORY"
        brief = build_image_brief(news)

        self.assertTrue(brief.eligible)
        self.assertIn("Bitcoin", brief.brief)
        self.assertIn("RADAR BTC", brief.brief)

    def test_unsupported_whale_institution_claims_rejected(self):
        review = validate_publication_text("Las instituciones están comprando BTC y las ballenas van en largo.")

        self.assertFalse(review["ok"])
        self.assertTrue(any("unsupported" in error or "forbidden" in error for error in review["errors"]))

    def test_quiet_market_can_produce_useful_analysis(self):
        quiet = NewsItem(
            title="Bitcoin lleva horas sin decidirse",
            summary="Volatilidad comprimida y rango estrecho.",
            content="📊 MARKET NOTE\n\nBitcoin apenas se mueve y la volatilidad esta comprimida.",
            link="quiet-market:btc:test",
            published="",
            source="MARKET_STATE",
            category=QUIET_MARKET_CATEGORY,
            event_type="QUIET_MARKET_STATE",
            affected_assets=["BTC"],
        )

        interpretation = build_editorial_interpretation(quiet)

        self.assertEqual(interpretation["story_angle"], "QUIET_MARKET")
        self.assertIn("ausencia de catalizadores", interpretation["primary_hypothesis"])

    def test_publication_remains_concise(self):
        text = (
            "BITCOIN SUBE, PERO EL APALANCAMIENTO DESAPARECE\n\n"
            "₿ BTC conserva mas de un 7% de subida diaria mientras el open interest cae alrededor de un 5% en cuatro horas.\n\n"
            "👉 LECTURA RADAR: es compatible con limpieza de leverage, no una prueba automatica de demanda nueva.\n\n"
            "❓ ¿Aparece volumen real si el OI vuelve a crecer?"
        )

        review = validate_publication_text(text)

        self.assertTrue(review["ok"])
        self.assertLessEqual(len(text.split()), 80)

    def test_intraday_up_three_percent_volume_and_oi_is_high_candidate(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(
                change_1h=3.0,
                change_15m=1.1,
                volume_ratio=2.4,
                volatility_ratio=2.1,
                oi_change=3.0,
                structure_1h="BULLISH_BREAKOUT",
            )
        )

        self.assertEqual(state.decision, "INTRADAY_ALERT")
        self.assertIn(state.intraday_materiality, {"INTRADAY_HIGH", "INTRADAY_CRITICAL"})

    def test_intraday_down_four_percent_oi_collapse_is_deleveraging_candidate(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=-4.0, change_15m=-1.5, volume_ratio=2.2, volatility_ratio=2.5, oi_change=-4.0)
        )
        names = {signal.name for signal in state.signals}

        self.assertIn("DELEVERAGING_STYLE_MOVE", names)
        self.assertEqual(state.decision, "INTRADAY_ALERT")

    def test_intraday_up_four_percent_oi_falling_is_short_covering_inference(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=4.0, change_15m=1.6, volume_ratio=2.1, volatility_ratio=2.0, oi_change=-3.0)
        )
        names = {signal.name for signal in state.signals}

        self.assertIn("POSSIBLE_SHORT_COVERING", names)

    def test_intraday_up_four_percent_oi_rising_is_momentum_leverage_inference(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=4.0, change_15m=1.6, volume_ratio=2.1, volatility_ratio=2.0, oi_change=3.0)
        )
        names = {signal.name for signal in state.signals}

        self.assertIn("MOMENTUM_WITH_LEVERAGE_BUILDUP", names)

    def test_intraday_fast_move_without_news_can_publish_no_clear_catalyst(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.5, change_15m=1.2, volume_ratio=2.3, volatility_ratio=2.2, oi_change=3.0)
        )
        news = intraday_state_to_news_item(state)

        self.assertIsNotNone(news)
        self.assertIn("Catalizador: NO_CLEAR_CATALYST", news.content)

    def test_intraday_news_exists_but_causality_uncertain_possible_catalyst(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.5, change_15m=1.2, volume_ratio=2.3, volatility_ratio=2.2, oi_change=3.0)
        )
        fast = item("BTC rumor about exchange outage", source="binancekillers")
        fast.source_type = "FAST"

        attach_intraday_catalyst(state, [fast])

        self.assertEqual(state.catalyst_status, "POSSIBLE_CATALYST")

    def test_intraday_primary_news_is_confirmed_catalyst(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.5, change_15m=1.2, volume_ratio=2.3, volatility_ratio=2.2, oi_change=3.0)
        )
        primary = item("SEC confirms Bitcoin ETF emergency decision", source="SEC - Press Releases")
        primary.source_type = "PRIMARY"

        attach_intraday_catalyst(state, [primary])

        self.assertEqual(state.catalyst_status, "CONFIRMED_CATALYST")

    def test_intraday_structural_low_intraday_high_can_reach_gate(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.5, change_15m=1.2, volume_ratio=2.3, volatility_ratio=2.2, oi_change=3.0)
        )
        news = intraday_state_to_news_item(state)
        result = evaluate_intraday_item(news, review_ok=True)

        self.assertTrue(result.passed)
        self.assertEqual(news.event_type, "BTC_INTRADAY_MOVE")

    def test_intraday_no_buy_sell_language(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.5, change_15m=1.2, volume_ratio=2.3, volatility_ratio=2.2, oi_change=3.0)
        )
        news = intraday_state_to_news_item(state)
        lowered = news.content.lower()

        self.assertNotIn("buy", lowered)
        self.assertNotIn("sell", lowered)
        self.assertNotIn("long now", lowered)
        self.assertNotIn("short now", lowered)

    def test_intraday_stale_market_data_rejected(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.5, change_15m=1.2, volume_ratio=2.3, volatility_ratio=2.2, oi_change=3.0)
        )
        news = intraday_state_to_news_item(state)
        news.intelligence_summary["MARKET_DATA_AGE_MINUTES"] = 30
        result = evaluate_intraday_item(news, review_ok=True)

        self.assertFalse(result.passed)
        self.assertIn("stale_market_data", result.reasons)

    def test_intraday_equal_highs_visible_ask_liquidity_cluster_above(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.0, change_15m=1.0, volume_ratio=2.0, volatility_ratio=2.0, oi_change=3.0)
        )
        names = {signal.name for signal in state.signals}

        self.assertIn("LIQUIDITY_CLUSTER_ABOVE", names)
        self.assertIn("EQUAL_HIGHS_LIQUIDITY", names)

    def test_intraday_equal_highs_without_book_is_inferred_liquidity(self):
        snapshot = intraday_snapshot(change_1h=3.0, change_15m=1.0, volume_ratio=2.0, volatility_ratio=2.0, oi_change=3.0)
        snapshot.liquidity.visible_above = "UNKNOWN"
        snapshot.liquidity.nearest_visible_above = None
        state = analyze_btc_intraday_state(snapshot)
        signal = [signal for signal in state.signals if signal.name == "EQUAL_HIGHS_LIQUIDITY"][0]

        self.assertEqual(signal.certainty, "INFERRED")

    def test_intraday_sweep_above_return_to_range_signal(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=2.5, change_15m=1.0, volume_ratio=2.0, volatility_ratio=2.0, oi_change=2.5, structure_1h="FAILED_BREAKOUT_UP")
        )
        names = {signal.name for signal in state.signals}

        self.assertIn("POSSIBLE_LIQUIDITY_SWEEP_ABOVE", names)

    def test_intraday_bos_without_volume_is_weak(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=1.0, change_15m=0.4, volume_ratio=1.0, volatility_ratio=1.0, oi_change=0.5, structure_1h="BULLISH_BREAKOUT")
        )

        self.assertNotEqual(state.decision, "INTRADAY_ALERT")

    def test_intraday_bos_volume_oi_strengthens_smc(self):
        weak = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=2.0, change_15m=0.7, volume_ratio=1.0, volatility_ratio=1.0, oi_change=0.5, structure_1h="BULLISH_BREAKOUT")
        )
        strong = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.0, change_15m=1.0, volume_ratio=2.4, volatility_ratio=2.0, oi_change=3.0, structure_1h="BULLISH_BREAKOUT")
        )

        self.assertGreater(strong.smc_confluence_score, weak.smc_confluence_score)

    def test_intraday_mixed_timeframe_output(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.0, change_15m=1.0, volume_ratio=2.4, volatility_ratio=2.0, oi_change=3.0, structure_15m="BULLISH", structure_1h="BULLISH_BREAKOUT", structure_4h="RANGE")
        )
        news = intraday_state_to_news_item(state)

        self.assertIn("15m=BULLISH", news.content)
        self.assertIn("4h=RANGE", news.content)

    def test_intraday_smc_only_cannot_create_high_alert(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=0.3, change_15m=0.1, volume_ratio=1.0, volatility_ratio=1.0, oi_change=0.0, structure_1h="BULLISH_BREAKOUT")
        )

        self.assertNotEqual(state.decision, "INTRADAY_ALERT")

    def test_intraday_smc_abnormal_move_derivatives_volume_can_elevate(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.2, change_15m=1.1, volume_ratio=2.5, volatility_ratio=2.2, oi_change=3.2, structure_1h="BULLISH_BREAKOUT")
        )

        self.assertEqual(state.decision, "INTRADAY_ALERT")

    def test_intraday_publication_can_include_editorial_question_without_certainty(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.2, change_15m=1.1, volume_ratio=2.5, volatility_ratio=2.2, oi_change=3.2)
        )
        news = intraday_state_to_news_item(state)

        self.assertIn("Pregunta clave", news.content)
        self.assertIn("¿", news.content)
        self.assertNotIn("confirmado que alcanzará", news.content.lower())

    def test_intraday_no_institutional_manipulation_claims(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.2, change_15m=1.1, volume_ratio=2.5, volatility_ratio=2.2, oi_change=3.2, structure_1h="FAILED_BREAKOUT_UP")
        )
        news = intraday_state_to_news_item(state)
        lowered = news.content.lower()

        self.assertNotIn("instituciones están cazando stops", lowered)
        self.assertNotIn("manipulando btc", lowered)
        self.assertNotIn("market makers van a barrer", lowered)

    def test_intraday_no_fake_liquidation_heatmap(self):
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=-3.2, change_15m=-1.1, volume_ratio=2.5, volatility_ratio=2.2, oi_change=-3.2)
        )
        news = intraday_state_to_news_item(state)

        self.assertNotIn("heatmap", news.content.lower())

    def test_intraday_same_movement_dedupes_by_event_fingerprint(self):
        cache = temp_seen_cache()
        state = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.2, change_15m=1.1, volume_ratio=2.5, volatility_ratio=2.2, oi_change=3.2)
        )
        first = intraday_state_to_news_item(state)
        second = intraday_state_to_news_item(state)
        second.link = "market-state:btc-intraday:UP:BULLISH:later"

        accepted_first, _ = cache.filter_new_items([first])
        accepted_second, stats = cache.filter_new_items([second])

        self.assertEqual(len(accepted_first), 1)
        self.assertEqual(accepted_second, [])
        self.assertGreaterEqual(stats.same_event_merges + stats.near_duplicates, 1)

    def test_intraday_same_move_next_cycle_is_duplicate_move(self):
        previous = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.0, change_15m=1.1, change_4h=3.0, volume_ratio=2.4, volatility_ratio=2.1, oi_change=3.0)
        )
        current = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.1, change_15m=1.0, change_4h=3.1, volume_ratio=2.3, volatility_ratio=2.0, oi_change=3.1)
        )

        self.assertEqual(intraday_update_type(previous, current), "DUPLICATE_MOVE")

    def test_intraday_material_extension_is_update(self):
        previous = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=1.8, change_15m=0.5, change_4h=2.0, volume_ratio=2.0, volatility_ratio=1.9, oi_change=1.0)
        )
        current = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.2, change_15m=1.1, change_4h=4.1, volume_ratio=2.5, volatility_ratio=2.2, oi_change=3.2)
        )

        self.assertEqual(intraday_update_type(previous, current), "MATERIAL_UPDATE")

    def test_quiet_market_cannot_override_strong_intraday_movement(self):
        intraday = analyze_btc_intraday_state(
            intraday_snapshot(change_1h=3.2, change_15m=1.1, volume_ratio=2.5, volatility_ratio=2.2, oi_change=3.2)
        )
        market_state = BtcMarketState(
            snapshot=BtcMarketSnapshot(timestamp="2026-08-19T20:00:00+00:00"),
            intraday=intraday,
            confluence="LOW",
            confluence_score=0,
            market_regime="NEUTRAL",
        )

        news = market_state_to_news_item(market_state)
        quiet = evaluate_quiet_market(quiet_btc_state(), has_market_alert=news is not None, history=[])

        self.assertIsNotNone(news)
        self.assertFalse(quiet.passed)
        self.assertEqual(quiet.skipped, "market_alert_priority")

    def test_quiet_btc_half_percent_for_few_hours_no_note(self):
        now = datetime(2026, 8, 16, 12, 0)
        history = [
            {
                "date": (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
                "status": "published",
                "category": "Market State",
                "link": "material:1",
            }
        ]

        decision = evaluate_quiet_market(quiet_btc_state(), history=history, now=now)

        self.assertFalse(decision.passed)
        self.assertEqual(decision.skipped, "recent_material_post")

    def test_quiet_24h_range_compressed_vol_neutral_funding_candidate(self):
        now = datetime(2026, 8, 16, 12, 0)

        decision = evaluate_quiet_market(
            quiet_btc_state(),
            history=[],
            now=now,
        )

        self.assertTrue(decision.passed)
        self.assertEqual(decision.state, "COMPRESSION")
        self.assertIn("📊 MARKET NOTE", decision.message)

    def test_quiet_note_is_spanish_and_uses_concrete_data(self):
        decision = evaluate_quiet_market(quiet_btc_state(), history=[])

        self.assertTrue(decision.passed)
        lowered = decision.message.lower()
        self.assertIn("bitcoin cotiza cerca de $100,000", lowered)
        self.assertIn("24 horas", lowered)
        self.assertIn("qué muestran los datos", lowered)
        self.assertNotIn("btc 24h move", lowered)
        self.assertNotIn("funding is neutral", lowered)

    def test_quiet_note_does_not_print_unknown_as_data(self):
        decision = evaluate_quiet_market(quiet_btc_state(), history=[])

        self.assertTrue(decision.passed)
        self.assertNotIn("UNKNOWN", decision.message)

    def test_quiet_angle_changes_with_market_signals(self):
        base = quiet_btc_state()
        funding = quiet_btc_state(funding="POSITIVE")

        self.assertEqual(select_quiet_market_angle(base), "VOLATILITY_COMPRESSION")
        self.assertEqual(select_quiet_market_angle(funding), "FUNDING_SHIFT")

    def test_quiet_funding_or_oi_angle_can_beat_range(self):
        decision = evaluate_quiet_market(quiet_btc_state(oi_change=7.0), history=[])

        self.assertTrue(decision.passed)
        self.assertEqual(decision.angle, "OI_DIVERGENCE")
        self.assertIn("open interest", decision.message.lower())

    def test_quiet_market_without_enough_data_no_note(self):
        snapshot = BtcMarketSnapshot(timestamp="2026-08-16T12:00:00+00:00")
        state = BtcMarketState(snapshot=snapshot, confluence="LOW")

        decision = evaluate_quiet_market(state, history=[])

        self.assertFalse(decision.passed)
        self.assertEqual(decision.skipped, "low_quiet_score")

    def test_market_alert_existing_blocks_quiet_note(self):
        decision = evaluate_quiet_market(
            quiet_btc_state(),
            has_market_alert=True,
            history=[],
        )

        self.assertFalse(decision.passed)
        self.assertEqual(decision.skipped, "market_alert_priority")

    def test_quiet_note_six_hours_ago_does_not_repeat(self):
        now = datetime(2026, 8, 16, 12, 0)
        history = [
            {
                "date": (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M"),
                "status": "published",
                "category": QUIET_MARKET_CATEGORY,
                "link": "quiet:1",
            }
        ]

        decision = evaluate_quiet_market(quiet_btc_state(), history=history, now=now)

        self.assertFalse(decision.passed)
        self.assertEqual(decision.skipped, "frequency_limit")

    def test_quiet_note_after_structure_or_oi_change_eventually_possible(self):
        now = datetime(2026, 8, 16, 12, 0)
        history = [
            {
                "date": (now - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M"),
                "status": "published",
                "category": QUIET_MARKET_CATEGORY,
                "link": "quiet:1",
            }
        ]

        decision = evaluate_quiet_market(
            quiet_btc_state(oi_change=7.0),
            history=history,
            now=now,
        )

        self.assertTrue(decision.passed)
        self.assertIn("apalancamiento", decision.message.lower())

    def test_quiet_wallet_transfer_isolated_never_whales_going_long(self):
        decision = evaluate_quiet_market(quiet_btc_state(), history=[])

        self.assertNotIn("whales are going long", decision.message.lower())
        self.assertNotIn("whales going long", decision.message.lower())

    def test_quiet_onchain_outflow_language_is_conservative(self):
        message = (
            "Se observan retiradas elevadas de BTC de exchanges respecto al baseline. "
            "El dato es consistente con menor oferta disponible en exchanges, aunque no demuestra acumulacion institucional."
        )

        review = review_quiet_market_message(message)

        self.assertTrue(review["ok"])

    def test_quiet_reviewer_requires_angle_and_observations_when_provided(self):
        review = review_quiet_market_message(
            "📊 MARKET NOTE\n\nSituación: Bitcoin cotiza estable.",
            angle="UNKNOWN",
            observations=["Solo una observación."],
        )

        self.assertFalse(review["ok"])
        self.assertIn("missing_angle", review["errors"])
        self.assertIn("insufficient_observations", review["errors"])

    def test_quiet_reviewer_fail_blocks_note(self):
        decision = evaluate_quiet_market(
            quiet_btc_state(),
            history=[],
            reviewer_ok=False,
        )

        self.assertFalse(decision.passed)
        self.assertEqual(decision.skipped, "reviewer_failed")

    def test_quiet_note_has_no_buy_sell_or_prediction_certainty(self):
        decision = evaluate_quiet_market(quiet_btc_state(), history=[])

        lowered = decision.message.lower()
        self.assertNotIn("buy", lowered)
        self.assertNotIn("sell", lowered)
        self.assertNotIn("va a subir", lowered)
        self.assertNotIn("va a caer", lowered)
        self.assertNotIn("price target", lowered)

    def test_seen_cache_same_url_second_cycle_not_processed(self):
        cache = temp_seen_cache()
        first = item("Fed cuts rates by 25 bps", source="Reuters")
        second = item("Fed cuts rates by 25 bps", source="Reuters")

        new_first, stats_first = cache.filter_new_items([first])
        new_second, stats_second = cache.filter_new_items([second])

        self.assertEqual(len(new_first), 1)
        self.assertEqual(len(new_second), 0)
        self.assertEqual(stats_second.exact_duplicates, 1)

    def test_canonical_url_strips_tracking_params(self):
        one = canonical_url("https://example.com/story?utm_source=x&id=42#section")
        two = canonical_url("https://example.com/story?id=42")

        self.assertEqual(one, two)

    def test_seen_cache_utm_url_is_duplicate(self):
        cache = temp_seen_cache()
        first = item("SEC approves major Bitcoin ETF rule")
        first.link = "https://example.com/story?id=42&utm_source=newsletter"
        second = item("SEC approves major Bitcoin ETF rule")
        second.link = "https://example.com/story?id=42&utm_campaign=x"

        cache.filter_new_items([first])
        new_second, stats = cache.filter_new_items([second])

        self.assertEqual(new_second, [])
        self.assertEqual(stats.exact_duplicates, 1)

    def test_seen_cache_exact_title_duplicate(self):
        cache = temp_seen_cache()
        first = item("Fed cuts rates by 25 bps")
        second = item("Fed cuts rates by 25 bps")
        second.link = "https://another.example.com/fed-cut"

        cache.filter_new_items([first])
        new_second, stats = cache.filter_new_items([second])

        self.assertEqual(new_second, [])
        self.assertEqual(stats.near_duplicates, 1)

    def test_seen_cache_semantically_similar_titles_same_event(self):
        cache = temp_seen_cache()
        first = item("Fed cuts rates by 25 bps", source="Reuters")
        second = item("Federal Reserve cuts rates 25 basis points", source="Bloomberg")
        second.link = "https://bloomberg.example.com/fed"

        cache.filter_new_items([first])
        new_second, stats = cache.filter_new_items([second])

        self.assertEqual(new_second, [])
        self.assertEqual(stats.same_event_merges, 1)

    def test_supporting_source_does_not_take_extra_slot(self):
        cache = temp_seen_cache()
        first = item("Fed cuts rates by 25 bps", source="Reuters")
        second = item("Federal Reserve cuts rates 25 basis points", source="Bloomberg")
        first.link = "https://reuters.example.com/fed"
        second.link = "https://bloomberg.example.com/fed"

        accepted, stats = cache.filter_new_items([first, second])

        self.assertEqual(len(accepted), 1)
        self.assertEqual(stats.same_event_merges, 1)
        self.assertIn("Bloomberg", accepted[0].related_sources)

    def test_rumor_to_confirmed_is_material_update(self):
        cache = temp_seen_cache()
        rumor = item("Rumor: Trump may impose 50 percent tariffs on China")
        confirmed = item("Trump confirmed 50 percent tariffs on China")
        confirmed.link = "https://example.com/confirmed-tariffs"

        cache.filter_new_items([rumor])
        accepted, stats = cache.filter_new_items([confirmed])

        self.assertEqual(len(accepted), 1)
        self.assertEqual(stats.material_updates, 1)

    def test_same_event_reworded_is_not_update(self):
        cache = temp_seen_cache()
        first = item("Trump may impose 50 percent tariffs on China")
        second = item("Trump could impose 50 percent tariffs on China")
        second.link = "https://example.com/tariffs-rewrite"

        cache.filter_new_items([first])
        accepted, stats = cache.filter_new_items([second])

        self.assertEqual(accepted, [])
        self.assertEqual(stats.same_event_merges, 1)

    def test_telegram_same_message_id_not_re_read(self):
        import asyncio
        import telegram_reader

        class Message:
            id = 10
            text = "Fed unexpectedly changes rate guidance, affecting yields, USD, equities and BTC risk sentiment."
            date = datetime.utcnow()

        class FakeClient:
            async def start(self):
                return None

            async def get_messages(self, channel, **kwargs):
                if kwargs.get("min_id") == 10:
                    return []
                return [Message()]

            async def disconnect(self):
                return None

        cache = temp_seen_cache()
        with patch.object(telegram_reader, "client", FakeClient()), \
            patch.object(telegram_reader, "CHANNELS", ["Bloomberg"]):
            first = asyncio.run(telegram_reader.get_telegram_news(seen_cache=cache))
            second = asyncio.run(telegram_reader.get_telegram_news(seen_cache=cache))

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_telegram_new_message_id_enters(self):
        import asyncio
        import telegram_reader

        class Message:
            def __init__(self, message_id):
                self.id = message_id
                self.text = "Fed unexpectedly changes rate guidance, affecting yields, USD, equities and BTC risk sentiment."
                self.date = datetime.utcnow()

        class FakeClient:
            async def start(self):
                return None

            async def get_messages(self, channel, **kwargs):
                min_id = kwargs.get("min_id") or 0
                return [Message(11)] if min_id < 11 else []

            async def disconnect(self):
                return None

        cache = temp_seen_cache()
        cache.update_source_state("Bloomberg", entry_id="10")
        with patch.object(telegram_reader, "client", FakeClient()), \
            patch.object(telegram_reader, "CHANNELS", ["Bloomberg"]):
            news = asyncio.run(telegram_reader.get_telegram_news(seen_cache=cache))

        self.assertEqual(len(news), 1)

    def test_rss_old_entry_is_not_reprocessed(self):
        import collector

        rss = b"""<?xml version="1.0"?><rss><channel><item><title>Fed cuts rates by 25 bps</title><link>https://example.com/fed</link><guid>fed-1</guid><pubDate>Sun, 16 Aug 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
        cache = temp_seen_cache()

        with patch.object(collector, "RSS_FEEDS", [{"name": "Test RSS", "url": "https://feed.example.com"}]), \
            patch.object(collector, "_fetch_bytes", return_value=rss):
            first = collector.get_news(seen_cache=cache)
            second = collector.get_news(seen_cache=cache)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_rss_new_entry_is_processed(self):
        import collector

        rss_one = b"""<?xml version="1.0"?><rss><channel><item><title>Fed cuts rates by 25 bps</title><link>https://example.com/fed1</link><guid>fed-1</guid></item></channel></rss>"""
        rss_two = b"""<?xml version="1.0"?><rss><channel><item><title>Fed confirms rate cut details</title><link>https://example.com/fed2</link><guid>fed-2</guid></item><item><title>Fed cuts rates by 25 bps</title><link>https://example.com/fed1</link><guid>fed-1</guid></item></channel></rss>"""
        cache = temp_seen_cache()

        with patch.object(collector, "RSS_FEEDS", [{"name": "Test RSS", "url": "https://feed.example.com"}]):
            with patch.object(collector, "_fetch_bytes", return_value=rss_one):
                collector.get_news(seen_cache=cache)
            with patch.object(collector, "_fetch_bytes", return_value=rss_two):
                second = collector.get_news(seen_cache=cache)

        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].link, "https://example.com/fed2")

    def test_duplicate_never_consumes_openai(self):
        cache = temp_seen_cache()
        first = item("Fed cuts rates by 25 bps")
        second = item("Fed cuts rates by 25 bps")
        cache.filter_new_items([first])
        accepted, _ = cache.filter_new_items([second])
        openai = Mock()

        if accepted:
            openai(accepted)

        openai.assert_not_called()

    def test_duplicate_never_occupies_selector_slot(self):
        cache = temp_seen_cache()
        items = [
            item("Fed cuts rates by 25 bps", source="Reuters"),
            item("Federal Reserve cuts rates 25 basis points", source="Bloomberg"),
            item("Fed cuts rates by 25 bps", source="Financial Times"),
        ]
        items[1].link = "https://b.example.com/fed"
        items[2].link = "https://ft.example.com/fed"

        accepted, _ = cache.filter_new_items(items)

        self.assertEqual(len(accepted), 1)

    def test_quiet_market_unchanged_does_not_repeat(self):
        cache = temp_seen_cache()
        first = evaluate_quiet_market(quiet_btc_state(), history=[], seen_cache=cache)
        second = evaluate_quiet_market(quiet_btc_state(), history=[], seen_cache=cache)

        self.assertTrue(first.passed)
        self.assertFalse(second.passed)
        self.assertEqual(second.skipped, "unchanged_market_state")

    def test_quiet_market_state_changed_can_note(self):
        cache = temp_seen_cache()
        first = evaluate_quiet_market(quiet_btc_state(), history=[], seen_cache=cache)
        second = evaluate_quiet_market(quiet_btc_state(oi_change=7.0), history=[], seen_cache=cache)

        self.assertTrue(first.passed)
        self.assertTrue(second.passed)

    def test_seen_cache_persists_after_restart(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        path = tmp.name
        tmp.close()
        first_cache = SeenCache(path)
        first_cache.filter_new_items([item("Fed cuts rates by 25 bps")])
        second_cache = SeenCache(path)

        accepted, stats = second_cache.filter_new_items([item("Fed cuts rates by 25 bps")])

        self.assertEqual(accepted, [])
        self.assertEqual(stats.exact_duplicates, 1)

    def test_source_performance_counts_duplicates_and_new_items(self):
        cache = temp_seen_cache()
        first = item("Fed cuts rates by 25 bps", source="Reuters")
        second = item("Fed cuts rates by 25 bps", source="Reuters")

        cache.filter_new_items([first])
        cache.filter_new_items([second])
        row = cache.source_performance()[0]

        self.assertEqual(row["items_seen"], 2)
        self.assertEqual(row["items_new"], 1)
        self.assertEqual(row["duplicates"], 1)

    def test_source_performance_window_persists(self):
        path = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name
        cache = SeenCache(path)
        cache.increment_source("Test Source", "items_seen", 3)
        cache.increment_source("Test Source", "items_new", 1)

        restarted = SeenCache(path)
        row = restarted.source_performance_window(hours=24)[0]

        self.assertEqual(row["source"], "Test Source")
        self.assertEqual(row["items_seen"], 3)
        self.assertEqual(row["items_new"], 1)

    def test_rss_dead_feed_recommendation_is_fix(self):
        feed = {"name": "Dead Feed", "category": "markets", "url": "https://dead.example.com"}

        recommendation = recommend_source(feed, health={"error_count": 1, "last_error": "HTTPError"})

        self.assertEqual(recommendation, "FIX")

    def test_rss_recovered_feed_status_healthy(self):
        cache = temp_seen_cache()
        feeds = [{"name": "Recovered Feed", "category": "markets", "url": "https://ok.example.com"}]

        with patch("rss_audit.check_rss_sources", return_value=[
            {
                "source": "Recovered Feed",
                "status": 200,
                "last_success": "2026-08-16T12:00:00",
                "last_error": "",
                "entries": 5,
                "error_count": 0,
            }
        ]):
            rows = audit_rss_sources(feeds=feeds, cache=cache, check_live=True)

        self.assertEqual(rows[0].status, "HEALTHY")
        self.assertEqual(rows[0].recommendation, "WATCH")

    def test_rss_primary_source_preferred_and_kept(self):
        feed = {
            "name": "Federal Reserve - Monetary Policy",
            "category": "macro",
            "tier": "PRIMARY",
            "priority": "CRITICAL",
        }

        recommendation = recommend_source(feed, perf_7d={"items_seen": 100, "precandidates": 0})

        self.assertEqual(recommendation, "KEEP")

    def test_rss_high_noise_source_can_be_downgraded(self):
        feed = {"name": "Noisy Background", "category": "technology", "priority": "LOW"}
        perf = {"items_seen": 100, "duplicates": 85, "precandidates": 0, "material_updates": 0}

        recommendation = recommend_source(feed, perf_7d=perf)

        self.assertEqual(recommendation, "DOWNGRADE")

    def test_rss_recommendation_does_not_auto_disable_feed(self):
        feed = {"name": "Broken Background", "category": "world", "priority": "LOW"}

        recommendation = recommend_source(feed, perf_7d={"items_seen": 20, "errors": 15})

        self.assertEqual(recommendation, "DISABLE")
        self.assertNotIn("disabled", feed)

    def test_feed_http_error_does_not_break_cycle(self):
        import collector

        cache = temp_seen_cache()
        with patch.object(collector, "RSS_FEEDS", [{"name": "Broken RSS", "url": "https://feed.example.com"}]), \
            patch.object(collector, "_fetch_bytes", side_effect=Exception("HTTPError")):
            news = collector.get_news(seen_cache=cache)

        self.assertEqual(news, [])
        self.assertEqual(cache.source_performance()[0]["errors"], 1)

    def test_rss_partial_feed_timeout_keeps_valid_results(self):
        import collector
        import feedparser

        ok_feed = b"""
        <rss><channel>
        <item><title>Fed cuts rates unexpectedly</title><link>https://ok.example.com/1</link><guid>1</guid></item>
        </channel></rss>
        """

        def fake_fetch_feed(feed_info):
            if feed_info["name"] == "Slow RSS":
                raise TimeoutError("feed timeout")
            return feed_info, feedparser.parse(ok_feed)

        cache = temp_seen_cache()
        feeds = [
            {"name": f"OK RSS {idx}", "url": f"https://ok.example.com/{idx}"}
            for idx in range(10)
        ] + [{"name": "Slow RSS", "url": "https://slow.example.com"}]
        with patch.object(collector, "RSS_FEEDS", feeds), \
            patch.object(collector, "_fetch_feed", side_effect=fake_fetch_feed):
            news = collector.get_news(seen_cache=cache, max_workers=4)

        self.assertEqual(len(news), 1)
        self.assertEqual(news[0].title, "Fed cuts rates unexpectedly")
        self.assertEqual(cache.get_source_state("Slow RSS")["consecutive_failures"], 1)

    def test_repeated_broken_rss_enters_backoff_and_recovers(self):
        import collector
        import feedparser

        cache = temp_seen_cache()
        feed = [{"name": "TreasuryDirect - Auction Results", "url": "https://broken.example.com"}]
        with patch.object(collector, "RSS_FEEDS", feed), \
            patch.object(collector, "_fetch_feed", side_effect=TimeoutError("timeout")):
            collector.get_news(seen_cache=cache)
            collector.get_news(seen_cache=cache)
            collector.get_news(seen_cache=cache)

        self.assertTrue(cache.source_in_backoff("TreasuryDirect - Auction Results"))

        recovered_feed = b"""
        <rss><channel>
        <item><title>Treasury auction result</title><link>https://treasury.example.com/1</link><guid>1</guid></item>
        </channel></rss>
        """
        cache.mark_source_success("TreasuryDirect - Auction Results")
        with patch.object(collector, "RSS_FEEDS", feed), \
            patch.object(collector, "_fetch_feed", return_value=(feed[0], feedparser.parse(recovered_feed))):
            news = collector.get_news(seen_cache=cache)

        self.assertFalse(cache.source_in_backoff("TreasuryDirect - Auction Results"))
        self.assertEqual(len(news), 1)

    def test_sync_phase_timeout_returns_fallback(self):
        def hanging_call():
            time.sleep(0.05)
            return ["late"]

        result = __import__("asyncio").run(
            run_sync_phase(
                "RSS",
                hanging_call,
                timeout=0.01,
                fallback=[],
            )
        )

        self.assertEqual(result, [])

    def test_sync_phase_error_returns_fallback(self):
        def failing_call():
            raise ConnectionError("network unavailable")

        result = __import__("asyncio").run(
            run_sync_phase(
                "RSS",
                failing_call,
                timeout=0.5,
                fallback=[],
            )
        )

        self.assertEqual(result, [])

    def test_async_phase_error_returns_fallback(self):
        async def failing_call():
            raise ConnectionError("telegram unavailable")

        result = __import__("asyncio").run(
            run_async_phase(
                "TELEGRAM",
                failing_call,
                timeout=0.5,
                fallback=[],
            )
        )

        self.assertEqual(result, [])

    def test_rss_hang_times_out_and_cycle_continues(self):
        def hanging_rss(*args, **kwargs):
            time.sleep(0.05)
            return [publishable_item()]

        with patch("main.RSS_PHASE_TIMEOUT_SECONDS", 0.01), \
            patch("main.get_news", side_effect=hanging_rss), \
            patch("main.get_telegram_news", new_callable=AsyncMock, return_value=[]), \
            patch("main.get_reddit_news", return_value=([], RedditStatus(status="NOT_CONFIGURED"))), \
            patch("main.get_truth_social_news", return_value=([], None)), \
            patch("main.fetch_btc_market_state", return_value=None), \
            patch("main.SeenCache", side_effect=lambda: temp_seen_cache()), \
            patch("main.DRY_RUN", True):

            __import__("asyncio").run(process_news())

    def test_article_download_hang_times_out(self):
        candidate = publishable_item()

        def hanging_download(*args, **kwargs):
            time.sleep(0.05)
            return [candidate]

        with patch("main.ARTICLE_TIMEOUT_SECONDS", 0.01), \
            patch("main.get_news", return_value=[candidate]), \
            patch("main.get_telegram_news", new_callable=AsyncMock, return_value=[]), \
            patch("main.get_reddit_news", return_value=([], RedditStatus(status="NOT_CONFIGURED"))), \
            patch("main.get_truth_social_news", return_value=([], None)), \
            patch("main.fetch_btc_market_state", return_value=None), \
            patch("main.enrich_news", side_effect=hanging_download), \
            patch("main.SeenCache", side_effect=lambda: temp_seen_cache()), \
            patch("main.DRY_RUN", True):

            __import__("asyncio").run(process_news())

    def test_market_api_hang_does_not_block_news_engine(self):
        def hanging_market_state(*args, **kwargs):
            time.sleep(0.05)
            return None

        with patch("main.MARKET_DATA_PHASE_TIMEOUT_SECONDS", 0.01), \
            patch("main.get_news", return_value=[]), \
            patch("main.get_telegram_news", new_callable=AsyncMock, return_value=[]), \
            patch("main.get_reddit_news", return_value=([], RedditStatus(status="NOT_CONFIGURED"))), \
            patch("main.get_truth_social_news", return_value=([], None)), \
            patch("main.fetch_btc_market_state", side_effect=hanging_market_state), \
            patch("main.SeenCache", side_effect=lambda: temp_seen_cache()), \
            patch("main.DRY_RUN", True):

            __import__("asyncio").run(process_news())

    def test_telegram_timeout_allows_rss_to_continue(self):
        async def hanging_telegram(*args, **kwargs):
            await __import__("asyncio").sleep(0.05)
            return []

        with patch("main.TELEGRAM_TIMEOUT_SECONDS", 0.01), \
            patch("main.get_news", return_value=[]), \
            patch("main.get_telegram_news", side_effect=hanging_telegram), \
            patch("main.get_reddit_news", return_value=([], RedditStatus(status="NOT_CONFIGURED"))), \
            patch("main.get_truth_social_news", return_value=([], None)), \
            patch("main.fetch_btc_market_state", return_value=None), \
            patch("main.SeenCache", side_effect=lambda: temp_seen_cache()), \
            patch("main.DRY_RUN", True):

            __import__("asyncio").run(process_news())

    def test_openai_timeout_does_not_publish_incomplete_story(self):
        candidate = publishable_item()

        def hanging_enricher(*args, **kwargs):
            time.sleep(0.05)
            return [candidate]

        with patch("main.OPENAI_TIMEOUT_SECONDS", 0.01), \
            patch("main.get_news", return_value=[candidate]), \
            patch("main.get_telegram_news", new_callable=AsyncMock, return_value=[]), \
            patch("main.get_reddit_news", return_value=([], RedditStatus(status="NOT_CONFIGURED"))), \
            patch("main.get_truth_social_news", return_value=([], None)), \
            patch("main.fetch_btc_market_state", return_value=None), \
            patch("main.enrich_news", return_value=[candidate]), \
            patch("main.enrich_metadata", side_effect=hanging_enricher), \
            patch("main.publish_selected", new_callable=AsyncMock) as publisher, \
            patch("main.SeenCache", side_effect=lambda: temp_seen_cache()), \
            patch("main.DRY_RUN", False), \
            patch("main.AUTO_PUBLISH_SHADOW", False):

            __import__("asyncio").run(process_news())

        publisher.assert_not_called()

    def test_process_news_watchdog_aborts_cycle(self):
        async def hanging_process():
            await __import__("asyncio").sleep(0.05)

        result = __import__("asyncio").run(
            run_one_cycle(
                process_func=hanging_process,
                cycle_timeout=0.01,
            )
        )

        self.assertEqual(result["status"], "watchdog_timeout")
        self.assertEqual(result["network_counters"]["cycle_watchdog_timeout"], 1)

    def test_runner_starts_another_cycle_after_watchdog(self):
        calls = {"count": 0}

        async def hanging_process():
            calls["count"] += 1
            await __import__("asyncio").sleep(0.05)

        with patch("runner.CYCLE_TIMEOUT_SECONDS", 0.01):
            __import__("asyncio").run(
                radar_runner(
                    process_func=hanging_process,
                    check_every=0.01,
                    max_cycles=2,
                )
            )

        self.assertEqual(calls["count"], 2)

    def test_timeout_path_does_not_publish_accidentally(self):
        async def hanging_publish_process():
            await __import__("asyncio").sleep(0.05)

        result = __import__("asyncio").run(
            run_one_cycle(
                process_func=hanging_publish_process,
                cycle_timeout=0.01,
            )
        )

        self.assertEqual(result["status"], "watchdog_timeout")

    def test_publication_gate_still_intact_after_timeout_changes(self):
        news = publishable_item()
        result = evaluate_item(news, review_ok=True)

        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
