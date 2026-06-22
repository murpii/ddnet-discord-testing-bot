import logging

import discord
from discord.ui import Button
from discord.ext import commands

from constants import Roles
from extensions.map_testing.cooldown import cooldown_response
from extensions.map_testing.services.checker import MapChecker
from extensions.map_testing.views.approval import send_debug_output
from extensions.map_testing.enums import TestingChannelEvent
from extensions.map_testing.states import TransitionContext, resolve_transition, role_tier
from extensions.map_testing.scores import add_score
from extensions.map_testing.views.embeds import ResetToTesting, WaitingMapper
from extensions.map_testing.views.rating_select import RatingSelect
from extensions.map_testing.views.server_select import ServerSelect
from extensions.map_testing.views.owner_select import OwnerSelect
from extensions.map_testing.views.modals.decline import DeclineReasonModal
from extensions.map_testing.views.modals.change_name import ChangeMapNameModal
from extensions.map_testing.views.modals.change_mappers import ChangeMappersModal
from utils.checks import is_staff

log = logging.getLogger("mt")

TESTER_ROLES = [
    Roles.ADMIN,
    Roles.TESTER,
    Roles.TESTER_EXCL_TOURNAMENTS,
    Roles.TRIAL_TESTER,
    Roles.TRIAL_TESTER_EXCL_TOURNAMENTS,
]

TESTER_CONTROLS_TEXT = (
    "## Tester Controls\n"
    f"<@&{Roles.TESTER}> Use these options to make changes:\n\n"
    "**Keep in mind:**\n"
    "Only **two** map updates are possible every **15 minutes**, "
    "otherwise the bot gets rate-limited."
)


class TestingMenu(discord.ui.LayoutView):
    """Persistent tester-control menu posted in each map channel's thread.

    Registered once via ``bot.add_view(TestingMenu(bot))`` so the buttons keep
    working after restarts.
    """

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        # Anti-spam: one press per user per 3s.
        self.cooldown = commands.CooldownMapping.from_cooldown(1.0, 3.0, lambda i: i.user.id)

        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(TESTER_CONTROLS_TEXT),
            accent_colour=discord.Color.blurple(),
        ))

        controls = [
            ("Ready", discord.ButtonStyle.green, "TestingMenu:ready", self.mt_ready),
            ("Waiting Mapper", discord.ButtonStyle.primary, "TestingMenu:waiting", self.mt_waiting),
            ("Decline", discord.ButtonStyle.danger, "TestingMenu:decline", self.mt_decline),
            ("Reset", discord.ButtonStyle.secondary, "TestingMenu:reset", self.mt_reset),
            ("Set to Released", discord.ButtonStyle.secondary, "TestingMenu:released", self.mt_released),
            ("Change Map Name", discord.ButtonStyle.secondary, "TestingMenu:CName", self.mt_change_name),
            ("Change Mappers", discord.ButtonStyle.secondary, "TestingMenu:CMappers", self.mt_change_mappers),
            ("Change Submission Owner", discord.ButtonStyle.secondary, "TestingMenu:COwner", self.mt_change_owner),
            ("Change Server", discord.ButtonStyle.secondary, "TestingMenu:CServer", self.mt_change_server),
            ("Debug", discord.ButtonStyle.secondary, "TestingMenu:debug", self.mt_debug),
            ("Archive", discord.ButtonStyle.danger, "TestingMenu:archive", self.mt_archive),
        ]
        rows = [discord.ui.ActionRow() for _ in range((len(controls) + 4) // 5)]
        for index, (label, style, custom_id, callback) in enumerate(controls):
            button = Button(label=label, style=style, custom_id=custom_id)
            button.callback = callback
            rows[index // 5].add_item(button)
        for row in rows:
            self.add_item(row)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.cooldown.update_rate_limit(interaction):
            await interaction.response.send_message("Hey! Don't spam the buttons.", ephemeral=True)
            return False

        if not is_staff(interaction.user, roles=TESTER_ROLES):
            await interaction.response.send_message(
                "You're missing the required role to do that!", ephemeral=True
            )
            return False

        if self.bot.testing_manager.get_tc_from_interaction(interaction) is None:
            await interaction.response.send_message(
                "This isn't a tracked testing channel.", ephemeral=True
            )
            return False

        # Debug is read-only -- t doesn't edit the channel, so it's exempt from the
        # channel-edit cooldown (still spam- and role-gated by the checks above).
        if interaction.data.get("custom_id") == "TestingMenu:debug":
            return True

        # Channel-edit cooldown (Discord allows ~2 edits / 15 min per channel).
        return not await cooldown_response(interaction)

    async def mt_ready(self, interaction: discord.Interaction):
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)

        # Pre-check the ready vote so we reject early instead of opening the rating
        # select. The actual vote is committed (re-resolved) in RatingSelect.
        ctx = TransitionContext(
            state=tc.state, votes=tc.votes,
            actor_id=interaction.user.id,
            actor_tier=role_tier(interaction.user),
            is_author=interaction.user.id in {author.id for author in tc.authors},
            bot_id=self.bot.user.id,
        )
        transition = resolve_transition(TestingChannelEvent.READY_VOTE, ctx)
        if not transition.allowed:
            await interaction.response.send_message(transition.reason, ephemeral=True)
            if ctx.is_author:
                log.info("Blocked %s from readying their own map in #%s", interaction.user, tc.channel)
            return

        await interaction.response.send_message(
            "Please select a map rating:", view=RatingSelect(self.bot), ephemeral=True
        )

    async def mt_waiting(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)

        transition = resolve_transition(TestingChannelEvent.MOVE_WAITING, TransitionContext(state=tc.state, votes=tc.votes))
        if not transition.allowed:
            await interaction.followup.send(transition.reason, ephemeral=True)
            return

        await self.bot.testing_manager.apply_transition(
            tc, transition, interaction.user,
            changelog_string=f'"{tc.map_name}" has been moved to WAITING.',
            notice=WaitingMapper(tc),
            ping_mappers=True,
        )
        await add_score(interaction.user.id, "WAITING")
        self.bot.testing_manager.request_scores_refresh()
        await interaction.followup.send("Map channel has been moved to waiting mapper.", ephemeral=True)

    async def mt_decline(self, interaction: discord.Interaction):
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)

        transition = resolve_transition(TestingChannelEvent.DECLINE, TransitionContext(state=tc.state, votes=tc.votes))
        if not transition.allowed:
            await interaction.response.send_message(transition.reason, ephemeral=True)
            return

        await interaction.response.send_modal(DeclineReasonModal(self.bot))

    async def mt_reset(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)

        transition = resolve_transition(TestingChannelEvent.RESET, TransitionContext(state=tc.state, votes=tc.votes))
        await self.bot.testing_manager.apply_transition(
            tc, transition, interaction.user,
            changelog_string=f'"{tc.map_name}" has been RESET.',
            notice=ResetToTesting(tc),
        )
        await interaction.followup.send("Moved channel back to TESTING.", ephemeral=True)

    async def mt_released(self, interaction: discord.Interaction):
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)

        transition = resolve_transition(TestingChannelEvent.RELEASE, TransitionContext(state=tc.state, votes=tc.votes))
        if not transition.allowed:
            await interaction.response.send_message(transition.reason, ephemeral=True)
            return

        message = await self.bot.testing_manager.release_channel(
            tc, interaction.user,
            changelog_string=f'"{tc.map_name}" has been manually set to RELEASED.',
        )
        await interaction.response.send_message(
            f"Map channel set to RELEASED: {message.jump_url}", ephemeral=True
        )

    async def mt_change_name(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ChangeMapNameModal(self.bot))

    async def mt_change_mappers(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ChangeMappersModal(self.bot))

    async def mt_change_owner(self, interaction: discord.Interaction):
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)
        await interaction.response.send_message(
            "Select the channel owner(s):",
            view=OwnerSelect(self.bot, tc.authors),
            ephemeral=True,
        )

    async def mt_change_server(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Please select a server:", view=ServerSelect(self.bot), ephemeral=True
        )

    async def mt_debug(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not MapChecker.enabled:
            await interaction.followup.send(
                "Automatic map checks are disabled on this instance.", ephemeral=True
            )
            return
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)
        if tc.submission is None:
            await interaction.followup.send("No map is pinned in this channel yet.", ephemeral=True)
            return

        output, cached = await MapChecker.debug_detailed(tc.submission)
        await send_debug_output(interaction, output, cached=cached)

    async def mt_archive(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)
        await self.bot.testing_manager.archive_channel(tc, interaction)
