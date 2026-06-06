import logging
import shlex
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from constants import Guilds
from extensions.map_testing.models.channel_factory import TestingChannel
from extensions.map_testing.utils.map_tools import MapEditor, MapVisualizer
from extensions.map_testing.views.testing_menu import TESTER_ROLES
from utils.checks import is_staff

log = logging.getLogger("mt")


class TestingCommands(commands.Cog):
    """Slash commands that operate on a testing channel's current (pinned) map.

    Both commands act on ``tc.submission`` -- the map the manager tracks as the
    channel's current version - so there's no need to re-scan the pin list.
    """

    def __init__(self, bot):
        self.bot = bot

    def get_testing_channel(self, interaction: discord.Interaction) -> TestingChannel | None:
        return self.bot.testing_manager.get_tc_from_interaction(interaction)

    @app_commands.command(
        name="visualize-size",
        description="Visualize what images and sounds take up the map's file size",
    )
    @app_commands.guilds(Guilds.DDNET)
    async def visualize_size(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        tc = self.get_testing_channel(interaction)
        if tc is None:
            await interaction.followup.send("This isn't a tracked testing channel.", ephemeral=True)
            return
        if tc.submission is None:
            await interaction.followup.send("No map is pinned in this channel yet.", ephemeral=True)
            return

        try:
            buf = await MapVisualizer.visualize_size(tc.submission)
        except Exception as exc:
            log.warning("Size visualization failed for #%s (%s): %s", tc.channel, tc.filename, exc)
            await interaction.followup.send(
                f"Failed to produce the size visualization: `{exc}`", ephemeral=True
            )
            return

        filename = f"{tc.filename}_size.png"

        # Testers get a public breakdown posted into the channel, everyone else only sees it themselves.
        if is_staff(interaction.user, roles=TESTER_ROLES):
            await tc.channel.send(
                "Map size breakdown 🔍", file=discord.File(buf, filename=filename)
            )
            await interaction.delete_original_response()
        else:
            await interaction.followup.send(
                "Map size breakdown 🔍",
                file=discord.File(buf, filename=filename),
                ephemeral=True,
            )

    @app_commands.command(
        name="twmap-edit",
        description="Run twmap-edit on the channel's current map",
    )
    @app_commands.describe(
        options="CLI options passed to twmap-edit, e.g. --scale-time 2 (use --help to list them)"
    )
    @app_commands.guilds(Guilds.DDNET)
    async def twmap_edit(self, interaction: discord.Interaction, options: str):
        tc = self.get_testing_channel(interaction)
        if tc is None:
            await interaction.response.send_message(
                "This isn't a tracked testing channel.", ephemeral=True
            )
            return

        is_author = interaction.user.id in {author.id for author in tc.authors}
        if not (is_staff(interaction.user, roles=TESTER_ROLES) or is_author):
            await interaction.response.send_message(
                "Only the testing team and the map's author can use this command.",
                ephemeral=True,
            )
            return

        if tc.submission is None:
            await interaction.response.send_message(
                "No map is pinned in this channel yet.", ephemeral=True
            )
            return

        try:
            argv = shlex.split(options)
        except ValueError as exc:
            await interaction.response.send_message(f"Invalid options: {exc}", ephemeral=True)
            return

        if not argv:
            await interaction.response.send_message(
                "Pass at least one option, e.g. `--remove-everything-unused`.", ephemeral=True
            )
            return

        # --mapdir writes a directory of loose files; the bot can only hand back a single .map, so reject it up front.
        if "--mapdir" in argv:
            await interaction.response.send_message(
                "Can't save as a MapDir through the bot.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            stdout, edited = await MapEditor.edit(tc.submission, *argv)
        except RuntimeError as exc:
            message = f"twmap-edit failed:\n```{exc}```"
            await interaction.followup.send(message[:1990], ephemeral=True)
            return

        # No output file: typically informational invocations like --help. Just
        # relay whatever twmap-edit printed back to the invoker.
        if edited is None:
            if stdout:
                await self.relay_text(interaction, stdout)
            else:
                await interaction.followup.send("twmap-edit produced no output.", ephemeral=True)
            return

        # Post the edited map into the channel as an artifact. Like the optimize
        # path, this is NOT auto-uploaded - the author re-submits it to make it live.
        files = [discord.File(BytesIO(edited), filename=f"{tc.filename}.map")]
        content = f"Edited map from {interaction.user.mention} (`twmap-edit {options}`):"
        if stdout:
            if len(stdout) > 1500:
                files.append(
                    discord.File(BytesIO(stdout.encode()), filename="twmap-edit-output.txt")
                )
                content += "\nChangelog attached."
            else:
                content += f"\n```{stdout}```"

        await tc.channel.send(
            content, files=files, allowed_mentions=discord.AllowedMentions(users=False)
        )
        await interaction.followup.send(
            "Edited map posted to the channel. Re-submit it yourself to make it the tested version.",
            ephemeral=True,
        )

    @staticmethod
    async def relay_text(interaction: discord.Interaction, text: str) -> None:
        """Relay command output to the invoker, as a file if it's too long to inline."""
        if len(text) > 1500:
            file = discord.File(BytesIO(text.encode()), filename="twmap-edit-output.txt")
            await interaction.followup.send("Output:", file=file, ephemeral=True)
        else:
            await interaction.followup.send(f"```{text}```", ephemeral=True)


async def setup(bot):
    await bot.add_cog(TestingCommands(bot))
