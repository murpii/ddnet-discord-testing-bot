# DDNet Map Testing Bot

A Discord bot that runs the DDNet map-testing workflow: mappers submit `.map` files,
testers approve them, and each map gets its own channel that moves through testing states
(`TESTING -> RC -> READY -> RELEASED`, plus `WAITING` / `DECLINED`). Along the way the bot
runs automatic map checks, renders preview thumbnails and visual version-diffs, keeps a
per-channel changelog, tracks tester scores, and auto-marks maps `RELEASED` when DDNet
announces them.

**No database required.** Changelog history is stored as JSON files; the released-map
name check is done over HTTP against `ddnet.org`.

---

## Table of contents

1. [What you need](#1-what-you-need)
2. [Get the code and install dependencies](#2-get-the-code-and-install-dependencies)
3. [Create the Discord application (bot)](#3-create-the-discord-application-bot)
4. [Set up the Discord server](#4-set-up-the-discord-server)
5. [Configure the bot (`config.ini` + `constants.py`)](#5-configure-the-bot)
6. [Install the map tools (binaries)](#6-install-the-map-tools-binaries)
7. [Run it](#7-run-it)
8. [How the workflow looks in Discord](#8-how-the-workflow-looks-in-discord)
9. [DDNet-specific integrations](#9-ddnet-specific-integrations)

---

## 1. What you need

- **Python 3.11 or newer** (developed/tested on 3.13). 3.11 is the floor because the code
  uses `enum.StrEnum`.
- A **Discord account** with permission to create an application and a server (or admin on
  an existing one).
- The **twmap / twgpu CLI binaries** (see [section 6](#6-install-the-map-tools-binaries)) -
  used for map validation, rendering and editing. Without them, submissions can't be
  checked and previews/diffs won't render.
- **For rendering only** (thumbnails + visual diffs): a GPU, or a headless software
  rasterizer. No GPU? Set `RENDERING = false` and the bot runs fine without them
  (see [section 6](#6-install-the-map-tools-binaries)).
- Internet access (the bot calls `ddnet.org` for the released-map list).
- **Optional:** an upload endpoint, only if you want the bot to push tested maps to a live
  test server (see [section 9](#9-ddnet-specific-integrations)).
- **No database** and **no Rust toolchain** are needed to run the bot.

---

## 2. Get the code and install dependencies

```sh
git clone <this-repo> ddnet-testing-bot
cd ddnet-testing-bot

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

Notes:

- `twmap` and `pillow`/`numpy`/`matplotlib` are real dependencies (used for diffing and
  rendering). `pip` should fetch prebuilt wheels for `twmap`.
- `asyncmy` is listed only for the **one-time changelog migration script**
  (`scripts/migrate_changelogs_to_json.py`). A fresh install never touches a database, so
  if `asyncmy` fails to build on your machine you can ignore it.

---

## 3. Create the Discord application (bot)

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) ->
   **New Application**.
2. Open the **Bot** tab -> **Reset Token** and copy the token (you'll put it in
   `config.ini` as `TOKEN_DISCORD`). Keep it secret.
3. Still on the **Bot** tab, enable all three **Privileged Gateway Intents**:
   - **Presence Intent**
   - **Server Members Intent**
   - **Message Content Intent**

   The bot starts with `Intents.all()`, so all three must be on or it won't connect.
4. **Invite the bot.** Under **OAuth2 -> URL Generator**, tick the scopes `bot` and
   `applications.commands`. For a dedicated testing server the simplest choice is to grant
   **Administrator**. If you prefer granular permissions, the bot needs at least:
   *Manage Channels, Manage Roles, Manage Messages, Manage Threads, Create Public Threads,
   Send Messages, Send Messages in Threads, Embed Links, Attach Files, Add Reactions,
   Read Message History, View Channels, View Audit Log.*
   Open the generated URL and add the bot to your server.

---

## 4. Set up the Discord server

Turn on **Developer Mode** in Discord (User Settings -> Advanced) so you can right-click
any role/channel/category and **Copy ID** - you'll need these IDs in
[section 5](#5-configure-the-bot).

### Roles

Create these roles (names are up to you; the bot only cares about the IDs):

| Constant | Purpose |
| --- | --- |
| `ADMIN` | Full staff. |
| `MODERATOR`, `DISCORD_MODERATOR` | Staff (counted by `is_staff`). |
| `TESTER`, `TESTER_EXCL_TOURNAMENTS` | Full testers - can approve maps and cast the deciding ready vote. |
| `TRIAL_TESTER`, `TRIAL_TESTER_EXCL_TOURNAMENTS` | Trial testers - can vote, but two trials alone can't reach `READY`. |
| `TESTING` | Granted to people who should see/participate in testing channels. |

### Categories and channels

Create three **categories** to hold the per-map channels, plus a few standalone channels:

| Constant | Type | Purpose |
| --- | --- | --- |
| `CAT_TESTING` | category | Active maps (`TESTING` / `RC`). |
| `CAT_WAITING` | category | Maps waiting on the mapper. |
| `CAT_EVALUATED` | category | Finished maps (`READY` / `DECLINED` / `RELEASED`). |
| `TESTING_SUBMIT` | text channel | Where mappers post `.map` submissions (e.g. `#submit-maps`). |
| `TESTING_INFO` | text channel | Info/rules channel. |
| `TESTER_CHAT` | text channel | Testers' chat; the bot keeps a live scores summary in its topic. |
| `DBG` | text channel | The bot posts unexpected error tracebacks here. |

The bot treats **every text channel inside the three categories as a map channel** on
startup, so any non-map channels you place there (submit/info/chat) must be listed in
`EXCLUDE` (see `config.ini` below).

### Map-releases webhook (optional, for auto-release)

Auto-release listens for a webhook whose ID matches `Webhooks.DDNET_MAP_RELEASES`, posting
a message that contains a `[Map Name](https://ddnet.org/maps/?map=...)` link. On DDNet this
is their existing releases webhook. On your own server you only need this if you want maps
to flip to `RELEASED` automatically - otherwise testers use the **Set to Released** button.

---

## 5. Configure the bot

Two files hold your settings. Each ships with a **committed example** you copy and fill in;
the real files are git-ignored.

### Tokens and settings -> `config.ini`

```sh
cp config_example.ini config.ini
```

Set `TOKEN_DISCORD` to your bot token. The `[DDNET]` endpoints are only needed to push maps
to a test server, and `[DATABASE]` is read only by the migration script - both can stay at
their defaults otherwise. Under `[TESTING_CHANNELS]`, set `RENDERING = false` on a host
without a GPU and list any non-map channels in the testing categories (submit/info/chat) in
`EXCLUDE`. Every option is commented in the example file.

### Discord IDs -> `constants.py`

```sh
cp constants_ddnet.py constants.py
```

`constants_ddnet.py` is the example (it carries DDNet's own IDs). Replace every value with
your server's - the guild, the categories/channels and roles from section 4, and the
map-releases webhook (leave it `0` to keep auto-release off).

---

## 6. Install the map tools (binaries)

The bot shells out to prebuilt CLI tools that live in `data/map-testing/`. They are **not**
committed (they're git-ignored), so download them for your OS and drop them in:

| File | From | Used for |
| --- | --- | --- |
| `twmap-edit` | [ddnet-rs/twmap](https://gitlab.com/ddnet-rs/twmap) (`twmap-tools`) | `/twmap-edit`, auto-optimize |
| `twmap-check` | same | map validation |
| `twmap-check-ddnet` | same | DDNet-specific checks |
| `twgpu-map-photography` | [Patiga/twgpu](https://gitlab.com/Patiga/twgpu) (`twgpu-tools`) | thumbnails + visual diffs |

On **Windows** they must end in `.exe` (`twmap-edit.exe`, ...). On **Linux/macOS** use the
matching native builds with **no extension**. The bot appends the right suffix at runtime.
See `data/map-testing/README.md` for details.

If these are missing, the bot still starts, but submission checks and image rendering will
fail.

### Rendering needs a GPU (or a software rasterizer)

`twgpu-map-photography` renders via the GPU, so thumbnails and visual diffs need either a
real GPU or a headless software rasterizer (on Linux, Mesa's `llvmpipe`/`lavapipe`, possibly
with `LIBGL_ALWAYS_SOFTWARE=1`). If you can provide neither, set `RENDERING = false` under
`[TESTING_CHANNELS]` in `config.ini`: the bot then skips thumbnails and the "View Visual
Diff" button, while the **text** diff summary, map checks, and everything else keep working.

---

## 7. Run it

From the repo root, with the virtualenv active:

```sh
python bot.py
```

On first start the bot:

- loads its extensions and connects,
- registers slash commands globally and for your guild (this can take a moment; guild
  commands appear almost immediately),
- scans the three testing categories and loads any existing map channels,
- creates runtime folders as needed (`logs/`, `data/map-testing/changelogs/`,
  `data/map-testing/diffs/`).

If `data/map-testing/tmp/` doesn't exist, create it (`mkdir -p data/map-testing/tmp`) -
it's used as scratch space for the map tools.

Logs are written to `logs/bot.log` and `logs/map_testing.log` (and to the console).

---

## 8. How the workflow looks in Discord

1. A mapper posts a `.map` in **`#submit-maps`** with a title like
   `"Map Name" by Mapper [Server]`.
2. The bot validates the name + runs map checks and replies with **Approve / Decline**
   buttons (testers only).
3. On **Approve**, the bot creates a map channel under `CAT_TESTING`, pins the map, posts a
   thumbnail + an info card + a tester-control thread (changelog, checklist, control
   buttons).
4. Testers use the control buttons to move the map through states. The **Ready** vote needs
   two distinct votes including one full Tester. New uploads from the author auto-update the
   current map and post a **"Changes vs previous version"** thread (summary + on-demand
   visual diff).
5. When the map's release is announced (or a tester hits **Set to Released**), the channel
   moves to `RELEASED` with a 2-week grace notice.

Slash commands: `/visualize-size` (map file-size breakdown) and `/twmap-edit` (run
`twmap-edit` on the current map). See `extensions/map_testing/STATES.md` for the full state
machine.

---

## 9. DDNet-specific integrations

This bot was built for DDNet, so a few features assume DDNet's infrastructure. The core
Discord workflow (submit -> approve -> states -> diffs -> changelog -> scores) works on any
server, but these are DDNet-tied:

- **Map upload to a test server** (`[DDNET]` `UPLOAD`/`DELETE`/`TOKEN`): pushes the current
  map to a live DDNet test server so testers can play it. Without valid endpoints, uploads
  just log an error and the rest keeps working.
- **Released-name check** (`URLs.DDNET_RELEASES_MAPS`): rejects submissions whose name
  already exists in DDNet's released-maps list (`ddnet.org/releases/maps.json`). Harmless to
  keep on your own server; it only blocks names already taken by released DDNet maps.
- **Auto-release** (`Webhooks.DDNET_MAP_RELEASES`): driven by DDNet's release-announcement
  webhook. Set the ID to your own release webhook, or leave it `0` and use the manual
  button.

### Optional: migrating changelogs from an old database

If you're upgrading from an older, database-backed instance of this bot, run the one-time
export once while the old MariaDB is still reachable (it reads `[DATABASE]` from
`config.ini`):

```sh
python scripts/migrate_changelogs_to_json.py
```

Fresh installs don't need this. See `scripts/README.md`.
