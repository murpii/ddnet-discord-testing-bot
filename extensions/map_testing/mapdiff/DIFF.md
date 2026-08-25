# `diff.py` - structural map diff

This module compares two versions of a map and reports what changed. It powers the
"Changes vs previous version" message the bot posts when a new map is uploaded.

It produces two things.

1. A **markdown summary** (`MapDiffResult.summary_markdown()`), a readable list of
   changed layers, images and info fields.
2. **Change masks**, boolean grids marking exactly which tiles changed, which the
   renderer (`render.py`) uses to tint the visual diff image.

Nothing here touches Discord or the disk, it is pure computation. The renderer and the
caching live in sibling files (`render.py`, `cache.py`, `discord_ui.py`).

---

## How a map is structured

The `twmap` library parses a `.map` file into objects. These are the parts we care about.

- A map has a list of **groups**. Each group has a list of **layers**.
- A **tile layer** holds a grid of tiles as a NumPy array of shape
  `(height, width, components)`. Think of it as a 2D grid where each cell holds a few
  small numbers ("components"). **Component 0 is the tile id**, where `0` means an empty
  cell and any other value means a placed tile.
- The **game layer** is the special physics layer, and its width/height is the map's size.
- There are also **quad layers** (free-form shapes, not a grid), **sound layers**, plus
  embedded **images** and **info** fields (author, version, ...).

We locate a layer by its position `(group_index, layer_index)`. Comparing the same
position in the old and new map tells us whether that slot was added, removed, swapped
for a different layer, or edited in place.

## Change masks

For the cell-level diff we keep three boolean grids, each the same size as the game
layer.

- `mask_added` marks cells that went from empty to filled.
- `mask_removed` marks cells that went from filled to empty.
- `mask_modified` marks cells that changed but stayed filled.

Tile layers are accumulated into **two** separate sets of these grids, physics and design
(`ChangeMasks`), and only one set ends up on the result.

- If any physics layer changed, the physics grids win and the design ones are discarded.
- Only if nothing physical changed do the design grids get used.

This is deliberate. A retexture rewrites design tiles across the whole map, and merging
those in would flood `change_clusters()` into a single map-sized region, hiding the
gameplay edit the testers need to look at. Discarded design changes are still reported in
the markdown summary, they don't steer the camera.

The renderer then paints the chosen set in one pass (added = green, removed = red,
modified = turquoise).

---

## The data classes

### `LayerChange`

One record describing how a single tile layer changed. It holds the layer's position
(`group`, `index`), its `kind` and `name`, the counts (`added` / `removed` / `modified`
tiles), an optional `bbox` (the changed region) and an optional `note` used instead of
counts, for example on a resize. It also carries these helpers.

- `total` adds up added + removed + modified.
- `is_physics` says whether it's a gameplay layer (`Game`, `Front`, `Tele`, `Switch`,
  `Speedup`, `Tune`). Everything else counts as design.
- `label()` builds the display name. Unnamed design layers get a `(g0/l1)` suffix so they
  can be told apart.

### `MapDiffResult`

The full result. It collects everything the diff found.

| Field | Meaning |
| --- | --- |
| `layer_changes` | per-layer edit records (`LayerChange`) |
| `added_layers` / `removed_layers` | whole layers added/removed (text labels) |
| `quad_changes` | `(label, delta)` - how many quads were added/removed per quad layer |
| `added_images` / `removed_images` | embedded image names added/removed |
| `info_changes` | changed info fields (author/version/credits/license) |
| `dimension_change` | text if the map was resized |
| `width` / `height` | the **new** map's size, so the renderer knows how to frame it |
| `error` | set if a map couldn't be parsed (the diff then reports just this) |
| `mask_added` / `mask_removed` / `mask_modified` | the change masks described above |

`MapDiffResult` also carries these methods.

- `has_changes` says whether anything changed at all.
- `union_mask()` ORs the three masks into a single "something changed here" grid.
- `change_clusters(...)` splits the changed cells into separate regions (see below).
- `summary_markdown()` builds the message text.

---

## The diff algorithm in `MapDiff.diff_bytes`

`MapDiff.diff(old, new)` is the async entry point used by the bot. It reads both map
files and runs `diff_bytes` in a worker thread, because parsing and NumPy are CPU work
that shouldn't block the event loop. `diff_bytes` is the pure, synchronous core.

1. **Parse both maps.** If either fails to parse, set `result.error` and return early.
2. **Prepare the combined masks** sized to the new map's game layer, or `None` if there
   is no game layer, in which case we can't build pixel-accurate masks.
3. **Index every layer by `(group, layer)` position** in both maps.
4. **Walk every position** present in either map and classify it.
   - present only in the new map -> a layer was **added**.
   - present only in the old map -> a layer was **removed**.
   - different `kind` at that slot -> treat as **remove + add**.
   - `Quads` -> record the change in quad count.
   - `Sounds` -> ignored (nothing visual).
   - otherwise a **tile layer** -> diff its grid (`diff_tile_layer`) and OR the result
     into the combined masks.
5. **Attach each combined mask** to the result only if it actually marks something.
6. **Diff the map-level stuff** (`diff_map_level`), meaning images, info fields and
   dimensions.

### `diff_tile_layer`

Compares one tile layer's grid against its previous version and returns three boolean
grids `(added, removed, modified)`, or `(None, None, None)` when there's nothing to
compare.

- If the layer has no `tiles`, bail.
- If the grid was **resized**, you can't compare cell-by-cell, so record a "resized
  WxH -> WxH" note and bail.
- `changed` = cells where **any** component differs.
- Classify each changed cell by its tile id (component 0). empty->filled is **added**,
  filled->empty is **removed**, the rest is **modified**.
- Record a `LayerChange` with the counts and the changed-region bounding box.

### `diff_map_level`

Diffs the things that aren't layers.

- **Images.** Compare the sets of embedded image names.
- **Info.** Compare `author`, `version`, `credits`, `license`.
- **Dimensions.** Record `width`/`height` of the new map, and a `dimension_change` string
  if the game-layer size differs.

---

## Clustering changed cells with `change_clusters`

A map edit can touch several far-apart spots. We don't want one giant bounding box
spanning the whole map (it would render as a tiny, useless overview). So we split the
changed cells into **clusters** of nearby edits, each rendered as its own focused image.

The algorithm is a connected-components flood fill on a coarse grid.

1. **`occupied_bins`** lays a coarse grid over the map, one cell per `bin_size` x
   `bin_size` block (20x20 tiles by default). It marks a bin as occupied if it contains
   any changed tile. This shrinks the problem and lets nearby edits share a bin.
2. **`connected_bin_groups`** groups occupied bins that touch into connected sets, using
   a breadth-first flood fill. Two bins belong to the same group if they're neighbours,
   horizontally, vertically **or diagonally** (the 8 surrounding bins). Each group is one
   cluster of nearby edits.
3. **`cells_in_bins`** turns each group of bins back into the actual changed cells inside
   it, and computes that cluster's bounding box and size.

The clusters are sorted largest-first, and the biggest `max_clusters` are returned. Each
returned cluster is `(added_mask, removed_mask, modified_mask, bbox)`, the three change
kinds restricted to that cluster plus its box, which is exactly what the renderer needs
to frame and colour one image. `change_clusters` also returns the **total** number of
clusters found, so the UI can say "showing 4 of 9 areas".

---

## Building the summary in `summary_markdown`

Produces the message text.

- Shows a "Map resized" line if the dimensions changed.
- Lists changed layers, **physics (gameplay) layers first**, then design layers, each
  sorted biggest-change-first. It caps the list at `MAX_LAYER_LINES` and adds a
  "...and N more" line if there are more.
- Adds lines for quad changes, added/removed layers, added/removed images and info
  changes.

`format_layer` formats one layer line (either its `note`, or `total tiles (+a / -b / ~c)`)
and `layer_desc` makes the short `g2 Tiles "front"` labels for the added/removed lists.

---

## Who uses this

- `render.py` -> `render_diff_images` calls `change_clusters` and uses `width`/`height`
  to frame each cluster, then tints the masks onto the rendered image.
- `manager.py` -> `post_version_diff` calls `MapDiff.diff` and posts
  `summary_markdown()` (with the on-demand visual-diff button) when `has_changes` is true.
