"""One-command deterministic Day 8 smoke replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.backtesting.artifacts import verify_artifacts, write_artifacts
from app.backtesting.datasets import fixture_cases
from app.backtesting.engine import BacktestEngine
from app.backtesting.research import report_dict, run_research
from app.strategy.policy import StrategyConfig


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("final", "verify", "research"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    cases = fixture_cases()
    strategy = StrategyConfig()
    if args.command in {"final", "verify"}:
        result = BacktestEngine(strategy).run(cases, split="TEST")
        artifact_root = root / "artifacts" / "backtests"
        if args.command == "verify":
            verified, differences = verify_artifacts(result, artifact_root)
            print(
                json.dumps(
                    {"run_id": result.run_id, "verified": verified, "differences": differences},
                    indent=2,
                )
            )
            if not verified:
                raise SystemExit(1)
            return
        target = write_artifacts(result, artifact_root)
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "artifact_path": str(target),
                    "metrics": result.metrics.as_dict(),
                },
                indent=2,
                default=str,
            )
        )
    else:
        print(json.dumps(report_dict(run_research(cases, strategy)), indent=2, default=str))


if __name__ == "__main__":
    main()
