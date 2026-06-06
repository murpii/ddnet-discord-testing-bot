import asyncio
import logging
import uuid
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from utils.misc import run_process_exec, check_os

log = logging.getLogger("mt")

# Sanity cap on the number of changed areas rendered for a single diff.
# Might have to reduce for ddnet, as we don't have a dedicated GPU there.
MAX_DIFF_AREAS = 20


class MapRenderer:
    """
    Render a map (full, or a framed region) to PNG bytes via twgpu-map-photography.
    """

    BASE_DIR = Path("data/map-testing")
    BASE_TILES = 33.65

    @classmethod
    async def render(
        cls, data: bytes, *, position: str | None = None,
        zoom: float | None = None, resolution: str = "700x700",
    ) -> bytes | None:
        uid = uuid.uuid4().hex
        tmp = cls.BASE_DIR / "tmp" / f"{uid}.map"
        await asyncio.to_thread(tmp.write_bytes, data)

        _, ext = check_os()
        exe = f"{cls.BASE_DIR}/twgpu-map-photography{ext}"
        args = ["-r", resolution]
        if position is not None:
            args += ["-p", position]
        if zoom is not None:
            args += ["-z", str(zoom)]
        args.append(str(tmp))

        try:
            await run_process_exec(exe, *args)
            outputs = sorted(Path(".").glob(f"{uid}*.png"))
            if not outputs:
                return None
            return await asyncio.to_thread(outputs[0].read_bytes)
        except Exception as exc:
            log.error("Map render failed: %s", exc)
            return None
        finally:
            if tmp.exists():
                tmp.unlink()
            for png in Path(".").glob(f"{uid}*.png"):
                png.unlink()

    # Show generous surroundings so the change is locatable in the map -- a physics
    # change has no design pixels of its own, so context tiles are what make the picture readable.
    MIN_SPAN_TILES = 40

    @classmethod
    def frame_for_bbox(cls, bbox: tuple[int, int, int, int], map_w: int, map_h: int) -> tuple[float, float, float]:
        """Camera ``(center_x, center_y, zoom)`` that frames a changed-tile bbox with
        generous context padding."""
        min_x, min_y, max_x, max_y = bbox
        cx = (min_x + max_x + 1) / 2
        cy = (min_y + max_y + 1) / 2
        span = max(max_x - min_x + 1, max_y - min_y + 1) * 2.5 + 24
        span = max(float(cls.MIN_SPAN_TILES), min(span, float(max(map_w, map_h))))
        zoom = max(0.03, min(span / cls.BASE_TILES, 100.0))
        return cx, cy, round(zoom, 3)

    @classmethod
    def fit_map(cls, map_w: int, map_h: int) -> tuple[float, float, float]:
        """Camera that frames the whole map (centre + zoom). Used for physics-only
        changes, where the change has no design pixels and is best shown as an overview
        with the overlay marking where it is."""
        cx, cy = map_w / 2, map_h / 2
        span = max(map_w, map_h) * 1.08
        zoom = max(0.03, min(span / cls.BASE_TILES, 100.0))
        return cx, cy, round(zoom, 3)


# Overlay colours for the three change kinds.
ADDED_COLOUR = (60, 220, 90)        # green
REMOVED_COLOUR = (235, 55, 55)      # red
MODIFIED_COLOUR = (40, 220, 210)    # turquoise (overwritten)


def overlay_changes(
    png: bytes,
    mask_added: "np.ndarray | None",
    mask_removed: "np.ndarray | None",
    mask_modified: "np.ndarray | None",
    cx: float, cy: float, zoom: float, res: int,
) -> bytes:
    """
    Tint the changed cells onto the (new-map) render at their coordinates, colouring
    added green, removed red, overwritten turquoise. Draws a single outline + tile-coord
    label around the whole changed region, plus a small colour legend. Returns PNG bytes.
    """
    img = Image.open(BytesIO(png)).convert("RGB")
    arr = np.asarray(img, dtype=np.float32).copy()
    h_img, w_img = arr.shape[:2]
    ppt = res / (MapRenderer.BASE_TILES * zoom)  # pixels per tile

    yy, xx = np.mgrid[0:h_img, 0:w_img]
    tx = np.floor(cx + (xx - w_img / 2) / ppt).astype(np.int64)
    ty = np.floor(cy + (yy - h_img / 2) / ppt).astype(np.int64)

    def tint(mask, colour):
        if mask is None:
            return
        h_m, w_m = mask.shape
        inb = (tx >= 0) & (tx < w_m) & (ty >= 0) & (ty < h_m)
        sel = np.zeros((h_img, w_img), dtype=bool)
        sel[inb] = mask[ty[inb], tx[inb]]
        arr[sel] = arr[sel] * 0.35 + np.asarray(colour, dtype=np.float32) * 0.65

    # Removed first, overwritten next, added on top (so an added cell always shows green).
    tint(mask_removed, REMOVED_COLOUR)
    tint(mask_modified, MODIFIED_COLOUR)
    tint(mask_added, ADDED_COLOUR)
    out = Image.fromarray(arr.astype(np.uint8), "RGB")
    draw = ImageDraw.Draw(out)

    union = None
    for mask in (mask_added, mask_removed, mask_modified):
        if mask is not None:
            union = mask if union is None else (union | mask)
    if union is not None and union.any():
        ys, xs = np.nonzero(union)
        tx0, tx1 = int(xs.min()), int(xs.max()) + 1
        ty0, ty1 = int(ys.min()), int(ys.max()) + 1
        px0 = w_img / 2 + (tx0 - cx) * ppt
        px1 = w_img / 2 + (tx1 - cx) * ppt
        py0 = h_img / 2 + (ty0 - cy) * ppt
        py1 = h_img / 2 + (ty1 - cy) * ppt
        mcx, mcy = (px0 + px1) / 2, (py0 + py1) / 2
        hx, hy = max((px1 - px0) / 2, 10.0), max((py1 - py0) / 2, 10.0)
        for t in range(2):
            draw.rectangle([mcx - hx - t, mcy - hy - t, mcx + hx + t, mcy + hy + t], outline=(255, 255, 255))
        draw.text((min(mcx + hx + 5, w_img - 70), max(mcy - hy - 14, 2)), f"({tx0},{ty0})", fill=(255, 255, 255))

    # Legend (only the kinds actually present).
    x = 6
    for label, mask, colour in (("added", mask_added, ADDED_COLOUR),
                                ("removed", mask_removed, REMOVED_COLOUR),
                                ("overwritten", mask_modified, MODIFIED_COLOUR)):
        if mask is not None and mask.any():
            draw.text((x, 6), label, fill=colour)
            x += int(draw.textlength(label)) + 12

    buf = BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


async def render_diff_images(new_bytes, result, res: int = 1200, max_clusters: int = MAX_DIFF_AREAS):
    """
    Render one focused image per changed *area* -- scattered edits don't collapse into a
    single whole-map box. Each image tints that area's cells (added green / removed red /
    overwritten turquoise).
    """
    clusters, total = (
        result.change_clusters(max_clusters=max_clusters)
        if (result.width and result.height) else ([], 0)
    )
    images: list[bytes] = []
    if clusters:
        for added, removed, modified, bbox in clusters:
            cx, cy, zoom = MapRenderer.frame_for_bbox(bbox, result.width, result.height)
            png = await MapRenderer.render(
                new_bytes, position=f"{cx:.1f},{cy:.1f}", zoom=zoom, resolution=f"{res}x{res}"
            )
            if png is not None:
                images.append(await asyncio.to_thread(
                    overlay_changes, png, added, removed, modified, cx, cy, zoom, res
                ))
        return images, total

    # No game-coordinate tile change (e.g. quad/tileset-only) -- show the whole map.
    if result.width and result.height:
        cx, cy, zoom = MapRenderer.fit_map(result.width, result.height)
        png = await MapRenderer.render(
            new_bytes, position=f"{cx:.1f},{cy:.1f}", zoom=zoom, resolution=f"{res}x{res}"
        )
    else:
        png = await MapRenderer.render(new_bytes, resolution=f"{res}x{res}")
    if png is not None:
        images.append(png)
    return images, total
