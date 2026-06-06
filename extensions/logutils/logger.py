import asyncio
import contextlib
import logging
import os
import difflib
import discord
from discord.ext import commands
import itertools
from datetime import datetime, timezone
from io import BytesIO
from typing import List, Tuple, Union

VALID_IMAGE_FORMATS = (".webp", ".jpeg", ".jpg", ".png", ".gif")

if not os.path.exists("logs"):
    os.mkdir("logs")


def setup_logger(name, level, filename, propagate):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = propagate

    file_handler = logging.FileHandler(filename, "a", encoding="utf-8")
    formatter = logging.Formatter(
        "[%(asctime)s][%(levelname)s][%(name)s]: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if name is not None:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)

    # root logger
    setup_logger(None, logging.INFO, "logs/bot.log", propagate=True)
    # map testing logger
    setup_logger("mt", logging.INFO, "logs/map_testing.log", propagate=False)

    # root
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)


async def setup(bot):
    await bot.add_cog(Logging(bot))

