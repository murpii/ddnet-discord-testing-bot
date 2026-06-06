import hashlib
import json
import logging
import os
import re
from io import BytesIO
from typing import Dict, List

import discord

from extensions.map_testing.models.channel_factory import TestingChannel
from utils.conn import ddnet_upload
from utils.misc import maybe_coroutine

log = logging.getLogger("mt")

# Bare-URL unwrap: turn Discord's <https://...> (suppressed-embed form) into the plain
# link so markdown/renderers treat it as a URL.
URL_RE = r"<((?:https?|steam):\/\/(?:-\.)?(?:[^\s\/?\.#-]+\.?)+(?:\/[^\s]*)?)>"
_IMAGE_EXTS = ("png", "jpg", "jpeg", "gif", "webp")
ASSET_DIRS = {"avatar": "avatars", "attachment": "attachments", "emoji": "emojis"}


def format_size(size):
    for unit in ("B", "KB", "MB"):
        if size < 1024.0:
            return round(size, 2), unit
        size /= 1024.0


class TestLogError(Exception):
    pass


class TestLog:
    """Serialises a testing channel's full history into the JSON + asset bundle
    consumed by the ddnet-map-testing-log web renderer.
    """

    __slots__ = (
        "bot",
        "tc",
        "guild",
        "_messages",
        "_avatars",
        "_attachments",
        "_emojis",
    )

    VERSION = 1.0

    def __init__(self, bot, tc: TestingChannel):
        self.bot = bot
        self.tc = tc
        self.guild = tc.guild

        self._messages = []
        self._avatars = {}
        self._attachments = {}
        self._emojis = {}

    @property
    def name(self) -> str:
        return self.tc.filename

    @property
    def topic(self) -> str:
        return self.tc.channel_topic().splitlines()[0].replace("**", "")

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def content(self) -> Dict:
        return {
            "protocol": {"version": self.VERSION},
            "name": self.name,
            "topic": self.topic,
            "messages": self._messages,
        }

    @property
    def assets(self) -> Dict:
        return {
            "avatar": self._avatars,
            "attachment": self._attachments,
            "emoji": self._emojis,
        }

    def json(self) -> str:
        return json.dumps(self.content)

    @staticmethod
    def color_hex(colour) -> str | None:
        return f"#{colour.value:06x}" if colour is not None else None

    def store_image(self, url: str) -> str:
        """Register an embed/component image URL for download; return its stored
        filename (under the renderer's files/attachments/ dir)."""
        tail = url.split("?", 1)[0].rsplit("/", 1)[-1]
        ext = tail.rsplit(".", 1)[-1].lower() if "." in tail else "png"
        if ext not in _IMAGE_EXTS:
            ext = "png"
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        filename = f"{key}.{ext}"
        self._attachments[filename] = url
        return filename

    def mention_name(self, uid: int) -> str:
        user = self.guild.get_member(uid) or self.bot.get_user(uid)
        if user is None:
            return "@unknown-user"
        name = user.display_name if isinstance(user, discord.Member) else user.name
        return f"@{name}"

    def channel_name(self, cid: int) -> str:
        channel = self.bot.get_channel(cid)
        return f"#{channel.name}" if channel is not None else "#unknown-channel"

    def role_name(self, rid: int) -> str:
        role = self.guild.get_role(rid)
        return f"@{role.name}" if role is not None else "@unknown-role"

    def resolve_inline(self, text: str) -> str:
        """Flatten Discord markup (mentions, emoji, subtext) to plain markdown the
        renderer can pass straight to Parsedown."""
        text = re.sub(r"(?m)^-#\s*", "", text)  # Discord "subtext" marker -> plain line
        text = re.sub(r"<@!?(\d+)>", lambda m: self.mention_name(int(m.group(1))), text)
        text = re.sub(r"<#(\d+)>", lambda m: self.channel_name(int(m.group(1))), text)
        text = re.sub(r"<@&(\d+)>", lambda m: self.role_name(int(m.group(1))), text)
        text = re.sub(r"<a?:(\w+):\d+>", r":\1:", text)  # custom emoji -> :name:
        text = re.sub(URL_RE, r"\1", text)
        return text

    @staticmethod
    def handle_multiline_codeblock(text: str) -> Dict:
        return {"multiline-codeblock": {"text": text}}

    @staticmethod
    def handle_inline_codeblock(self, text: str) -> Dict:
        return {"inline-codeblock": {"text": text}}

    async def handle_custom_emoji(self, animated: str, emoji_name: str, emoji_id: str) -> Dict:
        if not emoji_id.isdigit():
            raise TestLogError(f"{self.tc.map_name}: Invalid emoji ID")

        emoji = discord.PartialEmoji(
            animated=bool(animated), name=emoji_name, id=int(emoji_id)
        )

        emoji_url = str(emoji.url)
        async with self.bot.session.get(emoji_url) as resp:
            if resp.status != 200:
                raise TestLogError(":deleted-emoji:")

        self._emojis[f"{emoji.id}.png"] = emoji_url

        return {"custom-emoji": {"name": emoji.name, "id": emoji.id}}

    async def handle_user_mention(self, user_id: str) -> Dict:
        user_id = int(user_id)
        user = self.guild.get_member(user_id) or self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except discord.NotFound:
                raise TestLogError("@Deleted User")

        return {"user-mention": self.handle_user(user)}

    async def handle_channel_mention(self, channel_id: str) -> Dict:
        channel_id = int(channel_id)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.NotFound:
                raise TestLogError("#deleted-channel")

        return {
            "channel-mention": {
                "name": channel.name,
                "highlight": channel.guild == self.guild,
            }
        }

    def handle_role_mention(self, role_id: str) -> Dict:
        role = self.guild.get_role(int(role_id))
        if role is None:
            raise TestLogError("@Deleted Role")

        return {"role-mention": {"name": role.name, "highlight": role.mentionable}}

    def handle_user(self, user: discord.User) -> Dict:
        # display_avatar is the custom avatar if set, else the user's default avatar.
        avatar = user.display_avatar
        self._avatars[f"{avatar.key}.png"] = str(avatar.with_format("png").url)

        roles = ["generic"]
        if isinstance(user, discord.Member):
            roles += [r.name for r in user.roles if not r.is_default()]
        return {
            "name": user.name,
            "discriminator": user.discriminator,
            "avatar": {"id": avatar.key},
            "roles": roles[::-1],
        }

    async def _handle_text(self, text: str) -> Dict:
        out = [
            {"text": re.sub(URL_RE, r"\1", text)}
        ]  # TODO: handle urls after codeblocks

        regexes = {
            r"\`\`\`(?:[^\`]*?\n)?([^\`]+)\n?\`\`\`": self.handle_multiline_codeblock,
            r"(?:\`|\`\`)([^\`]+)(?:\`|\`\`)": self.handle_inline_codeblock,
            r"<(a)?:(.*):(\d*)>": self.handle_custom_emoji,
            r"<@!?(\d+)>": self.handle_user_mention,
            r"<#(\d+)>": self.handle_channel_mention,
            r"<@&(\d+)>": self.handle_role_mention,
        }

        for regex, handler in regexes.items():
            for i, chunk in enumerate(out):
                text = chunk.get("text", None)
                if text is None:
                    continue

                match = re.search(regex, text)
                if match is None:
                    continue

                start = text[: match.start()]
                end = text[match.end():]

                try:
                    processed = await maybe_coroutine(handler, *match.groups())
                except TestLogError as exc:
                    out[i] = {"text": start + str(exc) + end}
                else:
                    if start:
                        out[i] = {"text": start}
                        i += 1
                    else:
                        del out[i]

                    out.insert(i, processed)

                    if end:
                        out.insert(i + 1, {"text": end})

        return {"text": out}

    def handle_attachment(self, attachment: discord.Attachment, message: discord.Message) -> Dict:
        try:
            filename, ext = attachment.filename.rsplit(".", 1)
        except ValueError:
            raise TestLogError(
                "Attachment without extension | "
                f"filename={attachment.filename} | "
                f"attachment_url={attachment.url} | "
                f"message_url={message.jump_url}"
            )

        ext = ext.lower()
        self._attachments[f"{attachment.id}.{ext}"] = attachment.url

        out = {
            "id": attachment.id,
            "basename": filename,
            "extension": f".{ext}",
        }

        if ext in _IMAGE_EXTS:
            return {"image": out}
        else:
            # Non-images (incl. videos) render as a download link rather than being
            # dropped, so nothing in the channel silently disappears.
            size, unit = format_size(attachment.size)
            out.update({"filesize": size, "filesize-units": unit})
            return {"attachment": out}

    def handle_reactions(self, reactions: List[discord.Reaction]) -> Dict:
        out = []
        for reaction in reactions:
            emoji = reaction.emoji
            chunk = {"count": reaction.count}

            if reaction.is_custom_emoji():
                if isinstance(emoji, str):
                    continue
                else:
                    self._emojis[f"{emoji.id}.png"] = str(emoji.url)
                    chunk.update({"name": emoji.name, "id": emoji.id})
            else:
                chunk["emoji"] = emoji

            out.append(chunk)

        return {"reactions": out}

    def handle_embed(self, embed: discord.Embed) -> Dict:
        out: Dict = {"accent-color": self.color_hex(embed.colour)}
        if embed.author and embed.author.name:
            out["author"] = embed.author.name
            if embed.author.icon_url:
                out["author-icon"] = self.store_image(embed.author.icon_url)
        if embed.title:
            out["title"] = embed.title
        if embed.url:
            out["url"] = embed.url
        if embed.description:
            out["description"] = self.resolve_inline(embed.description)
        if embed.fields:
            out["fields"] = [
                {
                    "name": f.name,
                    "value": self.resolve_inline(f.value or ""),
                    "inline": bool(f.inline),
                }
                for f in embed.fields
            ]
        if embed.image and embed.image.url:
            out["image"] = self.store_image(embed.image.url)
        if embed.thumbnail and embed.thumbnail.url:
            out["thumbnail"] = self.store_image(embed.thumbnail.url)
        if embed.footer and embed.footer.text:
            out["footer"] = embed.footer.text
        return {"embed": out}


    def walk_container(self, comp) -> List[Dict]:
        # Mostly for ContainerViews
        CT = discord.ComponentType
        blocks: List[Dict] = []

        def add_text(s: str):
            if s and s.strip():
                blocks.append({"md": self.resolve_inline(s)})

        def add_buttons(children):
            btns = [
                {"label": b.label or "Link", "url": b.url}
                for b in children
                if getattr(b, "url", None)
            ]
            if btns:
                blocks.append({"buttons": btns})

        for child in getattr(comp, "children", []):
            t = child.type
            if t is CT.text_display:
                add_text(child.content)
            elif t is CT.separator:
                blocks.append({"separator": True})
            elif t is CT.section:
                for c in child.children:
                    if c.type is CT.text_display:
                        add_text(c.content)
                acc = child.accessory
                if acc is not None:
                    if acc.type is CT.thumbnail and acc.media:
                        blocks.append({"image": self.store_image(acc.media.url)})
                    elif acc.type is CT.button and getattr(acc, "url", None):
                        blocks.append({"buttons": [{"label": acc.label or "Link", "url": acc.url}]})
            elif t is CT.thumbnail and getattr(child, "media", None):
                blocks.append({"image": self.store_image(child.media.url)})
            elif t is CT.media_gallery:
                for item in child.items:
                    if item.media:
                        blocks.append({"image": self.store_image(item.media.url)})
            elif t is CT.action_row:
                add_buttons(child.children)

        return blocks

    def handle_components(self, message: discord.Message) -> List[Dict]:
        CT = discord.ComponentType
        out: List[Dict] = []
        for comp in message.components:
            t = comp.type
            if t is CT.container:
                out.append({
                    "container": {
                        "accent-color": self.color_hex(comp.accent_colour),
                        "blocks": self.walk_container(comp),
                    }
                })
            elif t is CT.action_row:
                btns = [
                    {"label": b.label or "Link", "url": b.url}
                    for b in comp.children
                    if getattr(b, "url", None)
                ]
                if btns:
                    out.append({"container": {"accent-color": None, "blocks": [{"buttons": btns}]}})
            elif t is CT.text_display:
                if comp.content and comp.content.strip():
                    out.append({
                        "container": {
                            "accent-color": None,
                            "blocks": [{"md": self.resolve_inline(comp.content)}],
                        }
                    })
        return out

    async def log_process(self):
        async for message in self.tc.history(limit=None, oldest_first=True):
            try:
                content: List[Dict] = []
                if message.content:
                    content.append(await self._handle_text(message.content))
                for attachment in message.attachments:
                    content.append(self.handle_attachment(attachment, message))
                for embed in message.embeds:
                    content.append(self.handle_embed(embed))
                content.extend(self.handle_components(message))
                if message.reactions:
                    content.append(self.handle_reactions(message.reactions))
            except TestLogError as e:
                raise TestLogError(
                    f"{e} | channel_id={self.tc.channel.id} | "
                    f"channel_name={self.tc.channel.name}"
                ) from e

            self._messages.append(
                {
                    "author": self.handle_user(message.author),
                    "timestamp": message.created_at.isoformat(),
                    "content": content,
                }
            )

    @classmethod
    async def from_testing_channel(cls, bot, tc: TestingChannel):
        self = cls(bot, tc)
        await self.log_process()
        return self


async def archive_testlog(bot, testlog: TestLog, *, output_dir: str, upload: bool = False) -> bool:
    failed = False
    session = bot.session
    config = bot.config

    json_dir = os.path.join(output_dir, "json")
    os.makedirs(json_dir, exist_ok=True)

    js = testlog.json()
    with open(os.path.join(json_dir, f"{testlog.name}.json"), "w", encoding="utf-8") as f:
        f.write(js)

    if upload:
        try:
            await ddnet_upload(session, config, "log", BytesIO(js.encode("utf-8")), testlog.name)
        except RuntimeError:
            failed = True

    for asset_type, assets in testlog.assets.items():
        if not assets:
            continue
        subdir = os.path.join(output_dir, "files", ASSET_DIRS[asset_type])
        os.makedirs(subdir, exist_ok=True)

        for filename, url in assets.items():
            async with session.get(url) as resp:
                if resp.status != 200:
                    log.error("Failed fetching asset %r: %s", filename, await resp.text())
                    failed = True
                    continue
                data = await resp.read()

            with open(os.path.join(subdir, filename), "wb") as f:
                f.write(data)

            if upload:
                try:
                    await ddnet_upload(session, config, asset_type, BytesIO(data), filename)
                except RuntimeError:
                    failed = True
                    continue

    return not failed
