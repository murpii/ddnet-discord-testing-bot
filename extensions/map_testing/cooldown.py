from datetime import datetime, timedelta

import discord


class GlobalCooldown:
    """Tracks and enforces a global cooldown for channel updates, per channel.

    Discord rate-limits channel edits (name/topic/category) to roughly twice
    every 10 minutes. The tester control buttons all edit the channel, so we
    gate them behind this cooldown to avoid getting throttled mid-update.
    """

    def __init__(self, rate: int, per: int):
        self.rate = rate
        self.per = per
        self.cooldowns: dict[int, tuple[datetime, int]] = {}

    def check(self, channel_id: int) -> tuple[bool, float]:
        now = datetime.now()
        if channel_id in self.cooldowns:
            last_used, rate = self.cooldowns[channel_id]
            if now - last_used < timedelta(seconds=self.per) and rate >= self.rate:
                remaining_time = self.per - (now - last_used).total_seconds()
                return True, remaining_time
        return False, 0

    def update_cooldown(self, channel_id: int) -> None:
        now = datetime.now()
        if channel_id in self.cooldowns:
            last_used, rate = self.cooldowns[channel_id]
            if now - last_used >= timedelta(seconds=self.per):
                self.cooldowns[channel_id] = (now, 1)
            else:
                self.cooldowns[channel_id] = (last_used, rate + 1)
        else:
            self.cooldowns[channel_id] = (now, 1)


global_cooldown = GlobalCooldown(rate=2, per=700)


async def cooldown_response(interaction: discord.Interaction) -> bool:
    """Returns True (and replies) if the interaction's channel is on cooldown."""
    if isinstance(interaction.channel, discord.Thread):
        channel_id = interaction.channel.parent.id
    else:
        channel_id = interaction.channel.id

    on_cooldown, remaining_time = global_cooldown.check(channel_id)
    if not on_cooldown:
        return False

    msg = (
        f"Cooldown active. Try again in {remaining_time:.2f} seconds.\n"
        "-# Map channels can only be updated twice every ~15 minutes. "
        "This is a Discord limitation."
    )
    try:
        await interaction.response.send_message(msg, ephemeral=True)
    except discord.errors.InteractionResponded:
        await interaction.followup.send(msg, ephemeral=True)
    return True