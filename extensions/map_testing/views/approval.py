import io
import logging
from typing import Callable, Any

import discord
from discord.ui import Button

from constants import Roles
from extensions.map_testing.enums import ApprovalResult
from extensions.map_testing.models.submissions import Submission
from extensions.map_testing.services.checker import MapChecker
from utils.checks import is_staff

log = logging.getLogger("mt")


class ResolvedNotice(discord.ui.LayoutView):
    """A buttonless view an approval message is edited into once acted on, so the
    buttons can't be reused and the outcome stays visible."""

    def __init__(self, text: str, colour: discord.Color):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(discord.ui.TextDisplay(text), accent_colour=colour))


def resolved(text: str, colour: discord.Color) -> discord.ui.LayoutView:
    return ResolvedNotice(text, colour)


class ViewTestingChannelButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"mt_view_channel:(?P<channel_id>\d+)",
):
    """#submit-maps: per-map access to an accepted submission's testing channel"""

    def __init__(self, channel_id: int):
        self.channel_id = channel_id
        super().__init__(Button(
            label="View Testing Channel",
            style=discord.ButtonStyle.secondary,
            custom_id=f"mt_view_channel:{channel_id}",
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["channel_id"]))

    async def callback(self, interaction: discord.Interaction):
        channel = interaction.client.get_channel(self.channel_id)
        if channel is None:
            await interaction.response.send_message(
                "That testing channel no longer exists.", ephemeral=True
            )
            return

        member = interaction.user
        try:
            if channel.overwrites_for(member).read_messages:
                await channel.set_permissions(
                    member, overwrite=None, reason="View Testing Channel button"
                )
                await interaction.response.send_message(
                    f"Removed your access to {channel.mention}.", ephemeral=True
                )
            elif channel.permissions_for(member).read_messages:
                # already visible through a role, no overwrite needed.
                await interaction.response.send_message(
                    f"You can already see {channel.mention}.", ephemeral=True
                )
            else:
                await channel.set_permissions(
                    member, read_messages=True, reason="View Testing Channel button"
                )
                await interaction.response.send_message(
                    f"You now have access to {channel.mention}. Press the button again to leave.",
                    ephemeral=True,
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I'm missing the permission to manage that channel's access.", ephemeral=True
            )


def resolved_with_channel(text: str, colour: discord.Color, channel_id: int) -> discord.ui.LayoutView:
    view = ResolvedNotice(text, colour)
    row = discord.ui.ActionRow()
    row.add_item(ViewTestingChannelButton(channel_id))
    view.add_item(row)
    return view


async def fetch_referenced_submission(interaction: discord.Interaction) -> discord.Message | None:
    """Resolve the submission/upload message an approval message replies to."""
    ref = interaction.message.reference
    if ref is None or ref.message_id is None:
        return None
    try:
        return await interaction.channel.fetch_message(ref.message_id)
    except discord.NotFound:
        return None


async def send_debug_output(
        interaction: discord.Interaction, output: str | None, *, cached: bool = False
) -> None:
    """
    Sends twmap map-check output as an ephemeral followup.
    Assumes the interaction is already deferred ephemerally.
    Keeps debug output out of the channel (it's only ever shown here).
    """
    footer = "\n-# Cached result" if cached else "\n-# Just checked"
    if not output:
        await interaction.followup.send(f"✅ No issues found in this map.{footer}", ephemeral=True)
    elif len(output) < 1900:
        await interaction.followup.send(f"```{output}```{footer}", ephemeral=True)
    else:
        file = discord.File(io.StringIO(output), filename="debug_output.txt")  # noqa
        await interaction.followup.send(
            f"See the attached debug output.{footer}", file=file, ephemeral=True
        )


class ReferencedView(discord.ui.LayoutView):
    """
    Shared scaffolding for persistent views whose buttons act on the message the
    view replies to (recovered from the reply reference, so no per-message state).
    """

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    def add(
            self,
            text: str,
            colour: discord.Color,
            buttons: list[tuple[str, int, str, Callable[[discord.Interaction], Any]]],
    ):
        self.add_item(discord.ui.Container(discord.ui.TextDisplay(text), accent_colour=colour))
        row = discord.ui.ActionRow()
        for label, style, custom_id, callback in buttons:
            button = Button(label=label, style=style, custom_id=custom_id)  # type: ignore[arg-type]
            button.callback = callback
            row.add_item(button)
        self.add_item(row)

    @staticmethod
    async def gone(interaction: discord.Interaction) -> None:
        """
        Bail when the referenced submission is gone, whether or not we've already
        deferred (action buttons defer first; the Decline button hasn't yet).
        """
        msg = "Could not find original submission message, nothing to act on."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        ref = interaction.message.reference
        if ref is not None and ref.message_id is not None:
            interaction.client.testing_manager.untrack_approval(ref.message_id)
        try:
            await interaction.message.edit(
                view=resolved("⚠️ The original submission was deleted.", discord.Color.dark_gray())
            )
        except discord.HTTPException:
            pass

    async def show_debug(self, interaction: discord.Interaction) -> None:
        """
        Resolve the map message this view replies to and show its (cached) debug
        output ephemerally. Shared by DebugReport and SubmitBuggyApproval.
        """
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not MapChecker.enabled:
            await interaction.followup.send(
                "Automatic map checks are disabled on this instance.", ephemeral=True
            )
            return
        map_message = await fetch_referenced_submission(interaction)
        if map_message is None:
            return await self.gone(interaction)

        attachment = next(
            (a for a in map_message.attachments if a.filename.endswith(".map")), None
        )
        if attachment is None:
            await interaction.followup.send("That message no longer has a map file.", ephemeral=True)
            return  # noqa

        output, cached = await MapChecker.debug_detailed(
            Submission(message=map_message, attachment=attachment)
        )
        await send_debug_output(interaction, output, cached=cached)  # noqa


class SubmitCleanApproval(ReferencedView):
    """
    #submit-maps: a valid submission awaiting staff approval.
    Approve builds the testing channel; Decline marks it declined and DMs the author.
    """

    def __init__(self, bot, member: discord.abc.User | None = None):
        super().__init__(bot)
        mention = member.mention if member else "Someone"
        self.add(
            f"☑️ {mention}'s submission is ready for review.\n"
            f"-# A Tester can create the testing channel or decline it below.",
            discord.Color.blurple(),
            [
                ("Approve & Create Channel", discord.ButtonStyle.green, "mt_submit_clean:approve", self.approve),
                ("Decline", discord.ButtonStyle.danger, "mt_submit_clean:decline", self.decline),
            ],
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not is_staff(interaction.user, roles=[Roles.ADMIN, Roles.TESTER, Roles.TESTER_EXCL_TOURNAMENTS]):
            await interaction.response.send_message("Only Testers are allowed to approve submissions!", ephemeral=True)
            return False
        return True

    async def approve(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        isubm = await fetch_referenced_submission(interaction)
        if isubm is None:
            await self.gone(interaction)
            return

        try:
            result, tc = await self.bot.testing_manager.approve_submission(isubm, interaction.user)
        except Exception:  # noqa
            log.exception("Approve failed for submission %s", isubm.id)
            await interaction.followup.send("Something went wrong creating the channel.", ephemeral=True)
            return

        if result is ApprovalResult.CREATED:
            self.bot.testing_manager.untrack_approval(isubm.id)
            await interaction.message.edit(
                view=resolved_with_channel(
                    f"✅ Approved by {interaction.user.mention} -- testing channel created.",
                    discord.Color.green(),
                    tc.channel.id,
                )
            )
            await interaction.followup.send("Testing channel created.", ephemeral=True)
            return
        elif result is ApprovalResult.CONFLICT:
            self.bot.testing_manager.untrack_approval(isubm.id)
            await interaction.message.edit(
                view=resolved(f"❌ Declined by {interaction.user.mention} -- the map name is already taken.",
                              discord.Color.dark_red())
            )
            await interaction.followup.send("Declined. A map with that name already exists.", ephemeral=True)
            return
        elif result is ApprovalResult.UNVERIFIED:
            # Released-map list unreachable: leave the buttons in place for a retry.
            await interaction.followup.send(
                "Couldn't verify the map name against the released-maps list right now. "
                "Please try again in a moment.",
                ephemeral=True,
            )
            return
        # ApprovalResult.BUSY
        else:
            await interaction.followup.send("This submission is already being processed!", ephemeral=True)
            return

    async def decline(self, interaction: discord.Interaction) -> None:
        isubm = await fetch_referenced_submission(interaction)
        if isubm is None:
            await self.gone(interaction)
            return
        await interaction.response.send_modal(
            SubmitDeclineModal(self.bot, isubm, interaction.message)
        )


class SubmitBuggyApproval(ReferencedView):
    """An initial submission that failed the automatic map checks."""

    def __init__(self, bot):
        super().__init__(bot)
        self.add(
            "## ⚠️ Map Bugs found!\n"
            "Your submission didn't pass the automatic checks -- press **View Debug Output** "
            "for the details.\n"
            "-# A Tester can accept it into **WAITING** anyway, or decline it.",
            discord.Color.orange(),
            [
                ("View Debug Output", discord.ButtonStyle.secondary, "mt_submit_buggy:debug", self.view_output),
                ("Accept into Waiting", discord.ButtonStyle.primary, "mt_submit_buggy:accept", self.accept),
                ("Decline", discord.ButtonStyle.danger, "mt_submit_buggy:decline", self.decline),
            ],
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.data.get("custom_id") == "mt_submit_buggy:debug":
            return True
        if not is_staff(interaction.user, roles=[Roles.ADMIN, Roles.TESTER, Roles.TESTER_EXCL_TOURNAMENTS]):
            await interaction.response.send_message("Only Testers are allowed to approve submissions!", ephemeral=True)
            return False
        return True

    async def view_output(self, interaction: discord.Interaction):
        await self.show_debug(interaction)

    async def accept(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        submission = await fetch_referenced_submission(interaction)
        if submission is None:
            await self.gone(interaction)
            return

        try:
            result, tc = await self.bot.testing_manager.force_accept_submission(submission, interaction.user)
        except Exception:  # noqa
            log.exception("Force-accept failed for submission %s", submission.id)
            await interaction.followup.send("Something went wrong creating the channel.", ephemeral=True)
            return

        if result is ApprovalResult.CREATED:
            self.bot.testing_manager.untrack_approval(submission.id)
            await interaction.message.edit(
                view=resolved_with_channel(
                    f"✅ Accepted into WAITING by {interaction.user.mention}.",
                    discord.Color.green(),
                    tc.channel.id,
                )
            )
            await interaction.followup.send("Channel created in WAITING.", ephemeral=True)
        elif result is ApprovalResult.CONFLICT:
            self.bot.testing_manager.untrack_approval(submission.id)
            await interaction.message.edit(
                view=resolved(f"❌ Declined by {interaction.user.mention} -- the map name is already taken.",
                              discord.Color.dark_red())
            )
            await interaction.followup.send("Declined -- a map with that name already exists.", ephemeral=True)
        elif result is ApprovalResult.UNVERIFIED:
            # Released-map list unreachable: leave the buttons in place for a retry.
            await interaction.followup.send(
                "Couldn't verify the map name against the released-maps list right now. "
                "Please try again in a moment.",
                ephemeral=True,
            )
        # ApprovalResult.BUSY
        else:
            await interaction.followup.send("This submission is already being processed.", ephemeral=True)

    async def decline(self, interaction: discord.Interaction):
        submission = await fetch_referenced_submission(interaction)
        if submission is None:
            await self.gone(interaction)
            return
        await interaction.response.send_modal(
            SubmitDeclineModal(self.bot, submission, interaction.message)
        )


class ChannelUploadApproval(ReferencedView):
    """
    In-channel: a pending upload (non-author, wrong filename, or buggy) held for
    manual approval. Approve uploads it as-is and makes it the current map.
    """

    def __init__(self, bot, member: discord.abc.User | None = None, reason: str = ""):
        super().__init__(bot)
        mention = member.mention if member else "Someone"
        suffix = f" ({reason})" if reason else ""
        self.add(
            f"Your submission is awaiting approval{suffix}.\n"
            f"-# Can be overridden by a staff member or channel owner.",
            discord.Color.orange(),
            [("Approve Upload", discord.ButtonStyle.green, "mt_channel:approve_upload", self.approve_upload)],
        )

    async def approve_upload(self, interaction: discord.Interaction):
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)
        if tc is None:
            await interaction.response.send_message("This isn't a tracked testing channel.", ephemeral=True)
            return
        if not (is_staff(interaction.user) or interaction.user.id in {a.id for a in tc.authors}):
            await interaction.response.send_message(
                "Only staff or the map author can approve this upload.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        submission = await fetch_referenced_submission(interaction)
        if submission is None:
            await self.gone(interaction)
            return

        try:
            uploaded = await self.bot.testing_manager.confirm_upload(submission, interaction.user)
        except Exception:  # noqa
            log.exception("Upload approval failed for message %s", submission.id)
            await interaction.followup.send("Something went wrong uploading the map.", ephemeral=True)
            return

        if not uploaded:
            await interaction.followup.send(
                "This map is identical to the current version, so nothing was uploaded.",
                ephemeral=True,
            )
            return

        self.bot.testing_manager.untrack_approval(submission.id)
        await interaction.message.edit(
            view=resolved(f"✅ Uploaded by {interaction.user.mention}.", discord.Color.green())
        )
        await interaction.followup.send("Map uploaded and set as the current version.", ephemeral=True)


class DebugReport(ReferencedView):
    """The twmap check notice posted when a map fails the automatic checks.

    The debug output is *not* written to the channel anymore. The button reveals it
    ephemerally on demand. Posted as a reply to the map message, so the button
    re-derives the output via ``MapChecker.debug``, a content-hash cache hit, so the
    same upload is never re-checked (it falls back to a fresh check only if the cache
    was cleared, e.g. by a restart).
    """

    def __init__(self, bot):
        super().__init__(bot)
        self.add(
            "## Map Bugs found!\n"
            "This map didn't pass the automatic checks. Press **View Debug Output** to see the details.\n"
            "Please address the issues, otherwise we're unable to release your map! "
            "If you're unable to resolve the bugs yourself, don't hesitate to ask!",
            discord.Color.dark_red(),
            [("View Debug Output", discord.ButtonStyle.secondary, "mt_debug_report:view", self.view_output)],
        )

    async def view_output(self, interaction: discord.Interaction):
        await self.show_debug(interaction)


class SubmitDeclineModal(discord.ui.Modal, title="Decline Reason"):
    """Collects an optional reason when declining a #submit-maps submission via button.

    Mirrors ``views/modals/decline.py::DeclineReasonModal``. Constructed fresh per
    click with the target submission + the approval message to update, so it needs
    no persistence.
    """

    decline_reason = discord.ui.TextInput(
        label="Decline Reason",
        placeholder="Shared with the author. You can leave this blank.",
        max_length=500,
        required=False,
        style=discord.TextStyle.long,
    )

    def __init__(self, bot, submission: discord.Message, approval_message: discord.Message):
        super().__init__(timeout=None)
        self.bot = bot
        self.submission = submission
        self.approval_message = approval_message

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await self.bot.testing_manager.decline_submission_manual(
                self.submission, interaction.user, self.decline_reason.value
            )
        except ValueError:
            # Submission no longer parses (e.g. edited) -- nothing to decline.
            await interaction.followup.send("That submission can no longer be declined.", ephemeral=True)
            return

        self.bot.testing_manager.untrack_approval(self.submission.id)
        await self.approval_message.edit(
            view=resolved(f"❌ Declined by {interaction.user.mention}.", discord.Color.dark_red())
        )
        await interaction.followup.send("Submission declined and the author notified.", ephemeral=True)
