import asyncio
import time
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import BOTW_FILE, BOTW_NOTIFY_ROLE_ID, PLAYER_PROFILES_FILE
from storage import load_json, save_json


WISE_OLD_MAN_BASE_URL = "https://api.wiseoldman.net/v2"
OSRS_WIKI_API_URL = "https://oldschool.runescape.wiki/api.php"
OSRS_WIKI_USER_AGENT = "NightLegionBot/1.0 Discord bot for OSRS clan events"


class WiseOldManRateLimitError(Exception):
    pass


BOSS_METRIC_ALIASES = {
    "abyssal sire": "abyssal_sire",
    "alchemical hydra": "alchemical_hydra",
    "amoxliatl": "amoxliatl",
    "araxxor": "araxxor",
    "artio": "artio",
    "barrows": "barrows_chests",
    "barrows chests": "barrows_chests",
    "bryophyta": "bryophyta",
    "callisto": "callisto",
    "calvarion": "calvarion",
    "calvar'ion": "calvarion",
    "cerberus": "cerberus",
    "chambers of xeric": "chambers_of_xeric",
    "cox": "chambers_of_xeric",
    "chambers of xeric challenge mode": "chambers_of_xeric_challenge_mode",
    "cox cm": "chambers_of_xeric_challenge_mode",
    "chaos elemental": "chaos_elemental",
    "chaos fanatic": "chaos_fanatic",
    "commander zilyana": "commander_zilyana",
    "corporeal beast": "corporeal_beast",
    "crazy archaeologist": "crazy_archaeologist",
    "dagannoth prime": "dagannoth_prime",
    "dagannoth rex": "dagannoth_rex",
    "dagannoth supreme": "dagannoth_supreme",
    "deranged archaeologist": "deranged_archaeologist",
    "duke": "duke_sucellus",
    "duke sucellus": "duke_sucellus",
    "general graardor": "general_graardor",
    "bandos": "general_graardor",
    "giant mole": "giant_mole",
    "grotesque guardians": "grotesque_guardians",
    "hespori": "hespori",
    "kalphite queen": "kalphite_queen",
    "king black dragon": "king_black_dragon",
    "kbd": "king_black_dragon",
    "kraken": "kraken",
    "kree arra": "kree_arra",
    "kree'arra": "kree_arra",
    "kril tsutsaroth": "kril_tsutsaroth",
    "k'ril tsutsaroth": "kril_tsutsaroth",
    "zamorak": "kril_tsutsaroth",
    "lunar chests": "lunar_chests",
    "mimic": "mimic",
    "nex": "nex",
    "nightmare": "nightmare",
    "phosanis nightmare": "phosanis_nightmare",
    "phosani's nightmare": "phosanis_nightmare",
    "obor": "obor",
    "phantom muspah": "phantom_muspah",
    "muspah": "phantom_muspah",
    "sarachnis": "sarachnis",
    "scorpia": "scorpia",
    "scurrius": "scurrius",
    "skotizo": "skotizo",
    "sol heredit": "sol_heredit",
    "spindel": "spindel",
    "the gauntlet": "the_gauntlet",
    "gauntlet": "the_gauntlet",
    "the corrupted gauntlet": "the_corrupted_gauntlet",
    "corrupted gauntlet": "the_corrupted_gauntlet",
    "cg": "the_corrupted_gauntlet",
    "the hueycoatl": "the_hueycoatl",
    "hueycoatl": "the_hueycoatl",
    "the leviathan": "the_leviathan",
    "leviathan": "the_leviathan",
    "the whisperer": "the_whisperer",
    "whisperer": "the_whisperer",
    "theatre of blood": "theatre_of_blood",
    "tob": "theatre_of_blood",
    "theatre of blood hard mode": "theatre_of_blood_hard_mode",
    "tob hm": "theatre_of_blood_hard_mode",
    "thermonuclear smoke devil": "thermonuclear_smoke_devil",
    "tombs of amascut": "tombs_of_amascut",
    "toa": "tombs_of_amascut",
    "tombs of amascut expert": "tombs_of_amascut_expert",
    "toa expert": "tombs_of_amascut_expert",
    "tzkal zuk": "tzkal_zuk",
    "inferno": "tzkal_zuk",
    "tztok jad": "tztok_jad",
    "jad": "tztok_jad",
    "vardorvis": "vardorvis",
    "venenatis": "venenatis",
    "vetion": "vetion",
    "vet'ion": "vetion",
    "vorkath": "vorkath",
    "wintertodt": "wintertodt",
    "zalcano": "zalcano",
    "zulrah": "zulrah",
}


def boss_name_to_metric(boss_name: str) -> str:
    normalized = boss_name.lower().strip().replace("’", "'")

    if normalized in BOSS_METRIC_ALIASES:
        return BOSS_METRIC_ALIASES[normalized]

    return (
        normalized
        .replace("'", "")
        .replace("-", " ")
        .replace(":", " ")
        .replace(",", " ")
        .replace("  ", " ")
        .replace(" ", "_")
    )


def get_saved_rsn(discord_user_id: int) -> str | None:
    data = load_json(PLAYER_PROFILES_FILE, {"players": {}})
    profile = data.get("players", {}).get(str(discord_user_id))

    if not profile:
        return None

    rsn = profile.get("rsn", "").strip()
    return rsn if rsn else None


def save_rsn(discord_user_id: int, discord_display_name: str, rsn: str) -> None:
    data = load_json(PLAYER_PROFILES_FILE, {"players": {}})

    data.setdefault("players", {})[str(discord_user_id)] = {
        "rsn": rsn.strip(),
        "discord_display_name": discord_display_name,
        "updated_at": int(time.time()),
    }

    save_json(PLAYER_PROFILES_FILE, data)


async def wom_update_player(username: str) -> dict:
    encoded_username = quote(username)
    url = f"{WISE_OLD_MAN_BASE_URL}/players/{encoded_username}"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers={"Content-Type": "application/json"}) as response:
            if response.status == 429:
                text = await response.text()

                if "PLAYER_IS_RATE_LIMITED" in text:
                    raise WiseOldManRateLimitError(
                        "Wise Old Man updated this player recently. Their KC will refresh on the next scheduled update."
                    )

                raise WiseOldManRateLimitError(
                    "Wise Old Man is rate limiting requests right now. Try again later."
                )

            if response.status >= 400:
                text = await response.text()
                raise RuntimeError(f"Wise Old Man update failed: {response.status} {text}")

            return await response.json()


def extract_boss_kills(player_details: dict, boss_metric: str) -> int:
    latest_snapshot = player_details.get("latestSnapshot") or player_details.get("latest_snapshot")

    if latest_snapshot is None:
        raise RuntimeError("Wise Old Man did not return a latest snapshot.")

    data = latest_snapshot.get("data", {})
    bosses = data.get("bosses", {})
    boss_data = bosses.get(boss_metric)

    if boss_data is None:
        raise RuntimeError(f"Could not find boss metric '{boss_metric}' in Wise Old Man data.")

    kills = boss_data.get("kills", -1)

    if kills is None or kills < 0:
        return 0

    return int(kills)


async def get_boss_image_url(boss_name: str) -> str | None:
    params = {
        "action": "query",
        "format": "json",
        "prop": "pageimages",
        "piprop": "thumbnail",
        "pithumbsize": "300",
        "redirects": "1",
        "titles": boss_name,
    }

    headers = {
        "User-Agent": OSRS_WIKI_USER_AGENT,
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(OSRS_WIKI_API_URL, params=params) as response:
            if response.status >= 400:
                return None

            data = await response.json()

    pages = data.get("query", {}).get("pages", {})

    for page in pages.values():
        thumbnail = page.get("thumbnail", {})
        source = thumbnail.get("source")

        if source:
            return source

    return None


class BotwNotifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Notify Me",
        emoji="🔔",
        style=discord.ButtonStyle.success,
        custom_id="nightlegion_botw_notify",
    )
    async def notify_me(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not interaction.guild:
            await interaction.response.send_message(
                "This only works inside the server.",
                ephemeral=True,
            )
            return

        if BOTW_NOTIFY_ROLE_ID == 0:
            await interaction.response.send_message(
                "BOTW notify role has not been configured yet.",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(BOTW_NOTIFY_ROLE_ID)

        if role is None:
            await interaction.response.send_message(
                "I could not find the configured BOTW notify role.",
                ephemeral=True,
            )
            return

        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Could not read your server member profile.",
                ephemeral=True,
            )
            return

        if role in member.roles:
            await member.remove_roles(role, reason="BOTW notification opt-out")
            await interaction.response.send_message(
                f"Removed {role.mention}. You will no longer be notified for BOTW.",
                ephemeral=True,
            )
        else:
            await member.add_roles(role, reason="BOTW notification opt-in")
            await interaction.response.send_message(
                f"Added {role.mention}. You will be notified for BOTW.",
                ephemeral=True,
            )


class BotwJoinView(discord.ui.View):
    def __init__(self, cog: "Botw"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Enter BOTW",
        emoji="⚔️",
        style=discord.ButtonStyle.success,
        custom_id="nightlegion_botw_enter",
    )
    async def enter_botw(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        event = self.cog.get_active_event()

        if event is None:
            await interaction.response.send_message(
                "There is no active BOTW event right now.",
                ephemeral=True,
            )
            return

        saved_rsn = get_saved_rsn(interaction.user.id)

        if saved_rsn:
            await interaction.response.defer(ephemeral=True)

            try:
                starting_kc, current_kc, gained_kc = await self.cog.join_event_with_rsn(
                    event=event,
                    interaction=interaction,
                    rsn=saved_rsn,
                )
            except WiseOldManRateLimitError:
                self.cog.register_participant_without_sync(event, interaction, saved_rsn)
                await self.cog.update_public_botw_message(event)

                await interaction.followup.send(
                    (
                        f"You are entered for **{event['boss']}** as **{saved_rsn}**.\n\n"
                        "Wise Old Man updated your account recently, so I could not refresh your KC right now. "
                        "Your KC will update automatically on the next scheduled refresh."
                    ),
                    ephemeral=True,
                )
                return
            except Exception as error:
                await interaction.followup.send(
                    (
                        f"I found your saved RSN, **{saved_rsn}**, but could not sync it.\n\n"
                        f"Use `/botw_set_rsn` if your RSN changed.\n\n"
                        f"Error: `{error}`"
                    ),
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                (
                    f"You are entered for **{event['boss']}** as **{saved_rsn}**.\n"
                    f"Starting KC: **{starting_kc}**\n"
                    f"Current KC: **{current_kc}**\n"
                    f"Current gained KC: **+{gained_kc}**"
                ),
                ephemeral=True,
            )
        else:
            await interaction.response.send_modal(BotwRsnModal(self.cog))


class BotwRsnModal(discord.ui.Modal, title="Enter BOTW"):
    rsn = discord.ui.TextInput(
        label="OSRS Username",
        placeholder="Type your RSN exactly as it appears in game",
        required=True,
        max_length=12,
    )

    def __init__(self, cog: "Botw"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        event = self.cog.get_active_event()

        if event is None:
            await interaction.response.send_message(
                "There is no active BOTW event right now.",
                ephemeral=True,
            )
            return

        entered_rsn = str(self.rsn.value).strip()

        if not entered_rsn:
            await interaction.response.send_message(
                "Please enter a valid RSN.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        save_rsn(interaction.user.id, interaction.user.display_name, entered_rsn)

        try:
            starting_kc, current_kc, gained_kc = await self.cog.join_event_with_rsn(
                event=event,
                interaction=interaction,
                rsn=entered_rsn,
            )
        except WiseOldManRateLimitError:
            self.cog.register_participant_without_sync(event, interaction, entered_rsn)
            await self.cog.update_public_botw_message(event)

            await interaction.followup.send(
                (
                    f"Saved your RSN as **{entered_rsn}** and entered you for **{event['boss']}**.\n\n"
                    "Wise Old Man updated your account recently, so I could not refresh your KC right now. "
                    "Your starting KC will be captured on the next scheduled refresh."
                ),
                ephemeral=True,
            )
            return
        except Exception as error:
            await interaction.followup.send(
                (
                    f"I saved your RSN as **{entered_rsn}**, but could not sync it with Wise Old Man.\n\n"
                    f"Error: `{error}`"
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            (
                f"Saved your RSN as **{entered_rsn}** and entered you for **{event['boss']}**.\n"
                f"Starting KC: **{starting_kc}**\n"
                f"Current KC: **{current_kc}**\n"
                f"Current gained KC: **+{gained_kc}**"
            ),
            ephemeral=True,
        )


class Botw(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.botw_auto_update_loop.start()

    def cog_unload(self):
        self.botw_auto_update_loop.cancel()

    async def cog_load(self):
        self.bot.add_view(BotwNotifyView())
        self.bot.add_view(BotwJoinView(self))

    def get_active_event(self) -> dict | None:
        data = load_json(BOTW_FILE, {"events": []})

        for event in data["events"]:
            if event.get("active"):
                return event

        return None

    def save_active_event(self, updated_event: dict) -> None:
        data = load_json(BOTW_FILE, {"events": []})

        for index, event in enumerate(data["events"]):
            if event.get("id") == updated_event.get("id"):
                data["events"][index] = updated_event
                save_json(BOTW_FILE, data)
                return

    async def update_public_botw_message(self, event: dict) -> None:
        channel_id = event.get("channel_id")
        message_id = event.get("message_id")

        if not channel_id or not message_id:
            return

        channel = self.bot.get_channel(channel_id)

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return

        try:
            message = await channel.fetch_message(message_id)
            await message.edit(
                embed=self.build_botw_embed(event),
                view=BotwJoinView(self) if event.get("active") else None,
            )
        except discord.HTTPException:
            return

    def build_botw_embed(self, event: dict) -> discord.Embed:
        boss = event["boss"]
        start_time = event["start_time"]
        end_time = event["end_time"]
        reward = event.get("reward", "Bragging rights")
        leaderboard = event.get("leaderboard", {})
        participants = event.get("participants", {})

        sorted_players = sorted(
            leaderboard.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        lines = []

        if sorted_players:
            for index, (rsn, gain) in enumerate(sorted_players[:10], start=1):
                participant = participants.get(rsn, {})
                discord_user_id = participant.get("discord_user_id")
                current_kc = participant.get("current_kc")
                starting_kc = participant.get("starting_kc")

                mention = f" <@{discord_user_id}>" if discord_user_id else ""

                kc_text = ""
                if current_kc is not None and starting_kc is not None:
                    kc_text = f" `({starting_kc} → {current_kc})`"
                elif participant.get("sync_pending"):
                    kc_text = " `sync pending`"

                medal = (
                    "🥇"
                    if index == 1
                    else "🥈"
                    if index == 2
                    else "🥉"
                    if index == 3
                    else f"**{index}.**"
                )

                lines.append(f"{medal} **{rsn}**{mention} — **+{gain} KC**{kc_text}")
        else:
            lines.append("No one has entered yet. Click **Enter BOTW** below to join.")

        status = "Active" if event.get("active") else "Completed"

        embed = discord.Embed(
            title=f"🏆 Boss of the Week: {boss}",
            description=(
                "Compete with the clan to gain the most boss KC before the event ends.\n\n"
                "Click **Enter BOTW** below to join. Your KC will be tracked through Wise Old Man."
            ),
            color=discord.Color.gold() if event.get("active") else discord.Color.dark_grey(),
        )

        boss_image_url = event.get("boss_image_url")
        if boss_image_url:
            embed.set_thumbnail(url=boss_image_url)

        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Reward", value=reward, inline=True)
        embed.add_field(name="Participants", value=str(len(participants)), inline=True)

        embed.add_field(name="Started", value=f"<t:{start_time}:f>", inline=True)
        embed.add_field(name="Ends", value=f"<t:{end_time}:R>", inline=True)

        last_updated = event.get("last_updated")
        if last_updated:
            embed.add_field(name="Last Updated", value=f"<t:{last_updated}:R>", inline=True)
        else:
            embed.add_field(name="Last Updated", value="Not yet", inline=True)

        embed.add_field(
            name="Leaderboard",
            value="\n".join(lines),
            inline=False,
        )

        embed.set_footer(text="Use /botw_set_rsn if you need to change your saved OSRS username.")

        return embed

    def register_participant_without_sync(
        self,
        event: dict,
        interaction: discord.Interaction,
        rsn: str,
    ) -> None:
        participants = event.setdefault("participants", {})
        participant = participants.setdefault(rsn, {})

        participant["discord_user_id"] = interaction.user.id
        participant["discord_display_name"] = interaction.user.display_name
        participant["registered_at"] = int(time.time())
        participant["sync_pending"] = True

        event.setdefault("leaderboard", {}).setdefault(rsn, 0)

        self.save_active_event(event)

    async def sync_participant(self, event: dict, rsn: str) -> tuple[int, int, int]:
        boss_metric = event.get("boss_metric", boss_name_to_metric(event["boss"]))

        player_details = await wom_update_player(rsn)
        current_kc = extract_boss_kills(player_details, boss_metric)

        participants = event.setdefault("participants", {})
        participant = participants.setdefault(rsn, {})

        if participant.get("starting_kc") is None:
            participant["starting_kc"] = current_kc

        participant["current_kc"] = current_kc
        participant["last_synced"] = int(time.time())
        participant["sync_pending"] = False

        starting_kc = int(participant.get("starting_kc", current_kc))
        gained_kc = max(0, current_kc - starting_kc)

        event.setdefault("leaderboard", {})[rsn] = gained_kc

        return starting_kc, current_kc, gained_kc

    async def join_event_with_rsn(
        self,
        event: dict,
        interaction: discord.Interaction,
        rsn: str,
    ) -> tuple[int, int, int]:
        starting_kc, current_kc, gained_kc = await self.sync_participant(event, rsn)

        participant = event.setdefault("participants", {}).setdefault(rsn, {})
        participant["discord_user_id"] = interaction.user.id
        participant["discord_display_name"] = interaction.user.display_name
        participant["registered_at"] = participant.get("registered_at", int(time.time()))

        self.save_active_event(event)
        await self.update_public_botw_message(event)

        return starting_kc, current_kc, gained_kc

    async def sync_active_event(self) -> tuple[dict | None, list[str]]:
        event = self.get_active_event()

        if event is None:
            return None, ["There is no active BOTW event."]

        participants = event.get("participants", {})

        if not participants:
            return event, ["No registered participants to update."]

        errors = []

        for rsn in list(participants.keys()):
            try:
                await self.sync_participant(event, rsn)
                await asyncio.sleep(2)
            except WiseOldManRateLimitError as error:
                errors.append(f"{rsn}: {error}")
            except Exception as error:
                errors.append(f"{rsn}: {error}")

        event["last_updated"] = int(time.time())
        self.save_active_event(event)
        await self.update_public_botw_message(event)

        return event, errors

    @tasks.loop(hours=1)
    async def botw_auto_update_loop(self):
        await self.bot.wait_until_ready()

        event = self.get_active_event()

        if event is None:
            return

        if int(time.time()) >= event["end_time"]:
            return

        await self.sync_active_event()

    @app_commands.command(
        name="botw_notify_panel",
        description="Post the BOTW notification role button.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_notify_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔔 BOTW Notifications",
            description=(
                "Click **Notify Me** to receive BOTW announcements. "
                "Click it again to remove the role."
            ),
            color=discord.Color.green(),
        )

        await interaction.response.send_message(
            embed=embed,
            view=BotwNotifyView(),
        )

    @app_commands.command(
        name="botw_start",
        description="Start a Boss of the Week event.",
    )
    @app_commands.describe(
        boss="Boss name, example: Duke Sucellus.",
        duration_days="How many days the event lasts.",
        reward="Reward text, example: 60m or 4 bonds.",
        boss_metric="Optional Wise Old Man metric. Only use if the boss name does not sync correctly.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_start(
        self,
        interaction: discord.Interaction,
        boss: str,
        duration_days: int = 7,
        reward: str = "Bragging rights",
        boss_metric: str = "",
    ):
        if duration_days < 1:
            await interaction.response.send_message(
                "Duration must be at least 1 day.",
                ephemeral=True,
            )
            return

        data = load_json(BOTW_FILE, {"events": []})

        for event in data["events"]:
            if event.get("active"):
                event["active"] = False

        start_time = int(time.time())
        end_time = start_time + duration_days * 24 * 60 * 60
        final_boss_metric = boss_metric.strip() if boss_metric.strip() else boss_name_to_metric(boss)
        boss_image_url = await get_boss_image_url(boss)

        event = {
            "id": str(start_time),
            "boss": boss,
            "boss_metric": final_boss_metric,
            "boss_image_url": boss_image_url,
            "reward": reward,
            "start_time": start_time,
            "end_time": end_time,
            "active": True,
            "leaderboard": {},
            "participants": {},
            "created_by": interaction.user.id,
            "last_updated": None,
            "channel_id": None,
            "message_id": None,
        }

        data["events"].append(event)
        save_json(BOTW_FILE, data)

        embed = self.build_botw_embed(event)

        content = f"<@&{BOTW_NOTIFY_ROLE_ID}> New Boss of the Week is live!" if BOTW_NOTIFY_ROLE_ID else None

        await interaction.response.send_message(
            content=content,
            embed=embed,
            view=BotwJoinView(self),
            allowed_mentions=discord.AllowedMentions(roles=True),
        )

        message = await interaction.original_response()

        event["channel_id"] = interaction.channel_id
        event["message_id"] = message.id

        self.save_active_event(event)

    @app_commands.command(
        name="botw_set_rsn",
        description="Save or update your OSRS username for BOTW.",
    )
    @app_commands.describe(
        rsn="Your OSRS username.",
    )
    async def botw_set_rsn(
        self,
        interaction: discord.Interaction,
        rsn: str,
    ):
        cleaned_rsn = rsn.strip()

        if not cleaned_rsn:
            await interaction.response.send_message(
                "Please enter a valid RSN.",
                ephemeral=True,
            )
            return

        save_rsn(interaction.user.id, interaction.user.display_name, cleaned_rsn)

        await interaction.response.send_message(
            f"Saved your BOTW RSN as **{cleaned_rsn}**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="botw_my_rsn",
        description="Check your saved BOTW OSRS username.",
    )
    async def botw_my_rsn(self, interaction: discord.Interaction):
        saved_rsn = get_saved_rsn(interaction.user.id)

        if not saved_rsn:
            await interaction.response.send_message(
                "You do not have a saved RSN yet. Click **Enter BOTW** on an event or use `/botw_set_rsn`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Your saved BOTW RSN is **{saved_rsn}**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="botw_join",
        description="Join the active BOTW with your saved or provided OSRS username.",
    )
    @app_commands.describe(
        rsn="Optional. Leave blank to use your saved RSN.",
    )
    async def botw_join(
        self,
        interaction: discord.Interaction,
        rsn: str = "",
    ):
        event = self.get_active_event()

        if event is None:
            await interaction.response.send_message(
                "There is no active BOTW event.",
                ephemeral=True,
            )
            return

        final_rsn = rsn.strip() if rsn.strip() else get_saved_rsn(interaction.user.id)

        if not final_rsn:
            await interaction.response.send_message(
                "You do not have a saved RSN yet. Click **Enter BOTW** on the event post or use `/botw_set_rsn`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        if rsn.strip():
            save_rsn(interaction.user.id, interaction.user.display_name, final_rsn)

        try:
            starting_kc, current_kc, gained_kc = await self.join_event_with_rsn(
                event=event,
                interaction=interaction,
                rsn=final_rsn,
            )
        except WiseOldManRateLimitError:
            self.register_participant_without_sync(event, interaction, final_rsn)
            await self.update_public_botw_message(event)

            await interaction.followup.send(
                (
                    f"You are entered for **{event['boss']}** as **{final_rsn}**.\n\n"
                    "Wise Old Man updated this account recently, so I could not refresh KC right now. "
                    "Your KC will update automatically on the next scheduled refresh."
                ),
                ephemeral=True,
            )
            return
        except Exception as error:
            await interaction.followup.send(
                f"I could not sync **{final_rsn}** with Wise Old Man.\n\nError: `{error}`",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            (
                f"You are entered for **{event['boss']}** as **{final_rsn}**.\n"
                f"Starting KC: **{starting_kc}**\n"
                f"Current KC: **{current_kc}**\n"
                f"Current gained KC: **+{gained_kc}**"
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="botw_bind_message",
        description="Bind the active BOTW to an existing Discord message so it can auto-update.",
    )
    @app_commands.describe(
        message_id="The message ID of the BOTW post to auto-update.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_bind_message(
        self,
        interaction: discord.Interaction,
        message_id: str,
    ):
        event = self.get_active_event()

        if event is None:
            await interaction.response.send_message(
                "There is no active BOTW event to bind.",
                ephemeral=True,
            )
            return

        try:
            parsed_message_id = int(message_id)
        except ValueError:
            await interaction.response.send_message(
                "That message ID is not valid. Right-click the BOTW post and copy its message ID.",
                ephemeral=True,
            )
            return

        event["channel_id"] = interaction.channel_id
        event["message_id"] = parsed_message_id

        self.save_active_event(event)

        try:
            await self.update_public_botw_message(event)
        except Exception:
            pass

        await interaction.response.send_message(
            "Bound the active BOTW to that message. Future joins/updates should edit that post automatically.",
            ephemeral=True,
        )

    @app_commands.command(
        name="botw_refresh_image",
        description="Refresh the boss image for the active BOTW from the OSRS Wiki.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_refresh_image(self, interaction: discord.Interaction):
        event = self.get_active_event()

        if event is None:
            await interaction.response.send_message(
                "There is no active BOTW event.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        boss_image_url = await get_boss_image_url(event["boss"])
        event["boss_image_url"] = boss_image_url

        self.save_active_event(event)
        await self.update_public_botw_message(event)

        if boss_image_url:
            await interaction.followup.send(
                f"Updated the BOTW boss image for **{event['boss']}**.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"I could not find a wiki thumbnail for **{event['boss']}**.",
                ephemeral=True,
            )

    @app_commands.command(
        name="botw_update",
        description="Force-update the active BOTW leaderboard from Wise Old Man.",
    )
    @app_commands.describe(
        public="Post the update result publicly. Defaults to private.",
    )
    async def botw_update(
        self,
        interaction: discord.Interaction,
        public: bool = False,
    ):
        await interaction.response.defer(ephemeral=not public)

        event, errors = await self.sync_active_event()

        if event is None:
            await interaction.followup.send("There is no active BOTW event.")
            return

        embed = self.build_botw_embed(event)

        real_errors = [error for error in errors if error != "No registered participants to update."]

        if real_errors:
            error_text = "\n".join(real_errors[:5])
            await interaction.followup.send(
                f"BOTW updated, but some players could not sync yet:\n```txt\n{error_text}\n```",
                embed=embed,
            )
        else:
            message = "BOTW leaderboard updated from Wise Old Man."
            if errors:
                message += f"\n{errors[0]}"

            await interaction.followup.send(message, embed=embed)

    @app_commands.command(
        name="botw_participants",
        description="Show registered BOTW participants.",
    )
    async def botw_participants(self, interaction: discord.Interaction):
        event = self.get_active_event()

        if event is None:
            await interaction.response.send_message(
                "There is no active BOTW event.",
                ephemeral=True,
            )
            return

        participants = event.get("participants", {})

        if not participants:
            await interaction.response.send_message(
                "No participants have joined BOTW yet.",
                ephemeral=True,
            )
            return

        lines = []

        for rsn, participant in participants.items():
            discord_user_id = participant.get("discord_user_id")
            starting_kc = participant.get("starting_kc", "?")
            current_kc = participant.get("current_kc", "?")
            last_synced = participant.get("last_synced")

            user_text = f"<@{discord_user_id}>" if discord_user_id else "Unknown Discord user"

            if participant.get("sync_pending"):
                sync_text = " — sync pending"
            else:
                sync_text = f" — synced <t:{last_synced}:R>" if last_synced else ""

            lines.append(
                f"**{rsn}** | {user_text} | `{starting_kc} → {current_kc}`{sync_text}"
            )

        embed = discord.Embed(
            title=f"👥 BOTW Participants - {event['boss']}",
            description="\n".join(lines[:25]),
            color=discord.Color.blurple(),
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="botw_add_kc",
        description="Manually add or update a player's KC gain for the active BOTW.",
    )
    @app_commands.describe(
        player_name="OSRS username.",
        gained_kc="KC gained during the event.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_add_kc(
        self,
        interaction: discord.Interaction,
        player_name: str,
        gained_kc: int,
    ):
        if gained_kc < 0:
            await interaction.response.send_message(
                "KC gained cannot be negative.",
                ephemeral=True,
            )
            return

        data = load_json(BOTW_FILE, {"events": []})

        active_event = None
        for event in data["events"]:
            if event.get("active"):
                active_event = event
                break

        if active_event is None:
            await interaction.response.send_message(
                "There is no active BOTW event.",
                ephemeral=True,
            )
            return

        active_event.setdefault("leaderboard", {})[player_name] = gained_kc

        save_json(BOTW_FILE, data)

        embed = self.build_botw_embed(active_event)
        await self.update_public_botw_message(active_event)

        await interaction.response.send_message(
            f"Manually updated **{player_name}** to **+{gained_kc} KC**.",
            embed=embed,
            ephemeral=True,
        )

    @app_commands.command(
        name="botw_leaderboard",
        description="Show the active BOTW leaderboard.",
    )
    @app_commands.describe(
        public="Post the leaderboard publicly. Defaults to private.",
    )
    async def botw_leaderboard(
        self,
        interaction: discord.Interaction,
        public: bool = False,
    ):
        active_event = self.get_active_event()

        if active_event is None:
            await interaction.response.send_message(
                "There is no active BOTW event.",
                ephemeral=True,
            )
            return

        embed = self.build_botw_embed(active_event)

        await interaction.response.send_message(
            embed=embed,
            ephemeral=not public,
        )

    @app_commands.command(
        name="botw_end",
        description="End the active BOTW event.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_end(self, interaction: discord.Interaction):
        data = load_json(BOTW_FILE, {"events": []})

        active_event = None
        for event in data["events"]:
            if event.get("active"):
                active_event = event
                break

        if active_event is None:
            await interaction.response.send_message(
                "There is no active BOTW event.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            await self.sync_active_event()
            data = load_json(BOTW_FILE, {"events": []})
            for event in data["events"]:
                if event.get("id") == active_event.get("id"):
                    active_event = event
                    break
        except Exception:
            pass

        active_event["active"] = False
        save_json(BOTW_FILE, data)
        await self.update_public_botw_message(active_event)

        leaderboard = active_event.get("leaderboard", {})

        if leaderboard:
            winner_name, winner_gain = max(
                leaderboard.items(),
                key=lambda item: item[1],
            )
            winner_text = f"👑 Winner: **{winner_name}** with **+{winner_gain} KC**"
        else:
            winner_text = "No KC was submitted."

        embed = self.build_botw_embed(active_event)

        await interaction.followup.send(
            content=f"🏆 BOTW ended! {winner_text}",
            embed=embed,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Botw(bot))