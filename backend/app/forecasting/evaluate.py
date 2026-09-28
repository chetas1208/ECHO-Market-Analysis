"""Frozen-artifact evaluation entry point.

The command intentionally does not retrain. It validates that the artifact and dataset
hash agree before evaluating the stored quantile models on the supplied rows.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.forecasting.engine import ForecastArtifactBundle
from app.forecasting.split import chronological_event_group_split, dataset_hash
from app.forecasting.training import load_rows, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate frozen ECHO forecast artifacts")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    rows = load_rows(args.input)
    bundle = ForecastArtifactBundle.load(args.artifact)
    if dataset_hash(rows) != bundle.dataset_hash:
        raise SystemExit("dataset hash does not match frozen artifact")
    split = chronological_event_group_split(rows)
    report = {
        "status": "complete" if split.test else "insufficient_test_data",
        "artifact": {
            "model_version": bundle.model_version,
            "artifact_hash": bundle.artifact_hash,
            "backend": bundle.backend,
        },
        "dataset": {"rows": len(rows), "dataset_hash": bundle.dataset_hash},
        "split": split.diagnostics,
        "test_rows": len(split.test),
        "retrained": False,
    }
    write_report(report, args.report)


if __name__ == "__main__":
    main()
