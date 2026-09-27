"""CSV and JSON exports for immutable Phase 3 learning records."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import csv
import json

from intrader.records_manager_pipeline import build_records_manager
from intrader.shadow_lab import development_blind_split, replay_mode
from intrader.storage import SQLiteStore


class ExportError(Exception):
    """Requested export could not be generated."""


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def export_shadow_results(store: SQLiteStore, target: Path) -> Path:
    bundles = store.load_completed_shadow_bundles()
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "trade_id", "decision_id", "opened_at", "action", "token", "strike",
        "option_type", "entry_price", "quantity", "stop_price", "target_price",
        "brain_version", "rule_version", "regime", "direction_score",
        "confidence", "entry_quality", "reversal_risk", "exit_at",
        "exit_reason", "exit_price", "gross_pnl", "adjusted_pnl",
        "mfe_amount", "mae_amount", "directional_spot_change",
    ]
    with target.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for decision, trade, outcome in bundles:
            writer.writerow({
                "trade_id": trade.trade_id,
                "decision_id": decision.decision_id,
                "opened_at": trade.opened_at.isoformat(),
                "action": trade.action,
                "token": trade.token,
                "strike": trade.strike,
                "option_type": trade.option_type,
                "entry_price": trade.entry_price,
                "quantity": trade.quantity,
                "stop_price": trade.stop_price,
                "target_price": trade.target_price,
                "brain_version": decision.brain_version,
                "rule_version": decision.rule_version,
                "regime": decision.regime,
                "direction_score": decision.direction_score,
                "confidence": decision.confidence,
                "entry_quality": decision.entry_quality,
                "reversal_risk": decision.reversal_risk,
                "exit_at": outcome.exit_at.isoformat(),
                "exit_reason": outcome.exit_reason,
                "exit_price": outcome.exit_price,
                "gross_pnl": outcome.gross_pnl,
                "adjusted_pnl": outcome.adjusted_pnl,
                "mfe_amount": outcome.mfe_amount,
                "mae_amount": outcome.mae_amount,
                "directional_spot_change": outcome.directional_spot_change,
            })
    return target


def export_shadow_review_bundle(
    store: SQLiteStore,
    target: Path,
    *,
    sessions: int,
    mode_key: str,
) -> Path:
    """Export one self-contained Shadow Trader review bundle for diagnosis."""

    mode = replay_mode(mode_key)
    development, blind = development_blind_split(sessions)
    decisions = store.load_decision_records()
    bundles = store.load_completed_shadow_bundles()
    audits = store.load_reason_audits()
    try:
        performance = build_records_manager(store)
        performance_payload = asdict(performance)
    except Exception:
        performance_payload = None

    payload = {
        "schema": "intrader-shadow-review-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "replay_configuration": {
            "requested_sessions": sessions,
            "development_sessions": development,
            "blind_sessions": blind,
            "mode": mode.key,
            "mode_label": mode.label,
            "requested_touchpoints": mode.feature_count,
            "feature_families": mode.families,
            "description": mode.description,
            "causality_rule": (
                "decision engine may only read observations with timestamp <= simulated clock"
            ),
        },
        "performance": performance_payload,
        "decision_records": [asdict(decision) for decision in decisions],
        "completed_shadow_trades": [
            {
                "decision": asdict(decision),
                "trade": asdict(trade),
                "outcome": asdict(outcome),
            }
            for decision, trade, outcome in bundles
        ],
        "reason_audits": [asdict(audit) for audit in audits],
        "review_notes": [
            "Missing historical families must remain missing; never infer expired option data.",
            "Compare development and blind results separately before changing rules.",
            "Upload this JSON back into ChatGPT for feature, regime, drawdown and expectancy review.",
        ],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return target


def export_reasoning(store: SQLiteStore, target: Path) -> Path:
    decisions = store.load_decision_records()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(decision) for decision in decisions]
    target.write_text(
        json.dumps(payload, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return target


def export_reason_audits(store: SQLiteStore, target: Path) -> Path:
    audits = store.load_reason_audits()
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "trade_id", "decision_id", "auditor_version", "thesis",
        "reason_code", "category", "expected_direction", "verdict",
        "trade_result", "adjusted_pnl", "spot_change",
    ]
    with target.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for audit in audits:
            writer.writerow(asdict(audit))
    return target
