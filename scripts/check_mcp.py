#!/usr/bin/env python3
"""Inspect MCP configuration without exposing credentials."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.execution.settings import ExecutionSettings
from app.world.settings import WorldSettings
from pydantic import ValidationError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="reserved for an authenticated read-only probe")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings()
        world = WorldSettings()
        execution = ExecutionSettings()
    except (ValidationError, ValueError) as exc:
        print(f"MCP: ERROR ({type(exc).__name__})")
        return 1

    failures = 0
    if settings.worldmonitor_mcp_enabled:
        if world.world_monitor_configured:
            print(f"World Monitor MCP: CONFIGURED transport={settings.worldmonitor_mcp_transport}")
        else:
            print("World Monitor MCP: UNCONFIGURED (credential missing)")
            failures += 1
    else:
        print("World Monitor MCP: DISABLED")

    if settings.alpaca_mcp_enabled:
        if execution.configured and execution.alpaca_paper:
            print("Alpaca MCP: CONFIGURED (paper guard is enforced by execution settings)")
        else:
            print("Alpaca MCP: UNCONFIGURED (paper credentials or paper flag missing)")
            failures += 1
    else:
        print("Alpaca MCP: DISABLED")

    if args.live:
        if settings.worldmonitor_mcp_enabled and world.world_monitor_configured:
            request = urllib.request.Request(
                settings.worldmonitor_mcp_url,
                data=json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
                ).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "User-Agent": "ECHO/0.2 (+read-only-config-check)",
                    "X-WorldMonitor-Key": world.world_monitor_api_key.get_secret_value(),
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read())
                if "error" in payload:
                    raise ValueError("JSON-RPC discovery returned an error")
                print("World Monitor MCP live probe: OK")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                print(f"World Monitor MCP live probe: ERROR ({type(exc).__name__})")
                failures += 1
        else:
            print("MCP live probe: NOT RUN (no authenticated World Monitor MCP is enabled)")
            if settings.worldmonitor_mcp_enabled:
                failures += 1
    return 1 if args.strict and failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
