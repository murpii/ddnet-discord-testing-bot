import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("mt")
CHANGELOG_DIR = Path("data/map-testing/changelogs")
_lock = asyncio.Lock()


def channel_path(channel_id: int) -> Path:
    return CHANGELOG_DIR / f"{channel_id}.json"


def read(channel_id: int) -> list[dict]:
    try:
        with open(channel_path(channel_id), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def write(channel_id: int, rows: list[dict]) -> None:
    CHANGELOG_DIR.mkdir(parents=True, exist_ok=True)
    path = channel_path(channel_id)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def entry(d: dict) -> tuple:
    """Convert a stored dict into the 6-tuple ChangelogPaginator expects."""
    raw = d.get("timestamp")
    try:
        ts = datetime.fromisoformat(raw) if raw else datetime.now(timezone.utc)
    except ValueError:
        ts = datetime.now(timezone.utc)
    # Normalize to aware UTC so mixed (migrated-naive vs new-aware) timestamps stay
    # comparable when the paginator sorts by timestamp.
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (
        ts,
        d.get("channel_name", ""),
        d.get("channel_id"),
        d.get("invoked_by", ""),
        d.get("type", ""),
        d.get("action", ""),
    )


def add(channel_id: int, entry: dict) -> None:
    rows = read(channel_id)
    rows.append(entry)
    write(channel_id, rows)


def delete(channel_id: int) -> None:
    try:
        channel_path(channel_id).unlink()
    except FileNotFoundError:
        pass


async def read_entries(channel_id: int) -> list[tuple]:
    """Return this channel's changelog entries as paginator tuples."""
    rows = await asyncio.to_thread(read, channel_id)
    return [entry(r) for r in rows]


async def add_entry(
    channel_id: int,
    channel_name: str,
    invoked_by: str,
    type_: str | None,
    action: str | None,
    *,
    timestamp: datetime | None = None,
) -> None:
    """Append one changelog entry for ``channel_id``."""
    entry = {
        "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
        "channel_name": channel_name,
        "channel_id": channel_id,
        "invoked_by": invoked_by,
        "type": type_,
        "action": action,
    }
    async with _lock:
        await asyncio.to_thread(add, channel_id, entry)


async def delete_channel(channel_id: int) -> None:
    """Drop a channel's changelog file (called when the channel is deleted)."""
    async with _lock:
        await asyncio.to_thread(delete, channel_id)
