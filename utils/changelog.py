import asyncio
import contextlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, NamedTuple, Union

import discord

log = logging.getLogger("mt")

CHANGELOG_DIR = Path("data/map-testing/changelogs")
changelock = asyncio.Lock()


class ChangelogEntry(NamedTuple):
    timestamp: datetime
    channel_name: str
    channel_id: int | None
    invoked_by: str
    category: str
    action: str
    url: str | None


def channel_path(channel_id: int) -> Path:
    return CHANGELOG_DIR / f"{channel_id}.json"


def read(channel_id: int) -> list[dict]:
    try:
        with open(channel_path(channel_id), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def write(channel_id: int, rows: list[dict]) -> None:
    CHANGELOG_DIR.mkdir(parents=True, exist_ok=True)
    path = channel_path(channel_id)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def parse_entry(d: dict) -> ChangelogEntry:
    raw = d.get("timestamp")
    try:
        ts = datetime.fromisoformat(raw) if raw else datetime.now(timezone.utc)
    except ValueError:
        ts = datetime.now(timezone.utc)

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ChangelogEntry(
        timestamp=ts,
        channel_name=d.get("channel_name", ""),
        channel_id=d.get("channel_id"),
        invoked_by=d.get("invoked_by", ""),
        category=d.get("type", ""),
        action=d.get("action", ""),
        url=d.get("url"),
    )


def add(channel_id: int, row: dict) -> None:
    rows = read(channel_id)
    rows.append(row)
    write(channel_id, rows)


def delete(channel_id: int) -> None:
    with contextlib.suppress(FileNotFoundError):
        channel_path(channel_id).unlink()


async def read_entries(channel_id: int) -> list[ChangelogEntry]:
    rows = await asyncio.to_thread(read, channel_id)
    return [parse_entry(r) for r in rows]


async def add_entry(
        channel_id: int,
        channel_name: str,
        invoked_by: str,
        type_: str | None,
        action: str | None,
        *,
        timestamp: datetime | None = None,
        url: str | None = None,
) -> None:
    row = {
        "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
        "channel_name": channel_name,
        "channel_id": channel_id,
        "invoked_by": invoked_by,
        "type": type_,
        "action": action,
        "url": url,
    }
    async with changelock:
        await asyncio.to_thread(add, channel_id, row)


async def delete_channel(channel_id: int) -> None:
    async with changelock:
        await asyncio.to_thread(delete, channel_id)


class ChangelogPaginator(discord.ui.View):
    def __init__(
            self,
            bot,
            data: tuple = (),
            changelog: discord.Message = None,
            channel: discord.TextChannel = None,
            embeds: discord.Embed | list[discord.Embed] = None
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.data = tuple(sorted(data, key=lambda x: x.timestamp, reverse=True)) if data else ()
        self.channel = channel
        self.changelog: discord.Message = changelog
        self.page = 0
        self.entries_per_page = 4

        if embeds is None:
            self.embeds = []
        elif isinstance(embeds, discord.Embed):
            self.embeds = [embeds]
        else:
            self.embeds = list(embeds)

        self.total_pages = len(self.data) // self.entries_per_page
        if len(self.data) % self.entries_per_page != 0:
            self.total_pages += 1

        self.update_buttons()

    def __repr__(self):
        return f"ChangelogPaginator object for channel={self.channel},\ndata=\"{self.data}\""

    @property
    def _channel(self):
        return self.channel

    @property
    def _data(self):
        return self.data

    @property
    def _changelog(self):
        return self.changelog

    async def assign_changelog_message(
            self,
            *,
            thread: discord.Thread = None,
            message: discord.Message = None
    ) -> discord.Message:
        if thread:  # map testing specific
            messages = [msg async for msg in thread.history(limit=2, oldest_first=True)]
            self.changelog = messages[1] if len(messages) > 1 else None
        else:
            self.changelog = message

        return self.changelog

    async def get_data(self, message: discord.Message = None, channel: discord.TextChannel = None):
        """Loads the changelog data for a channel from the file-backed store."""
        if message:
            channel_id = message.channel.id
        elif channel:
            channel_id = channel.id
        elif self.channel:
            channel_id = self.channel.id
        else:
            raise ValueError("Must specify either message, channel, or self.channel")

        data = await read_entries(channel_id)
        self.data = tuple(sorted(data, key=lambda x: x.timestamp, reverse=True))
        self.update_total_pages()

    async def update_extras(self, embed: Union[discord.Embed, Iterable[discord.Embed]]):
        self.embeds = [embed] if isinstance(embed, discord.Embed) else list(embed)

    def format_changelog_embed(self) -> discord.Embed:
        start = self.page * self.entries_per_page
        end = start + self.entries_per_page
        paginated_data = self.data[start:end]
        changelog_description = []

        for entry in paginated_data:
            time_text = f"`{entry.timestamp.strftime('[%d/%m %H:%M]')}`"
            if entry.url:
                time_text = f"[{time_text}]({entry.url})"
            changelog_description.append(f"{time_text} {entry.invoked_by}: {entry.action}")

        changelog_desc = "\n".join(changelog_description)
        page_info = f"-# Page {self.page + 1} / {self.total_pages}"

        return discord.Embed(
            title="📑 Changelog",
            description=f"{changelog_desc}\n\n{page_info}",
            color=discord.Color.red(),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(
        label="◀", style=discord.ButtonStyle.secondary, custom_id="Paginator:testing:prev", disabled=True
    )
    async def previous_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            self.update_buttons()

            await interaction.response.edit_message(
                embeds=[
                    self.format_changelog_embed(),
                    *self.embeds
                ],
                view=self
            )

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="Paginator:testing:next")
    async def next_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
            self.update_buttons()

            await interaction.response.edit_message(
                embeds=[
                    self.format_changelog_embed(),
                    *self.embeds
                ],
                view=self
            )

    def update_total_pages(self):
        self.total_pages = len(self.data) // self.entries_per_page
        if len(self.data) % self.entries_per_page != 0:
            self.total_pages += 1

    def update_buttons(self):
        self.children[0].disabled = self.page == 0 or self.total_pages <= 1  # Previous button # noqa
        self.children[1].disabled = self.page == self.total_pages - 1 or self.total_pages <= 1  # Next button # noqa

    async def update_changelog(self):
        if self.changelog is None:
            logging.warning("[ChangelogPaginator] Cannot update changelog: self.changelog is None.")
            if self.channel:
                logging.warning(f"[ChangelogPaginator] Channel is assigned: {self.channel.id} ({self.channel.name})")
            else:
                logging.warning("[ChangelogPaginator] No channel assigned.")
            raise ValueError("Cannot update changelog: no message is assigned.")

        message_channel = self.changelog.channel
        if isinstance(message_channel, discord.Thread) and message_channel.archived:
            await message_channel.edit(archived=False)

        self.update_buttons()
        embeds = [self.format_changelog_embed(), *self.embeds]
        try:
            await self.changelog.edit(embeds=embeds, view=self)
        except discord.HTTPException as exc:
            if exc.code != 50083 or not isinstance(message_channel, discord.Thread):
                raise
            await message_channel.edit(archived=False)
            await self.changelog.edit(embeds=embeds, view=self)

    async def add_changelog(
            self,
            channel,
            user: Union[discord.User, discord.Member, discord.Interaction.user],
            category: str = None,
            string: str = None,
            map_name: str = None,
            url: str = None,
    ) -> None:
        if isinstance(user, discord.Interaction):
            user = user.user  # Get the user from the interaction

        await add_entry(
            channel.id,
            map_name or channel.name,
            user.mention,
            category,
            string,
            url=url,
        )

        await self.get_data(channel=channel)  # reload after insertion
        self.update_buttons()
