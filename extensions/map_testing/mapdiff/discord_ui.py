import io

import discord
from discord.ui import Button

from extensions.map_testing.mapdiff.cache import diff_key, load_cached_diff, store_cached_diff
from extensions.map_testing.mapdiff.diff import MapDiff
from extensions.map_testing.mapdiff.render import render_diff_images
from extensions.map_testing.models.submissions import Submission

PER_PAGE = 10  # discords hard limit of attachments per message


async def map_submission(channel: discord.abc.Messageable, message_id: int) -> Submission | None:
    try:
        message = await channel.fetch_message(message_id)
    except discord.HTTPException:
        return None
    attachment = next((a for a in message.attachments if a.filename.endswith(".map")), None)
    if attachment is None:
        return None
    return Submission(message=message, attachment=attachment)


def diff_files(images: list[bytes], start: int) -> list[discord.File]:
    return [
        discord.File(io.BytesIO(img), filename=f"area_{start + i + 1}.png")
        for i, img in enumerate(images)
    ]


class DiffPaginator(discord.ui.View):
    """
    Pages through the per-area diff images.
    Each press swaps the ephemeral message attachments for the next batch.
    """

    def __init__(self, images: list[bytes], total: int):
        super().__init__(timeout=600)
        self.images = images
        self.total = total
        self.pages = (len(images) + PER_PAGE - 1) // PER_PAGE
        self.page = 0
        self.prev_button = Button(label="◀", style=discord.ButtonStyle.secondary)
        self.next_button = Button(label="▶", style=discord.ButtonStyle.secondary)
        self.prev_button.callback = self._go_prev
        self.next_button.callback = self._go_next
        self.add_item(self.prev_button)
        self.add_item(self.next_button)
        self.sync()

    def sync(self) -> None:
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.pages - 1

    def files(self) -> list[discord.File]:
        start = self.page * PER_PAGE
        return diff_files(self.images[start:start + PER_PAGE], start)

    def content(self) -> str:
        start = self.page * PER_PAGE + 1
        end = min((self.page + 1) * PER_PAGE, len(self.images))
        note = f" (largest {len(self.images)} of {self.total})" if self.total > len(self.images) else ""
        return f"-# Changed areas {start}–{end} of {len(self.images)}{note} · page {self.page + 1}/{self.pages}"

    async def _go_prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self.sync()
        await interaction.response.edit_message(content=self.content(), attachments=self.files(), view=self)

    async def _go_next(self, interaction: discord.Interaction):
        self.page = min(self.pages - 1, self.page + 1)
        self.sync()
        await interaction.response.edit_message(content=self.content(), attachments=self.files(), view=self)


class VisualDiffButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"mt_vdiff:(?P<old>\d+):(?P<new>\d+)",
):
    """On-demand render of the changed region (new map, changed cells colour-coded),
    sent ephemerally.

    The old + new map message ids are encoded in the custom_id, so it survives bot
    restarts with no stored state.
    """

    def __init__(self, old_id: int, new_id: int):
        self.old_id = old_id
        self.new_id = new_id
        super().__init__(discord.ui.Button(
            label="View Visual Diff",
            style=discord.ButtonStyle.secondary,
            custom_id=f"mt_vdiff:{old_id}:{new_id}",
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["old"]), int(match["new"]))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        if not getattr(interaction.client, "rendering_enabled", True):
            await interaction.followup.send(
                "Map rendering is disabled on this instance.", ephemeral=True
            )
            return
        # The diff may live in a per-upload thread, but the map messages are in the
        # parent testing channel. Resolve maps (and key the cache) against that channel
        # so it works whether the button sits in the channel or a thread, and so the
        # cache lines up with clear_channel_diffs(channel.id).
        source = interaction.channel
        if isinstance(source, discord.Thread):
            source = source.parent or interaction.channel

        old_sub = await map_submission(source, self.old_id)
        new_sub = await map_submission(source, self.new_id)
        if old_sub is None or new_sub is None:
            await interaction.followup.send(
                "One of the map versions is no longer available to render.", ephemeral=True
            )
            return

        old_bytes = (await old_sub.buffer()).getvalue()
        new_bytes = (await new_sub.buffer()).getvalue()
        channel_id = source.id

        key = diff_key(old_bytes, new_bytes)
        cached = load_cached_diff(channel_id, key)
        if cached is None:
            result = await MapDiff.diff(old_sub, new_sub)
            images, total = await render_diff_images(new_bytes, result)
            if not images:
                await interaction.followup.send("Couldn't render the map image(s).", ephemeral=True)
                return
            store_cached_diff(channel_id, key, images, total)
            cached = (images, total)

        images, total = cached
        if len(images) <= PER_PAGE:
            await interaction.followup.send(files=diff_files(images, 0), ephemeral=True)
            return
        paginator = DiffPaginator(images, total)
        await interaction.followup.send(
            content=paginator.content(), files=paginator.files(), view=paginator, ephemeral=True
        )


class VersionDiff(discord.ui.LayoutView):
    """
    Auto-posted summary of what changed versus the previous map version, plus an
    on-demand "View Visual Diff" button that renders the changed region ephemerally.
    """

    def __init__(
        self,
        summary_markdown: str,
        old_id: int,
        new_id: int,
        show_visual_diff: bool = True,
        compared_url: str | None = None,
    ):
        super().__init__(timeout=None)
        text = summary_markdown
        if compared_url:
            text += f"\n-# Compared against the [previous version](<{compared_url}>)"
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(text),
            accent_colour=discord.Color.blue(),
        ))
        # The visual-diff button renders images (needs a GPU/software rasterizer); omit it
        # when rendering is disabled -- the text summary above still stands on its own.
        if show_visual_diff:
            row = discord.ui.ActionRow()
            row.add_item(VisualDiffButton(old_id, new_id))
            self.add_item(row)
