"""ECHO-owned provider interface. Adapters normalize SDK objects to ``Bar`` at this boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from app.market.types import Bar, ProviderHealth, ProviderName


@runtime_checkable
class MarketDataProvider(Protocol):
    name: ProviderName

    async def connect(self) -> None:
        """Open the connection. Raises on failure (the supervisor handles retry/backoff)."""

    async def disconnect(self) -> None:
        """Close cleanly; idempotent."""

    async def subscribe(self, symbols: list[str]) -> None: ...

    async def unsubscribe(self, symbols: list[str]) -> None: ...

    def stream(self) -> AsyncIterator[Bar]:
        """Yield CLOSED 1m bars normalized to ``Bar``. Ends (StopAsyncIteration) on EOF/replay end;
        raises ConnectionError-family on link failure."""

    def health(self) -> ProviderHealth: ...
