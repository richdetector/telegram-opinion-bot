import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from auto_publish_engine import should_auto_publish
from crypto_market_engine import (
    analyze_btc_market_state,
    analyze_btc_market_snapshot,
    fetch_btc_market_state,
    market_state_to_news_item,
)
from deduper import dedupe_news
from dry_run_report import print_dry_run_report
from editor_selector import select_news_with_ai
from market_scorer import score_market_item
from market_data import BtcEtfFlowSnapshot, BtcMarketSnapshot
from market_data import BtcOnchainSnapshot, LargeBtcTransfer, classify_large_transfer
from models import NewsItem
from publishing import DryRunPublishBlocked


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
            "FOMC says inflation risk may require tighter financial conditions, higher yields, a stronger dollar and pressure on global risk assets.",
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
        self.assertEqual(state.summary, "NO MATERIAL BTC MARKET ANOMALY")
        self.assertIsNone(market_state_to_news_item(state))

    def test_market_data_api_down_keeps_engine_alive(self):
        def failing_fetcher():
            raise RuntimeError("api down")

        state = fetch_btc_market_state(fetcher=failing_fetcher)

        self.assertIn("market_data:RuntimeError", state.snapshot.errors)
        self.assertEqual(state.confluence, "LOW")

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


if __name__ == "__main__":
    unittest.main()
