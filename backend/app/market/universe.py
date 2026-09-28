"""Market universe: single source of truth for tracked symbols (config/universe.yaml)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ValidationError, field_validator

from app.market.settings import UNIVERSE_PATH

Role = Literal["equity", "benchmark"]


class UniverseError(ValueError):
    """Raised when the universe configuration is invalid."""


class UniverseEntry(BaseModel):
    symbol: str
    group: str
    role: Role
    sector_benchmark: str | None = None

    @field_validator("symbol", "sector_benchmark")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper()
        if not v:
            raise ValueError("symbol must be non-empty")
        return v


class Universe:
    def __init__(
        self,
        entries: list[UniverseEntry],
        market_benchmark: str,
        default_sector_benchmark: str | None = None,
    ) -> None:
        self.entries = list(entries)
        self.market_benchmark = market_benchmark.strip().upper()
        self.default_sector_benchmark = (
            (default_sector_benchmark or self.market_benchmark).strip().upper()
        )
        self._by_symbol = {e.symbol: e for e in self.entries}
        self._validate()

    def _validate(self) -> None:
        if len(self._by_symbol) != len(self.entries):
            seen: set[str] = set()
            dupes = sorted(
                {e.symbol for e in self.entries if e.symbol in seen or seen.add(e.symbol)}
            )
            raise UniverseError(f"duplicate symbols: {dupes}")
        benches = set(self.benchmarks())
        if self.market_benchmark not in benches:
            raise UniverseError(
                f"market_benchmark {self.market_benchmark} is not a benchmark entry"
            )
        if self.default_sector_benchmark not in benches:
            raise UniverseError(
                f"default_sector_benchmark {self.default_sector_benchmark} is not a benchmark entry"
            )
        for e in self.entries:
            if e.sector_benchmark is not None and e.sector_benchmark not in benches:
                raise UniverseError(
                    f"{e.symbol}: sector_benchmark {e.sector_benchmark} "
                    "does not exist with role benchmark"
                )

    def symbols(self) -> list[str]:
        return [e.symbol for e in self.entries]

    def equities(self) -> list[str]:
        return [e.symbol for e in self.entries if e.role == "equity"]

    def benchmarks(self) -> list[str]:
        return [e.symbol for e in self.entries if e.role == "benchmark"]

    def entry(self, symbol: str) -> UniverseEntry | None:
        return self._by_symbol.get(symbol.upper())

    def sector_benchmark_for(self, symbol: str) -> str:
        e = self.entry(symbol)
        if e is not None and e.sector_benchmark:
            return e.sector_benchmark
        return self.default_sector_benchmark

    def group_of(self, symbol: str) -> str | None:
        e = self.entry(symbol)
        return e.group if e is not None else None


def load_universe(path: Path = UNIVERSE_PATH) -> Universe:
    try:
        raw: Any = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise UniverseError(f"invalid universe yaml: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("symbols"), list):
        raise UniverseError("universe yaml must be a mapping with a 'symbols' list")
    if not raw.get("market_benchmark"):
        raise UniverseError("universe yaml missing 'market_benchmark'")
    try:
        entries = [UniverseEntry.model_validate(item) for item in raw["symbols"]]
    except ValidationError as exc:
        raise UniverseError(f"invalid universe entry: {exc}") from exc
    return Universe(
        entries,
        market_benchmark=str(raw["market_benchmark"]),
        default_sector_benchmark=raw.get("default_sector_benchmark"),
    )


@lru_cache(maxsize=1)
def get_universe() -> Universe:
    return load_universe()
