"""Configuration and immutable planning metadata for Intrader Shadow Trader Lab.

This module intentionally contains no broker execution path.  It defines the
research protocol that the desktop UI can display while the historical replay
engine is built incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass


NEWS_RESOURCES: tuple[tuple[str, str], ...] = (
    ("Google News", "https://news.google.com/home"),
    ("Moneycontrol", "https://www.moneycontrol.com/"),
    ("Investing.com", "https://in.investing.com/"),
    ("Bloomberg", "https://www.bloomberg.com/"),
    ("TradingView", "https://www.tradingview.com/markets/stocks-india/"),
    ("Zerodha Pulse", "https://pulse.zerodha.com/"),
)


FEATURE_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "NIFTY price / structure",
        (
            "spot_return_1m",
            "spot_return_5m",
            "ema9_ema20_spread",
            "vwap_distance",
            "opening_range_position",
        ),
    ),
    (
        "Momentum / volatility",
        (
            "rsi14",
            "roc5",
            "macd_histogram",
            "atr14_normalized",
            "realized_volatility_20m",
        ),
    ),
    (
        "Futures",
        (
            "future_basis",
            "future_basis_change",
            "future_relative_volume",
            "future_oi_change",
            "future_order_flow_imbalance",
        ),
    ),
    (
        "Options",
        (
            "call_put_oi_ratio",
            "call_put_volume_ratio",
            "atm_call_ltp_change",
            "atm_put_ltp_change",
            "option_oi_concentration",
        ),
    ),
    (
        "Options microstructure",
        (
            "call_oi_acceleration",
            "put_oi_acceleration",
            "call_volume_acceleration",
            "put_volume_acceleration",
            "option_premium_momentum",
        ),
    ),
    (
        "SENSEX confirmation",
        (
            "sensex_return_1m",
            "sensex_return_5m",
            "sensex_nifty_divergence",
            "sensex_lead_lag_1m",
            "sensex_momentum_confirmation",
        ),
    ),
    (
        "Breadth / constituents",
        (
            "nifty_advancers_ratio",
            "nifty_above_vwap_ratio",
            "nifty_above_ema20_ratio",
            "heavyweight_participation",
            "breadth_acceleration",
        ),
    ),
    (
        "Sectors / cross-index",
        (
            "banknifty_relative_strength",
            "financial_services_relative_strength",
            "it_relative_strength",
            "auto_relative_strength",
            "sector_dispersion",
        ),
    ),
    (
        "Volatility / macro context",
        (
            "india_vix_level",
            "india_vix_change",
            "gap_size",
            "event_proximity",
            "global_risk_context",
        ),
    ),
    (
        "News / regime / time",
        (
            "news_relevance_score",
            "news_sentiment_score",
            "news_surprise_score",
            "market_regime",
            "time_of_day_bucket",
        ),
    ),
)


DATA_COVERAGE: tuple[tuple[str, str, str, str], ...] = (
    (
        "NIFTY 50 index",
        "Angel One",
        "AVAILABLE",
        "Historical 1-minute candles; download in bounded request windows.",
    ),
    (
        "SENSEX index",
        "Angel One",
        "AVAILABLE",
        "Use as measured confirmation/divergence and test lead-lag empirically.",
    ),
    (
        "BANK NIFTY / sector indices",
        "Angel One",
        "AVAILABLE",
        "Cross-index confirmation where the instrument token is available.",
    ),
    (
        "NIFTY constituents / breadth",
        "Angel One + official membership",
        "AVAILABLE",
        "Reconstruct breadth and heavyweight participation from constituent candles.",
    ),
    (
        "India VIX",
        "Angel One",
        "AVAILABLE",
        "Volatility regime input when the historical token/data is available.",
    ),
    (
        "Expired NIFTY options",
        "Upstox later",
        "PENDING",
        "Angel One does not provide expired-option history. Add after Upstox reactivation.",
    ),
    (
        "Forward option snapshots",
        "Angel One",
        "RECORD NOW",
        "Persist live option LTP/OI/volume/depth so expiry never deletes our history.",
    ),
    (
        "Historical news / events",
        "Public timestamped sources",
        "PARTIAL",
        "Replay must expose only information published at or before the simulated timestamp.",
    ),
)


@dataclass(frozen=True, slots=True)
class ShadowLabPlan:
    historical_sessions: int = 90
    development_sessions: int = 60
    blind_sessions: int = 30
    forward_sessions: int = 60
    feature_count: int = 50
    execution_mode: str = "SHADOW_ONLY"
    primary_historical_source: str = "Angel One"
    expired_options_source: str = "Upstox (pending reactivation)"

    @property
    def split_label(self) -> str:
        return (
            f"{self.development_sessions} development + "
            f"{self.blind_sessions} locked blind"
        )


DEFAULT_SHADOW_LAB_PLAN = ShadowLabPlan()


def flattened_features() -> tuple[str, ...]:
    return tuple(
        feature
        for _family, features in FEATURE_FAMILIES
        for feature in features
    )


if len(flattened_features()) != DEFAULT_SHADOW_LAB_PLAN.feature_count:
    raise RuntimeError("Shadow Trader feature catalog must contain exactly 50 features.")
