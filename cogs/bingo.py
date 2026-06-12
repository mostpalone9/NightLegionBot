import time

import discord
from discord import app_commands
from discord.ext import commands

from config import BINGO_FILE, HALL_OF_FAME_FILE
from storage import load_json, save_json


class Bingo(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_active_bingo(self) -> dict | None:
        data = load_json(BINGO_FILE, {"events": []})

        for event in data["events"]:
            if event.get("active"):
                return event

        return None

    def build_bingo_embed(self, event: dict) -> discord.Embed:
        name = event["name"]

        # New schema
        player_scores = event.get("player_scores", {})

        # Legacy fallback in case old data exists
        if not player_scores and "team_scores" in event:
            player_scores = event.get("team_scores", {})

        tasks = event.get("tasks", [])

        sorted_players = sorted(
            player_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        player_lines = []
        if sorted_players:
            for index, (player_id_or_name, points) in enumerate(sorted_players, start=1):
                if str(player_id_or_name).isdigit():
                    player_label = f"<@{player_id_or_name}>"
                else:
                    player_label = player_id_or_name

                player_lines.append(f"**{index}. {player_label}** — {points} points")
        else:
            player_lines.append("No player scores yet.")

        task_lines = []
        if tasks:
            for index, task in enumerate(tasks[:20], start=1):
                task_lines.append(f"{index}. {task}")
        else:
            task_lines.append("No tasks listed yet.")

        embed = discord.Embed(
            title=f"🎯 Bingo Event: {name}",
            color=discord.Color.purple() if event.get("active") else discord.Color.dark_grey(),
        )

        embed.add_field(
            name="Status",
            value="Active" if event.get("active") else "Completed",
            inline=True,
        )
        embed.add_field(name="Started", value=f"<t:{event['start_time']}:f>", inline=True)
        embed.add_field(name="Ends", value=f"<t:{event['end_time']}:f>", inline=True)
        embed.add_field(name="Players", value="\n".join(player_lines), inline=False)
        embed.add_field(name="Tasks", value="\n".join(task_lines), inline=False)

        return embed

    @app_commands.command(
        name="bingo_start",
        description="Start a bingo event.",
    )
    @app_commands.describe(
        name="Name of the bingo event.",
        duration_days="How many days it lasts.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bingo_start(
        self,
        interaction: discord.Interaction,
        name: str,
        duration_days: int = 7,
    ):
        if duration_days < 1:
            await interaction.response.send_message(
                "Duration must be at least 1 day.",
                ephemeral=True,
            )
            return

        data = load_json(BINGO_FILE, {"events": []})

        for event in data["events"]:
            if event.get("active"):
                event["active"] = False

        start_time = int(time.time())
        end_time = start_time + duration_days * 24 * 60 * 60

        event = {
            "id": str(start_time),
            "name": name,
            "start_time": start_time,
            "end_time": end_time,
            "active": True,
            "player_scores": {},
            "tasks": [],
            "created_by": interaction.user.id,
        }

        data["events"].append(event)
        save_json(BINGO_FILE, data)

        await interaction.response.send_message(embed=self.build_bingo_embed(event))

    @app_commands.command(
        name="bingo_add_player",
        description="Add a Discord user to the active bingo event.",
    )
    @app_commands.describe(
        player="The Discord user to add.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bingo_add_player(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
    ):
        data = load_json(BINGO_FILE, {"events": []})

        active_event = None
        for event in data["events"]:
            if event.get("active"):
                active_event = event
                break

        if active_event is None:
            await interaction.response.send_message(
                "There is no active bingo event.",
                ephemeral=True,
            )
            return

        active_event.setdefault("player_scores", {})[str(player.id)] = 0
        save_json(BINGO_FILE, data)

        await interaction.response.send_message(
            f"Added {player.mention} to bingo.",
            embed=self.build_bingo_embed(active_event),
        )

    @app_commands.command(
        name="bingo_add_task",
        description="Add a task/tile to the active bingo event.",
    )
    @app_commands.describe(
        task="Example: Get a purple from ToA, Complete a Barrows set, Get a pet drop.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bingo_add_task(
        self,
        interaction: discord.Interaction,
        task: str,
    ):
        data = load_json(BINGO_FILE, {"events": []})

        active_event = None
        for event in data["events"]:
            if event.get("active"):
                active_event = event
                break

        if active_event is None:
            await interaction.response.send_message(
                "There is no active bingo event.",
                ephemeral=True,
            )
            return

        active_event.setdefault("tasks", []).append(task)
        save_json(BINGO_FILE, data)

        await interaction.response.send_message(
            f"Added bingo task: **{task}**.",
            embed=self.build_bingo_embed(active_event),
        )

    @app_commands.command(
        name="bingo_set_score",
        description="Set a player's bingo score.",
    )
    @app_commands.describe(
        player="The Discord user.",
        points="Total points.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bingo_set_score(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        points: int,
    ):
        data = load_json(BINGO_FILE, {"events": []})

        active_event = None
        for event in data["events"]:
            if event.get("active"):
                active_event = event
                break

        if active_event is None:
            await interaction.response.send_message(
                "There is no active bingo event.",
                ephemeral=True,
            )
            return

        active_event.setdefault("player_scores", {})[str(player.id)] = points
        save_json(BINGO_FILE, data)

        await interaction.response.send_message(
            f"Set {player.mention} to **{points} points**.",
            embed=self.build_bingo_embed(active_event),
        )

    @app_commands.command(
        name="bingo_add_points",
        description="Add points to a player's bingo score.",
    )
    @app_commands.describe(
        player="The Discord user.",
        points="Points to add.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bingo_add_points(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        points: int,
    ):
        data = load_json(BINGO_FILE, {"events": []})

        active_event = None
        for event in data["events"]:
            if event.get("active"):
                active_event = event
                break

        if active_event is None:
            await interaction.response.send_message(
                "There is no active bingo event.",
                ephemeral=True,
            )
            return

        scores = active_event.setdefault("player_scores", {})
        current_score = scores.get(str(player.id), 0)
        scores[str(player.id)] = current_score + points

        save_json(BINGO_FILE, data)

        await interaction.response.send_message(
            f"Added **{points} points** to {player.mention}. New total: **{scores[str(player.id)]}**.",
            embed=self.build_bingo_embed(active_event),
        )

    @app_commands.command(
        name="bingo_leaderboard",
        description="Show the active bingo leaderboard.",
    )
    async def bingo_leaderboard(self, interaction: discord.Interaction):
        active_event = self.get_active_bingo()

        if active_event is None:
            await interaction.response.send_message(
                "There is no active bingo event.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(embed=self.build_bingo_embed(active_event))

    @app_commands.command(
        name="bingo_end",
        description="End the active bingo event.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bingo_end(self, interaction: discord.Interaction):
        data = load_json(BINGO_FILE, {"events": []})

        active_event = None
        for event in data["events"]:
            if event.get("active"):
                active_event = event
                break

        if active_event is None:
            await interaction.response.send_message(
                "There is no active bingo event.",
                ephemeral=True,
            )
            return

        active_event["active"] = False

        player_scores = active_event.get("player_scores", {})

        # Legacy fallback
        if not player_scores and "team_scores" in active_event:
            player_scores = active_event.get("team_scores", {})

        winner_text = "No player scores were submitted."

        if player_scores:
            winner_id_or_name, winner_score = max(
                player_scores.items(),
                key=lambda item: item[1],
            )

            if str(winner_id_or_name).isdigit():
                winner_name = f"<@{winner_id_or_name}>"
            else:
                winner_name = winner_id_or_name

            winner_text = f"👑 Winner: **{winner_name}** with **{winner_score} points**"

            hof = load_json(HALL_OF_FAME_FILE, {"winners": []})
            hof["winners"].append(
                {
                    "event_type": "Bingo Event",
                    "event_name": active_event["name"],
                    "winner_name": winner_name,
                    "score": winner_score,
                    "note": "Individual bingo winner",
                    "ended_at": int(time.time()),
                }
            )
            save_json(HALL_OF_FAME_FILE, hof)

        save_json(BINGO_FILE, data)

        await interaction.response.send_message(
            content=f"🎯 **Bingo ended!** {winner_text}",
            embed=self.build_bingo_embed(active_event),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Bingo(bot))