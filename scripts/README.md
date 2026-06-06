# scripts/

One-off maintenance and migration scripts. These are **not** part of the running
bot - nothing imports them. You run them by hand, usually once.

## `migrate_changelogs_to_json.py`

**What it does:** exports every row of the MariaDB `discordbot_testing_channel_history`
table into the bot's file-backed changelog store
(`data/map-testing/changelogs/<channel_id>.json`, one file per testing channel).

**Why it exists:** the bot was moved off MariaDB so it can run without a database.
Changelog history was the one thing that genuinely needed persistence, so it now
lives in JSON files instead of the DB. This script is the one-time bridge that
carries the existing history across, so in-flight testing channels keep their past
changelog entries after the cutover. Without it, changelogs would simply start empty
from the switch-over.

**When to run:** once, at cutover, while the old database is still reachable. It
reads DB credentials from `config.ini` ([DATABASE] section) and needs `asyncmy`
installed. It is idempotent - re-running just overwrites the JSON files from the
current DB contents. The output path is anchored to the repo root, so it doesn't
matter what directory you launch it from:

```sh
python scripts/migrate_changelogs_to_json.py
```

**After it's done:** the `[DATABASE]` config section and the `asyncmy` dependency are
only kept around for this script. Once you've migrated and don't plan to re-run it,
both can be removed.
