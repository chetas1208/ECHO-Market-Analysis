#!/usr/bin/env python3
"""Validate configured AURE paths and run its verified read-only integrity check."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from pydantic import ValidationError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings()
    except (ValidationError, ValueError) as exc:
        print(f"AURE: ERROR ({type(exc).__name__})")
        return 1
    if not settings.aure_enabled:
        print("AURE: UNCONFIGURED (AURE_ENABLED=false)")
        return 1 if args.strict and settings.graph_backend == "aure" else 0

    binary = settings.aure_binary or (Path(shutil.which("aure")) if shutil.which("aure") else None)
    if binary is None or not binary.is_file() or not binary.stat().st_mode & 0o111:
        print("AURE: UNCONFIGURED (executable not found)")
        return 1 if args.strict else 0
    if settings.aure_database_path is None:
        print("AURE: UNCONFIGURED (AURE_DATABASE_PATH missing)")
        return 1 if args.strict else 0
    if not settings.aure_database_path.exists():
        print("AURE: ERROR (database path does not exist)")
        return 1

    try:
        result = subprocess.run(
            [str(binary), "db", "check", str(settings.aure_database_path), "--output", "json"],
            capture_output=True,
            text=True,
            timeout=settings.aure_query_timeout_seconds,
            check=False,
        )
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
        status = payload.get("status", "ERROR")
        print(f"AURE: {'OK' if result.returncode == 0 and status == 'CLEAN' else 'ERROR'}")
        return 0 if result.returncode == 0 and status == "CLEAN" else 1
    except subprocess.TimeoutExpired:
        print("AURE: ERROR (integrity check timed out)")
        return 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"AURE: ERROR ({type(exc).__name__})")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
