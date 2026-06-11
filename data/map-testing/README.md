# map-testing tooling

This directory is where the **external, prebuilt binaries** from the Teeworlds/DDNet
Rust ecosystem belong. They are **not shipped with this repository**, download them from the sources below and place them here. They are not
part of this project's source - the bot just shells out to them. They do the actual
heavy lifting (parsing, editing, checking and rendering maps); the bot's own code is
only a thin wrapper that feeds them a map file and reads the result back.

This file exists to record where they come from. It is not code.

## Binaries

| File | Used by | What it does |
| --- | --- | --- |
| `twmap-edit` | `MapEditor.edit` (`extensions/map_testing/utils/map_tools.py`) - the `/twmap-edit` command and the auto-optimize step | Applies edits to a map (shrink layers, remove unused assets, scale, etc.). |
| `twmap-check` | `MapChecker` (`extensions/map_testing/services/checker.py`) | Validates a map file. |
| `twmap-check-ddnet` | `MapChecker` (`extensions/map_testing/services/checker.py`) | DDNet-specific map checks. |
| `twgpu-map-photography` | `MapThumbnailer` (`utils/map_tools.py`) and the visual diffs (`extensions/map_testing/mapdiff/render.py`) | Renders a map to a PNG image. |
| `twmap-automapper` | (bundled, not currently invoked) | Runs automapper rules over a map. |
| `twmap-dilate` | (bundled, not currently invoked) | Dilates image edges to fix tile bleeding. |
| `twmap-extract-files` | (bundled, not currently invoked) | Extracts embedded images/sounds from a map. |
| `twmap-fix` | (bundled, not currently invoked) | Repairs common map issues. |

## Sources

- **`twmap-*`** - the `twmap-tools` suite from the **twmap** Rust library by Patiga, Zwelf /
  the ddnet-rs group:
  https://gitlab.com/ddnet-rs/twmap (tools live under `twmap-tools/`).
  This is the same library the bot uses in-process via the `twmap` Python bindings
  (see `extensions/map_testing/mapdiff/diff.py`).
- **`twgpu-map-photography`** - part of the `twgpu-tools` suite from the **twgpu**
  renderer, also by Patiga & Zwelf:
  https://gitlab.com/Patiga/twgpu (published as the `twgpu-tools` crate on crates.io).

## Notes

- These are **platform-specific** builds. On Windows they carry a `.exe` suffix; the
  bot appends the right extension at runtime via `utils.misc.check_os()`, so a Linux
  deployment needs the matching Linux builds dropped in here under the same base names
  (no `.exe`).
- The binaries are **not** committed to version control (see the repo `.gitignore`);
  download the appropriate release builds from the sources above and place them here.
- Other contents of this directory are runtime working data, not tooling:
  `tmp/` (scratch map files), `diffs/` (cached diff renders), `testlogs/` (archived
  test logs).
