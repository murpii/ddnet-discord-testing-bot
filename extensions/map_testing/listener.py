import discord
from discord.ext import commands, tasks

from constants import Channels, Webhooks
from extensions.map_testing.views.approval import resolved


class TestingListener(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.scores_topic_fallback.start()

    def cog_unload(self):
        self.scores_topic_fallback.cancel()

    @tasks.loop(hours=3)
    async def scores_topic_fallback(self):
        if self.scores_topic_fallback.current_loop == 0:
            return
        self.bot.testing_manager.request_scores_refresh()

    @scores_topic_fallback.before_loop
    async def before_scores_topic_fallback(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return

        manager = self.bot.testing_manager

        if message.channel.id == Channels.TESTING_SUBMIT:
            await manager.handle_initial_submission(message)
        elif message.channel.id in manager.test_channels:
            tc = manager.test_channels[message.channel.id]
            await manager.handle_testing_submission(message, tc)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        entry = self.bot.testing_manager.pending_approvals.pop(payload.message_id, None)
        if entry is None:
            return
        channel_id, prompt_id = entry
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        try:
            prompt = await channel.fetch_message(prompt_id)
            await prompt.edit(
                view=resolved("⚠️ The original submission was deleted.", discord.Color.dark_gray())
            )
        except discord.HTTPException:
            pass

    @commands.Cog.listener("on_message")
    async def cleanup_pin_messages(self, message: discord.Message):
        # We pin the current map in each testing channel, which makes Discord
        # post a "pinned a message" system notice. Not something we need to see and unncessarily extends the chat.
        if (
                message.type is discord.MessageType.pins_add
                and message.author.id == self.bot.user.id
                and message.channel.id != Channels.TESTING_SUBMIT
                and getattr(message.channel, "category_id", None)
                in (Channels.CAT_TESTING, Channels.CAT_WAITING, Channels.CAT_EVALUATED)
        ):
            try:
                await message.delete()
            except discord.HTTPException:
                pass

    @commands.Cog.listener("on_message")
    async def handle_map_release(self, message: discord.Message):
        # The DDNet map-releases webhook announces a released map; auto-set its testing
        # channel to RELEASED. Webhook messages have author.bot=True, so the main
        # on_message ignores them -- this dedicated listener handles them.
        if message.webhook_id != Webhooks.DDNET_MAP_RELEASES:
            return
        await self.bot.testing_manager.handle_map_release(message)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await self.bot.testing_manager.handle_channel_delete(channel)
