import logging

import discord

from constants import Channels, Guilds, URLs
from extensions.map_testing.enums import MapState
from extensions.map_testing.models.channel_factory import TestingChannel, build_topic
from extensions.map_testing.models.submissions import InitialSubmission, Submission
from extensions.map_testing.utils.map_tools import MapThumbnailer
from extensions.map_testing.views.checklist import ChecklistView
from extensions.map_testing.views.testing_menu import TestingMenu
from utils.changelog import ChangelogPaginator
from utils.text import sanitize, human_join

log = logging.getLogger("mt")


async def build_channel(
    bot, submission: InitialSubmission, *, state: MapState = MapState.TESTING
) -> TestingChannel:
    guild: discord.Guild = bot.get_guild(Guilds.DDNET)
    member = guild.get_member(submission.author.id) or submission.author

    channel_name = f"{state.value}{submission.server_emoji}{sanitize(submission.name)}"
    topic = build_topic(
        map_name=submission.name,
        mappers=submission.mappers,
        server=submission.server,
        author_mentions=submission.author_mention,
    )

    if state in (MapState.TESTING, MapState.RC):
        category_id = Channels.CAT_TESTING
    elif state is MapState.WAITING:
        category_id = Channels.CAT_WAITING
    else:
        category_id = Channels.CAT_EVALUATED
    category: discord.CategoryChannel = guild.get_channel(category_id)
    create_options: dict = {"name": channel_name, "topic": topic}
    if state not in (MapState.TESTING, MapState.RC):
        create_options["position"] = 0  # evaluated/waiting maps sit on top
    discord_channel = await category.create_text_channel(**create_options)
    log.info("Created testing channel #%s (%d)", channel_name, discord_channel.id)

    # First channel message: submission info card + thumbnail attempt.
    # users=True so the author mention inside the card actually pings them.
    view, thumbnail_file = await build_submission_info(submission, bot.rendering_enabled)
    await discord_channel.send(
        view=view,
        file=thumbnail_file,  # None is silently ignored by discord.py
        allowed_mentions=discord.AllowedMentions(users=True),
    )

    # Send the map file as a message, then create the thread FROM it
    # This makes the map file the thread starter (messages[0]),
    # so the changelog we send next lands at messages[1] as assign_changelog_message() expects.
    buf = await submission.buffer()
    map_message = await discord_channel.send(
        file=discord.File(buf, filename=submission.filename)
    )
    thread = await discord_channel.create_thread(
        name=f"{submission.name} -- Testing",
        message=map_message,
    )

    # The map file is the channel's current map. Pin it so it's discoverable
    # for the RC->READY optimize step and for reload-from-pins after a restart.
    map_submission = Submission(
        message=map_message,
        attachment=map_message.attachments[0],
        bytes=submission.bytes,
    )
    await map_message.pin()

    paginator = await setup_changelog(bot, thread, discord_channel, submission)

    # Thread checklist
    checklist = ChecklistView()
    await thread.send(view=checklist, allowed_mentions=discord.AllowedMentions.none())

    # Thread tester controls (the control text lives inside the menu view now)
    await thread.send(
        view=TestingMenu(bot),
        allowed_mentions=discord.AllowedMentions.none(),
    )

    return TestingChannel(
        channel=discord_channel,
        thread=thread,
        state=state,
        map_name=submission.name,
        server=submission.server,
        mappers=submission.mappers,
        mapper_mentions=submission.author_mention,
        authors=[member],
        submission=map_submission,
        changelog=paginator,
    )


async def build_submission_info(
    submission: InitialSubmission,
    rendering_enabled: bool = True,
) -> tuple[discord.ui.LayoutView, discord.File | None]:
    """Build the channel's info card and, if rendering is enabled and generation
    succeeds, the map preview thumbnail file it references."""
    preview_url = f"https://ddnet.org/testmaps/?map={sanitize(submission.name)}"
    mappers_fmt = human_join([f"**{m}**" for m in submission.mappers])

    thumbnail_file = None
    if rendering_enabled:
        try:
            thumb_buf = await MapThumbnailer.generate(submission)
            thumbnail_file = discord.File(thumb_buf, filename="thumbnail.png")
        except Exception as exc:
            log.warning("Thumbnail generation failed for %s: %s", submission.name, exc)

    card = discord.ui.Section(
        discord.ui.TextDisplay(
            f"# [{submission.name}]({preview_url})\n"
            f"by {mappers_fmt} · {submission.author_mention}\n\n"
            f"**Server:** {submission.server_emoji} {submission.server}\n"
            f"**Preview:** [testmaps]({preview_url})"
        ),
        accessory=discord.ui.Thumbnail(submission.author.display_avatar.url),
    )
    container = discord.ui.Container(card, accent_colour=discord.Color.blurple())

    if thumbnail_file is not None:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.MediaGallery(
            discord.MediaGalleryItem("attachment://thumbnail.png")
        ))

    container.add_item(discord.ui.TextDisplay(
        f"-# Submitted • {submission.message.created_at.strftime('%Y-%m-%d')}"
    ))
    container.add_item(discord.ui.ActionRow(
        discord.ui.Button(
            label="Mapping Rules", style=discord.ButtonStyle.url, url=URLs.DDNET_MAPPING_RULES
        ),
        discord.ui.Button(
            label="Mapping Guidelines", style=discord.ButtonStyle.url, url=URLs.DDNET_MAPPING_GUIDELINES
        ),
    ))

    view = discord.ui.LayoutView(timeout=None)
    view.add_item(container)

    return view, thumbnail_file


async def setup_changelog(
    bot,
    thread: discord.Thread,
    channel: discord.TextChannel,
    submission: InitialSubmission,
) -> ChangelogPaginator:
    paginator = ChangelogPaginator(bot, channel=channel)

    # Write the creation entry first so the embed isn't empty on first render
    await paginator.add_changelog(
        channel,
        submission.author,
        category="MapTesting/CREATION",
        string=f'Channel for "{submission.name}" successfully created.',
        map_name=submission.name,
    )
    await paginator.get_data()

    # messages[1] in thread history -- the contract with assign_changelog_message()
    changelog_msg = await thread.send(
        embed=paginator.format_changelog_embed(),
        view=paginator,
        allowed_mentions=discord.AllowedMentions.none(),
    )

    paginator.changelog = changelog_msg
    bot.add_view(view=paginator, message_id=changelog_msg.id)

    return paginator