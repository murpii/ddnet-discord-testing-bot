import logging
import re
from typing import Optional, Any

import discord

from constants import DIFF_THREAD_NAME
from extensions.map_testing.enums import MapState
from extensions.map_testing.models.channel_factory import TestingChannel
from extensions.map_testing.states import role_tier
from extensions.map_testing.models.submissions import Submission
from utils.changelog import ChangelogPaginator
from utils.text import resolve_mentions


async def load_testing_channel(bot, channel: discord.TextChannel) -> TestingChannel:
    if not channel.topic:
        raise ValueError(f"{channel.name}: Missing topic")

    state = next(
        (s for s in MapState if s.value == channel.name[0]),
        MapState.TESTING
    )

    thread = await get_channel_thread(channel)
    meta = parse_topic(channel)

    tc = TestingChannel(
        channel=channel,
        thread=thread,
        state=state,
        map_name=meta["map_name"],
        server=meta["server"],
        mappers=meta["mappers"],
        mapper_mentions=meta["mapper_mentions"],
        authors=meta["authors"],
    )
    tc.votes = {
        member.id: role_tier(member)
        for member in meta["voters"]
    }
    tc.submission = await load_submission_from_pins(channel)

    # changelog
    tc.changelog = ChangelogPaginator(bot, channel=channel)
    await tc.changelog.get_data()
    await tc.changelog.assign_changelog_message(thread=tc.thread)
    if tc.changelog.changelog:
        bot.add_view(
            view=tc.changelog,
            message_id=tc.changelog.changelog.id
        )

    return tc


async def load_submission_from_pins(channel: discord.TextChannel) -> Optional[Submission]:
    try:
        pins = await channel.pins()
    except discord.Forbidden:
        logging.warning(f"{channel.name}: Cannot fetch pins")
        return None

    pins = sorted(pins, key=lambda m: m.created_at, reverse=True)
    for pinned in pins:
        msg = await channel.fetch_message(pinned.id) # This makes everything very slow unfortunately.
        attachment = next(
            (a for a in msg.attachments if a.filename.endswith(".map")),
            None
        )
        if not attachment:
            print("No Attachment")
            continue

        return Submission(message=msg, attachment=attachment)
    return None


def parse_topic(channel: discord.TextChannel) -> dict[str, Any]:
    lines = [line.strip() for line in (channel.topic or "").splitlines() if line.strip()]

    map_name = None
    server = None

    if lines:
        if m := re.search(r'\*\*"(.*?)"\*\*', lines[0]):
            map_name = m.group(1)
        if m := re.search(r'\[(.*?)\]', lines[0]):
            server = m.group(1)

    authors = resolve_mentions(channel.guild, lines[2]) if len(lines) > 2 else []
    voters = resolve_mentions(channel.guild, lines[3]) if len(lines) > 3 else []

    if m := re.search(r'\*\*".*?"\*\* by (.+?) \[', lines[0]):
        mappers = re.split(r', | & ', m.group(1))
    else:
        mappers = []

    return {
        "map_name": map_name,
        "server": server,
        "authors": authors,
        "voters": voters,
        "mappers": mappers,
        "mapper_mentions": lines[2] if len(lines) > 2 else "",
    }


async def get_channel_thread(channel: discord.TextChannel):
    """Find a channel's tester-control thread (the one we track on the channel object).

    A channel may now hold several threads: the single control thread plus one
    per-upload version-diff thread. The diff threads carry a known constant name, so
    we pick the first thread that *isn't* a diff thread (active first, then archived).
    """
    def is_control(t) -> bool:
        return t.name != DIFF_THREAD_NAME

    thread = next((t for t in channel.threads if is_control(t)), None)

    if thread is None:
        async for t in channel.archived_threads():
            if is_control(t):
                thread = t
                break

    if thread and thread.archived:
        try:
            await thread.edit(archived=False)
        except Exception as e:
            logging.warning(f"{channel.name}: thread issue: {e}")

    return thread