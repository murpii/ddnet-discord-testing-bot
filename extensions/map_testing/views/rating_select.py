import io
import logging
import re
from io import BytesIO

import discord

from extensions.map_testing.enums import MapState, TestingChannelEvent
from extensions.map_testing.models.submissions import Submission
from extensions.map_testing.services.checker import MapChecker
from extensions.map_testing.states import TransitionContext, resolve_transition, role_tier
from extensions.map_testing.utils.map_tools import MapEditor
from extensions.map_testing.scores import add_score
from extensions.map_testing.views.embeds import MapReady, ReadyEmbed, TrialReadyEmbed, VoteNeedsTester
from extensions.map_testing.views.error_report import ErrorReporter
from utils import changelog
from utils.misc import rating

log = logging.getLogger("mt")

VOTE_CLEARING_CATEGORIES = {"MapTesting/RESET", "MapTesting/AUTO_RESET", "MapTesting/WAITING"}
STARS_RE = re.compile(r"[★☆]{5}")


async def collect_prior_ratings(channel_id: int) -> list[str]:
    entries = await changelog.read_entries(channel_id)
    entries.sort(key=lambda entry: entry.timestamp, reverse=True)
    ratings = []
    for entry in entries:
        if entry.category in VOTE_CLEARING_CATEGORIES:
            break
        if entry.category == "MapTesting/RC" and entry.action:
            match = STARS_RE.search(entry.action)
            if match:
                ratings.append(match.group())
    ratings.reverse()
    return ratings


async def _report_map_errors(submission: Submission, interaction: discord.Interaction) -> bool:
    """Run the map check; if it fails, surface the output on the deferred interaction.

    Returns True when errors were found, False otherwise.
    """
    output = await MapChecker.debug(submission)
    if not output:
        return False

    prefix = "Unable to ready map. Fix the map 🐞's first:"
    if len(output) < 1900:
        await interaction.edit_original_response(content=f"{prefix}\n```{output}```")
    else:
        # Keep the output ephemeral to the tester (the interaction is already
        # ephemeral) rather than posting it into the channel.
        file = discord.File(io.StringIO(output), filename="debug_output.txt")
        await interaction.edit_original_response(
            content=f"{prefix} See the attached debug output.", attachments=[file]
        )
    return True


class RatingSelect(ErrorReporter, discord.ui.View):
    """Ephemeral rating select shown after the Ready button.

    First press (TESTING -> RC) records the tester's vote and posts a suggested
    rating. Second press by a *different* tester (RC -> READY) re-checks the map,
    optimizes it and finalizes the channel.
    """

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.select = discord.ui.Select(
            placeholder="Choose a rating...",
            options=rating(),
            custom_id="mt_rselect",
        )
        self.select.callback = self.callback
        self.add_item(self.select)

    async def callback(self, interaction: discord.Interaction):
        label = next(o.label for o in rating() if o.value == self.select.values[0])
        if await self.ready_callback(interaction, label):
            await add_score(interaction.user.id, "READY")
            self.bot.testing_manager.request_scores_refresh()

    async def ready_callback(self, interaction: discord.Interaction, rating_label: str) -> bool:
        """Record a ready vote. Returns True if a vote was actually cast"""
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)
        if tc is None:
            await interaction.response.send_message(
                "This isn't a tracked testing channel.", ephemeral=True
            )
            return False

        ctx = TransitionContext(
            state=tc.state,
            votes=tc.votes,
            actor_id=interaction.user.id,
            actor_tier=role_tier(interaction.user),
            is_author=interaction.user.id in {a.id for a in tc.authors},
            bot_id=self.bot.user.id,
        )
        transition = resolve_transition(TestingChannelEvent.READY_VOTE, ctx)
        if not transition.allowed:
            await interaction.response.send_message(transition.reason, ephemeral=True)
            return False

        await interaction.response.defer(thinking=True, ephemeral=True)

        if transition.requires_map_recheck:
            return await self.finalize_ready(interaction, tc, transition, rating_label)

        stars = rating_label.removeprefix("Rating: ")
        map_url = tc.submission.message.jump_url if tc.submission else None
        manager = self.bot.testing_manager
        if ctx.state is MapState.RC:
            # The vote counts, but every voter so far is a Trial Tester, a full
            # Tester is still required to push the map to READY.
            await manager.apply_transition(
                tc, transition, interaction.user,
                changelog_string=f'"{tc.map_name}" received an additional vote ({stars}); a full Tester is still required for READY.',
                changelog_url=map_url,
                notice=VoteNeedsTester(tc, interaction.user),
            )
            await interaction.edit_original_response(
                content="Vote recorded, a full Tester still needs to confirm before READY."
            )
            return True

        # First vote: TESTING -> RC.
        embed = TrialReadyEmbed(rating_label) if ctx.actor_tier == "trial" else ReadyEmbed(rating_label)
        await manager.apply_transition(
            tc, transition, interaction.user,
            changelog_string=f'"{tc.map_name}" has been set to RELEASE CANDIDATE with a suggested rating of {stars}.',
            changelog_url=map_url,
            notice=embed,
        )
        await interaction.edit_original_response(content="Map channel state has been changed to RC.")
        return True

    async def finalize_ready(self, interaction: discord.Interaction, tc, transition, rating_label: str) -> bool:
        """Second vote reached READY: re-check, optimize and finalize the map.

        Returns True if the map was set to READY, False if it bailed (no current
        map or the map check failed) so no vote is counted.
        """

        submission = tc.submission
        if submission is None:
            await interaction.edit_original_response(content="No map file to optimize.")
            return False

        if await _report_map_errors(submission, interaction):
            return False

        stars = rating_label.removeprefix("Rating: ")
        prior_ratings = await collect_prior_ratings(tc.channel.id)
        await self.bot.testing_manager.apply_transition(
            tc, transition, interaction.user,
            changelog_string=f'"{tc.map_name}" has been set to state READY with a suggested rating of {stars}.',
            changelog_url=submission.message.jump_url,
        )

        current = submission.message
        file = None
        if current.content.startswith("Optimized"):
            detail = f"Optimized version: {current.jump_url}\n"
        else:
            try:
                stdout, edited = await MapEditor.edit(
                    submission, "--remove-everything-unused", "--shrink-tiles-layers"
                )
            except Exception:
                log.exception("Optimization failed for %s", tc.map_name)
                detail = "⚠️ Automatic optimization failed, please optimize and attach the map manually.\n"
            else:
                if edited is not None:
                    file = discord.File(BytesIO(edited), filename=f"{tc.filename}.map")
                if stdout and len(stdout) > 1500:
                    stdout = stdout[:1500] + "\n[...]"
                detail = (
                    f"Optimized version attached.\nChangelog:\n```{stdout}```\n"
                    if stdout else "Optimized version attached.\n"
                )

        detail += f"Unoptimized version: {current.jump_url}"

        all_ratings = prior_ratings + [stars]
        if len(all_ratings) > 1:
            rating_text = "Suggested ratings: " + ", ".join(all_ratings)
        else:
            rating_text = rating_label
        ready_message = await tc.channel.send(view=MapReady(tc, rating_text, detail))
        if file is not None:
            await ready_message.reply(file=file, mention_author=False)
        await interaction.edit_original_response(content="Map channel has been set to READY.")
        return True