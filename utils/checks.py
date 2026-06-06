import discord
from typing import Iterable

from constants import Roles


def is_staff(member: discord.abc.User, *, roles: Iterable[int] = None) -> bool:
    """Check if a member has staff roles.

    Args:
        member (discord.Member): The Discord member to check.
        roles (Iterable[int], optional): A collection of role IDs to check against. Defaults to all Staff IDs from DDNet.

    Returns:
        bool: True if the member has at least one of the specified roles, False otherwise.
    """

    staff = [
        Roles.ADMIN,
        Roles.TESTER, Roles.TESTER_EXCL_TOURNAMENTS,
        Roles.TRIAL_TESTER, Roles.TRIAL_TESTER_EXCL_TOURNAMENTS,
        Roles.MODERATOR, Roles.DISCORD_MODERATOR
    ]

    # Users don't have roles, so immediately return False
    if not isinstance(member, discord.Member):
        return False

    if roles is None:
        roles = staff

    return any(r.id in roles for r in member.roles)
