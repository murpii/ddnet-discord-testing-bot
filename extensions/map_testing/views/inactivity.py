import logging

import discord
from discord.ui import Button

from constants import Roles
from extensions.map_testing.views.approval import resolved
from utils.checks import is_staff

log = logging.getLogger("mt")

ANSWER_ROLES = [
    Roles.ADMIN,
    Roles.TESTER,
    Roles.TESTER_EXCL_TOURNAMENTS,
    Roles.TRIAL_TESTER,
    Roles.TRIAL_TESTER_EXCL_TOURNAMENTS,
]


async def resolve_prompt_channel(interaction: discord.Interaction, channel_id: int):
    tc = interaction.client.testing_manager.test_channels.get(channel_id)
    if tc is None:
        await interaction.response.send_message(
            "This isn't a tracked testing channel anymore.", ephemeral=True
        )
        return None

    is_mapper = interaction.user.id in {author.id for author in tc.authors}
    if not is_mapper and not is_staff(interaction.user, roles=ANSWER_ROLES):
        await interaction.response.send_message(
            "Only the mapper(s) or a tester can answer this.", ephemeral=True
        )
        return None
    return tc


class StillInterestedButton(
    discord.ui.DynamicItem[Button],
    template=r"mt_inactive_yes:(?P<channel_id>\d+)",
):
    def __init__(self, channel_id: int):
        self.channel_id = channel_id
        super().__init__(Button(
            label="Yes, I'm still working on it",
            style=discord.ButtonStyle.green,
            custom_id=f"mt_inactive_yes:{channel_id}",
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["channel_id"]))

    async def callback(self, interaction: discord.Interaction):
        tc = await resolve_prompt_channel(interaction, self.channel_id)
        if tc is None:
            return

        await interaction.response.edit_message(view=resolved(
            f"✅ {interaction.user.display_name} confirmed the map is still being worked on.",
            discord.Color.green(),
        ))
        await interaction.client.testing_manager.write_changelog(
            tc, interaction.user,
            category="MapTesting/STILL_INTERESTED",
            string="The mapper confirmed they want to continue.",
        )


class ArchiveRequestButton(
    discord.ui.DynamicItem[Button],
    template=r"mt_inactive_no:(?P<channel_id>\d+)",
):
    def __init__(self, channel_id: int):
        self.channel_id = channel_id
        super().__init__(Button(
            label="No, archive the channel",
            style=discord.ButtonStyle.danger,
            custom_id=f"mt_inactive_no:{channel_id}",
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["channel_id"]))

    async def callback(self, interaction: discord.Interaction):
        tc = await resolve_prompt_channel(interaction, self.channel_id)
        if tc is None:
            return

        await interaction.response.edit_message(view=resolved(
            f"🗑️ {interaction.user.display_name} asked to archive the channel. Archiving now...",
            discord.Color.dark_gray(),
        ))
        ok, detail = await interaction.client.testing_manager.archive_channel(
            tc, reason="the mapper asked to archive it"
        )
        if not ok:
            log.error("Archive requested via prompt failed for #%s: %s", tc.channel, detail)
            await interaction.edit_original_response(view=resolved(
                "⚠️ Archiving failed, the testers will take care of it.",
                discord.Color.orange(),
            ))


class InactivityPrompt(discord.ui.LayoutView):
    def __init__(self, tc, archive_after: str):
        super().__init__(timeout=None)
        buttons = discord.ui.ActionRow()
        buttons.add_item(StillInterestedButton(tc.channel.id))
        buttons.add_item(ArchiveRequestButton(tc.channel.id))
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                f"{tc.mapper_mentions} This channel has been in **WAITING MAPPER** for a while. "
                "Are you still interested in continuing this map?\n"
                f"-# Without a response, the channel gets archived after {archive_after}. "
                "Its full history stays available in the public testlog archive."
            ),
            buttons,
            accent_colour=discord.Color.dark_purple(),
        ))
