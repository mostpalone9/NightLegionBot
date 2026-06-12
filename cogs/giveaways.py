import random
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import GIVEAWAYS_FILE
from storage import load_json, save_json


def parse_duration(duration: str) -> int:
    """
    Converts duration strings like:
    30s, 10m, 2h, 7d

    Returns seconds.
    """
    duration = duration.strip().lower()

    if len(duration) < 2:
        raise ValueError("Invalid duration.")

    amount = int(duration[:-1])
    unit = duration[-1]

    multipliers = {
        "s": 1,
        "m": 60,
        "h": 60 * 60,
        "d": 60 * 60 * 24,
    }

    if unit not in multipliers:
        raise ValueError("Duration must end in s, m, h, or d.")

    return amount * multipliers[unit]


class GiveawayEntryView(discord.ui.View):
    def __init__(self, giveaway_id: str):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

    @discord.ui.button(
        label="Enter Giveaway",
        emoji="🎉",
        style=discord.ButtonStyle.primary,
        custom_id="nightlegion_giveaway_enter",
    )
    async def enter_giveaway(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        data = load_json(GIVEAWAYS_FILE, {})

        giveaway = data.get(self.giveaway_id)
        if not giveaway:
            await interaction.response.send_message(
                "This giveaway no longer exists.",
                ephemeral=True,
            )
            return

        if giveaway.get("ended"):
            await interaction.response.send_message(
                "This giveaway has already ended.",
                ephemeral=True,
            )
            return

        user_id = str(interaction.user.id)
        entries = giveaway.setdefault("entries", [])

        if user_id in entries:
            await interaction.response.send_message(
                "You are already entered in this giveaway.",
                ephemeral=True,
            )
            return

        entries.append(user_id)
        save_json(GIVEAWAYS_FILE, data)

        await interaction.response.send_message(
            "You entered the giveaway. Good luck!",
            ephemeral=True,
        )


class Giveaways(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.giveaway_check_loop.start()

    def cog_unload(self):
        self.giveaway_check_loop.cancel()

    async def cog_load(self):
        """
        Re-register persistent views after bot restart.
        """
        data = load_json(GIVEAWAYS_FILE, {})

        for giveaway_id, giveaway in data.items():
            if not giveaway.get("ended"):
                self.bot.add_view(GiveawayEntryView(giveaway_id))

    def build_giveaway_embed(self, giveaway: dict, ended: bool = False) -> discord.Embed:
        prize = giveaway["prize"]
        winners_count = giveaway["winners_count"]
        host_id = giveaway["host_id"]
        end_time = giveaway["end_time"]
        entries = giveaway.get("entries", [])

        title = "🎉 GIVEAWAY ENDED 🎉" if ended else "🎉 GIVEAWAY 🎉"

        embed = discord.Embed(
            title=title,
            description=f"**{prize}**",
            color=discord.Color.blurple() if not ended else discord.Color.dark_grey(),
        )

        if ended:
            winner_mentions = giveaway.get("winner_mentions", [])
            winners_text = ", ".join(winner_mentions) if winner_mentions else "No valid entrants."
            embed.add_field(name="Winner(s)", value=winners_text, inline=False)
        else:
            embed.add_field(
                name="Ends",
                value=f"<t:{end_time}:R> • <t:{end_time}:f>",
                inline=False,
            )

        embed.add_field(name="Hosted By", value=f"<@{host_id}>", inline=True)
        embed.add_field(name="Entries", value=str(len(entries)), inline=True)
        embed.add_field(name="Winners", value=str(winners_count), inline=True)

        embed.set_footer(text="Click the button below to enter.")

        return embed

    async def finish_giveaway(self, giveaway_id: str) -> Optional[dict]:
        data = load_json(GIVEAWAYS_FILE, {})
        giveaway = data.get(giveaway_id)

        if not giveaway or giveaway.get("ended"):
            return None

        channel = self.bot.get_channel(giveaway["channel_id"])
        if channel is None:
            return None

        entries = giveaway.get("entries", [])
        winners_count = giveaway["winners_count"]

        if entries:
            selected = random.sample(entries, min(winners_count, len(entries)))
        else:
            selected = []

        winner_mentions = [f"<@{user_id}>" for user_id in selected]

        giveaway["ended"] = True
        giveaway["winner_ids"] = selected
        giveaway["winner_mentions"] = winner_mentions

        save_json(GIVEAWAYS_FILE, data)

        try:
            message = await channel.fetch_message(giveaway["message_id"])
            embed = self.build_giveaway_embed(giveaway, ended=True)
            await message.edit(embed=embed, view=None)
        except discord.NotFound:
            pass

        prize = giveaway["prize"]

        if winner_mentions:
            await channel.send(
                f"🎉 Congratulations {', '.join(winner_mentions)}! "
                f"You won **{prize}**."
            )
        else:
            await channel.send(
                f"🎉 Giveaway for **{prize}** ended, but nobody entered."
            )

        return giveaway

    @tasks.loop(seconds=30)
    async def giveaway_check_loop(self):
        await self.bot.wait_until_ready()

        now = int(time.time())
        data = load_json(GIVEAWAYS_FILE, {})

        for giveaway_id, giveaway in list(data.items()):
            if not giveaway.get("ended") and giveaway["end_time"] <= now:
                await self.finish_giveaway(giveaway_id)

    @app_commands.command(
        name="giveaway_start",
        description="Start a giveaway.",
    )
    @app_commands.describe(
        prize="The prize being given away.",
        duration="How long the giveaway lasts. Example: 30m, 2h, 7d.",
        winners="Number of winners.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_start(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winners: int = 1,
    ):
        try:
            seconds = parse_duration(duration)
        except ValueError:
            await interaction.response.send_message(
                "Invalid duration. Use something like `30m`, `2h`, or `7d`.",
                ephemeral=True,
            )
            return

        if winners < 1:
            await interaction.response.send_message(
                "Winner count must be at least 1.",
                ephemeral=True,
            )
            return

        end_time = int(time.time()) + seconds

        giveaway_id = str(int(time.time() * 1000))

        giveaway = {
            "id": giveaway_id,
            "guild_id": interaction.guild_id,
            "channel_id": interaction.channel_id,
            "message_id": None,
            "host_id": interaction.user.id,
            "prize": prize,
            "winners_count": winners,
            "end_time": end_time,
            "entries": [],
            "ended": False,
            "winner_ids": [],
            "winner_mentions": [],
        }

        view = GiveawayEntryView(giveaway_id)
        embed = self.build_giveaway_embed(giveaway)

        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()

        giveaway["message_id"] = message.id

        data = load_json(GIVEAWAYS_FILE, {})
        data[giveaway_id] = giveaway
        save_json(GIVEAWAYS_FILE, data)

        self.bot.add_view(view)

    @app_commands.command(
        name="giveaway_end",
        description="End a giveaway immediately.",
    )
    @app_commands.describe(
        message_id="The message ID of the giveaway.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_end(
        self,
        interaction: discord.Interaction,
        message_id: str,
    ):
        data = load_json(GIVEAWAYS_FILE, {})

        giveaway_id = None
        for current_id, giveaway in data.items():
            if str(giveaway.get("message_id")) == message_id:
                giveaway_id = current_id
                break

        if giveaway_id is None:
            await interaction.response.send_message(
                "Could not find a giveaway with that message ID.",
                ephemeral=True,
            )
            return

        await self.finish_giveaway(giveaway_id)

        await interaction.response.send_message(
            "Giveaway ended.",
            ephemeral=True,
        )

    @app_commands.command(
        name="giveaway_reroll",
        description="Reroll winners for an ended giveaway.",
    )
    @app_commands.describe(
        message_id="The message ID of the giveaway.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_reroll(
        self,
        interaction: discord.Interaction,
        message_id: str,
    ):
        data = load_json(GIVEAWAYS_FILE, {})

        giveaway = None
        for current in data.values():
            if str(current.get("message_id")) == message_id:
                giveaway = current
                break

        if giveaway is None:
            await interaction.response.send_message(
                "Could not find a giveaway with that message ID.",
                ephemeral=True,
            )
            return

        entries = giveaway.get("entries", [])
        winners_count = giveaway["winners_count"]

        if not entries:
            await interaction.response.send_message(
                "Nobody entered this giveaway.",
                ephemeral=True,
            )
            return

        selected = random.sample(entries, min(winners_count, len(entries)))
        winner_mentions = [f"<@{user_id}>" for user_id in selected]

        giveaway["winner_ids"] = selected
        giveaway["winner_mentions"] = winner_mentions

        save_json(GIVEAWAYS_FILE, data)

        await interaction.response.send_message(
            f"🎉 New winner(s): {', '.join(winner_mentions)}",
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))