from __future__ import annotations

from pathlib import Path

import pytest

from app.market.universe import Universe, UniverseError, get_universe, load_universe

HEADER = "market_benchmark: SPY\ndefault_sector_benchmark: SPY\nsymbols:\n"
SPY = "  - {symbol: SPY, group: benchmark, role: benchmark}\n"
SOXX = "  - {symbol: SOXX, group: benchmark, role: benchmark}\n"


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "u.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_real_yaml_loads() -> None:
    u = load_universe()
    assert len(u.equities()) >= 25
    assert len(u.benchmarks()) == 6
    assert set(u.symbols()) == set(u.equities()) | set(u.benchmarks())
    assert u.market_benchmark == "SPY"
    assert u.sector_benchmark_for("NVDA") == "SOXX"
    assert u.sector_benchmark_for("XOM") == "XLE"
    assert u.sector_benchmark_for("JPM") == "XLF"
    assert u.sector_benchmark_for("DAL") == "XLI"
    assert u.group_of("NVDA") == "semiconductors"
    assert u.group_of("NOPE") is None


def test_get_universe_cached() -> None:
    assert get_universe() is get_universe()
    assert isinstance(get_universe(), Universe)


def test_fallback_to_default_sector_benchmark(tmp_path: Path) -> None:
    body = HEADER + SPY + "  - {symbol: ABC, group: misc, role: equity}\n"
    u = load_universe(_write(tmp_path, body))
    assert u.sector_benchmark_for("ABC") == "SPY"
    assert u.sector_benchmark_for("UNKNOWN") == "SPY"


def test_duplicate_symbol(tmp_path: Path) -> None:
    body = HEADER + SPY + SPY
    with pytest.raises(UniverseError, match="duplicate"):
        load_universe(_write(tmp_path, body))


def test_missing_benchmark(tmp_path: Path) -> None:
    body = HEADER + SPY + "  - {symbol: ABC, group: g, role: equity, sector_benchmark: SOXX}\n"
    with pytest.raises(UniverseError, match="SOXX"):
        load_universe(_write(tmp_path, body))


def test_sector_benchmark_must_have_benchmark_role(tmp_path: Path) -> None:
    body = (
        HEADER
        + SPY
        + "  - {symbol: XYZ, group: g, role: equity}\n"
        + "  - {symbol: ABC, group: g, role: equity, sector_benchmark: XYZ}\n"
    )
    with pytest.raises(UniverseError, match="XYZ"):
        load_universe(_write(tmp_path, body))


def test_missing_market_benchmark(tmp_path: Path) -> None:
    body = HEADER + SOXX
    with pytest.raises(UniverseError, match="market_benchmark"):
        load_universe(_write(tmp_path, body))


def test_bad_role(tmp_path: Path) -> None:
    body = HEADER + SPY + "  - {symbol: ABC, group: g, role: futures}\n"
    with pytest.raises(UniverseError, match="invalid universe entry"):
        load_universe(_write(tmp_path, body))


def test_bad_structure(tmp_path: Path) -> None:
    with pytest.raises(UniverseError):
        load_universe(_write(tmp_path, "- just\n- a list\n"))
