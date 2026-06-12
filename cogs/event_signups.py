import time

import discord
from discord import app_commands
from discord.ext import commands

from config import EVENT_SIGNUPS_FILE
from storage import load_json, save_json


class EventSignupView(discord.ui.View):
    def __init__(self, event_id: str):
        super().__init__(timeout=None)
        self.event_id = event_id

        self.add_item(
            discord.ui.Button(
                label="Join Event",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=f"nightlegion_event_join_{event_id}",
            )
        )

        self.add_item(
            discord.ui.Button(
                label="Leave Event",
                emoji="❌",
                style=discord.ButtonStyle.danger,
                custom_id=f"nightlegion_event_leave_{event_id}",
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id", "")

        if custom_id.startswith("nightlegion_event_join_"):
            await self.handle_join(interaction)
            return False

        if custom_id.startswith("nightlegion_event_leave_"):
            await self.handle_leave(interaction)
            return False

        return False

    def find_event(self) -> dict | None:
        data = load_json(EVENT_SIGNUPS_FILE, {"events": []})

        for event in data["events"]:
            if event.get("id") == self.event_id:
                return event

        return None

    async def update_panel_message(self, interaction: discord.Interaction, event: dict):
        if not interaction.guild or not interaction.message:
            return

        role = interaction.guild.get_role(event["role_id"])

        if role is None:
            return

        embed = build_signup_embed(event, role)

        try:
            await interaction.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass

    async def handle_join(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "This only works inside a server.",
                ephemeral=True,
            )
            return

        event = self.find_event()

        if event is None or not event.get("active", True):
            await interaction.response.send_message(
                "This event signup is no longer active.",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(event["role_id"])

        if role is None:
            await interaction.response.send_message(
                "I could not find the event role for this signup.",
                ephemeral=True,
            )
            return

        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "I could not read your server member profile.",
                ephemeral=True,
            )
            return

        if role in member.roles:
            await interaction.response.send_message(
                f"You are already signed up for **{event['name']}**.",
                ephemeral=True,
            )
            return

        try:
            await member.add_roles(role, reason=f"Joined event: {event['name']}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "I do not have permission to give that role. Make sure my bot role is above the event role.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"You joined **{event['name']}** and received {role.mention}.",
            ephemeral=True,
        )

        await self.update_panel_message(interaction, event)

    async def handle_leave(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "This only works inside a server.",
                ephemeral=True,
            )
            return

        event = self.find_event()

        if event is None:
            await interaction.response.send_message(
                "This event signup no longer exists.",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(event["role_id"])

        if role is None:
            await interaction.response.send_message(
                "I could not find the event role for this signup.",
                ephemeral=True,
            )
            return

        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "I could not read your server member profile.",
                ephemeral=True,
            )
            return

        if role not in member.roles:
            await interaction.response.send_message(
                f"You are not currently signed up for **{event['name']}**.",
                ephemeral=True,
            )
            return

        try:
            await member.remove_roles(role, reason=f"Left event: {event['name']}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "I do not have permission to remove that role. Make sure my bot role is above the event role.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"You left **{event['name']}** and {role.mention} was removed.",
            ephemeral=True,
        )

        await self.update_panel_message(interaction, event)


def build_signup_embed(event: dict, role: discord.Role | None = None) -> discord.Embed:
    name = event["name"]
    event_type = event.get("type", "Clan Event")
    description = event.get("description", "")
    created_at = event.get("created_at", int(time.time()))
    active = event.get("active", True)

    embed = discord.Embed(
        title=f"📋 {event_type} Signup: {name}",
        color=discord.Color.green() if active else discord.Color.dark_grey(),
    )

    if description:
        embed.description = description
    else:
        embed.description = "Click **Join Event** to sign up. Click **Leave Event** to opt out."

    embed.add_field(
        name="Status",
        value="Active" if active else "Closed",
        inline=True,
    )

    if role is not None:
        embed.add_field(
            name="Event Role",
            value=role.mention,
            inline=True,
        )

        embed.add_field(
            name="Signed Up",
            value=str(len(role.members)),
            inline=True,
        )

    embed.add_field(
        name="Created",
        value=f"<t:{created_at}:f>",
        inline=True,
    )

    embed.set_footer(text="NightLegion event signup panel")

    return embed


class EventSignups(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        data = load_json(EVENT_SIGNUPS_FILE, {"events": []})

        for event in data["events"]:
            if event.get("active", True):
                self.bot.add_view(EventSignupView(event["id"]))

    @app_commands.command(
        name="event_signup_create",
        description="Create an event signup panel with a Join/Leave button and event role.",
    )
    @app_commands.describe(
        event_type="Example: BOTW, SOTW, Bingo, Loot of the Week.",
        name="Name of the event.",
        description="Optional description shown on the signup panel.",
        role_name="Optional role name. If blank, the bot makes one from the event name.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def event_signup_create(
        self,
        interaction: discord.Interaction,
        event_type: str,
        name: str,
        description: str = "",
        role_name: str = "",
    ):
        if not interaction.guild:
            await interaction.response.send_message(
                "This command only works inside a server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        final_role_name = role_name.strip() if role_name.strip() else f"{event_type} - {name}"

        try:
            role = await interaction.guild.create_role(
                name=final_role_name,
                mentionable=True,
                reason=f"Created event signup role for {name}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I do not have permission to create roles. Give me Manage Roles and make sure my bot role is high enough.",
                ephemeral=True,
            )
            return

        event_id = str(int(time.time() * 1000))

        event = {
            "id": event_id,
            "type": event_type,
            "name": name,
            "description": description,
            "role_id": role.id,
            "guild_id": interaction.guild.id,
            "channel_id": interaction.channel_id,
            "message_id": None,
            "created_at": int(time.time()),
            "created_by": interaction.user.id,
            "active": True,
        }

        view = EventSignupView(event_id)
        embed = build_signup_embed(event, role)

        message = await interaction.followup.send(embed=embed, view=view, wait=True)

        event["message_id"] = message.id

        data = load_json(EVENT_SIGNUPS_FILE, {"events": []})
        data["events"].append(event)
        save_json(EVENT_SIGNUPS_FILE, data)

        self.bot.add_view(view)

    @app_commands.command(
        name="event_signup_close",
        description="Close an event signup panel.",
    )
    @app_commands.describe(
        name="Name of the event to close.",
        delete_role="Whether to delete the event role.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def event_signup_close(
        self,
        interaction: discord.Interaction,
        name: str,
        delete_role: bool = False,
    ):
        if not interaction.guild:
            await interaction.response.send_message(
                "This command only works inside a server.",
                ephemeral=True,
            )
            return

        data = load_json(EVENT_SIGNUPS_FILE, {"events": []})

        event = None
        for current_event in data["events"]:
            if current_event.get("active", True) and current_event["name"].lower() == name.lower():
                event = current_event
                break

        if event is None:
            await interaction.response.send_message(
                f"I could not find an active signup event named **{name}**.",
                ephemeral=True,
            )
            return

        event["active"] = False
        save_json(EVENT_SIGNUPS_FILE, data)

        role = interaction.guild.get_role(event["role_id"])

        if delete_role and role is not None:
            try:
                await role.delete(reason=f"Closed event signup: {event['name']}")
                role = None
            except discord.Forbidden:
                await interaction.response.send_message(
                    "I closed the signup, but I could not delete the role because I lack permission.",
                    ephemeral=True,
                )
                return

        embed = build_signup_embed(event, role)

        channel = interaction.guild.get_channel(event["channel_id"])
        if channel is not None:
            try:
                message = await channel.fetch_message(event["message_id"])
                await message.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            f"Closed signup for **{event['name']}**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="event_signup_list",
        description="List active event signup panels.",
    )
    async def event_signup_list(self, interaction: discord.Interaction):
        data = load_json(EVENT_SIGNUPS_FILE, {"events": []})
        active_events = [event for event in data["events"] if event.get("active", True)]

        if not active_events:
            await interaction.response.send_message(
                "There are no active event signup panels.",
                ephemeral=True,
            )
            return

        lines = []

        for event in active_events[-15:]:
            role_text = f"<@&{event['role_id']}>"
            lines.append(
                f"**{event['type']} — {event['name']}** | {role_text} | <t:{event['created_at']}:R>"
            )

        embed = discord.Embed(
            title="📋 Active Event Signups",
            description="\n".join(lines),
            color=discord.Color.green(),
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EventSignups(bot))