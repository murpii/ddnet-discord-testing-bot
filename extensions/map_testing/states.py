from __future__ import annotations

from dataclasses import dataclass
from typing import Union

import discord

from constants import Roles
from extensions.map_testing.enums import MapState, TestingChannelEvent as TCEvent


def role_tier(member: Union[discord.Member, discord.User]) -> str:
    """Return "trial" if the member is a Trial Tester, else "tester"."""
    trial_roles = {Roles.TRIAL_TESTER, Roles.TRIAL_TESTER_EXCL_TOURNAMENTS}
    role_ids = {role.id for role in getattr(member, "roles", [])}
    return "trial" if role_ids & trial_roles else "tester"


def state_from_votes(votes: dict[int, str]) -> MapState:
    """
    READY needs >= 2 distinct votes including >= 1 full Tester; a single vote is RC;
    none is TESTING. Trial-only votes can never reach READY.
    """
    tester_votes = sum(1 for tier in votes.values() if tier == "tester")
    total = len(votes)
    if total >= 2 and tester_votes >= 1:
        return MapState.READY
    if total >= 1:
        return MapState.RC
    return MapState.TESTING


def vote_fallback(votes: dict[int, str], user_id: int) -> dict[int, str]:
    """
    If any full Tester approved, return one placeholder Tester vote owned by
    ``user_id`` (the bot) so the map drops to RC needing just one more vote,
    and no real tester is locked out.
    """
    if any(tier == "tester" for tier in votes.values()):
        return {user_id: "tester"}
    return {}


@dataclass(frozen=True)
class TransitionContext:
    """Everything `resolve_transition` needs."""
    state: MapState
    votes: dict[int, str]
    actor_id: int = 0
    actor_tier: str = "tester"
    is_author: bool = False
    bot_id: int = 0


@dataclass
class Transition:
    allowed: bool
    reason: str | None = None                # rejection text for the caller to surface
    next_state: MapState | None = None
    new_votes: dict[int, str] | None = None  # None => leave votes unchanged
    requires_map_recheck: bool = False       # READY state: caller must debug + optimize
    changelog_category: str | None = None


def rejected(reason: str) -> Transition:
    return Transition(allowed=False, reason=reason)


def resolve_transition(event: TCEvent, ctx: TransitionContext) -> Transition:
    """Resolve an event against the current context into a Transition"""
    if event is TCEvent.READY_VOTE:
        return resolve_ready(ctx)

    if event is TCEvent.MOVE_WAITING:
        if ctx.state is MapState.WAITING:
            return rejected("Map is already in WAITING MAPPER.")
        return Transition(True, next_state=MapState.WAITING, changelog_category="MapTesting/WAITING")

    if event is TCEvent.RESET:
        # Full reset, as if the channel was just created. Clears all votes as well!.
        return Transition(True, next_state=MapState.TESTING, new_votes={}, changelog_category="MapTesting/RESET")

    if event is TCEvent.RELEASE:
        if ctx.state is MapState.RELEASED:
            return rejected("Map is already set to RELEASED.")
        return Transition(True, next_state=MapState.RELEASED, changelog_category="MapTesting/RELEASED")

    if event is TCEvent.DECLINE:
        if ctx.state is MapState.DECLINED:
            return rejected("Map has already been declined.")
        if ctx.state is MapState.RELEASED:
            return rejected("Unable to decline an already released map.")
        return Transition(True, next_state=MapState.DECLINED, changelog_category="MapTesting/DECLINE")

    if event is TCEvent.AUTHOR_CLEAN_UPLOAD:
        new_votes = vote_fallback(ctx.votes, ctx.bot_id)
        return Transition(
            True,
            next_state=state_from_votes(new_votes),
            new_votes=new_votes,
            changelog_category="MapTesting/AUTO_RESET",
        )

    if event is TCEvent.AUTHOR_BUGGY_UPLOAD:
        # Only advanced maps (i.e. readied maps) move to WAITNG
        if ctx.state not in (MapState.RC, MapState.READY):
            return Transition(True, next_state=ctx.state)
        return Transition(
            True,
            next_state=MapState.WAITING,
            new_votes=vote_fallback(ctx.votes, ctx.bot_id),
            changelog_category="MapTesting/WAITING",
        )

    raise ValueError(f"Unhandled event: {event}")


def resolve_ready(ctx: TransitionContext) -> Transition:
    if ctx.state is MapState.READY:
        return rejected("Map is already set to `Ready`.")
    if ctx.state is MapState.WAITING:
        return rejected("Unable to ready a map in `WAITING`. Reset the channel first, then try again.")
    if ctx.state not in (MapState.TESTING, MapState.RC):
        return rejected(f"Can't ready a map in state `{ctx.state.name}`.")
    if ctx.is_author:
        return rejected(
            "You can't ready your own map. As the channel's owner, it needs to be "
            "readied by a different tester."
        )
    if ctx.actor_id in ctx.votes:
        return rejected(
            "You've already voted on this map. A different tester needs to cast the next vote."
        )

    new_votes = dict(ctx.votes)
    new_votes[ctx.actor_id] = ctx.actor_tier
    next_state = state_from_votes(new_votes)
    return Transition(
        allowed=True,
        next_state=next_state,
        new_votes=new_votes,
        requires_map_recheck=next_state is MapState.READY,
        changelog_category="MapTesting/READY" if next_state is MapState.READY else "MapTesting/RC",
    )
