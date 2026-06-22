import discord

from extensions.map_testing.cooldown import cooldown_response
from extensions.map_testing.views.embeds import OwnerChanged
from extensions.map_testing.views.owner_select import apply_owners
from utils.checks import is_staff

ADD_COAUTHOR_ID = "info_card:add_coauthor"


def _resolve_tc(interaction: discord.Interaction):
    return interaction.client.testing_manager.get_tc_from_interaction(interaction)


def _is_owner_or_staff(user, tc) -> bool:
    return is_staff(user) or user.id in {author.id for author in tc.authors}


class AddCoAuthorButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Add Co-Author",
            style=discord.ButtonStyle.secondary,
            custom_id=ADD_COAUTHOR_ID,
        )

    async def callback(self, interaction: discord.Interaction):
        tc = _resolve_tc(interaction)
        if tc is None:
            await interaction.response.send_message(
                "This isn't a tracked testing channel.", ephemeral=True
            )
            return
        if not _is_owner_or_staff(interaction.user, tc):
            await interaction.response.send_message(
                "Only the channel owner can add co-authors.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Select the member(s) to add as co-author(s):",
            view=CoAuthorSelect(),
            ephemeral=True,
        )


class AddCoAuthorView(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.ActionRow(AddCoAuthorButton()))


class CoAuthorSelect(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.select = discord.ui.UserSelect(
            placeholder="Select co-author(s) to add...",
            min_values=1,
            max_values=25,
        )
        self.select.callback = self.callback
        self.add_item(self.select)

    async def callback(self, interaction: discord.Interaction):
        tc = _resolve_tc(interaction)
        if tc is None:
            await interaction.response.send_message(
                "This isn't a tracked testing channel.", ephemeral=True
            )
            return
        if not _is_owner_or_staff(interaction.user, tc):
            await interaction.response.send_message(
                "Only the channel owner can add co-authors.", ephemeral=True
            )
            return

        if await cooldown_response(interaction):
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        existing_ids = {author.id for author in tc.authors}
        additions = [m for m in self.select.values if m.id not in existing_ids]
        if not additions:
            await interaction.followup.send(
                "Those members are already owners.", ephemeral=True
            )
            return

        owners = list(tc.authors) + additions
        mentions = await apply_owners(tc, interaction.user, owners)

        added = ", ".join(m.mention for m in additions)
        await interaction.followup.send(
            f"Added {added} as co-author(s). Owners are now {mentions}.", ephemeral=True
        )
        await tc.channel.send(view=OwnerChanged(tc), allowed_mentions=discord.AllowedMentions.none())
