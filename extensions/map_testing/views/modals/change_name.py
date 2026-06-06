import contextlib
import logging

import discord

from extensions.map_testing.cooldown import global_cooldown
from extensions.map_testing.views.embeds import NameChanged
from utils.conn import ddnet_delete

log = logging.getLogger("mt")


class ChangeMapNameModal(discord.ui.Modal, title="Change Map Name"):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    new_name = discord.ui.TextInput(
        label="The New Map Name",
        placeholder="Back in Time 4",
        max_length=32,
        style=discord.TextStyle.short,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)
        if tc is None:
            await interaction.followup.send("This isn't a tracked testing channel.", ephemeral=True)
            return

        old_filename = tc.filename
        await tc.update(map_name=self.new_name.value)
        global_cooldown.update_cooldown(tc.channel.id)

        await tc.changelog.add_changelog(
            tc.channel,
            interaction.user,
            category="MapTesting/CHANGE_NAME",
            string=f'Map name has been changed to: "{tc.map_name}".',
            map_name=tc.map_name,
        )
        await tc.changelog.update_changelog()

        # Remove the old filename from the test server (best effort).
        with contextlib.suppress(RuntimeError):
            await ddnet_delete(self.bot.session, self.bot.config, old_filename)

        await interaction.followup.send(f"Changed the map name to `{tc.map_name}`.", ephemeral=True)
        await tc.channel.send(view=NameChanged(tc), allowed_mentions=discord.AllowedMentions.none())