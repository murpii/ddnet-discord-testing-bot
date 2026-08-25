import logging
import re
from configparser import ConfigParser

import discord

from constants import Channels
from extensions.map_testing.enums import CategoryGroup, MapState

log = logging.getLogger("mt")

DISCORD_CATEGORY_LIMIT = 50


class NoCategorySpace(RuntimeError):
    """Every category of a group is full and no new one could be added"""


def group_for_state(state: MapState) -> CategoryGroup:
    if state in (MapState.TESTING, MapState.RC):
        return CategoryGroup.TESTING
    if state is MapState.WAITING:
        return CategoryGroup.WAITING
    return CategoryGroup.EVALUATED


def base_name(name: str) -> str:
    return re.sub(r"\s*\d+$", "", name).strip() or name.strip()


def overflow_index(name: str, base: str) -> int | None:
    match = re.fullmatch(rf"{re.escape(base)}(?:\s*(\d+))?", name.strip(), re.IGNORECASE)
    if match is None:
        return None
    return int(match[1]) if match[1] else 1


def position_in(category: discord.CategoryChannel, state: MapState) -> int:
    if state in (MapState.TESTING, MapState.RC) and category.channels:
        return category.channels[-1].position + 1
    return 0


def read_ids(config: ConfigParser, option: str) -> list[int]:
    raw = config.get("TESTING_CHANNELS", option, fallback="")
    return [int(part.strip()) for part in raw.split(",") if part.strip().isdigit()]


class CategoryRegistry:
    ANCHORS: dict[CategoryGroup, int] = {
        CategoryGroup.TESTING: Channels.CAT_TESTING,
        CategoryGroup.WAITING: Channels.CAT_WAITING,
        CategoryGroup.EVALUATED: Channels.CAT_EVALUATED,
    }

    def __init__(self):
        self.limit = DISCORD_CATEGORY_LIMIT
        self.auto_create = True
        self.prune_empty = False
        self.extra: dict[CategoryGroup, list[int]] = {}
        self._cache: dict[int, tuple[dict[CategoryGroup, list[int]], frozenset[int]]] = {}

    def configure(self, config: ConfigParser) -> None:
        limit = config.getint(
            "TESTING_CHANNELS", "CATEGORY_CHANNEL_LIMIT", fallback=DISCORD_CATEGORY_LIMIT
        )
        self.limit = max(1, min(limit, DISCORD_CATEGORY_LIMIT))
        self.auto_create = config.getboolean("TESTING_CHANNELS", "CATEGORY_AUTO_CREATE", fallback=True)
        self.prune_empty = config.getboolean("TESTING_CHANNELS", "CATEGORY_PRUNE_EMPTY", fallback=False)
        self.extra = {
            group: read_ids(config, f"EXTRA_CATEGORIES_{group.value}")
            for group in CategoryGroup
        }
        self._cache.clear()

    def invalidate(self, guild: discord.Guild) -> None:
        self._cache.pop(guild.id, None)

    def categories(self, guild: discord.Guild, group: CategoryGroup) -> list[discord.CategoryChannel]:
        groups, _ = self.resolve(guild)
        found = (guild.get_channel(cid) for cid in groups.get(group, ()))
        return [c for c in found if isinstance(c, discord.CategoryChannel)]

    def all_categories(self, guild: discord.Guild) -> list[discord.CategoryChannel]:
        return [c for group in CategoryGroup for c in self.categories(guild, group)]

    def ids(self, guild: discord.Guild) -> frozenset[int]:
        _, flat = self.resolve(guild)
        return flat

    def holds_map_channels(self, channel) -> bool:
        guild = getattr(channel, "guild", None)
        category_id = getattr(channel, "category_id", None)
        if guild is None or category_id is None:
            return False
        return category_id in self.ids(guild)

    def resolve(self, guild: discord.Guild):
        cached = self._cache.get(guild.id)
        if cached is None:
            cached = self.discover(guild)
            self._cache[guild.id] = cached
        return cached

    def discover(self, guild: discord.Guild):
        anchor_ids = {int(cid) for cid in self.ANCHORS.values()}
        groups: dict[CategoryGroup, list[int]] = {}

        for group, anchor_id in self.ANCHORS.items():
            anchor = guild.get_channel(int(anchor_id))
            if not isinstance(anchor, discord.CategoryChannel):
                log.warning(
                    "CAT_%s (%d) is not a category in %s; only its EXTRA_CATEGORIES will be used",
                    group.value, anchor_id, guild,
                )
                groups[group] = list(self.extra.get(group, ()))
                continue

            base = base_name(anchor.name)
            siblings = []
            for category in guild.categories:
                if category.id == anchor.id or category.id in anchor_ids:
                    continue
                index = overflow_index(category.name, base)
                if index is not None:
                    siblings.append((index, category.position, category.id))
            siblings.sort()

            ids = [anchor.id] + [cid for _, _, cid in siblings]
            for extra_id in self.extra.get(group, ()):
                if extra_id not in ids:
                    ids.append(extra_id)
            groups[group] = ids

        flat = frozenset(cid for ids in groups.values() for cid in ids)
        return groups, flat

    async def category_for_state(
            self, guild: discord.Guild, state: MapState
    ) -> discord.CategoryChannel:
        group = group_for_state(state)
        categories = self.categories(guild, group)
        if not categories:
            raise NoCategorySpace(
                f"No {group.value} category found. Check CAT_{group.value} in constants.py."
            )

        for category in categories:
            if len(category.channels) < self.limit:
                return category

        if not self.auto_create:
            raise NoCategorySpace(
                f"All {len(categories)} {group.value} categories hold {self.limit} channels "
                f"and CATEGORY_AUTO_CREATE is off."
            )
        return await self.create_overflow(guild, group, categories)

    async def create_overflow(
            self,
            guild: discord.Guild,
            group: CategoryGroup,
            categories: list[discord.CategoryChannel],
    ) -> discord.CategoryChannel:
        anchor = categories[0]
        base = base_name(anchor.name)
        index = max((overflow_index(c.name, base) or 1) for c in categories) + 1

        overwrites = {}
        for target, overwrite in anchor.overwrites.items():
            if isinstance(target, (discord.Role, discord.Member)):
                overwrites[target] = overwrite
            else:
                log.warning(
                    "Dropping unresolvable overwrite %d while cloning #%s", target.id, anchor.name
                )

        try:
            category = await guild.create_category(
                name=f"{base} {index}",
                overwrites=overwrites,
                position=categories[-1].position + 1,
                reason=f"All {group.value} categories reached {self.limit} channels",
            )
        except discord.HTTPException as exc:
            raise NoCategorySpace(
                f"Couldn't create an overflow {group.value} category: {exc}"
            ) from exc

        self.invalidate(guild)
        log.info("Created overflow category #%s (%d) for %s", category.name, category.id, group.value)
        return category

    async def prune(self, guild: discord.Guild) -> int:
        if not self.prune_empty:
            return 0

        deleted = 0
        for group in CategoryGroup:
            for category in self.categories(guild, group)[1:]:
                if category.channels:
                    continue
                try:
                    await category.delete(reason="Empty map testing overflow category")
                except discord.HTTPException as exc:
                    log.warning("Couldn't delete empty category #%s: %s", category.name, exc)
                    continue
                deleted += 1
                log.info("Deleted empty overflow category #%s (%d)", category.name, category.id)

        if deleted:
            self.invalidate(guild)
        return deleted


category_registry = CategoryRegistry()
