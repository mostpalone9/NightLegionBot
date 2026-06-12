import time

import discord
from discord import app_commands
from discord.ext import commands

from config import HALL_OF_FAME_FILE
from storage import load_json, save_json


class HallOfFame(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def build_hof_embed(self) -> discord.Embed:
        data = load_json(HALL_OF_FAME_FILE, {"winners": []})
        winners = data.get("winners", [])

        embed = discord.Embed(
            title="🏅 NightLegion Hall of Fame",
            color=discord.Color.gold(),
        )

        if not winners:
            embed.description = "No winners have been recorded yet."
            return embed

        recent = list(reversed(winners[-15:]))

        lines = []
        for winner in recent:
            event_type = winner.get("event_type", "Event")
            event_name = winner.get("event_name", "Unknown")
            winner_name = winner.get("winner_name", "Unknown")
            score = winner.get("score", "N/A")
            note = winner.get("note", "")
            ended_at = winner.get("ended_at", int(time.time()))

            line = (
                f"**{winner_name}** won **{event_type}: {event_name}** "
                f"with **{score}**"
            )

            if note:
                line += f" `({note})`"

            line += f" — <t:{ended_at}:d>"

            lines.append(line)

        embed.description = "\n".join(lines)

        return embed

    @app_commands.command(
        name="hof",
        description="Show the NightLegion Hall of Fame.",
    )
    async def hof(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self.build_hof_embed())

    @app_commands.command(
        name="hall_of_fame",
        description="Show the NightLegion Hall of Fame.",
    )
    async def hall_of_fame(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self.build_hof_embed())

    @app_commands.command(
        name="hof_add",
        description="Manually add a winner to the Hall of Fame.",
    )
    @app_commands.describe(
        event_type="Example: BOTW, SOTW, Loot of the Week, Bingo.",
        event_name="Example: Duke Sucellus, Mining, Theatre of Blood.",
        winner_name="Winner name.",
        score="Score, KC, GP value, points, etc.",
        note="Optional note.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def hof_add(
        self,
        interaction: discord.Interaction,
        event_type: str,
        event_name: str,
        winner_name: str,
        score: int,
        note: str = "",
    ):
        data = load_json(HALL_OF_FAME_FILE, {"winners": []})

        data["winners"].append(
            {
                "event_type": event_type,
                "event_name": event_name,
                "winner_name": winner_name,
                "score": score,
                "note": note,
                "ended_at": int(time.time()),
                "added_by": interaction.user.id,
            }
        )

        save_json(HALL_OF_FAME_FILE, data)

        await interaction.response.send_message(
            f"Added **{winner_name}** to the Hall of Fame.",
            embed=self.build_hof_embed(),
        )

    @app_commands.command(
        name="hall_of_fame_add",
        description="Manually add a winner to the Hall of Fame.",
    )
    @app_commands.describe(
        event_type="Example: BOTW, SOTW, Loot of the Week, Bingo.",
        event_name="Example: Duke Sucellus, Mining, Theatre of Blood.",
        winner_name="Winner name.",
        score="Score, KC, GP value, points, etc.",
        note="Optional note.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def hall_of_fame_add(
        self,
        interaction: discord.Interaction,
        event_type: str,
        event_name: str,
        winner_name: str,
        score: int,
        note: str = "",
    ):
        data = load_json(HALL_OF_FAME_FILE, {"winners": []})

        data["winners"].append(
            {
                "event_type": event_type,
                "event_name": event_name,
                "winner_name": winner_name,
                "score": score,
                "note": note,
                "ended_at": int(time.time()),
                "added_by": interaction.user.id,
            }
        )

        save_json(HALL_OF_FAME_FILE, data)

        await interaction.response.send_message(
            f"Added **{winner_name}** to the Hall of Fame.",
            embed=self.build_hof_embed(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(HallOfFame(bot))