import asyncio
import logging
from io import BytesIO
from pathlib import Path

from utils.misc import run_process_shell, run_process_exec, check_os

log = logging.getLogger("mt")

# TODO: Move this to utils instead

class MapEditor:
    BASE_DIR = Path("data/map-testing")

    @classmethod
    async def edit(cls, submission, *args: str):
        tmp = cls.BASE_DIR / "tmp" / f"{submission.message.id}.map"
        edited = tmp.with_name(tmp.name + "_edit")

        buf = await submission.buffer()
        await asyncio.to_thread(tmp.write_bytes, buf.getvalue())

        _, ext = check_os()

        try:
            stdout, stderr = await run_process_exec(
                f"{cls.BASE_DIR}/twmap-edit{ext}",
                str(tmp),
                str(edited),
                *args
            )
        except RuntimeError as exc:
            raise RuntimeError(str(exc))

        if stderr:
            raise RuntimeError(stderr)

        file = None
        if edited.exists():
            file = await asyncio.to_thread(edited.read_bytes)
            edited.unlink()

        tmp.unlink()
        return stdout, file


class MapThumbnailer:
    BASE_DIR = Path("data/map-testing")

    @classmethod
    async def generate(cls, submission):
        tmp = cls.BASE_DIR / "tmp" / f"{submission.message.id}.map"
        png = Path(f"{submission.message.id}.png")

        buf = await submission.buffer()
        await asyncio.to_thread(tmp.write_bytes, buf.getvalue())

        _, ext = check_os()
        exe = f"{cls.BASE_DIR}/twgpu-map-photography{ext}"

        try:
            await run_process_shell(f"{exe} {tmp}")
            data = await asyncio.to_thread(png.read_bytes)
            return BytesIO(data)
        finally:
            if tmp.exists():
                tmp.unlink()
            if png.exists():
                png.unlink()


class MapVisualizer:
    @staticmethod
    async def visualize_size(submission) -> BytesIO:
        """
        Render a file-size breakdown (images/sounds/remaining) for a submission.

        Parsing the map and drawing the matplotlib figure are both blocking and
        CPU-bound, so the work is pushed to a worker thread to keep the event loop
        responsive.
        """
        # Imported lazily so matplotlib/kaitai (a heavy, optional dependency chain)
        # only load the first time someone actually visualizes a map.
        from extensions.map_testing.visualize_size import visualize_from_bytes

        buf = await submission.buffer()
        out = await asyncio.to_thread(visualize_from_bytes, buf.getvalue())
        return BytesIO(out.getvalue())
