import time
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from config import COMPETITIONS_FILE, HALL_OF_FAME_FILE
from storage import load_json, save_json


CompetitionType = Literal[
    "Skill of the Week",
    "Loot of the Week",
    "Pet of the Week",
    "Collection Log of the Week",
    "Monthly MVP Rankings",
]


COMPETITION_EMOJIS = {
    "Skill of the Week": "⚔️",
    "Loot of the Week": "💰",
    "Pet of the Week": "🐱",
    "Collection Log of the Week": "📜",
    "Monthly MVP Rankings": "👑",
}


class Competitions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def find_active_event(self, event_type: str) -> dict | None:
        data = load_json(COMPETITIONS_FILE, {"events": []})

        for event in data["events"]:
            if event.get("active") and event.get("type") == event_type:
                return event

        return None

    def build_competition_embed(self, event: dict) -> discord.Embed:
        event_type = event["type"]
        emoji = COMPETITION_EMOJIS.get(event_type, "🏆")
        name = event["name"]
        reward = event.get("reward", "Bragging rights")
        start_time = event["start_time"]
        end_time = event["end_time"]
        entries = event.get("entries", {})

        sorted_entries = sorted(
            entries.items(),
            key=lambda item: item[1]["score"],
            reverse=True,
        )

        lines = []

        if sorted_entries:
            for index, (player_name, entry) in enumerate(sorted_entries[:10], start=1):
                score = entry["score"]
                note = entry.get("note", "")

                if note:
                    lines.append(f"**{index}. {player_name} — {score}** `({note})`")
                else:
                    lines.append(f"**{index}. {player_name} — {score}**")
        else:
            lines.append("No entries yet.")

        status = "Active" if event.get("active") else "Completed"

        embed = discord.Embed(
            title=f"{emoji} {event_type}: {name}",
            color=discord.Color.gold() if event.get("active") else discord.Color.dark_grey(),
        )

        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Reward", value=reward, inline=True)
        embed.add_field(name="Started", value=f"<t:{start_time}:f>", inline=True)
        embed.add_field(name="Ends", value=f"<t:{end_time}:f>", inline=True)
        embed.add_field(name="Leaderboard", value="\n".join(lines), inline=False)

        embed.set_footer(text="Scores are manually updated by staff.")

        return embed

    @app_commands.command(
        name="competition_start",
        description="Start a weekly/monthly clan competition.",
    )
    @app_commands.describe(
        event_type="The type of competition.",
        name="Example: Mining, Blood Shards, Pet Drops, Araxxor Log Slots, MVP.",
        duration_days="How many days the event lasts.",
        reward="Reward text.",
    )
    @app_commands.choices(
        event_type=[
            app_commands.Choice(name="⚔️ Skill of the Week", value="Skill of the Week"),
            app_commands.Choice(name="💰 Loot of the Week", value="Loot of the Week"),
            app_commands.Choice(name="🐱 Pet of the Week", value="Pet of the Week"),
            app_commands.Choice(name="📜 Collection Log of the Week", value="Collection Log of the Week"),
            app_commands.Choice(name="👑 Monthly MVP Rankings", value="Monthly MVP Rankings"),
        ]
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def competition_start(
        self,
        interaction: discord.Interaction,
        event_type: app_commands.Choice[str],
        name: str,
        duration_days: int = 7,
        reward: str = "Bragging rights",
    ):
        if duration_days < 1:
            await interaction.response.send_message(
                "Duration must be at least 1 day.",
                ephemeral=True,
            )
            return

        data = load_json(COMPETITIONS_FILE, {"events": []})

        for event in data["events"]:
            if event.get("active") and event.get("type") == event_type.value:
                event["active"] = False

        start_time = int(time.time())
        end_time = start_time + duration_days * 24 * 60 * 60

        event = {
            "id": str(start_time),
            "type": event_type.value,
            "name": name,
            "reward": reward,
            "start_time": start_time,
            "end_time": end_time,
            "active": True,
            "entries": {},
            "created_by": interaction.user.id,
        }

        data["events"].append(event)
        save_json(COMPETITIONS_FILE, data)

        embed = self.build_competition_embed(event)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="competition_add_score",
        description="Add or update a player's score for an active competition.",
    )
    @app_commands.describe(
        event_type="The type of competition.",
        player_name="OSRS username or Discord display name.",
        score="Score, KC, GP value, points, log slots, etc.",
        note="Optional note, like item name or proof.",
    )
    @app_commands.choices(
        event_type=[
            app_commands.Choice(name="⚔️ Skill of the Week", value="Skill of the Week"),
            app_commands.Choice(name="💰 Loot of the Week", value="Loot of the Week"),
            app_commands.Choice(name="🐱 Pet of the Week", value="Pet of the Week"),
            app_commands.Choice(name="📜 Collection Log of the Week", value="Collection Log of the Week"),
            app_commands.Choice(name="👑 Monthly MVP Rankings", value="Monthly MVP Rankings"),
        ]
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def competition_add_score(
        self,
        interaction: discord.Interaction,
        event_type: app_commands.Choice[str],
        player_name: str,
        score: int,
        note: str = "",
    ):
        data = load_json(COMPETITIONS_FILE, {"events": []})

        active_event = None
        for event in data["events"]:
            if event.get("active") and event.get("type") == event_type.value:
                active_event = event
                break

        if active_event is None:
            await interaction.response.send_message(
                f"There is no active **{event_type.value}** event.",
                ephemeral=True,
            )
            return

        active_event.setdefault("entries", {})[player_name] = {
            "score": score,
            "note": note,
            "updated_by": interaction.user.id,
            "updated_at": int(time.time()),
        }

        save_json(COMPETITIONS_FILE, data)

        embed = self.build_competition_embed(active_event)

        await interaction.response.send_message(
            f"Updated **{player_name}** to **{score}**.",
            embed=embed,
        )

    @app_commands.command(
        name="competition_leaderboard",
        description="Show the active leaderboard for a competition.",
    )
    @app_commands.describe(
        event_type="The type of competition.",
    )
    @app_commands.choices(
        event_type=[
            app_commands.Choice(name="⚔️ Skill of the Week", value="Skill of the Week"),
            app_commands.Choice(name="💰 Loot of the Week", value="Loot of the Week"),
            app_commands.Choice(name="🐱 Pet of the Week", value="Pet of the Week"),
            app_commands.Choice(name="📜 Collection Log of the Week", value="Collection Log of the Week"),
            app_commands.Choice(name="👑 Monthly MVP Rankings", value="Monthly MVP Rankings"),
        ]
    )
    async def competition_leaderboard(
        self,
        interaction: discord.Interaction,
        event_type: app_commands.Choice[str],
    ):
        event = self.find_active_event(event_type.value)

        if event is None:
            await interaction.response.send_message(
                f"There is no active **{event_type.value}** event.",
                ephemeral=True,
            )
            return

        embed = self.build_competition_embed(event)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="competition_end",
        description="End an active competition and optionally save the winner to Hall of Fame.",
    )
    @app_commands.describe(
        event_type="The type of competition.",
        save_to_hof="Whether to save the winner to Hall of Fame.",
    )
    @app_commands.choices(
        event_type=[
            app_commands.Choice(name="⚔️ Skill of the Week", value="Skill of the Week"),
            app_commands.Choice(name="💰 Loot of the Week", value="Loot of the Week"),
            app_commands.Choice(name="🐱 Pet of the Week", value="Pet of the Week"),
            app_commands.Choice(name="📜 Collection Log of the Week", value="Collection Log of the Week"),
            app_commands.Choice(name="👑 Monthly MVP Rankings", value="Monthly MVP Rankings"),
        ]
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def competition_end(
        self,
        interaction: discord.Interaction,
        event_type: app_commands.Choice[str],
        save_to_hof: bool = True,
    ):
        data = load_json(COMPETITIONS_FILE, {"events": []})

        active_event = None
        for event in data["events"]:
            if event.get("active") and event.get("type") == event_type.value:
                active_event = event
                break

        if active_event is None:
            await interaction.response.send_message(
                f"There is no active **{event_type.value}** event.",
                ephemeral=True,
            )
            return

        active_event["active"] = False

        entries = active_event.get("entries", {})

        winner_text = "No entries were submitted."

        if entries:
            winner_name, winner_entry = max(
                entries.items(),
                key=lambda item: item[1]["score"],
            )
            winner_score = winner_entry["score"]
            winner_note = winner_entry.get("note", "")

            winner_text = f"👑 Winner: **{winner_name}** with **{winner_score}**"

            if winner_note:
                winner_text += f" `({winner_note})`"

            if save_to_hof:
                hof = load_json(HALL_OF_FAME_FILE, {"winners": []})
                hof["winners"].append(
                    {
                        "event_type": active_event["type"],
                        "event_name": active_event["name"],
                        "winner_name": winner_name,
                        "score": winner_score,
                        "note": winner_note,
                        "ended_at": int(time.time()),
                    }
                )
                save_json(HALL_OF_FAME_FILE, hof)

        save_json(COMPETITIONS_FILE, data)

        embed = self.build_competition_embed(active_event)

        await interaction.response.send_message(
            content=f"{COMPETITION_EMOJIS.get(event_type.value, '🏆')} **{event_type.value} ended!** {winner_text}",
            embed=embed,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Competitions(bot))