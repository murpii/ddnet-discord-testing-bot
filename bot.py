import asyncio
import logging
import platform
import time
import sys
from configparser import ConfigParser
from typing import Optional
import traceback

import aiohttp
import discord
from discord import Intents
from discord.ext import commands
from colorama import Back, Fore, Style

from constants import Guilds

from extensions.map_testing.manager import TestingManager

config = ConfigParser()
config.read("config.ini")

discord.voice_client.VoiceClient.warn_nacl = False
log = logging.getLogger()

extensions = [
    ("extensions.logutils.logger", True),
    ("extensions.logutils.errorhandler", True),
    ("extensions.map_testing", True),
    # ("extensions.map_testing.secret_testing", True),
]


class DDNetTestingBot(commands.Bot):
    """Represents the DDNet Testing bot.

    This class extends the `commands.Bot` to provide additional functionality specific to the DDNet community.
    It initializes various components such as session management and caching.

    Attributes:
        config: Configuration settings for the bot.
        session: The current session for managing user interactions.
        session_manager: An instance of the SessionManager for managing sessions.
        synced: A flag indicating whether the bot's commands have been synced.
    """

    def __init__(self, **kwargs):
        super().__init__(
            command_prefix="$",
            help_command=None,
            intents=Intents().all(),
        )

        self.config = kwargs.pop("config")
        # Map rendering (thumbnails + visual diffs) needs a GPU or software rasterizer.
        # Set [TESTING_CHANNELS] RENDERING = false on hosts without one.
        self.rendering_enabled = self.config.getboolean("TESTING_CHANNELS", "RENDERING", fallback=True)
        # Automatic map checks shell out to the twmap-check binaries in data/map-testing/.
        # Set [TESTING_CHANNELS] MAP_CHECKS = false to skip them entirely.
        self.map_checks_enabled = self.config.getboolean("TESTING_CHANNELS", "MAP_CHECKS", fallback=True)
        self.session = None
        self.testing_manager = TestingManager(self)
        self.session_manager = SessionManager()
        self.synced = False

    async def close(self):
        """Closes the bot and releases all resources."""

        log.info("Closing")
        for session in self.session_manager.sessions.values():
            await session.close()
        await super().close()

    async def setup_hook(self):
        """|coro|
        Initializes the bot by loading extensions and acquiring the HTTP session.

        This function iterates through the extensions, loading each one that is
        marked for initialization, then retrieves a session for the bot's operations.
        """

        for cog, init in extensions:
            if init:
                try:
                    await self.load_extension(cog)
                    log.info(f"Successfully loaded {cog}")
                except Exception:
                    logging.error("Failed to load extension:\n%s", traceback.format_exc())

        log.info(f"Python version: {sys.version}")
        log.info(f"Discord.py version: {discord.__version__}")

        self.session = await self.session_manager.get_session(self.__class__.__name__)

    async def on_ready(self):
        await self.wait_until_ready()
        # Using colorama here, so ANSI escape character sequences work under MS Windows
        prefix = (
                Back.RESET
                + Fore.GREEN
                + time.strftime("%H:%M:%S UTC", time.gmtime())
                + Back.RESET
                + Fore.WHITE
                + Style.BRIGHT
        )
        print(f"{prefix} Logged in as {Fore.YELLOW}{self.user.name}")
        print(f"{prefix} Bot ID {Fore.YELLOW}{str(self.user.id)}")
        print(f"{prefix} Discord.py Version {Fore.YELLOW}{discord.__version__}")
        print(f"{prefix} Python Version {Fore.YELLOW}{str(platform.python_version())}")

        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Game(name="DDNet")
        )

        await self.testing_manager.load_testing_channels()
        # FOR DEBUG PURPOSES ONLY: self.testing_manager.debug_dump()

        # on_ready is called multiple times and syncing is heavily rate-limited
        # so a check here should hopefully ensure this only happens once
        if not self.synced:
            synced_global = await self.tree.sync()
            # Commands useful only on the DDNet discord server (i.e: map testing related commands)
            synced_guild = await self.tree.sync(guild=discord.Object(Guilds.DDNET))

            self.synced = True
            log.info(
                f"Slash CMDs Synced - Global: {len(synced_global)}, Guild: {len(synced_guild)}"
            )

    # This is kinda useless as we reload the bot daily. The message cache gets cleared with every reload.
    def get_message(self, message_id: int) -> Optional[discord.Message]:
        return discord.utils.get(self.cached_messages, id=message_id)

    @staticmethod
    async def reply(message: discord.Message, content: Optional[str] = None, **kwargs) -> discord.Message:
        reference = message if message.reference is None else message.reference
        if isinstance(reference, discord.MessageReference):
            reference.fail_if_not_exists = False
        return await message.channel.send(content, reference=reference, **kwargs)

    async def get_or_fetch_member(self, *, guild: discord.Guild, user_id: int) -> discord.Member | discord.User | None:
        try:
            return guild.get_member(user_id) or await guild.fetch_member(user_id)
        except discord.NotFound:
            try:
                return await self.fetch_user(user_id)
            except discord.NotFound:
                return None


class SessionManager:
    """Manages HTTP sessions for different components of the bot.

    Attributes:
        sessions (dict): A dictionary that stores active sessions keyed by cog names.

    Methods:
        get_session(cog_name): Retrieves an existing session or creates a new one for the specified cog.
        Close_session(cog_name): Closes and removes the session associated with the specified cog.
    """

    def __init__(self):
        self.sessions = {}

    def __repr__(self):
        return f"{self.sessions}"

    async def get_session(self, cog_name):
        if cog_name not in self.sessions:
            self.sessions[cog_name] = aiohttp.ClientSession()
        return self.sessions[cog_name]

    async def close_session(self, cog_name):
        if cog_name in self.sessions:
            await self.sessions[cog_name].close()
            del self.sessions[cog_name]


async def main():
    async with aiohttp.ClientSession() as session:
        client = DDNetTestingBot(config=config, session=session)
        await client.start(config.get("AUTH", "TOKEN_DISCORD"), reconnect=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped via keyboard interrupt")
