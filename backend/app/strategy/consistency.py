"""Consistency check between the frozen YAML and Conviction handoff artifacts."""

from __future__ import annotations

from pathlib import Path

from app.strategy.policy import StrategyConfig


def validate_conviction_consistency(
    config_path: Path, spec_path: Path, prompt_path: Path
) -> list[str]:
    config = StrategyConfig.from_yaml(config_path)
    text = f"{spec_path.read_text(encoding='utf-8')}\n{prompt_path.read_text(encoding='utf-8')}"
    expected = {
        "echo-rp-v1": "strategy_version",
        f"{config.min_probability:.2f}": "min_probability",
        f"{config.min_q50_abs:.3f}": "min_q50_abs",
        f"{config.stop_atr_multiple:.1f}": "stop_atr_multiple",
        f"{config.risk_per_trade * 100:.2f}%": "risk_per_trade",
        str(config.max_positions): "max_positions",
        config.hedge.value: "hedge",
    }
    return [label for token, label in expected.items() if token not in text]
