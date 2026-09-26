"""CSV and JSON exports for immutable Phase 3 learning records."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import csv
import json

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
