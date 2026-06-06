import asyncio
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from utils.misc import run_process_exec, check_os

log = logging.getLogger("mt")
_MISS = object()


class MapChecker:
    BASE_DIR = Path("data/map-testing")
    TMP_DIR = BASE_DIR / "tmp"

    CACHE_MAX = 128
    cache: "OrderedDict[int, Optional[str]]" = OrderedDict()

    @classmethod
    async def debug(cls, submission) -> Optional[str]:
        output, _ = await cls.debug_detailed(submission)
        return output

    @classmethod
    async def debug_detailed(cls, submission) -> tuple[Optional[str], bool]:
        """
        Run the map check, returning ``(output, from_cache)``.

        ``output`` is None for a clean map. ``from_cache`` is True when the result was
        served from the cache rather than freshly checked.
        """
        try:
            key = submission.message.id

            cached = cls.cache.get(key, _MISS)
            if cached is not _MISS:
                cls.cache.move_to_end(key)
                return cached, True

            data = (await submission.buffer()).getvalue()
            result = await cls.run_checks(data, key)
            cls.cache_put(key, result)
            return result, False

        except Exception as exc:
            # Failures (unreadable attachment, missing binary)
            # are returned but never cached, so a retry can succeed.
            log.error("Map debug failed (%s): %s", submission.filename, exc)
            return str(exc), False

    @classmethod
    async def run_checks(cls, data: bytes, message_id: int) -> Optional[str]:
        tmp_path = cls.TMP_DIR / f"{message_id}.map"
        try:
            # TESTING, UNSURE IF SAFE:
            # Offloading the (multi-MB) write so it doesn't block the event loop.
            await asyncio.to_thread(tmp_path.write_bytes, data)

            _, ext = check_os()

            base_check = run_process_exec(
                f"{cls.BASE_DIR}/twmap-check{ext}",
                "-vv", "--", str(tmp_path)
            )
            ddnet_check = run_process_exec(
                f"{cls.BASE_DIR}/twmap-check-ddnet{ext}",
                "--omit-unreliable-checks", "--", str(tmp_path)
            )
            base_result, ddnet_result = await asyncio.gather(
                base_check, ddnet_check, return_exceptions=True
            )

            if isinstance(base_result, Exception):
                raise base_result
            stdout, stderr = base_result
            output = stdout + stderr

            if isinstance(ddnet_result, Exception):
                log.error("DDNet check failed: %s", ddnet_result)
            else:
                dd_stdout, dd_stderr = ddnet_result
                if not dd_stderr:
                    output += dd_stdout
            return output or None

        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    @classmethod
    def cache_put(cls, key: int, value: Optional[str]) -> None:
        cls.cache[key] = value
        cls.cache.move_to_end(key)
        while len(cls.cache) > cls.CACHE_MAX:
            cls.cache.popitem(last=False)