"""ECHO-owned world-event provider interface. Adapters convert payloads to RawWorldEvent."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.world.types import RawWorldEvent, WorldProviderHealth, WorldProviderName


@runtime_checkable
class WorldEventProvider(Protocol):
    name: WorldProviderName

    async def connect(self) -> None:
        """Prepare the provider. Raises on failure; must not raise when merely unconfigured
        unless documented (callers check health().state first)."""

    async def disconnect(self) -> None: ...

    async def fetch_recent(self, since: datetime | None = None) -> list[RawWorldEvent]:
        """One poll. Malformed upstream items are skipped and counted, never raised."""

    def stream(self) -> AsyncIterator[RawWorldEvent]:
        """Poll loop yielding RawWorldEvents (honoring poll interval / Retry-After). Ends on
        replay exhaustion or disconnect(); provider errors are absorbed into health()."""

    def health(self) -> WorldProviderHealth: ...
