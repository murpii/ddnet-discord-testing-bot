import asyncio
import logging
import re
from datetime import timedelta

import discord

from constants import Guilds, Channels, DIFF_THREAD_NAME
from extensions.map_testing.cooldown import global_cooldown
from extensions.map_testing.enums import ApprovalResult, MapState, TestingChannelEvent
from extensions.map_testing.models.channel_factory import TestingChannel
from extensions.map_testing.states import Transition, TransitionContext, resolve_transition
from extensions.map_testing.models.submissions import Submission, InitialSubmission
from extensions.map_testing.services.checker import MapChecker
from extensions.map_testing.services.channel import build_channel
from extensions.map_testing.services.loader import load_testing_channel, load_submission_from_pins
from extensions.map_testing.services.released_maps import ReleasedMaps, ReleasedMapsUnavailable
from extensions.map_testing.services.uploader import upload_submission
from extensions.map_testing.mapdiff import MapDiff, VersionDiff, clear_channel_diffs
from extensions.map_testing.testlog import TestLog, archive_testlog
from extensions.map_testing.scores import ScoresTopicUpdater
from extensions.map_testing.views.approval import (
    ChannelUploadApproval,
    DebugReport,
    SubmitBuggyApproval,
    SubmitCleanApproval,
)
from extensions.map_testing.views.embeds import (
    BuggyWaiting,
    IdenticalUpload,
    MapReleased,
    MovedBackAfterUpdate,
    SubmissionDeclinedNotice,
)
from utils import changelog_store
from utils.checks import is_staff
from utils.conn import ddnet_delete
from utils.text import to_discord_timestamp

log = logging.getLogger("mt")

# Matches the [Map Name](https://ddnet.org/maps/?map=...) link in a release announcement.
RELEASE_ANNOUNCEMENT_RE = re.compile(
    r"\[(?P<name>.+?)\]\(<?https://ddnet\.org/(?:maps|mappreview)/\?map=.+?>?\)"
)


class TestingManager:
    def __init__(self, bot):
        self.bot = bot
        self.test_channels: dict[int, TestingChannel] = {}
        self.scores_topic = ScoresTopicUpdater(bot)
        self.lock = asyncio.Lock()
        # submit-message IDs currently being (or already) turned into a channel.
        # blocks (hopefully) staff approving the same submission simultaneously.
        self.building: set[int] = set()

        # sourced from ddnet.org's release list.
        self.released_maps = ReleasedMaps(bot)

        self.pending_approvals: dict[int, tuple[int, int]] = {}

    def track_approval(self, upload_id: int, prompt: discord.Message) -> None:
        self.pending_approvals[upload_id] = (prompt.channel.id, prompt.id)

    def untrack_approval(self, upload_id: int) -> None:
        self.pending_approvals.pop(upload_id, None)

    def request_scores_refresh(self) -> None:
        self.scores_topic.request()

    def debug_dump(self):
        for cid, tc in self.test_channels.items():
            print(
                f"\nChannel ID: {cid}\n"
                f"  Name: {tc.channel.name}\n"
                f"  State: {tc.state.name}\n"
                f"  Authors: {[a.id for a in tc.authors]}\n"
                f"  Votes: {tc.votes}\n"
                f"  Submission: {tc.submission}\n"
                f"  MapName: \"{tc.map_name}\"\n"
                f"  Server: {tc.server}\n"
            )

    async def load_testing_channels(self):
        guild = self.bot.get_guild(Guilds.DDNET)
        config = self.bot.config

        excluded = set()
        if config.has_option("TESTING_CHANNELS", "EXCLUDE"):
            excluded = {
                int(x.strip())
                for x in config.get("TESTING_CHANNELS", "EXCLUDE").split(",")
                if x.strip().isdigit()
            }

        categories = (Channels.CAT_TESTING, Channels.CAT_WAITING, Channels.CAT_EVALUATED)
        channels = [
            channel
            for category in guild.categories if category.id in categories
            for channel in category.text_channels if channel.id not in excluded
        ]

        # STILL TESTING, UNSURE IF SAFE:
        # Load channels concurrently but bounded, so a guild with many testing
        # channels doesn't burst the Discord REST API and trip rate limits.
        sem = asyncio.Semaphore(8)

        async def _load(channel):
            async with sem:
                return await load_testing_channel(self.bot, channel)

        results = await asyncio.gather(
            *(_load(c) for c in channels), return_exceptions=True
        )
        for channel, result in zip(channels, results):
            if isinstance(result, Exception):
                log.warning("Failed to load testing channel #%s (%d): %s", channel.name, channel.id, result)
            else:
                self.test_channels[channel.id] = result

        # Reflect the current scores in the TESTER_CHAT topic on startup.
        self.request_scores_refresh()

    async def handle_initial_submission(self, message: discord.Message):
        attachment = next(
            (a for a in message.attachments if a.filename.endswith(".map")), None
        )
        if not attachment:
            return

        isubm = InitialSubmission(message=message, attachment=attachment)
        try:
            isubm.parse()
        except ValueError:
            await message.reply(
                "❌ That isn't a valid submission. Use the format "
                '`"Map Name" by Mapper [Server]` with a matching `.map` file attached.',
                mention_author=False,
            )
            log.info("Rejected malformed submission %r from %s", attachment.filename, message.author)
            return

        # Map Name check. If the released-map list is momentarily unavailable we
        # don't punish the author here -- the approval step re-checks and fails
        # closed, so a possibly-released name still can't create a channel.
        try:
            conflict = await self.name_conflict(isubm.name)
        except ReleasedMapsUnavailable as exc:
            log.warning("Released-map check unavailable while validating %r: %s", isubm.name, exc)
            conflict = None
        if conflict:
            await self.decline_submission(isubm, conflict)
            return

        # twmaps check
        debug_output = await MapChecker.debug(isubm)
        if debug_output:
            prompt = await message.reply(
                view=SubmitBuggyApproval(self.bot),
                mention_author=False,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
            self.track_approval(message.id, prompt)
            log.info("Submission %r from %s failed map validation", isubm.filename, message.author)
            return

        # Valid map: post the approval buttons. The testing channel is only created
        # once a staff member clicks Approve (see SubmitCleanApproval / approve_submission).
        prompt = await message.reply(
            view=SubmitCleanApproval(self.bot, message.author),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.track_approval(message.id, prompt)
        log.info("Submission %r from %s validated; awaiting staff approval", isubm.filename, message.author)

    async def name_conflict(self, name: str) -> str | None:
        """Return a reason if a map named `name` already exists, else None.

        Raises ``ReleasedMapsUnavailable`` if the released-map list can't be
        consulted and nothing is cached, so callers can fail closed rather than
        risk creating a channel for an already-released map.
        """
        lowered = name.lower()
        if any(tc.map_name.lower() == lowered for tc in self.test_channels.values()):
            return "a testing channel for a map with that name already exists"

        if await self.released_maps.is_released(name):
            return "a map with that name has already been released"

        return None

    @staticmethod
    async def decline_submission(isubm: InitialSubmission, reason: str) -> None:
        """Reject a submission and DM the author the reason."""
        notice = f"Your map submission **{isubm.name}** was declined because {reason}."
        try:
            await isubm.author.send(notice)  # noqa
        except discord.Forbidden:
            await isubm.message.channel.send(
                view=SubmissionDeclinedNotice(isubm.author, isubm.name, reason),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        log.info("Declined submission %r: %s", isubm.filename, reason)

    async def approve_submission(
            self, message: discord.Message, member
    ) -> tuple[ApprovalResult, TestingChannel | None]:
        """Build the testing channel for a validated submission."""
        attachment = next(
            (a for a in message.attachments if a.filename.endswith(".map")), None
        )
        if not attachment:
            return ApprovalResult.BUSY, None

        isubm = InitialSubmission(message=message, attachment=attachment).parse()

        async with self.lock:
            if message.id in self.building:
                return ApprovalResult.BUSY, None

            # Re-check under the lock: a same named map may have been approved
            # or released since this submission was validated. If we can't verify
            # against the released-map list, fail closed & don't build the channel.
            try:
                conflict = await self.name_conflict(isubm.name)
            except ReleasedMapsUnavailable as exc:
                log.warning("Released-map check unavailable approving %r: %s", isubm.name, exc)
                return ApprovalResult.UNVERIFIED, None
            if conflict:
                await self.decline_submission(isubm, conflict)
                return ApprovalResult.CONFLICT, None
            self.building.add(message.id)
            try:
                tc = await build_channel(self.bot, isubm)
                self.test_channels[tc.channel.id] = tc
            except Exception:
                # Allow another approval attempt if creation failed midway.
                self.building.discard(message.id)
                raise

        log.info("%s approved submission %r -> #%s", member, isubm.filename, tc.channel)

        try:
            await upload_submission(self.bot.session, tc.submission, tc, self.bot.config)
        except RuntimeError as exc:
            log.error("Initial submission upload failed for %r in #%s: %s", tc.filename, tc.channel, exc)
        else:
            log.info("Uploaded %r to the test backend", tc.filename)
        # Release the in-memory map, buffer() re-fetches lazily if a later diff/optimize needs it.
        tc.submission.bytes = None
        return ApprovalResult.CREATED, tc

    async def force_accept_submission(
            self, message: discord.Message, member
    ) -> tuple[ApprovalResult, TestingChannel | None]:
        """Accepts a *bugged* submission into WAITING.

        The counterpart to approve_submission for maps that failed the automatic
        checks. Rather than blocking the submission, an Admin or Tester can take it
        into testing anyway. The channel is created straight in WAITING MAPPER, the
        bug report is posted there, and the map is uploaded so it can be playtested.
        """
        attachment = next(
            (a for a in message.attachments if a.filename.endswith(".map")), None
        )
        if not attachment:
            return ApprovalResult.BUSY, None

        isubm = InitialSubmission(message=message, attachment=attachment).parse()

        async with self.lock:
            if message.id in self.building:
                return ApprovalResult.BUSY, None

            try:
                conflict = await self.name_conflict(isubm.name)
            except ReleasedMapsUnavailable as exc:
                log.warning("Released-map check unavailable force-accepting %r: %s", isubm.name, exc)
                return ApprovalResult.UNVERIFIED, None
            if conflict:
                await self.decline_submission(isubm, conflict)
                return ApprovalResult.CONFLICT, None
            self.building.add(message.id)

            try:
                # moved directly in WAITING.
                tc = await build_channel(self.bot, isubm, state=MapState.WAITING)
                self.test_channels[tc.channel.id] = tc
                await tc.channel.send(view=BuggyWaiting(tc), allowed_mentions=discord.AllowedMentions(users=True))
            except Exception:
                # allow another accept attempt if creation failed midway.
                self.building.discard(message.id)
                raise

        log.info("%s force-accepted buggy submission %r -> #%s (WAITING)", member, isubm.filename, tc.channel)

        # Post the bug report in the new channel and push the map to the test backend
        debug_output = await MapChecker.debug(isubm)
        if debug_output:
            await self.debug_report(tc.submission.message)

        try:
            await upload_submission(self.bot.session, tc.submission, tc, self.bot.config)
        except RuntimeError as exc:
            log.error("Initial upload failed for %r in #%s: %s", tc.filename, tc.channel, exc)
        else:
            log.info("Uploaded %r to the test backend", tc.filename)
        # Release the in-memory map; buffer() re-fetches lazily if a later diff/optimize needs it
        tc.submission.bytes = None
        return ApprovalResult.CREATED, tc

    async def decline_isubm_submission(self, message: discord.Message, member, reason: str) -> None:
        """
        Decline a #submit-maps submission via the Decline button.
        Parses the submission off the original message and DMs the author.
        """
        attachment = next(
            (a for a in message.attachments if a.filename.endswith(".map")), None
        )
        if not attachment:
            raise ValueError("no map attachment")
        initial = InitialSubmission(message=message, attachment=attachment).parse()
        await self.decline_submission(initial, reason or "it did not meet our submission requirements")
        log.info("%s declined submission %r", member, initial.filename)

    async def debug_report(self, map_message: discord.Message) -> None:
        """
        Sends a 'Map Bugs found!' notice as a reply to the map message.
        The debug output itself is never written to the channel, the notice's button
        reveals it ephemerally on demand.
        """
        await map_message.reply(
            view=DebugReport(self.bot),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def handle_testing_submission(self, message: discord.Message, tc: TestingChannel):
        attachment = next(
            (a for a in message.attachments if a.filename.endswith(".map")),
            None
        )
        if not attachment:
            return

        submission = Submission(message=message, attachment=attachment)
        debug_output = await MapChecker.debug(submission)

        filename_matches = attachment.filename[:-4].lower() == tc.map_name.lower()
        is_author = message.author.id in {author.id for author in tc.authors}
        is_trusted = is_staff(message.author) or is_author

        # A clean upload from a trusted author with the right filename goes live immediatelyy
        if is_trusted and filename_matches and not debug_output:
            if await self.same_as_current(tc, submission):
                await message.reply(
                    view=IdenticalUpload(),
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                log.info("Skipped identical re-upload from %s in #%s", message.author, tc.channel)
                return
            previous = tc.submission
            await upload_submission(self.bot.session, submission, tc, self.bot.config)
            await self.set_current_map(tc, submission)
            log.info("%s uploaded a new map version in #%s", message.author, tc.channel)
            await self.apply_author_update(tc, message.author)
            await self.post_version_diff(tc, previous, submission)
            submission.bytes = None  # release the in-memory map; re-fetched lazily if needed
            return

        # Bad update from the map author (right filename): never force-upload it.
        # Report the bugs and, if the map had progressed, bump it to WAITING so the
        # author fixes and resubmits.
        if is_author and filename_matches and debug_output:
            await self.debug_report(message)
            await self.waiting_for_bugs(tc, message.author)
            log.info("Rejected bad update from author %s in #%s", message.author, tc.channel)
            return

        # Otherwise (non-author, or filename mismatch) hold for manual approval via
        # the Approve-Upload button, which uploads it as-is (override possible).
        reasons = []
        if debug_output:
            reasons.append("failed map checks")
        if not filename_matches:
            reasons.append(f"filename doesn't match `{tc.map_name}.map`")
        if not is_trusted:
            reasons.append("uploaded by a non-author")
        reason = ", ".join(reasons)

        if debug_output:
            await self.debug_report(message)

        prompt = await message.channel.send(
            view=ChannelUploadApproval(self.bot, message.author, reason),
            allowed_mentions=discord.AllowedMentions.none(),
            reference=message,
        )
        self.track_approval(message.id, prompt)
        log.info("Submission from %s in #%s awaiting approval (%s)", message.author, tc.channel, reason)

    async def confirm_upload(self, message: discord.Message, member) -> bool:
        """Upload a pending submission as is and make it the channel's current map.
        Returns False (uploading nothing) when it is identical to the current map."""
        tc = self.test_channels.get(message.channel.id)
        if tc is None:
            return False

        attachment = next(
            (a for a in message.attachments if a.filename.endswith(".map")),
            None
        )
        if not attachment:
            return False

        submission = Submission(message=message, attachment=attachment)
        if await self.same_as_current(tc, submission):
            log.info("Skipped identical approved upload from %s in #%s", member, tc.channel)
            return False

        previous = tc.submission
        await upload_submission(self.bot.session, submission, tc, self.bot.config)
        await self.set_current_map(tc, submission)
        log.info("%s approved & uploaded a pending submission in #%s", member, tc.channel)
        await self.apply_author_update(tc, submission.message.author)
        await self.post_version_diff(tc, previous, submission)
        submission.bytes = None  # release the in-memory map; re-fetched lazily if needed
        return True

    async def set_current_map(self, tc: TestingChannel, submission: Submission) -> None:
        """
        Makes a ``submission`` the channel's current map.
        Pins the new submission's message and unpins the previous current map
        """
        tc.submission = submission

        if not submission.message.pinned:
            try:
                await submission.message.pin()
            except discord.HTTPException as exc:
                log.warning("Failed to pin submission in #%s: %s", tc.channel, exc)

    @staticmethod
    async def same_as_current(tc: TestingChannel, submission: Submission) -> bool:
        """
        True if `submission` is byte-identical to the channel's current map, so
        there's nothing new to upload.
        """
        current = tc.submission
        if current is None:
            return False
        try:
            current_bytes = (await current.buffer()).getvalue()
            new_bytes = (await submission.buffer()).getvalue()
        except discord.HTTPException:
            return False
        return current_bytes == new_bytes

    async def diff_against_base(
            self, tc: TestingChannel, previous: Submission | None, new: Submission
    ) -> tuple[Submission | None, "MapDiffResult | None"]:
        if previous is not None and previous.message.id != new.message.id:
            try:
                return previous, await MapDiff.diff(previous, new)
            except Exception:
                log.warning("Diff against the previous version failed in #%s; trying pins", tc.channel)

        base = await load_submission_from_pins(tc.channel, exclude_message_id=new.message.id)
        if base is None or base.message.id == new.message.id:
            return None, None
        try:
            return base, await MapDiff.diff(base, new)
        except Exception:
            log.exception("Version diff failed in #%s", tc.channel)
            return None, None

    async def post_version_diff(self, tc: TestingChannel, previous: Submission | None, new: Submission) -> None:
        """Post what changed vs. the previous map in a thread off the new upload."""
        baseline, result = await self.diff_against_base(tc, previous, new)
        if result is None or not result.has_changes:
            return

        view = VersionDiff(
            result.summary_markdown(), baseline.message.id, new.message.id,
            show_visual_diff=self.bot.rendering_enabled,
            compared_url=baseline.message.jump_url,
        )
        try:
            thread = await new.message.create_thread(name=DIFF_THREAD_NAME)
        except discord.HTTPException as exc:
            # Thread creation can fail (already has a thread, missing perms, etc).
            # Fall back to the previous behaviour: reply in-channel.
            log.warning("Couldn't create diff thread in #%s (%s); replying in-channel", tc.channel, exc)
            try:
                await new.message.reply(
                    view=view, mention_author=False, allowed_mentions=discord.AllowedMentions.none()
                )
            except discord.HTTPException as exc2:
                log.warning("Couldn't post version diff in #%s: %s", tc.channel, exc2)
            return

        try:
            await thread.send(view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.warning("Couldn't post version diff into the diff thread in #%s: %s", tc.channel, exc)

    async def apply_transition(
            self,
            tc: TestingChannel,
            transition: Transition,
            actor,
            *,
            changelog_string: str,
            notice: discord.ui.LayoutView | None = None,
            ping_mappers: bool = False,
    ) -> None:
        """Apply a resolved Transition's common effects.

        Sets votes + state, bumps the edit cooldown, writes the changelog, and posts
        ``notice`` if given. Transition-specific effects (optimize, upload, score,
        grace/decline embeds) stay with the caller after this returns.
        """
        if transition.new_votes is not None:
            tc.votes = transition.new_votes
        await tc.set_state(transition.next_state)
        global_cooldown.update_cooldown(tc.channel.id)

        if transition.changelog_category:
            await tc.changelog.add_changelog(
                tc.channel, actor,
                category=transition.changelog_category,
                string=changelog_string,
                map_name=tc.map_name,
            )
            await tc.changelog.update_changelog()

        if notice is not None:
            allowed = (
                discord.AllowedMentions(users=True)
                if ping_mappers
                else discord.AllowedMentions.none()
            )
            await tc.channel.send(view=notice, allowed_mentions=allowed)

    async def release_channel(self, tc: TestingChannel, actor, *, changelog_string: str) -> discord.Message | None:
        """Apply the RELEASE transition and post the 2-week grace notice.

        Shared by the manual "Set to Released" button and the automatic release
        listener. Returns the posted notice message, or None if the map is already
        RELEASED (the transition is rejected).
        """
        transition = resolve_transition(
            TestingChannelEvent.RELEASE, TransitionContext(state=tc.state, votes=tc.votes)
        )
        if not transition.allowed:
            return None

        await self.apply_transition(tc, transition, actor, changelog_string=changelog_string)

        grace_end = to_discord_timestamp(discord.utils.utcnow() + timedelta(weeks=2), style="F")
        return await tc.channel.send(
            view=MapReleased(tc, grace_end),
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    async def handle_map_release(self, message: discord.Message) -> None:
        """Auto-set a tracked channel to RELEASED when its map is announced as released.

        Triggered by the DDNet map-releases webhook (see TestingListener). Matches the
        announced map name to a tracked channel and runs the same release flow as the
        manual button.
        """
        match = RELEASE_ANNOUNCEMENT_RE.search(message.content or "")
        if not match:
            return

        name = match["name"].lower()
        tc = next(
            (c for c in self.test_channels.values() if c.map_name.lower() == name), None
        )
        if tc is None:
            return

        notice = await self.release_channel(
            tc, self.bot.user,
            changelog_string=f'"{tc.map_name}" has been officially released.',
        )
        if notice is not None:
            log.info("Auto-released #%s after its release announcement", tc.channel)

    async def apply_author_update(self, tc: TestingChannel, uploader) -> None:
        """Collapse evaluation progress after a map author uploads a clean version.

        READY drops to RC keeping one placeholder Tester vote (so any tester can
        re-ready it solo); WAITING returns to RC (if a Tester had approved) or
        TESTING; plain TESTING/RC are unchanged.
        """
        if uploader.id not in {author.id for author in tc.authors}:
            return

        transition = resolve_transition(TestingChannelEvent.AUTHOR_CLEAN_UPLOAD, TransitionContext(
            state=tc.state, votes=tc.votes, bot_id=self.bot.user.id,
        ))
        if transition.next_state is tc.state:
            return  # no-op (plain TESTING/RC)

        await self.apply_transition(
            tc, transition, uploader,
            changelog_string=f'"{tc.map_name}" moved to {transition.next_state.name} after a new submission by the author.',
            notice=MovedBackAfterUpdate(tc, transition.next_state.name),
        )
        log.info("Auto-moved #%s to %s after author update", tc.channel, transition.next_state.name)

    async def waiting_for_bugs(self, tc: TestingChannel, author) -> None:
        """Bump an evaluated map to WAITING after its author submits a bad update."""
        transition = resolve_transition(TestingChannelEvent.AUTHOR_BUGGY_UPLOAD, TransitionContext(
            state=tc.state, votes=tc.votes, bot_id=self.bot.user.id,
        ))
        if transition.next_state is tc.state:
            return  # TESTING/WAITING: bugs already reported, no movee

        await self.apply_transition(
            tc, transition, author,
            changelog_string=f'"{tc.map_name}" moved to WAITING -- the latest submission failed map checks.',
            notice=BuggyWaiting(tc),
            ping_mappers=True,
        )
        log.info("Auto-moved #%s to WAITING after buggy author update", tc.channel)

    def get_tc_from_interaction(self, interaction: discord.Interaction) -> TestingChannel | None:
        channel_id = (
            interaction.channel.parent_id
            if isinstance(interaction.channel, discord.Thread)
            else interaction.channel_id
        )
        return self.test_channels.get(channel_id)

    async def archive_channel(self, tc: TestingChannel, interaction: discord.Interaction) -> None:
        """Export the channel's testlog, then optionally delete the channel.

        The testlog (JSON + downloaded avatars/attachments/emojis) is written to
        ``TESTLOG_DIR`` in the layout the ddnet-map-testing-log renderer reads. Two
        config switches, see config.ini.
        """
        config = self.bot.config
        output_dir = config.get(
            "TESTING_CHANNELS", "TESTLOG_DIR", fallback="data/map-testing/testlogs"
        )
        upload = config.getboolean("TESTING_CHANNELS", "TESTLOG_UPLOAD", fallback=False)
        delete = config.getboolean(
            "TESTING_CHANNELS", "TESTLOG_DELETE_ON_ARCHIVE", fallback=False
        )

        try:
            testlog = await TestLog.from_testing_channel(self.bot, tc)
            ok = await archive_testlog(self.bot, testlog, output_dir=output_dir, upload=upload)
        except Exception:
            log.exception("Testlog export crashed for #%s", tc.channel)
            await interaction.followup.send(
                "Archiving failed -- the testlog export crashed. The channel was kept. "
                "See the bot logs for details.",
                ephemeral=True,
            )
            return

        if not ok:
            await interaction.followup.send(
                "Archiving partially failed -- some assets couldn't be saved/uploaded. "
                "The channel was kept. See the bot logs for details.",
                ephemeral=True,
            )
            log.error("Archive incomplete for #%s; channel kept.", tc.channel)
            return

        summary = (
                f"Archived **{tc.map_name}** ({testlog.message_count} messages) to "
                f"`{output_dir}`"
                + (" and uploaded to DDNet." if upload else ".")
        )

        if delete:
            log.info("Archived #%s; deleting channel (delete-on-archive on).", tc.channel)
            await interaction.followup.send(summary + " Deleting the channel now.", ephemeral=True)
            # on_guild_channel_delete -> handle_channel_delete does the DB/backend cleanup.
            await tc.channel.delete(reason="Map testing channel archived")
        else:
            await interaction.followup.send(
                summary + "\nChannel kept (`TESTLOG_DELETE_ON_ARCHIVE` is off).",
                ephemeral=True,
            )
            log.info("Archived #%s; channel kept (delete-on-archive off).", tc.channel)

    async def handle_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Clean up after a tracked testing channel is deleted.

        Fires for both manual deletions and archiving.
        Drops the channel's changelog history and removes the map from the test backend.
        """
        tc = self.test_channels.pop(channel.id, None)
        if tc is None:
            return

        deleter = await self.lookup_channel_deleter(channel)
        log.info(
            "Testing channel #%s (%d) deleted%s; removing map %r and its changelog history.",
            channel.name, channel.id,
            f" by {deleter}" if deleter else "",
            tc.filename,
        )

        # Drop the channel's changelog history file
        await changelog_store.delete_channel(channel.id)

        # Free the channel's on-disk image cache
        clear_channel_diffs(channel.id)

        try:
            await ddnet_delete(self.bot.session, self.bot.config, tc.filename)
        except RuntimeError as exc:
            log.error("Backend delete failed for %r: %s", tc.filename, exc)
        else:
            log.info("Removed %r from the test backend.", tc.filename)

    @staticmethod
    async def lookup_channel_deleter(channel: discord.abc.GuildChannel) -> str | None:
        """Returns the user who deleted a channel, via the audit log"""

        try:
            entry = await anext(
                channel.guild.audit_logs(
                    limit=1, action=discord.AuditLogAction.channel_delete  # noqa
                ),
                None,
            )
        except discord.Forbidden:
            log.warning("Missing permissions to read audit logs for delete attribution.")
            return None

        if entry and entry.target.id == channel.id:
            return str(entry.user)
        return None
