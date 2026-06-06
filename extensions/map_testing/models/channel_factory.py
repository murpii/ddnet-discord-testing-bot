from dataclasses import field, dataclass
from typing import Optional, Union

import discord

from constants import Channels
from extensions.map_testing.enums import MapState, MapServer
from extensions.map_testing.models.submissions import Submission
from utils.changelog import ChangelogPaginator
from utils.text import human_join, sanitize


def build_topic(
    map_name: str,
    mappers: list[str],
    server: str,
    author_mentions: str = "",
    voter_mentions: str = "",
) -> str:
    mapper_str = human_join(mappers)
    preview_url = f"https://ddnet.org/testmaps/?map={sanitize(map_name)}"
    lines = [
        f'**"{map_name}"** by {mapper_str} [{server}]',
        preview_url,
        author_mentions,
    ]
    if voter_mentions:
        lines.append(voter_mentions)
    return "\n".join(lines)


@dataclass(slots=True, kw_only=True)
class TestingChannel:
    channel: discord.TextChannel
    thread: Optional[discord.Thread]
    state: MapState = MapState.TESTING
    map_name: str = ""
    server: str = ""
    mappers: list[str] = field(default_factory=list)
    mapper_mentions: str = ""
    authors: list[Union[discord.Member, discord.User]] = field(default_factory=list)
    votes: dict[int, str] = field(default_factory=dict)
    submission: Optional[Submission] = None
    changelog: Optional[ChangelogPaginator] = None

    def __repr__(self) -> str:
        return (
            f"TestingChannel("
            f"channel={self.channel.id}, "
            f"state={self.state.name}, "
            f"map_name={self.map_name!r}, "
            f"server={self.server!r}, "
            f"votes={self.votes})"
        )

    def __getattr__(self, item):
        return getattr(self.channel, item)

    @property
    def filename(self) -> str:
        return sanitize(self.map_name)

    @property
    def preview_url(self) -> str:
        return f"https://ddnet.org/testmaps/?map={self.filename}"

    @property
    def channel_name(self) -> str:
        try:
            emoji = MapServer[self.server].value
        except KeyError:
            emoji = ""
        return f"{self.state.value}{emoji}{self.filename}"

    def channel_topic(self) -> str:
        voter_mentions = " ".join(f"<@{uid}>" for uid in self.votes)
        return build_topic(
            map_name=self.map_name,
            mappers=self.mappers,
            server=self.server,
            author_mentions=self.mapper_mentions,
            voter_mentions=voter_mentions,
        )

    async def set_state(self, state: MapState) -> None:
        """Apply ``state`` to the Discord channel (name/topic/category).

        Pure effector: it sets ``self.state`` and edits the channel to match. Vote
        bookkeeping and all transition rules live in the state machine -- callers
        set ``self.votes`` (via ``TestingManager.apply_transition``) before this.
        """
        self.state = state

        if state in (MapState.TESTING, MapState.RC):
            category_id = Channels.CAT_TESTING
        elif state is MapState.WAITING:
            category_id = Channels.CAT_WAITING
        else:
            category_id = Channels.CAT_EVALUATED

        options: dict = {
            "name": self.channel_name,
            "topic": self.channel_topic(),
        }
        if self.channel.category_id != category_id:
            category = self.channel.guild.get_channel(category_id)
            options["category"] = category
            options["position"] = (
                category.channels[-1].position + 1
                if state in (MapState.TESTING, MapState.RC)
                else 0
            )

        await self.channel.edit(**options)

    async def update(
        self,
        map_name: str = None,
        mappers: list[str] = None,
        server: str = None,
        mapper_mentions: str = None,
    ) -> None:
        if map_name is not None:
            self.map_name = map_name
        if mappers is not None:
            self.mappers = mappers
        if server is not None:
            self.server = server.capitalize()
        if mapper_mentions is not None:
            self.mapper_mentions = mapper_mentions

        await self.channel.edit(
            name=self.channel_name,
            topic=self.channel_topic(),
        )