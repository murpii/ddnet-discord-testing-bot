# visualize_size (vendored)

This directory holds **third-party code**, not bot code. It renders a breakdown of
which embedded images and sounds make up a DDNet map's file size (the picture you
get from `/visualize-size`).

It lives in its own package on purpose: the implementation was written by **Patiga**,
 and `tw_map_v4.py` is machine-generated.

## Files

| File | What it is | Provenance |
| --- | --- | --- |
| `render.py` | The matplotlib renderer (`visualize_from_bytes`). | Patiga's original, lightly adapted (see below). MIT. |
| `tw_map_v4.py` | Parser for the Teeworlds/DDNet map v4 datafile format. | **Generated** by kaitai-struct-compiler from `map_v4.ksy`. Do not hand-edit. |
| `__init__.py` | Re-exports `visualize_from_bytes`. | Bot code. |

## Public API

```python
from extensions.map_testing.visualize_size import visualize_from_bytes

png_buffer = visualize_from_bytes(map_bytes)  # -> io.BytesIO (PNG)
```

`visualize_from_bytes` is **synchronous (it parses the map and draws
with matplotlib). The bot calls it through `MapVisualizer.visualize_size`, which runs
it via `asyncio.to_thread` so it never blocks the event loop.

The kaitai grammar doesn't understand every map variant, so it
can raise on some maps. Callers (`extensions/map_testing/commands.py`) catch that and
report a friendly failure instead of crashing the command.

## Attribution / sources

- **Renderer** (`render.py`) - original by Patiga, contributed via a PR to the DDNet
  testing bot:
  https://github.com/Patiga/ddnet-discordbot-dev/commit/144787d899bc2199016cb46589dd0797facf6741
  Licensed MIT.
- **Map format parser** (`tw_map_v4.py`) - generated from the `map_v4.ksy` Kaitai
  Struct definition in heinrich5991's libtw2:
  https://github.com/heinrich5991/libtw2/blob/master/doc/map_v4.ksy
  Datafile format reference:
  https://github.com/heinrich5991/libtw2/blob/master/doc/datafile.md

### Local changes to `render.py`

The renderer was adapted only where the bot's runtime required it; the size logic is
untouched:

- Switched from the global `pyplot` interface to the object-oriented `Figure` API so
  it is safe to run inside a worker thread (no shared global figure state).
- Forced the headless `Agg` backend.
- Drew the **sounds** pie chart, which the original allocated a subplot for but left
  blank.

## Regenerating the parser

`tw_map_v4.py` is generated, not written. To update it, edit/obtain the `.ksy` and run
the Kaitai Struct compiler for Python:

```sh
kaitai-struct-compiler -t python map_v4.ksy
```

Then drop the generated `tw_map_v4.py` in here. The Python runtime dependency is
`kaitaistruct` (already in `requirements.txt`).
