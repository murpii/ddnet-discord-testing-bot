import logging
from datetime import timedelta

import discord
from discord.ext import commands, tasks

from constants import Guilds
from extensions.map_testing.categories import category_registry
from extensions.map_testing.enums import MapState
from extensions.map_testing.views.embeds import GraceEndingSoon, GraceOver
from extensions.map_testing.views.inactivity import InactivityPrompt
from utils import changelog
from utils.misc import last_message_time, last_user_message
from utils.text import fmt_days, to_discord_timestamp

log = logging.getLogger("mt")


class TestingHousekeeper(commands.Cog):
    """Housekeeping over the tracked testing channels"""
    def __init__(self, bot):
        self.bot = bot

        def config_days(key: str, default: float) -> timedelta:
            return timedelta(days=bot.config.getfloat("TESTING_CHANNELS", key, fallback=default))

        self.grace_warning_lead = config_days("GRACE_WARNING_LEAD_DAYS", 2)
        self.grace_archive_buffer = config_days("GRACE_ARCHIVE_BUFFER_DAYS", 3)
        self.waiting_quiet_after = config_days("WAITING_QUIET_AFTER_DAYS", 14)
        self.prompt_no_response_after = config_days("PROMPT_NO_RESPONSE_AFTER_DAYS", 7)
        self.quiet_after_response = config_days("QUIET_AFTER_RESPONSE_DAYS", 30)

    async def cog_load(self):
        self.housekeeping_task.start()

    def cog_unload(self):
        self.housekeeping_task.cancel()

    @tasks.loop(hours=12)
    async def housekeeping_task(self):
        now = discord.utils.utcnow()
        for tc in list(self.bot.testing_manager.test_channels.values()):
            try:
                await self.check_channel(tc, now)
            except Exception:
                log.exception("Housekeeping failed for #%s", tc.channel)

        guild = self.bot.get_guild(Guilds.DDNET)
        if guild is not None:
            try:
                await category_registry.prune(guild)
            except Exception:
                log.exception("Pruning empty overflow categories failed")

    @housekeeping_task.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()
        await self.bot.testing_manager.channels_loaded.wait()

    async def check_channel(self, tc, now) -> None:
        entries = await changelog.read_entries(tc.channel.id)
        if not entries:
            return
        entries.sort(key=lambda entry: entry.timestamp, reverse=True)

        def newest(category):
            return next((entry for entry in entries if entry.category == category), None)

        if tc.state is MapState.RELEASED:
            await self.check_grace(tc, now, newest)
        elif tc.state is MapState.WAITING:
            await self.check_waiting(tc, now, newest)

    async def auto_archive(self, tc, reason: str) -> None:
        ok, detail = await self.bot.testing_manager.archive_channel(tc, reason=reason)
        if not ok:
            log.error("Auto-archive of #%s failed: %s", tc.channel, detail)

    async def check_grace(self, tc, now, newest) -> None:
        """
        Warn the mapper shortly before the release grace period ends, post a
        notice once it is over, then archive after a small buffer
        """
        released = newest("MapTesting/RELEASED")
        if released is None:
            return
        grace_end = released.timestamp + self.bot.testing_manager.grace_period

        if now >= grace_end + self.grace_archive_buffer and self.bot.testing_manager.delete_on_archive:
            await self.auto_archive(tc, "the release grace period ended")
            return

        if now >= grace_end:
            over = newest("MapTesting/GRACE_OVER")
            if over is not None and over.timestamp > released.timestamp:
                return
            await tc.channel.send(view=GraceOver(tc), allowed_mentions=discord.AllowedMentions.none())
            await self.bot.testing_manager.write_changelog(
                tc, self.bot.user,
                category="MapTesting/GRACE_OVER",
                string=f'The grace period of "{tc.map_name}" ended.',
            )
            return

        if now >= grace_end - self.grace_warning_lead:
            warned = newest("MapTesting/GRACE_WARNING")
            if warned is not None and warned.timestamp > released.timestamp:
                return
            await tc.channel.send(
                view=GraceEndingSoon(tc, to_discord_timestamp(grace_end, style="R")),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
            await self.bot.testing_manager.write_changelog(
                tc, self.bot.user,
                category="MapTesting/GRACE_WARNING",
                string=f'Grace period reminder sent for "{tc.map_name}".',
            )

    async def check_waiting(self, tc, now, newest) -> None:
        """
        Ask the mapper whether they still want the channel once WAITING goes
        quiet, then archive it if it stays quiet
        """
        entered = newest("MapTesting/WAITING") or newest("MapTesting/CREATION")
        if entered is None:
            return

        # a prompt from an earlier stay in WAITING doesn't count for this one
        prompt = newest("MapTesting/INACTIVITY_PROMPT")
        if prompt is None or prompt.timestamp < entered.timestamp:
            await self.prompt_if_quiet(tc, now, entered.timestamp)
        else:
            await self.archive_if_unanswered(tc, now, prompt.timestamp, newest)

    async def prompt_if_quiet(self, tc, now, entered_at) -> None:
        quiet_since = entered_at
        last_msg = last_message_time(tc.channel)
        if last_msg is not None and last_msg > quiet_since:
            quiet_since = last_msg
        if now - quiet_since < self.waiting_quiet_after:
            return

        await tc.channel.send(
            view=InactivityPrompt(tc, archive_after=fmt_days(self.prompt_no_response_after)),
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await self.bot.testing_manager.write_changelog(
            tc, self.bot.user,
            category="MapTesting/INACTIVITY_PROMPT",
            string="Asked the mapper(s) whether they want to continue.",
        )

    async def archive_if_unanswered(self, tc, now, prompted_at, newest) -> None:
        # checked first so channel history isn't read when nothing can come of it
        if not self.bot.testing_manager.delete_on_archive:
            return

        # a button and any user chat message both count as a response
        responses = []
        interested = newest("MapTesting/STILL_INTERESTED")
        if interested is not None:
            responses.append(interested.timestamp)
        human_msg = await last_user_message(tc.channel)
        if human_msg is not None:
            responses.append(human_msg)
        responded_at = max((stamp for stamp in responses if stamp > prompted_at), default=None)

        if responded_at is None:
            if now - prompted_at >= self.prompt_no_response_after:
                await self.auto_archive(tc, "there was no response to the inactivity check")
        elif now - responded_at >= self.quiet_after_response:
            await self.auto_archive(tc, "the channel stayed inactive after the inactivity check")
