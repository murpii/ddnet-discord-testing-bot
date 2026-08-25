import asyncio
import logging
from datetime import datetime, timedelta, timezone

from constants import URLs

log = logging.getLogger("mt")

REFRESH_TTL = timedelta(hours=6)


class ReleasedMapsUnavailable(RuntimeError):
    """The released map list couldn't be fetched and nothing is cached."""


class ReleasedMaps:
    def __init__(self, bot, *, url: str = URLs.DDNET_RELEASES_MAPS, ttl: timedelta = REFRESH_TTL):
        self.bot = bot
        self.url = url
        self.ttl = ttl
        self.names: set[str] | None = None
        self.fetched_at: datetime | None = None
        self.lock = asyncio.Lock()

    def _fresh(self) -> bool:
        return (
                self.names is not None
                and self.fetched_at is not None
                and datetime.now(timezone.utc) - self.fetched_at < self.ttl
        )

    async def _refresh(self) -> None:
        async with self.bot.session.get(self.url) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)

        names = {entry["name"].lower() for entry in data if entry.get("name")}
        if not names:
            raise ValueError("released-maps response contained no names")

        self.names = names
        self.fetched_at = datetime.now(timezone.utc)
        log.info("Loaded %d released map names from %s", len(names), self.url)

    async def ensure_loaded(self) -> None:
        if self._fresh():
            return
        async with self.lock:
            # re-check inside the lock. Another caller may have just refreshed.
            if self._fresh():
                return
            try:
                await self._refresh()
            except Exception as exc:
                if self.names is None:
                    # unreachable -> caller must fail closed
                    raise ReleasedMapsUnavailable(str(exc)) from exc
                log.warning("Released-maps refresh failed; using cached list: %s", exc)

    async def is_released(self, name: str) -> bool:
        """True if ``name`` matches an already-released map."""
        await self.ensure_loaded()
        return name.lower() in self.names
