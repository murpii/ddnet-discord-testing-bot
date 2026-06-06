import logging

import discord

from extensions.map_testing.cooldown import global_cooldown
from extensions.map_testing.views.embeds import OwnerChanged

log = logging.getLogger("mt")


class ChangeSubmissionOwnerModal(discord.ui.Modal, title="Change Submission Owner"):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    ident = discord.ui.TextInput(
        label="The user's ID.",
        placeholder="Up to 19 digits",
        max_length=19,
        style=discord.TextStyle.short,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)
        if tc is None:
            await interaction.followup.send("This isn't a tracked testing channel.", ephemeral=True)
            return

        try:
            user = await self.bot.fetch_user(int(self.ident.value))
        except (ValueError, discord.NotFound):
            await interaction.followup.send("Invalid user ID.", ephemeral=True)
            return

        previous_owner = tc.mapper_mentions
        await tc.changelog.add_changelog(
            tc.channel,
            interaction.user,
            category="MapTesting/CHANGE_OWNER",
            string=f'"{tc.map_name}" ownership has been transferred from {previous_owner} to {user.mention}.',
            map_name=tc.map_name,
        )
        await tc.changelog.update_changelog()

        await tc.update(mapper_mentions=user.mention)
        # Keep the upload-permission list in sync so the new owner is trusted.
        tc.authors = [tc.channel.guild.get_member(user.id) or user]
        global_cooldown.update_cooldown(tc.channel.id)

        await interaction.followup.send(
            f"Changed the submission owner to {tc.mapper_mentions}.", ephemeral=True
        )
        await tc.channel.send(view=OwnerChanged(tc), allowed_mentions=discord.AllowedMentions.none())