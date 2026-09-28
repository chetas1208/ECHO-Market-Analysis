"""Command entry point for reproducible forecasting training."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.forecasting.fixture import write_fixture
from app.forecasting.training import load_rows, train_bundle, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train/evaluate ECHO Day 6 forecast artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    fixture = subparsers.add_parser("fixture", help="write deterministic synthetic rows")
    fixture.add_argument("--output", type=Path, required=True)
    train = subparsers.add_parser("train", help="train a frozen forecast bundle")
    train.add_argument("--input", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--report", type=Path, required=True)
    train.add_argument("--backend", choices=("auto", "linear", "lightgbm"), default="auto")
    args = parser.parse_args()
    if args.command == "fixture":
        write_fixture(args.output)
        return
    rows = load_rows(args.input)
    backend = "auto" if args.backend == "auto" else args.backend
    report = train_bundle(rows, args.output, backend=backend)
    write_report(report, args.report)


if __name__ == "__main__":
    main()
