import logging

import discord

from extensions.map_testing.enums import TestingChannelEvent
from extensions.map_testing.states import TransitionContext, resolve_transition
from extensions.map_testing.views.embeds import MapDeclined
from extensions.map_testing.scores import add_score

log = logging.getLogger("mt")


class DeclineReasonModal(discord.ui.Modal, title="Decline Reason"):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    decline_reason = discord.ui.TextInput(
        label="Your Decline Reason",
        placeholder="You can leave this blank. The modal exists so you can give the reason anonymously.",
        max_length=500,
        required=False,
        style=discord.TextStyle.long,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)
        if tc is None:
            await interaction.followup.send("This isn't a tracked testing channel.", ephemeral=True)
            return

        transition = resolve_transition(TestingChannelEvent.DECLINE, TransitionContext(state=tc.state, votes=tc.votes))
        if not transition.allowed:
            await interaction.followup.send(transition.reason, ephemeral=True)
            return

        # Anonymous when a reason IS supplied.
        # No reason -> attribute the decline to the tester (anonymity isn't needed).
        actor = self.bot.user if self.decline_reason.value else interaction.user
        await self.bot.testing_manager.apply_transition(
            tc, transition, actor,
            changelog_string=f'"{tc.map_name}" has been DECLINED.',
        )

        await interaction.followup.send(
            content=f'Declined submission "{tc.map_name}" successfully.',
            ephemeral=True,
        )

        await tc.channel.send(
            view=MapDeclined(tc, self.decline_reason.value),
            allowed_mentions=discord.AllowedMentions(users=True),
        )

        await add_score(interaction.user.id, "DECLINED")
        self.bot.testing_manager.request_scores_refresh()
        log.info("%s declined submission #%s", interaction.user, tc.channel)