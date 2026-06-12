import discord
from discord.ext import commands

from config import DISCORD_TOKEN, GUILD_ID


class NightLegionBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True

        super().__init__(
            command_prefix="!",
            intents=intents,
        )

    async def setup_hook(self):
        await self.load_extension("cogs.giveaways")
        await self.load_extension("cogs.botw")
        await self.load_extension("cogs.competitions")
        await self.load_extension("cogs.bingo")
        await self.load_extension("cogs.challenges")
        await self.load_extension("cogs.hall_of_fame")
        await self.load_extension("cogs.event_signups")

        print("Loaded command tree:")
        for command in self.tree.get_commands():
            print(f"- /{command.name}")

        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)

            self.tree.clear_commands(guild=guild)
            self.tree.copy_global_to(guild=guild)

            synced_commands = await self.tree.sync(guild=guild)

            print(f"Synced {len(synced_commands)} commands to guild {GUILD_ID}:")
            for command in synced_commands:
                print(f"- /{command.name}")
        else:
            synced_commands = await self.tree.sync()

            print(f"Synced {len(synced_commands)} commands globally:")
            for command in synced_commands:
                print(f"- /{command.name}")

    async def on_ready(self):
        print(f"Logged in as {self.user} ({self.user.id})")


bot = NightLegionBot()

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in .env")

bot.run(DISCORD_TOKEN)