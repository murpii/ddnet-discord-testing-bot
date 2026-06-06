import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone

from constants import Channels

log = logging.getLogger("mt")

SCORE_FILE = "data/map-testing/scores.json"
ACTIONS = ("READY", "DECLINED", "RESET", "WAITING")
ACTION_LABELS = {
    "READY": "R",
    "DECLINED": "D",
    "WAITING": "W",
    "RESET": "Rs",
}
_score_lock = asyncio.Lock()


def read_scores() -> dict:
    try:
        with open(SCORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def bump_score(user_id: int, button_name: str) -> None:
    """Synchronous read-modify-write of the score file. Runs in a thread."""
    scores = read_scores()
    user_id_str = str(user_id)
    if user_id_str not in scores:
        scores[user_id_str] = {action: 0 for action in ACTIONS}
    scores[user_id_str][button_name] += 1
    with open(SCORE_FILE, "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=4)


async def add_score(user_id: int, button_name: str) -> None:
    """Track a tester action.

    Args:
        user_id: The Discord user ID.
        button_name: One of "READY", "DECLINED", "RESET", "WAITING".
    """
    button_name = button_name.upper()
    if button_name not in ACTIONS:
        raise ValueError(f"Invalid button name: {button_name}")

    async with _score_lock:
        await asyncio.to_thread(bump_score, user_id, button_name)


async def update_scores_topic(bot) -> None:
    """Update the TESTER_CHAT channel topic with the top tester activity."""
    scores = await asyncio.to_thread(read_scores)

    def format_actions(actions: dict[str, int]) -> str:
        return "/".join(
            f"{count}{label}"
            for action, label in ACTION_LABELS.items()
            if (count := actions.get(action, 0))
        )

    scored_list = []
    for user_id, actions in scores.items():
        try:
            breakdown = format_actions(actions)
            if breakdown:
                total = sum(actions.get(action, 0) for action in ACTIONS)
                scored_list.append((user_id, breakdown, total))
        except Exception as exc:
            log.warning("Skipping user %s due to invalid data: %s", user_id, exc)

    if not scored_list:
        log.info("No scores to display.")
        return

    # Most active testers first.
    scored_list.sort(key=lambda x: x[2], reverse=True)

    prefix = "Testers -- "
    sep = " | "
    entries: list[str] = []
    length = len(prefix)
    for user_id, breakdown, _ in scored_list:
        entry = f"<@{user_id}> {breakdown}"
        extra = len(entry) + (len(sep) if entries else 0)
        if length + extra > 1024:
            break
        entries.append(entry)
        length += extra
    topic = prefix + sep.join(entries)

    channel = bot.get_channel(Channels.TESTER_CHAT)
    if channel is None:
        log.warning("Tester channel not found.")
        return

    try:
        await channel.edit(topic=topic)
    except Exception as exc:
        log.error("Failed to update tester topic: %s", exc)


class ScoresTopicUpdater:
    WINDOW = timedelta(minutes=15)  # stay within "2 edits / 15 min" -- under Discord's limit
    MAX_EDITS = 2

    def __init__(self, bot):
        self.bot = bot
        self._recent: deque[datetime] = deque(maxlen=self.MAX_EDITS)
        self._pending: asyncio.Task | None = None

    def request(self) -> None:
        if self._pending is not None and not self._pending.done():
            return  # a refresh is already queued; it will pick up the latest scores
        self._pending = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            now = datetime.now(timezone.utc)
            while self._recent and now - self._recent[0] >= self.WINDOW:
                self._recent.popleft()
            if len(self._recent) >= self.MAX_EDITS:
                delay = (self._recent[0] + self.WINDOW - now).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)
            await update_scores_topic(self.bot)
            self._recent.append(datetime.now(timezone.utc))
        except Exception:
            log.exception("Scores-topic refresh failed")
