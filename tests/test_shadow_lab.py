"""Integrity checks for the additive Shadow Trader research protocol."""

from intrader.shadow_lab import (
    DATA_COVERAGE,
    DEFAULT_SHADOW_LAB_PLAN,
    FEATURE_FAMILIES,
    NEWS_RESOURCES,
    DEFAULT_TRADER_TIMEFRAMES,
    MAX_REPLAY_SESSION_INPUT,
    REPLAY_MODES,
    REPLAY_SESSION_OPTIONS,
    ShadowReplayConfig,
    development_blind_split,
    flattened_features,
    replay_mode,
    validate_replay_config,
)


def test_shadow_lab_uses_90_60_30_60_protocol() -> None:
    plan = DEFAULT_SHADOW_LAB_PLAN
    assert plan.historical_sessions == 90
    assert plan.development_sessions == 60
    assert plan.blind_sessions == 30
    assert plan.development_sessions + plan.blind_sessions == plan.historical_sessions
    assert plan.forward_sessions == 60
    assert plan.execution_mode == "SHADOW_ONLY"


def test_shadow_lab_has_exactly_50_unique_features() -> None:
    features = flattened_features()
    assert len(features) == 50
    assert len(set(features)) == 50


def test_sensex_is_modelled_as_evidence_not_causation() -> None:
    families = dict(FEATURE_FAMILIES)
    sensex = families["SENSEX confirmation"]
    assert "sensex_nifty_divergence" in sensex
    assert "sensex_lead_lag_1m" in sensex


def test_news_resource_catalog_contains_requested_sources() -> None:
    names = {name for name, _url in NEWS_RESOURCES}
    assert {
        "Google News",
        "Moneycontrol",
        "Investing.com",
        "Bloomberg",
        "TradingView",
        "Zerodha Pulse",
    } <= names


def test_expired_options_are_explicitly_pending() -> None:
    rows = {dataset: (source, status, rule) for dataset, source, status, rule in DATA_COVERAGE}
    source, status, rule = rows["Expired NIFTY options"]
    assert "Upstox" in source
    assert status == "PENDING"
    assert "Angel One" in rule


def test_replay_presets_remain_but_custom_splits_are_supported() -> None:
    assert REPLAY_SESSION_OPTIONS == (30, 60, 90, 250)
    assert MAX_REPLAY_SESSION_INPUT == 500
    assert development_blind_split(30) == (20, 10)
    config = validate_replay_config(
        ShadowReplayConfig(
            development_sessions=1,
            blind_sessions=1,
            trader_timeframes=(1, 5, 10, 15),
        )
    )
    assert config.total_sessions == 2
    assert config.trader_timeframes == DEFAULT_TRADER_TIMEFRAMES


def test_low_medium_high_touchpoints_are_monotonic() -> None:
    assert [mode.key for mode in REPLAY_MODES] == ["LOW", "MEDIUM", "HIGH"]
    assert replay_mode("LOW").feature_count == 15
    assert replay_mode("MEDIUM").feature_count == 30
    assert replay_mode("HIGH").feature_count == 50
