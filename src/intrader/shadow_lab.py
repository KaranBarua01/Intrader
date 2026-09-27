"""Configuration and immutable planning metadata for Intrader Shadow Trader Lab.

This module intentionally contains no broker execution path. It defines the
research protocol, selectable replay depth, and feature coverage exposed by the
desktop Shadow Trader workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


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


REPLAY_SESSION_OPTIONS: tuple[int, ...] = (30, 60, 90, 250)
MAX_REPLAY_SESSION_INPUT = 500
DEFAULT_TRADER_TIMEFRAMES: tuple[int, ...] = (1, 5, 10, 15)
VALIDATION_MODES: tuple[str, ...] = ("STANDARD", "WALK_FORWARD")
EXECUTION_MODES: tuple[str, ...] = ("PROXY", "OPTION_PREMIUM")
TRADER_HOLD_MINUTES: tuple[tuple[int, int], ...] = (
    (1, 10),
    (5, 30),
    (10, 45),
    (15, 60),
)


@dataclass(frozen=True, slots=True)
class ReplayModeSpec:
    key: str
    label: str
    feature_count: int
    families: tuple[str, ...]
    description: str


REPLAY_MODES: tuple[ReplayModeSpec, ...] = (
    ReplayModeSpec(
        key="LOW",
        label="Low",
        feature_count=15,
        families=(
            "NIFTY price / structure",
            "Momentum / volatility",
            "Volatility / macro context",
        ),
        description=(
            "Fastest replay. Core NIFTY price/structure, momentum/volatility and "
            "macro-volatility context only."
        ),
    ),
    ReplayModeSpec(
        key="MEDIUM",
        label="Medium",
        feature_count=30,
        families=(
            "NIFTY price / structure",
            "Momentum / volatility",
            "Futures",
            "SENSEX confirmation",
            "Breadth / constituents",
            "Volatility / macro context",
        ),
        description=(
            "Balanced replay. Adds futures, SENSEX confirmation and NIFTY breadth "
            "to the Low profile."
        ),
    ),
    ReplayModeSpec(
        key="HIGH",
        label="High",
        feature_count=50,
        families=tuple(family for family, _features in FEATURE_FAMILIES),
        description=(
            "All-in replay. Requests all 50 feature touchpoints. Any unavailable "
            "historical family must be marked missing rather than fabricated."
        ),
    ),
)



@dataclass(frozen=True, slots=True)
class ShadowReplayConfig:
    development_sessions: int = 60
    blind_sessions: int = 30
    mode_key: str = "MEDIUM"
    validation_mode: str = "STANDARD"
    walk_train_sessions: int = 60
    walk_test_sessions: int = 15
    walk_step_sessions: int = 15
    walk_windows: int = 4
    execution_mode: str = "PROXY"
    starting_capital: Decimal = Decimal("50000")
    allocation_pct: Decimal = Decimal("25")
    friction_bps: Decimal = Decimal("5")
    trader_timeframes: tuple[int, ...] = DEFAULT_TRADER_TIMEFRAMES

    @property
    def total_sessions(self) -> int:
        return self.development_sessions + self.blind_sessions

    @property
    def walk_required_sessions(self) -> int:
        return (
            self.walk_train_sessions
            + self.walk_test_sessions
            + self.walk_step_sessions * (self.walk_windows - 1)
        )

    @property
    def required_sessions(self) -> int:
        if self.validation_mode == "WALK_FORWARD":
            return max(self.total_sessions, self.walk_required_sessions)
        return self.total_sessions


def validate_replay_config(config: ShadowReplayConfig) -> ShadowReplayConfig:
    if not 1 <= int(config.development_sessions) <= MAX_REPLAY_SESSION_INPUT:
        raise ValueError("development sessions must be between 1 and 500")
    if not 1 <= int(config.blind_sessions) <= MAX_REPLAY_SESSION_INPUT:
        raise ValueError("blind sessions must be between 1 and 500")
    replay_mode(config.mode_key)
    validation_mode = str(config.validation_mode).strip().upper()
    if validation_mode not in VALIDATION_MODES:
        raise ValueError("validation mode must be STANDARD or WALK_FORWARD")
    execution_mode = str(config.execution_mode).strip().upper()
    if execution_mode not in EXECUTION_MODES:
        raise ValueError("execution mode must be PROXY or OPTION_PREMIUM")
    if not 1 <= int(config.walk_train_sessions) <= MAX_REPLAY_SESSION_INPUT:
        raise ValueError("walk-forward train sessions must be between 1 and 500")
    if not 1 <= int(config.walk_test_sessions) <= MAX_REPLAY_SESSION_INPUT:
        raise ValueError("walk-forward test sessions must be between 1 and 500")
    if not 1 <= int(config.walk_step_sessions) <= MAX_REPLAY_SESSION_INPUT:
        raise ValueError("walk-forward step sessions must be between 1 and 500")
    if not 1 <= int(config.walk_windows) <= 20:
        raise ValueError("walk-forward windows must be between 1 and 20")
    if config.starting_capital <= 0:
        raise ValueError("starting capital must be positive")
    if not Decimal("1") <= config.allocation_pct <= Decimal("100"):
        raise ValueError("allocation percent must be between 1 and 100")
    if not Decimal("0") <= config.friction_bps <= Decimal("1000"):
        raise ValueError("friction bps must be between 0 and 1000")
    frames = tuple(sorted(set(int(value) for value in config.trader_timeframes)))
    if not frames or any(value not in DEFAULT_TRADER_TIMEFRAMES for value in frames):
        raise ValueError("trader timeframes must use 1, 5, 10 or 15 minutes")
    return ShadowReplayConfig(
        development_sessions=int(config.development_sessions),
        blind_sessions=int(config.blind_sessions),
        mode_key=str(config.mode_key).upper(),
        validation_mode=validation_mode,
        walk_train_sessions=int(config.walk_train_sessions),
        walk_test_sessions=int(config.walk_test_sessions),
        walk_step_sessions=int(config.walk_step_sessions),
        walk_windows=int(config.walk_windows),
        execution_mode=execution_mode,
        starting_capital=Decimal(config.starting_capital),
        allocation_pct=Decimal(config.allocation_pct),
        friction_bps=Decimal(config.friction_bps),
        trader_timeframes=frames,
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


def replay_mode(key: str) -> ReplayModeSpec:
    normalized = str(key).strip().upper()
    for mode in REPLAY_MODES:
        if mode.key == normalized:
            return mode
    raise ValueError(f"unknown Shadow Trader replay mode: {key}")


def development_blind_split(sessions: int) -> tuple[int, int]:
    if sessions < 2:
        raise ValueError("Shadow Trader replay needs at least 2 sessions")
    blind = max(1, sessions // 3)
    return sessions - blind, blind


if len(flattened_features()) != DEFAULT_SHADOW_LAB_PLAN.feature_count:
    raise RuntimeError("Shadow Trader feature catalog must contain exactly 50 features.")

for _mode in REPLAY_MODES:
    if sum(
        len(features)
        for family, features in FEATURE_FAMILIES
        if family in _mode.families
    ) != _mode.feature_count:
        raise RuntimeError(f"Replay mode {_mode.key} feature count does not match its families.")
