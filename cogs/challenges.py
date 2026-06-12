import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import CHALLENGES_FILE
from storage import load_json, save_json


DEFAULT_CHALLENGES = [
    "Complete 10 Barrows chests.",
    "Get 25 boss KC anywhere.",
    "Complete 5 clue scrolls.",
    "Earn 250k total XP.",
    "Send one Chambers of Xeric raid.",
    "Send one Theatre of Blood raid.",
    "Send one Tombs of Amascut raid.",
    "Get one collection log slot.",
    "Complete 50 slayer task kills.",
    "Get one unique drop screenshot.",
    "Do 30 minutes of skilling.",
    "Kill Zulrah 10 times.",
    "Kill Vorkath 10 times.",
    "Complete one wilderness boss trip.",
    "Get one combat achievement.",
]


class Challenges(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def build_challenge_embed(self, challenge: dict) -> discord.Embed:
        embed = discord.Embed(
            title=f"🎲 {challenge['type']} Challenge",
            description=f"**{challenge['text']}**",
            color=discord.Color.orange(),
        )

        embed.add_field(name="Generated", value=f"<t:{challenge['created_at']}:f>", inline=True)

        return embed

    @app_commands.command(
        name="challenge_random",
        description="Generate a random daily or weekly challenge.",
    )
    @app_commands.describe(
        challenge_type="Daily or Weekly.",
    )
    @app_commands.choices(
        challenge_type=[
            app_commands.Choice(name="Daily", value="Daily"),
            app_commands.Choice(name="Weekly", value="Weekly"),
        ]
    )
    async def challenge_random(
        self,
        interaction: discord.Interaction,
        challenge_type: app_commands.Choice[str],
    ):
        text = random.choice(DEFAULT_CHALLENGES)

        challenge = {
            "id": str(int(time.time())),
            "type": challenge_type.value,
            "text": text,
            "created_at": int(time.time()),
            "created_by": interaction.user.id,
        }

        data = load_json(CHALLENGES_FILE, {"challenges": []})
        data["challenges"].append(challenge)
        save_json(CHALLENGES_FILE, data)

        await interaction.response.send_message(embed=self.build_challenge_embed(challenge))

    @app_commands.command(
        name="challenge_custom",
        description="Post a custom daily or weekly challenge.",
    )
    @app_commands.describe(
        challenge_type="Daily or Weekly.",
        text="Challenge text.",
    )
    @app_commands.choices(
        challenge_type=[
            app_commands.Choice(name="Daily", value="Daily"),
            app_commands.Choice(name="Weekly", value="Weekly"),
        ]
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def challenge_custom(
        self,
        interaction: discord.Interaction,
        challenge_type: app_commands.Choice[str],
        text: str,
    ):
        challenge = {
            "id": str(int(time.time())),
            "type": challenge_type.value,
            "text": text,
            "created_at": int(time.time()),
            "created_by": interaction.user.id,
        }

        data = load_json(CHALLENGES_FILE, {"challenges": []})
        data["challenges"].append(challenge)
        save_json(CHALLENGES_FILE, data)

        await interaction.response.send_message(embed=self.build_challenge_embed(challenge))

    @app_commands.command(
        name="challenge_list",
        description="Show recent random challenges.",
    )
    async def challenge_list(self, interaction: discord.Interaction):
        data = load_json(CHALLENGES_FILE, {"challenges": []})
        challenges = data["challenges"][-10:]

        if not challenges:
            await interaction.response.send_message(
                "No challenges have been generated yet.",
                ephemeral=True,
            )
            return

        lines = []
        for challenge in reversed(challenges):
            lines.append(
                f"**{challenge['type']}** — {challenge['text']} `(<t:{challenge['created_at']}:R>)`"
            )

        embed = discord.Embed(
            title="🎲 Recent Challenges",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Challenges(bot))