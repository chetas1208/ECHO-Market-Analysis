#!/usr/bin/env python3
"""Validate the paper execution profile without placing an order."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.execution.settings import ExecutionSettings
from pydantic import ValidationError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    try:
        settings = ExecutionSettings()
    except (ValidationError, ValueError) as exc:
        print(f"Alpaca paper: ERROR ({type(exc).__name__})")
        return 1
    ready = (
        settings.execution_mode == "PAPER"
        and settings.alpaca_paper
        and settings.configured
        and not settings.execution_kill_switch
    )
    state = "READY" if ready else "NOT_READY"
    print(f"Alpaca paper: {state} mode={settings.execution_mode} configured={'yes' if settings.configured else 'no'}")
    return 0 if ready or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
