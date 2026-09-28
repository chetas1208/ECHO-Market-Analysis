"""Deliberate execution profile commands; no command submits a broker order."""

from __future__ import annotations

import argparse
import json

from app.execution.service import ExecutionRejected, ExecutionService
from app.execution.settings import get_execution_settings
from app.execution.types import PaperDecision


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("status", "dry-run"))
    args = parser.parse_args()
    service = ExecutionService(get_execution_settings())
    if args.command == "status":
        print(json.dumps(service.health().__dict__, default=str, indent=2))
        return
    decision = PaperDecision(
        decision_id="cli-dry-run",
        state="PAPER_TRADE",
        forecast_id="cli-forecast",
        strategy_version="echo-rp-v1",
        config_hash="dry-run",
        symbol="NVDA",
        side="LONG",
        quantity=1.0,
        market_fresh=True,
        forecast_valid=True,
        risk_allowed=True,
        max_positions_ok=True,
        max_exposure_ok=True,
    )
    try:
        intent, order, state = service.execute(decision, dry_run=True)
        output = {
            "mode": service.mode.value,
            "state": state.value,
            "intent": intent.__dict__,
            "broker_called": order is not None,
            "rejection_reasons": [],
        }
    except ExecutionRejected as exc:
        output = {
            "mode": service.mode.value,
            "state": "REJECTED_PRE_EXECUTION",
            "intent": None,
            "broker_called": False,
            "rejection_reasons": list(exc.reasons),
        }
    print(json.dumps(output, default=str, indent=2))


if __name__ == "__main__":
    main()
