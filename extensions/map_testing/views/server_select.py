import discord

from extensions.map_testing.cooldown import global_cooldown
from extensions.map_testing.views.embeds import ServerChanged


class ServerSelect(discord.ui.View):
    """ephemeral select for changing a map channel's server/difficulty."""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.select = discord.ui.Select(placeholder="Choose a server...", options=self.servers())
        self.select.callback = self.callback
        self.add_item(self.select)

    @staticmethod
    def servers() -> list[discord.SelectOption]:
        return [
            discord.SelectOption(label="👶 Novice", value="0"),
            discord.SelectOption(label="🌸 Moderate", value="1"),
            discord.SelectOption(label="💪 Brutal", value="2"),
            discord.SelectOption(label="💀 Insane", value="3"),
            discord.SelectOption(label="♿ Dummy", value="4"),
            discord.SelectOption(label="👴 Oldschool", value="5"),
            discord.SelectOption(label="⚡ Solo", value="6"),
            discord.SelectOption(label="🏁 Race", value="7"),
            discord.SelectOption(label="🎉 Fun", value="8"),
        ]

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        tc = self.bot.testing_manager.get_tc_from_interaction(interaction)
        if tc is None:
            await interaction.followup.send("This isn't a tracked testing channel.", ephemeral=True)
            return

        label = next(o.label for o in self.servers() if o.value == self.select.values[0])
        server = label[2:]

        await tc.update(server=server)
        global_cooldown.update_cooldown(tc.channel.id)

        await tc.changelog.add_changelog(
            tc.channel,
            interaction.user,
            category="MapTesting/CHANGE_SERVER",
            string=f'Server has been changed to: "{tc.server}".',
            map_name=tc.map_name,
        )
        await tc.changelog.update_changelog()

        await interaction.followup.send(f"Changed the server type to `{tc.server}`.", ephemeral=True)
        await tc.channel.send(view=ServerChanged(tc), allowed_mentions=discord.AllowedMentions.none())