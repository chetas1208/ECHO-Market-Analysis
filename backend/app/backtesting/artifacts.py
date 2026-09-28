"""Independent, immutable-once-created backtest artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.backtesting.engine import BacktestResult


def artifact_contents(result: BacktestResult) -> dict[str, str]:
    """Render every immutable artifact in memory for writing or reproducibility checks."""
    return {
        "config.json": json.dumps(
            {
                "strategy_version": result.strategy_version,
                "config_hash": result.config_hash,
                "parameters": result.strategy_config,
            },
            indent=2,
        )
        + "\n",
        "metrics.json": json.dumps(result.metrics.as_dict(), indent=2, default=str) + "\n",
        "equity.csv": _csv(result.equity),
        "drawdown.csv": _csv(
            {"timestamp": row["timestamp"], "drawdown": row["drawdown"]} for row in result.equity
        ),
        "trades.csv": _csv(trade.as_dict() for trade in result.trades),
        "report.md": (
            f"# ECHO historical replay {result.run_id}\n\n"
            f"Mode: HISTORICAL REPLAY\n\nSplit: {result.split}\n\n"
            f"Dataset hash: `{result.dataset_hash}`\n\n"
            f"Metrics status: `{result.metrics.status}`\n\n"
            f"```json\n{json.dumps(result.metrics.as_dict(), indent=2, default=str)}\n```\n"
        ),
        "metadata.json": json.dumps(result.metadata, indent=2, default=str) + "\n",
    }


def write_artifacts(result: BacktestResult, root: Path) -> Path:
    target = root / result.run_id
    if target.exists():
        raise FileExistsError(f"backtest artifact already exists: {target}")
    target.mkdir(parents=True)
    for name, content in artifact_contents(result).items():
        (target / name).write_text(content, encoding="utf-8")
    return target


def verify_artifacts(result: BacktestResult, root: Path) -> tuple[bool, list[str]]:
    """Compare a deterministic replay against an existing immutable artifact directory."""
    target = root / result.run_id
    expected = artifact_contents(result)
    missing = [name for name in expected if not (target / name).is_file()]
    mismatched = [
        name for name, content in expected.items()
        if name not in missing and (target / name).read_text(encoding="utf-8") != content
    ]
    return not missing and not mismatched, [f"missing:{name}" for name in missing] + [
        f"mismatch:{name}" for name in mismatched
    ]


def _csv(rows) -> str:
    rows = list(rows)
    if not rows:
        return "\n"
    keys = sorted({key for row in rows for key in row})
    import io

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=keys, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
