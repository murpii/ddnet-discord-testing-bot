from typing import Union, Iterable
import logging
import discord

from utils import changelog_store


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
        self.data = tuple(sorted(data, key=lambda x: x[0], reverse=True)) if data else ()
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

        data = await changelog_store.read_entries(channel_id)
        self.data = tuple(sorted(data, key=lambda x: x[0], reverse=True))
        self.update_total_pages()

    async def update_extras(self, embed: Union[discord.Embed, Iterable[discord.Embed]]):
        self.embeds = [embed] if isinstance(embed, discord.Embed) else list(embed)

    def format_changelog_embed(self) -> discord.Embed:
        start = self.page * self.entries_per_page
        end = start + self.entries_per_page
        paginated_data = self.data[start:end]
        changelog_description = []

        for entry in paginated_data:
            timestamp, _, _, invoked_by, _, log = entry
            formatted_time = timestamp.strftime("[%d/%m %H:%M]")
            entry_text = f"`{formatted_time}` › {invoked_by}: {log}"
            changelog_description.append(entry_text)

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

        if isinstance(self.channel, discord.Thread) and self.channel.archived:
            await self.channel.edit(archived=False)

        self.update_buttons()
        await self.changelog.edit(
            embeds=[self.format_changelog_embed(), *self.embeds],
            view=self
        )

    async def add_changelog(
            self,
            channel,
            user: Union[discord.User, discord.Member, discord.Interaction.user],
            category: str = None,
            string: str = None,
            map_name: str = None,
    ) -> None:
        if isinstance(user, discord.Interaction):
            user = user.user  # Get the user from the interaction

        await changelog_store.add_entry(
            channel.id,
            map_name or channel.name,
            user.mention,
            category,
            string,
        )

        await self.get_data(channel=channel)  # reload after insertion
        self.update_buttons()
