import asyncio
import json
import sys
from configparser import ConfigParser
from datetime import timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import asyncmy  # noqa: E402
from utils.changelog_store import CHANGELOG_DIR  # noqa: E402

OUTPUT_DIR = REPO_ROOT / CHANGELOG_DIR

QUERY = (
    "SELECT timestamp, channel_name, channel_id, invoked_by, type, action "
    "FROM discordbot_testing_channel_history;"
)


def iso(ts) -> str:
    if ts is None:
        return ""
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


async def main() -> int:
    config = ConfigParser()
    config.read(REPO_ROOT / "config.ini")

    if not config.has_section("DATABASE"):
        print("No [DATABASE] section in config.ini - nothing to migrate from.")
        return 1

    db = config["DATABASE"]
    pool = await asyncmy.create_pool(
        user=db["MARIADB_USER"],
        password=db["MARIADB_PASSWORD"],
        db=db["MARIADB_DB"],
        host=db["MARIADB_HOST"],
        port=int(db["MARIADB_PORT"]),
    )

    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(QUERY)
                rows = await cur.fetchall()
    finally:
        pool.close()
        await pool.wait_closed()

    # Group rows by channel, preserving the columns the store expects.
    by_channel: dict[int, list[dict]] = {}
    for timestamp, channel_name, channel_id, invoked_by, type_, action in rows:
        by_channel.setdefault(channel_id, []).append({
            "timestamp": iso(timestamp),
            "channel_name": channel_name,
            "channel_id": channel_id,
            "invoked_by": invoked_by,
            "type": type_,
            "action": action,
        })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for channel_id, entries in by_channel.items():
        path = OUTPUT_DIR / f"{channel_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    print(
        f"Migrated {len(rows)} changelog entries across {len(by_channel)} channels "
        f"into {OUTPUT_DIR}/"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
