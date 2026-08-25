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
        tmp.parent.mkdir(parents=True, exist_ok=True)
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
            stdout, stderr = await run_process_exec(exe, *args)
            outputs = sorted(Path(".").glob(f"{uid}*.png"))
            if not outputs:
                # The renderer resolves the DDNet 'data' dir (mapres tilesets) from an
                # installed game, a 'data' dir in the working directory, or one next to its
                # executable. On a server with none of these it loads the map but emits no image...
                hint = ""
                if "NotFound" in stderr and "Data" in stderr:
                    hint = (
                        f"DDNet 'data' directory (mapres tilesets) not found. Place one at "
                        f"'{Path('data').resolve()}' (the bot's working dir) or install DDNet "
                        f"on this host (see data/map-testing/README.md)"
                    )
                log.error(
                    "Map render produced no image (exe=%s args=%s)%s\nstdout: %s\nstderr: %s",
                    exe, args, hint, stdout.strip(), stderr.strip(),
                )
                return None
            return await asyncio.to_thread(outputs[0].read_bytes)
        except Exception as exc:
            log.exception("Map render failed (exe=%s args=%s): %s", exe, args, exc)
            return None
        finally:
            if tmp.exists():
                tmp.unlink()
            for png in Path(".").glob(f"{uid}*.png"):
                png.unlink()

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


def draw_white_box(draw, bbox, cx: float, cy: float, ppt: float, w_img: int, h_img: int) -> None:
    min_x, min_y, max_x, max_y = bbox
    px0 = w_img / 2 + (min_x - cx) * ppt
    px1 = w_img / 2 + (max_x + 1 - cx) * ppt
    py0 = h_img / 2 + (min_y - cy) * ppt
    py1 = h_img / 2 + (max_y + 1 - cy) * ppt
    mcx, mcy = (px0 + px1) / 2, (py0 + py1) / 2
    hx, hy = max((px1 - px0) / 2, 10.0), max((py1 - py0) / 2, 10.0)
    for t in range(2):
        draw.rectangle([mcx - hx - t, mcy - hy - t, mcx + hx + t, mcy + hy + t], outline=(255, 255, 255))
    draw.text((min(mcx + hx + 5, w_img - 70), max(mcy - hy - 14, 2)), f"({min_x},{min_y})", fill=(255, 255, 255))


def camera_tile_grids(h_img: int, w_img: int, cx: float, cy: float, ppt: float):
    yy, xx = np.mgrid[0:h_img, 0:w_img]
    tx = np.floor(cx + (xx - w_img / 2) / ppt).astype(np.int64)
    ty = np.floor(cy + (yy - h_img / 2) / ppt).astype(np.int64)
    return tx, ty


def overlay_masks(png: bytes, items, cx: float, cy: float, zoom: float, res: int) -> bytes:
    """
    Tint the changed cells onto the (new-map) render at their coordinates, colouring
    added green, removed red, overwritten turquoise. Draws a single outline + tile-coord
    label around the whole changed region, plus a small colour legend. Returns PNG bytes.
    """
    img = Image.open(BytesIO(png)).convert("RGB")
    arr = np.asarray(img, dtype=np.float32).copy()
    h_img, w_img = arr.shape[:2]
    ppt = res / (MapRenderer.BASE_TILES * zoom)  # pixels per tile
    tx, ty = camera_tile_grids(h_img, w_img, cx, cy, ppt)

    def tint(mask, colour):
        if mask is None:
            return
        h_m, w_m = mask.shape
        inb = (tx >= 0) & (tx < w_m) & (ty >= 0) & (ty < h_m)
        sel = np.zeros((h_img, w_img), dtype=bool)
        sel[inb] = mask[ty[inb], tx[inb]]
        arr[sel] = arr[sel] * 0.35 + np.asarray(colour, dtype=np.float32) * 0.65

    for mask, colour, _ in items:
        tint(mask, colour)
    out = Image.fromarray(arr.astype(np.uint8), "RGB")
    draw = ImageDraw.Draw(out)

    union = None
    for mask, _, _ in items:
        if mask is not None:
            union = mask if union is None else (union | mask)
    if union is not None and union.any():
        ys, xs = np.nonzero(union)
        draw_white_box(
            draw, (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
            cx, cy, ppt, w_img, h_img,
        )

    # Legend (only the kinds actually present).
    x = 6
    for mask, colour, label in items:
        if mask is not None and mask.any() and label:
            draw.text((x, 6), label, fill=colour)
            x += int(draw.textlength(label)) + 12

    buf = BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def overlay_changes(
    png: bytes,
    mask_added: "np.ndarray | None",
    mask_removed: "np.ndarray | None",
    mask_modified: "np.ndarray | None",
    cx: float, cy: float, zoom: float, res: int,
) -> bytes:
    return overlay_masks(png, [
        (mask_removed, REMOVED_COLOUR, "removed"),
        (mask_modified, MODIFIED_COLOUR, "overwritten"),
        (mask_added, ADDED_COLOUR, "added"),
    ], cx, cy, zoom, res)


async def render_diff_images(new_bytes, result, res: int = 1200, max_clusters: int = MAX_DIFF_AREAS):
    clusters, total = (
        result.change_clusters(max_clusters=max_clusters)
        if (result.width and result.height) else ([], 0)
    )
    log.debug(
        "render_diff_images: map=%sx%s clusters=%d total_changed_areas=%d",
        result.width, result.height, len(clusters), total,
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
        if not images:
            log.error(
                "render_diff_images: all %d cluster render(s) failed: see preceding render errors",
                len(clusters),
            )
        return images, total

    if result.width and result.height:
        cx, cy, zoom = MapRenderer.fit_map(result.width, result.height)
        png = await MapRenderer.render(
            new_bytes, position=f"{cx:.1f},{cy:.1f}", zoom=zoom, resolution=f"{res}x{res}"
        )
    else:
        png = await MapRenderer.render(new_bytes, resolution=f"{res}x{res}")
    if png is not None:
        images.append(png)
    else:
        log.error(
            "render_diff_images: whole-map render failed (map=%sx%s): see preceding render error",
            result.width, result.height,
        )
    return images, total

SXS_RES = 900
SXS_GAP = 10


def compose_side_by_side(
    old_png: bytes, new_png: bytes, bbox, cx: float, cy: float, zoom: float, res: int, gap: int = SXS_GAP,
) -> bytes:
    left = Image.open(BytesIO(old_png)).convert("RGB")
    right = Image.open(BytesIO(new_png)).convert("RGB")
    ppt = res / (MapRenderer.BASE_TILES * zoom)
    for img, tag in ((left, "Before"), (right, "After")):
        draw = ImageDraw.Draw(img)
        if bbox is not None:
            draw_white_box(draw, bbox, cx, cy, ppt, img.width, img.height)
        draw.text((6, 6), tag, fill=(255, 255, 255))

    height = max(left.height, right.height)
    canvas = Image.new("RGB", (left.width + gap + right.width, height), (25, 25, 25))
    canvas.paste(left, (0, 0))
    canvas.paste(right, (left.width + gap, 0))
    buf = BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


async def render_side_by_side_images(
    old_bytes, new_bytes, result, res: int = SXS_RES, max_clusters: int = MAX_DIFF_AREAS,
):
    clusters, total = (
        result.change_clusters(max_clusters=max_clusters)
        if (result.width and result.height) else ([], 0)
    )
    log.debug(
        "render_side_by_side_images: map=%sx%s clusters=%d total_changed_areas=%d",
        result.width, result.height, len(clusters), total,
    )
    images: list[bytes] = []
    if clusters:
        for _added, _removed, _modified, bbox in clusters:
            cx, cy, zoom = MapRenderer.frame_for_bbox(bbox, result.width, result.height)
            pos, resolution = f"{cx:.1f},{cy:.1f}", f"{res}x{res}"
            old_png = await MapRenderer.render(old_bytes, position=pos, zoom=zoom, resolution=resolution)
            new_png = await MapRenderer.render(new_bytes, position=pos, zoom=zoom, resolution=resolution)
            if old_png is not None and new_png is not None:
                images.append(await asyncio.to_thread(
                    compose_side_by_side, old_png, new_png, bbox, cx, cy, zoom, res
                ))
        if not images:
            log.error(
                "render_side_by_side_images: all %d cluster render(s) failed: see preceding render errors",
                len(clusters),
            )
        return images, total

    if result.width and result.height:
        cx, cy, zoom = MapRenderer.fit_map(result.width, result.height)
        pos, resolution = f"{cx:.1f},{cy:.1f}", f"{res}x{res}"
        old_png = await MapRenderer.render(old_bytes, position=pos, zoom=zoom, resolution=resolution)
        new_png = await MapRenderer.render(new_bytes, position=pos, zoom=zoom, resolution=resolution)
    else:
        cx = cy = 0.0
        zoom = 1.0
        old_png = await MapRenderer.render(old_bytes, resolution=f"{res}x{res}")
        new_png = await MapRenderer.render(new_bytes, resolution=f"{res}x{res}")
    if old_png is not None and new_png is not None:
        images.append(await asyncio.to_thread(
            compose_side_by_side, old_png, new_png, None, cx, cy, zoom, res
        ))
    else:
        log.error(
            "render_side_by_side_images: whole-map render failed (map=%sx%s): see preceding render error",
            result.width, result.height,
        )
    return images, total
