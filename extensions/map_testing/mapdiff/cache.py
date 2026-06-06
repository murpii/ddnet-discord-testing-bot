import hashlib
import logging
import shutil
from pathlib import Path

log = logging.getLogger("mt")
DIFF_DIR = Path("data/map-testing/diffs")


def channel_diff_dir(channel_id) -> Path:
    return DIFF_DIR / str(channel_id)


def clear_channel_diffs(channel_id) -> None:
    """Delete a channel's cached visual-diff images -- called when the channel is removed."""
    shutil.rmtree(DIFF_DIR / str(channel_id), ignore_errors=True)


def diff_key(old_bytes: bytes, new_bytes: bytes) -> str:
    return hashlib.sha256(old_bytes).hexdigest()[:16] + "_" + hashlib.sha256(new_bytes).hexdigest()[:16]


def load_cached_diff(channel_id: int, key: str) -> tuple[list[bytes], int] | None:
    """Load a previously rendered diff for this pair from the channels disk folder"""
    matches = sorted(channel_diff_dir(channel_id).glob(f"{key}_*.png"))
    if not matches:
        return None
    try:
        total = int(matches[0].stem.rsplit("_", 2)[1])
    except (IndexError, ValueError):
        total = len(matches)
    try:
        return [p.read_bytes() for p in matches], total
    except OSError:
        return None


def store_cached_diff(channel_id: int, key: str, images: list[bytes], total: int) -> None:
    folder = channel_diff_dir(channel_id)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for i, image in enumerate(images):
            (folder / f"{key}_{total}_{i:02d}.png").write_bytes(image)
    except OSError as exc:
        log.warning("Couldn't cache diff images for channel %s: %s", channel_id, exc)
