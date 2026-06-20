import re
from dataclasses import dataclass
from io import BytesIO
from typing import Optional
import discord

from extensions.map_testing.enums import SubmissionState, UploadState, MapServer
from utils.text import sanitize


@dataclass(slots=True)
class Submission:
    message: discord.Message
    attachment: discord.Attachment
    state: SubmissionState = SubmissionState.PENDING
    upload_state: UploadState = UploadState.PENDING
    bytes: Optional[bytes] = None

    def __post_init__(self):
        if not self.attachment.filename.endswith(".map"):
            raise ValueError("Attachment is not a .map file")

    @property
    def filename(self) -> str:
        return self.attachment.filename

    async def buffer(self) -> BytesIO:
        if self.bytes is None:
            self.bytes = await self.attachment.read()
        return BytesIO(self.bytes)

    async def set_upload_state(self, state: UploadState):
        self.upload_state = state

        for reaction in self.message.reactions:
            if str(reaction.emoji) in {s.value for s in UploadState}:
                await self.message.clear_reaction(reaction.emoji)

        await self.message.add_reaction(state.value)

    def __repr__(self):
        return (
            f"Submission("
            f"file={self.filename}, "
            f"state={self.state}, "
            f"messageID={self.message.id}, "
            f"message.author={self.message.author}, "
            f"message.timestamp={self.message.created_at}, "
            f"messageURL={self.message.jump_url}, "
            f"author={self.message.author.id})"
        )


class SubmissionValidator:
    @staticmethod
    async def check(submission: Submission) -> list[str]:
        errors = []

        if not submission.filename.endswith(".map"):
            errors.append("Invalid file extension")

        data = await submission.buffer()
        if len(data.getvalue()) == 0:
            errors.append("Empty file")

        return errors


@dataclass
class InitialSubmission(Submission):
    FORMAT_RE = r'^"(?P<name>.+)" +by +(?P<mappers>.+) +\[(?P<server>.+)\]$'

    # Populated by parse()
    name: Optional[str] = None
    mappers: Optional[list[str]] = None
    server: Optional[str] = None

    def parse(self) -> "InitialSubmission":
        match = re.search(self.FORMAT_RE, self.message.content, re.IGNORECASE)
        if not match:
            raise ValueError("Invalid submission format")

        name = match["name"]
        if sanitize(name) != self.filename[:-4]:
            raise ValueError("Filename mismatch")

        self.name = name
        self.mappers = re.split(r", | , | & | and ", match["mappers"])
        self.server = match["server"].capitalize()
        return self

    @property
    def author(self) -> discord.abc.User:
        return self.message.author

    @property
    def author_mention(self) -> str:
        return self.message.author.mention

    @property
    def server_emoji(self) -> str:
        try:
            return MapServer[self.server].value
        except KeyError:
            return ""
