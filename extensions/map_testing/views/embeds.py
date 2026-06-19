import discord


# Filename is not really accurate, these aren't just embeds anymore.
# Not sure how to name it yet.


class MapReleased(discord.ui.LayoutView):
    def __init__(self, tc, timestamp):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                "# 📢 Map Released!\n"
                f"{tc.mapper_mentions} your map has just been released! 🎉\n\n"
                "You now have a **2-week grace period** to identify and resolve any unnoticed bugs or skips. "
                "After this period, only **design** and **quality of life** fixes will be allowed, provided "
                "they do **not** affect leaderboard rankings.\n\n"
                "⚠️ Significant gameplay changes may result in **rank removals**.\n\n"
                "Good luck with your map!"
            ),
            discord.ui.Separator(),
            discord.ui.TextDisplay(f"**🕒 Grace Period Ends**\n{timestamp}"),
            # `-#` renders as small "subtext", a natural stand-in for an embed footer.
            discord.ui.TextDisplay(
                "-# Make sure to review your map thoroughly before the grace period ends!"
            ),
            accent_colour=discord.Color.dark_gray(),
        ))


class TrialReadyEmbed(discord.ui.LayoutView):
    def __init__(self, rating):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                "## ⭐ Channel state set to Release Candidate!\n"
                "First ready set by Trial Tester. "
                "The map needs to be tested again by an official tester before fully evaluated.\n\n"
                f"Suggested rating: {rating}"
            ),
            accent_colour=discord.Color.yellow(),
        ))


class ReadyEmbed(discord.ui.LayoutView):
    def __init__(self, rating):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                "## ⭐ Channel state set to Release Candidate!\n"
                "First ready set. "
                "The map needs to be tested again by a different tester before fully evaluated.\n\n"
                f"Suggested rating: {rating}"
            ),
            accent_colour=discord.Color.yellow(),
        ))


class MapReady(discord.ui.LayoutView):
    def __init__(self, tc, rating: str, detail: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                f"## ⭐ {tc.map_name} is now ready to be released!\n"
                f"{rating}\n\n{detail}"
            ),
            accent_colour=discord.Color.green(),
        ))


class VoteNeedsTester(discord.ui.LayoutView):
    """Recorded a vote, but only Trial Testers have voted so far."""

    def __init__(self, tc, voter):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                f"{voter.mention}'s vote was recorded, but a full **Tester** "
                f"still needs to confirm before **{tc.map_name}** can be set to READY."
            ),
            accent_colour=discord.Color.orange(),
        ))


class WaitingMapper(discord.ui.LayoutView):
    def __init__(self, tc):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                f"{tc.mapper_mentions}\nYour map channel has been moved to **WAITING MAPPER**.\n"
                "Kindly review the issues highlighted by our Testers."
            ),
            accent_colour=discord.Color.dark_purple(),
        ))


class BuggyWaiting(discord.ui.LayoutView):
    """Map failed the automatic checks and was moved to WAITING.

    Used both when a map author submits a buggy update in-channel and when a tester
    force-accepts a buggy initial submission from #submit-maps.
    """

    def __init__(self, tc):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                f"{tc.mapper_mentions} Your latest map failed the automatic checks, so this "
                "channel has been moved to **WAITING**. Please fix the issues and resubmit."
            ),
            accent_colour=discord.Color.dark_purple(),
        ))


class ResetToTesting(discord.ui.LayoutView):
    def __init__(self, tc):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                f"{tc.mapper_mentions} Your map channel has been moved back to **TESTING**."
            ),
            accent_colour=discord.Color.darker_grey(),
        ))


class MovedBackAfterUpdate(discord.ui.LayoutView):
    """Author uploaded a clean new version; evaluation progress was collapsed."""

    def __init__(self, tc, state_name: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                f"{tc.mapper_mentions} A new version was submitted, so the map has been "
                f"moved back to **{state_name}**."
            ),
            accent_colour=discord.Color.darker_grey(),
        ))


class IdenticalUpload(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                "This map is identical to the current version. Did you save your changes?"
            ),
            accent_colour=discord.Color.orange(),
        ))


class ServerChanged(discord.ui.LayoutView):
    def __init__(self, tc):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"{tc.mapper_mentions} Changed the server type to `{tc.server}`."),
            accent_colour=discord.Color.darker_grey(),
        ))


class MappersChanged(discord.ui.LayoutView):
    def __init__(self, tc, mappers_fmt: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"{tc.mapper_mentions} Changed the mapper(s) to {mappers_fmt}."),
            accent_colour=discord.Color.darker_grey(),
        ))


class OwnerChanged(discord.ui.LayoutView):
    def __init__(self, tc):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"Submission owner changed to {tc.mapper_mentions}."),
            accent_colour=discord.Color.darker_grey(),
        ))


class NameChanged(discord.ui.LayoutView):
    def __init__(self, tc):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"{tc.mapper_mentions} The map name has been changed to `{tc.map_name}`."),
            accent_colour=discord.Color.darker_grey(),
        ))


class MapDeclined(discord.ui.LayoutView):
    """Posted in the map channel when a tested map is declined."""

    def __init__(self, tc, reason: str | None = None):
        super().__init__(timeout=None)
        text = (
            "## ❌ Submission has been declined.\n"
            f"{tc.mapper_mentions}\nUnfortunately, your map submission has been declined. "
            "Don't worry though -- take a look at the feedback from our Testers, and consider playing "
            "our latest releases to gain more experience."
        )
        if reason:
            text += f"\n\n**The reason provided:**\n{reason}"
        self.add_item(discord.ui.Container(discord.ui.TextDisplay(text)))


class SubmissionDeclinedNotice(discord.ui.LayoutView):
    def __init__(self, author, map_name: str, reason: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                f"{author.mention} your map submission **{map_name}** was declined because {reason}."
            ),
            accent_colour=discord.Color.dark_red(),
        ))
