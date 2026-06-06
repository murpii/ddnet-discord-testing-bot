import discord

from extensions.map_testing.cooldown import global_cooldown
from extensions.map_testing.views.embeds import MappersChanged
from utils.text import slugify2


class ChangeMappersModal(discord.ui.Modal, title="Change Mappers"):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    mappers = discord.ui.TextInput(
        label="Mappers",
        placeholder="Example: Welf, louis, Pipou, Ravie",
        max_length=64,
        style=discord.TextStyle.short,
    )

    @staticmethod
    def get_mapper_urls(mappers: list[str]) -> list[str]:
        return [f"[{m}](https://ddnet.org/mappers/{slugify2(m)})" for m in mappers]

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)
        if tc is None:
            await interaction.followup.send("This isn't a tracked testing channel.", ephemeral=True)
            return

        mappers_list = [m.strip() for m in self.mappers.value.split(",")]
        mapper_urls = self.get_mapper_urls(mappers_list)

        await tc.update(mappers=mappers_list)
        global_cooldown.update_cooldown(tc.channel.id)

        await tc.changelog.add_changelog(
            tc.channel,
            interaction.user,
            category="MapTesting/CHANGE_MAPPERS",
            string=f'Mappers have been changed to: {", ".join(mapper_urls)}.',
            map_name=tc.map_name,
        )
        await tc.changelog.update_changelog()

        await interaction.followup.send(
            f'Changed the mapper(s) to {", ".join(mapper_urls)}.', ephemeral=True
        )
        await tc.channel.send(
            view=MappersChanged(tc, ", ".join(mapper_urls)),
            allowed_mentions=discord.AllowedMentions.none(),
        )