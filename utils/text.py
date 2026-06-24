import re
from typing import List, Union, Iterable
from datetime import datetime

import discord


def slugify2(name: str) -> str:
    x = "[\t !\"#$%&'()*-/<=>?@[\\]^_`{|},.:]+"
    return "".join(f"-{ord(c)}-" if c in x or ord(c) >= 128 else c for c in name)


def human_join(seq: List[str], delim: str = ", ", final: str = " & ") -> str:
    size = len(seq)
    if size == 0:
        return ""
    elif size == 1:
        return seq[0]
    elif size == 2:
        return seq[0] + final + seq[1]
    else:
        return delim.join(seq[:-1]) + final + seq[-1]


def sanitize(text: str) -> str:
    return re.sub(r"[^\w-]", "", text.replace(" ", "_"))


def to_discord_timestamp(dt: datetime, style: str = 'f') -> str:
    """
    Convert a datetime object to a Discord-formatted timestamp string.

    Parameters:
        dt : datetime
            The datetime object to convert. Should be timezone-aware or in UTC.
        style : str, optional
            The Discord timestamp style to use (default is 'f'). Options are:
            - 't' : Short time (e.g. 16:20)
            - 'T' : Long time (e.g. 16:20:30)
            - 'd' : Short date (e.g. 20/04/2021)
            - 'D' : Long date (e.g. 20 April 2021)
            - 'f' : Short date/time (e.g. 20 April 2021 16:20)
            - 'F' : Long date/time (e.g. Tuesday, 20 April 2021 16:20)
            - 'R' : Relative time (e.g. 2 months ago, in 10 minutes)

    Returns:
        str: A Discord timestamp string in the format `<t:unix_timestamp:style>`.
    """
    unix_ts = int(dt.timestamp())
    return f"<t:{unix_ts}:{style}>"


def extract_ids_from_mentions(mentions_line: str, prefix: str = None) -> List[int]:
    """
    Extract user IDs from a line containing Discord mentions.

    Args:
        mentions_line: Line containing Discord user mentions
        prefix: Optional prefix to use

    Returns:
        List of extracted user IDs
    """
    mention_text = mentions_line.strip()
    if prefix:
        mention_text = mention_text.removeprefix(prefix)

    extracted_user_ids = []
    for token in mention_text.split():
        if token.startswith("<@") and token.endswith(">"):
            try:
                clean_id = token.strip("<@!>")
                user_id = int(clean_id)
                extracted_user_ids.append(user_id)
            except ValueError:
                continue

    return extracted_user_ids


def user_ids_to_mentions(
        users: Union[int, discord.User, discord.Member, Iterable[Union[int, discord.User, discord.Member]]]
) -> str:
    """
    Format user IDs or user objects into Discord mention strings.

    Args:
        users: A single user ID, user object, or an iterable of those.

    Returns:
        Space-separated string of user mentions.
    """
    if not isinstance(users, (list, set, tuple)):
        users = [users]

    mentions = []
    for user in users:
        if isinstance(user, int):
            user_id = user
        elif hasattr(user, "id"):
            user_id = user.id
        else:
            raise TypeError(f"Unsupported type {type(user)} in users input")

        mentions.append(f"<@{user_id}>")

    return " ".join(mentions)


def resolve_mentions(guild: discord.Guild, text: str) -> list[discord.Member]:
    ids = re.findall(r"<@!?(\d+)>", text)
    return [m for uid in ids if (m := guild.get_member(int(uid)))]
