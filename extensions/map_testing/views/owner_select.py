import discord

from extensions.map_testing.cooldown import global_cooldown
from extensions.map_testing.views.embeds import OwnerChanged


async def apply_owners(tc, actor: discord.abc.User, owners: list) -> str:
    mentions = " ".join(owner.mention for owner in owners)
    previous_owner = tc.mapper_mentions

    await tc.changelog.add_changelog(
        tc.channel,
        actor,
        category="MapTesting/CHANGE_OWNER",
        string=f'"{tc.map_name}" ownership has been transferred from {previous_owner} to {mentions}.',
        map_name=tc.map_name,
    )
    await tc.changelog.update_changelog()

    await tc.update(mapper_mentions=mentions)
    # keep the upload permission list in sync so the new owners are trusted
    tc.authors = owners
    global_cooldown.update_cooldown(tc.channel.id)
    return mentions


class OwnerSelect(discord.ui.View):
    def __init__(self, bot, current_owners=None):
        super().__init__()
        self.bot = bot
        self.select = discord.ui.UserSelect(
            placeholder="Select the channel owner(s)...",
            min_values=1,
            max_values=25,
            default_values=list(current_owners or []),
        )
        self.select.callback = self.callback
        self.add_item(self.select)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)
        if tc is None:
            await interaction.followup.send("This isn't a tracked testing channel.", ephemeral=True)
            return

        owners = list(self.select.values)
        mentions = await apply_owners(tc, interaction.user, owners)

        await interaction.followup.send(
            f"Changed the submission owner(s) to {mentions}.", ephemeral=True
        )
        await tc.channel.send(view=OwnerChanged(tc), allowed_mentions=discord.AllowedMentions.none())
