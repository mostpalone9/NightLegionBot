import asyncio
import io
import re
import time
from difflib import SequenceMatcher
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import BOTW_FILE, BOTW_NOTIFY_ROLE_ID, BOTW_TEST_CHANNEL_ID, PLAYER_PROFILES_FILE
from storage import load_json, save_json

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None


WISE_OLD_MAN_BASE_URL = "https://api.wiseoldman.net/v2"
OSRS_WIKI_API_URL = "https://oldschool.runescape.wiki/api.php"
OSRS_WIKI_USER_AGENT = "NightLegionBot/1.0 Discord bot for OSRS clan events"
OSRS_PRICES_MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
OSRS_PRICES_LATEST_URL = "https://prices.runescape.wiki/api/v1/osrs/latest"

EVENT_SCOPE_LIVE = "live"
EVENT_SCOPE_TEST = "test"


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


def event_scope_from_is_test(is_test: bool) -> str:
    return EVENT_SCOPE_TEST if is_test else EVENT_SCOPE_LIVE


def event_is_scope(event: dict, scope: str) -> bool:
    if "scope" in event:
        return event.get("scope") == scope
    return event_scope_from_is_test(bool(event.get("is_test", False))) == scope


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


def format_gp(value: int | None) -> str:
    if value is None:
        return "price unavailable"

    if value >= 1_000_000:
        text = f"{value / 1_000_000:.1f}m"
        return text.replace(".0m", "m")
    if value >= 1_000:
        text = f"{value / 1_000:.1f}k"
        return text.replace(".0k", "k")
    return f"{value:,} gp"


def clean_item_name(item_name: str | None) -> str:
    return (item_name or "").strip()


def prettify_item_name(item_name: str) -> str:
    """Display-only cleanup. Keep the real Wiki/API item name untouched for price lookups."""
    name = item_name.strip()
    name = re.sub(r"\s*\([^)]*\)", "", name).strip()
    return name[:1].upper() + name[1:] if name else name


def cash_stack_color(price: int | None) -> tuple[int, int, int, int]:
    # OSRS-style stack quantity colors: yellow for small, white for large, green for huge.
    if price is None:
        return (255, 255, 0, 255)
    if price >= 10_000_000:
        return (0, 255, 0, 255)
    if price >= 100_000:
        return (255, 255, 255, 255)
    return (255, 255, 0, 255)


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
                        "Wise Old Man updated this player recently. "
                        "Their KC will refresh on the next scheduled update."
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
    headers = {"User-Agent": OSRS_WIKI_USER_AGENT}

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


async def get_wiki_thumbnail_url(title: str, size: int = 96) -> str | None:
    params = {
        "action": "query",
        "format": "json",
        "prop": "pageimages",
        "piprop": "thumbnail",
        "pithumbsize": str(size),
        "redirects": "1",
        "titles": title,
    }
    headers = {"User-Agent": OSRS_WIKI_USER_AGENT}

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


async def fetch_json(url: str, params: dict | None = None) -> dict | list:
    headers = {"User-Agent": OSRS_WIKI_USER_AGENT}

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, params=params) as response:
            if response.status >= 400:
                raise RuntimeError(f"Request failed: {response.status} {await response.text()}")

            return await response.json()


def find_best_item_match(item_name: str, mapping: list[dict]) -> dict | None:
    wanted = item_name.strip().lower()

    exact = [item for item in mapping if item.get("name", "").lower() == wanted]
    if exact:
        exact.sort(key=lambda item: len(item.get("name", "")))
        return exact[0]

    best_item = None
    best_score = 0.0

    for item in mapping:
        name = item.get("name", "")
        score = SequenceMatcher(None, wanted, name.lower()).ratio()

        if wanted in name.lower():
            score += 0.25

        if score > best_score:
            best_score = score
            best_item = item

    return best_item if best_score >= 0.72 else None


async def enrich_prize_item(place: str, item_name: str | None) -> dict | None:
    cleaned_name = clean_item_name(item_name)
    if not cleaned_name:
        return None

    prize = {
        "place": place,
        "name": cleaned_name,
        "item_id": None,
        "price": None,
        "price_text": "price unavailable",
        "image_url": None,
    }

    try:
        mapping = await fetch_json(OSRS_PRICES_MAPPING_URL)
        item = find_best_item_match(cleaned_name, mapping)

        if item:
            item_id = int(item["id"])
            official_name = item.get("name", cleaned_name)

            latest = await fetch_json(OSRS_PRICES_LATEST_URL, params={"id": str(item_id)})
            latest_item = latest.get("data", {}).get(str(item_id), {})
            high = latest_item.get("high")
            low = latest_item.get("low")

            if high is not None and low is not None:
                price = round((int(high) + int(low)) / 2)
            elif high is not None:
                price = int(high)
            elif low is not None:
                price = int(low)
            else:
                price = None

            prize["name"] = official_name
            prize["item_id"] = item_id
            prize["price"] = price
            prize["price_text"] = format_gp(price)

        prize["image_url"] = await get_wiki_thumbnail_url(prize["name"], size=96)
    except Exception:
        pass

    return prize


async def enrich_prizes(first_prize: str, second_prize: str = "", third_prize: str = "") -> list[dict]:
    raw_prizes = [
        ("1st", first_prize),
        ("2nd", second_prize),
        ("3rd", third_prize),
    ]

    enriched = []
    for place, item_name in raw_prizes:
        prize = await enrich_prize_item(place, item_name)
        if prize:
            enriched.append(prize)

    return enriched


async def download_image_bytes(url: str) -> bytes | None:
    headers = {"User-Agent": OSRS_WIKI_USER_AGENT}

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url) as response:
            if response.status >= 400:
                return None

            return await response.read()


async def build_prize_card_file(prizes: list[dict], scope: str) -> discord.File | None:
    if Image is None or ImageDraw is None:
        return None

    # Minimal OSRS-style prize strip. Render huge so Discord scaling stays crisp on high-DPI/4K displays.
    width = 2400
    height = 620
    classic_yellow = (255, 255, 0, 255)
    transparent = (0, 0, 0, 0)

    image = Image.new("RGBA", (width, height), transparent)
    draw = ImageDraw.Draw(image)

    def load_runescape_font(size: int):
        # Put the RuneScape font file here:
        # C:\dev\NightLegionBot\assets\fonts\RuneScape.ttf
        candidates = [
            "assets/fonts/RuneScape.ttf",
            "assets/fonts/runescape.ttf",
            "assets/fonts/runescape_uf.ttf",
            "assets/fonts/RuneScape UF.ttf",
            "assets/fonts/OSRS.ttf",
            "assets/fonts/osrs.ttf",
            "fonts/RuneScape.ttf",
            "fonts/runescape.ttf",
            "RuneScape.ttf",
            "runescape.ttf",
            "runescape_uf.ttf",
            "RuneScape UF.ttf",
            "OSRS.ttf",
            "osrs.ttf",
            "C:/Windows/Fonts/RuneScape.ttf",
            "C:/Windows/Fonts/runescape.ttf",
            "C:/Windows/Fonts/runescape_uf.ttf",
            "C:/Windows/Fonts/RuneScape UF.ttf",
        ]
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue

        # Fallback only if the RuneScape font file is not present locally.
        fallback_candidates = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for candidate in fallback_candidates:
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
        return ImageFont.load_default()

    name_font = load_runescape_font(58)
    price_font = load_runescape_font(54)

    def centered_text(x_center: int, y: int, value: str, fill, font):
        bbox = draw.textbbox((0, 0), value, font=font)
        text_width = bbox[2] - bbox[0]
        draw.text((x_center - text_width / 2, y), value, fill=fill, font=font)

    def draw_text_with_shadow(position: tuple[int, int], value: str, fill, font):
        x, y = position
        shadow = (0, 0, 0, 255)
        draw.text((x + 3, y + 3), value, fill=shadow, font=font)
        draw.text((x, y), value, fill=fill, font=font)

    def centered_text_with_shadow(x_center: int, y: int, value: str, fill, font):
        bbox = draw.textbbox((0, 0), value, font=font)
        text_width = bbox[2] - bbox[0]
        draw_text_with_shadow((int(x_center - text_width / 2), y), value, fill, font)

    async def paste_wiki_sprite(title: str, x_center: int, y_center: int, max_size: int) -> None:
        try:
            image_url = await get_wiki_thumbnail_url(title, size=max_size)
            if not image_url:
                return
            image_bytes = await download_image_bytes(image_url)
            if not image_bytes:
                return
            sprite = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

            # OSRS sprites are tiny pixel art. Scale with nearest-neighbor so they stay crisp, not smeared.
            scale = min(max_size / sprite.width, max_size / sprite.height)
            new_size = (
                max(1, int(sprite.width * scale)),
                max(1, int(sprite.height * scale)),
            )
            sprite = sprite.resize(new_size, Image.Resampling.NEAREST)
            image.paste(sprite, (int(x_center - sprite.width / 2), int(y_center - sprite.height / 2)), sprite)
        except Exception:
            return

    bar_titles = {
        "1st": "Gold bar",
        "2nd": "Silver bar",
        "3rd": "Bronze bar",
    }

    columns = [400, 1200, 2000]

    for index, prize in enumerate(prizes[:3]):
        x_center = columns[index]
        place = prize.get("place", "")

        # Gold/silver/bronze bars replace medals in the generated image.
        await paste_wiki_sprite(bar_titles.get(place, "Gold bar"), x_center, 78, 132)

        if prize.get("image_url"):
            try:
                image_bytes = await download_image_bytes(prize["image_url"])
                if image_bytes:
                    icon = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
                    # Large item render for 4K monitors. Still nearest-neighbor for OSRS-native pixel sharpness.
                    scale = min(270 / icon.width, 270 / icon.height)
                    new_size = (
                        max(1, int(icon.width * scale)),
                        max(1, int(icon.height * scale)),
                    )
                    icon = icon.resize(new_size, Image.Resampling.NEAREST)
                    image.paste(icon, (int(x_center - icon.width / 2), int(245 - icon.height / 2)), icon)
            except Exception:
                pass

        # Display-only cleanup: API lookups still use the exact item name, but the graphic strips suffixes like (u), (unf), etc.
        display_name = prettify_item_name(prize["name"])
        if len(display_name) > 24:
            display_name = display_name[:21] + "..."

        centered_text_with_shadow(x_center, 390, display_name, classic_yellow, name_font)

        price = prize.get("price")
        price_text = prize.get("price_text", "price unavailable")
        price_color = cash_stack_color(price)
        price_label = f"{price_text} GP" if price is not None else price_text

        # Classic cash stack sprite next to OSRS-colored GP value.
        cash_stack_url = await get_wiki_thumbnail_url("Coins", size=96)

        if cash_stack_url:
            try:
                image_bytes = await download_image_bytes(cash_stack_url)
                if image_bytes:
                    coins = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
                    scale = min(72 / coins.width, 72 / coins.height)
                    new_size = (
                        max(1, int(coins.width * scale)),
                        max(1, int(coins.height * scale)),
                    )
                    coins = coins.resize(new_size, Image.Resampling.NEAREST)

                    text_bbox = draw.textbbox((0, 0), price_label, font=price_font)
                    text_width = text_bbox[2] - text_bbox[0]
                    total_width = coins.width + 18 + text_width
                    start_x = int(x_center - total_width / 2)
                    image.paste(coins, (start_x, 493), coins)
                    draw_text_with_shadow((start_x + coins.width + 18, 486), price_label, price_color, price_font)
                else:
                    centered_text_with_shadow(x_center, 486, price_label, price_color, price_font)
            except Exception:
                centered_text_with_shadow(x_center, 486, price_label, price_color, price_font)
        else:
            centered_text_with_shadow(x_center, 486, price_label, price_color, price_font)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    return discord.File(buffer, filename="botw_prizes.png")

def build_prize_text(event: dict) -> str:
    prizes = event.get("prizes", [])

    if prizes:
        lines = []
        for prize in prizes:
            medal = "🥇" if prize["place"] == "1st" else "🥈" if prize["place"] == "2nd" else "🥉"
            display_name = prettify_item_name(prize["name"])
            price = prize.get("price_text", "price unavailable")
            lines.append(f"{medal} **{display_name}**\n> 💰 **{price} GP**")
        return "\n".join(lines)

    old_reward = event.get("reward")
    if old_reward:
        return old_reward

    return "Bragging rights"

class BotwNotifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Notify Me",
        emoji="🔔",
        style=discord.ButtonStyle.success,
        custom_id="nightlegion_botw_notify",
    )
    async def notify_me(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            await interaction.response.send_message("This only works inside the server.", ephemeral=True)
            return

        if BOTW_NOTIFY_ROLE_ID == 0:
            await interaction.response.send_message("BOTW notify role has not been configured yet.", ephemeral=True)
            return

        role = interaction.guild.get_role(BOTW_NOTIFY_ROLE_ID)
        if role is None:
            await interaction.response.send_message("I could not find the configured BOTW notify role.", ephemeral=True)
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Could not read your server member profile.", ephemeral=True)
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
    async def enter_botw(self, interaction: discord.Interaction, button: discord.ui.Button):
        event = self.cog.get_event_for_interaction(interaction)

        if event is None:
            await interaction.response.send_message("There is no active BOTW event for this post.", ephemeral=True)
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
                        "Use `/botw_set_rsn` if your RSN changed.\n\n"
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
        event = self.cog.get_event_for_interaction(interaction)

        if event is None:
            await interaction.response.send_message("There is no active BOTW event for this post.", ephemeral=True)
            return

        entered_rsn = str(self.rsn.value).strip()
        if not entered_rsn:
            await interaction.response.send_message("Please enter a valid RSN.", ephemeral=True)
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

    async def send_ephemeral_notice(self, interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def enforce_scope_channel_rules(self, interaction: discord.Interaction, scope: str) -> bool:
        if BOTW_TEST_CHANNEL_ID == 0:
            return True

        if scope == EVENT_SCOPE_TEST and interaction.channel_id != BOTW_TEST_CHANNEL_ID:
            await self.send_ephemeral_notice(
                interaction,
                "Test BOTW commands can only be used in the bot testing channel.",
            )
            return False

        if scope == EVENT_SCOPE_LIVE and interaction.channel_id == BOTW_TEST_CHANNEL_ID:
            await self.send_ephemeral_notice(
                interaction,
                "Live BOTW commands are blocked inside the bot testing channel. Use `is_test: True` there.",
            )
            return False

        return True

    def get_active_event(self, scope: str = EVENT_SCOPE_LIVE) -> dict | None:
        data = load_json(BOTW_FILE, {"events": []})

        for event in data["events"]:
            if event.get("active") and event_is_scope(event, scope):
                return event

        return None

    def get_event_for_interaction(self, interaction: discord.Interaction) -> dict | None:
        data = load_json(BOTW_FILE, {"events": []})
        message_id = interaction.message.id if interaction.message else None
        channel_id = interaction.channel_id

        for event in data["events"]:
            if (
                event.get("active")
                and event.get("message_id") == message_id
                and event.get("channel_id") == channel_id
            ):
                return event

        if BOTW_TEST_CHANNEL_ID and channel_id == BOTW_TEST_CHANNEL_ID:
            return self.get_active_event(EVENT_SCOPE_TEST)

        return self.get_active_event(EVENT_SCOPE_LIVE)

    def save_event(self, updated_event: dict) -> None:
        data = load_json(BOTW_FILE, {"events": []})

        for index, event in enumerate(data["events"]):
            if event.get("id") == updated_event.get("id"):
                data["events"][index] = updated_event
                save_json(BOTW_FILE, data)
                return

        data["events"].append(updated_event)
        save_json(BOTW_FILE, data)

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
            embed = self.build_botw_embed(event)
            view = BotwJoinView(self) if event.get("active") else None
            file = await build_prize_card_file(event.get("prizes", []), event.get("scope", EVENT_SCOPE_LIVE))

            if file:
                embed.set_image(url="attachment://botw_prizes.png")
                await message.edit(embed=embed, attachments=[file], view=view)
            else:
                await message.edit(embed=embed, view=view)
        except discord.HTTPException:
            return

    def build_botw_embed(self, event: dict) -> discord.Embed:
        boss = event["boss"]
        start_time = event["start_time"]
        end_time = event["end_time"]
        leaderboard = event.get("leaderboard", {})
        participants = event.get("participants", {})
        scope = event.get("scope", EVENT_SCOPE_LIVE)

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

                medal = "🥇" if index == 1 else "🥈" if index == 2 else "🥉" if index == 3 else f"`#{index}`"
                gain_text = f"+{gain:,} KC"
                lines.append(f"{medal} **{rsn}**{mention} — `{gain_text}`{kc_text}")
        else:
            lines.append("No entries yet.\n\nClick **Enter BOTW** below to join.")

        status = "Active" if event.get("active") else "Completed"
        if scope == EVENT_SCOPE_TEST:
            status = f"{status} Test"

        embed = discord.Embed(
            title=f"{'🧪 TEST — ' if scope == EVENT_SCOPE_TEST else ''}Boss of the Week: {boss}",
            description=(
                "Rack up as much boss KC as possible before the event ends.\n\n"
                "Click **Enter BOTW** below to join. Your gains are tracked through Wise Old Man."
            ),
            color=discord.Color.purple() if scope == EVENT_SCOPE_TEST else discord.Color.gold()
            if event.get("active") else discord.Color.dark_grey(),
        )

        boss_image_url = event.get("boss_image_url")
        if boss_image_url:
            embed.set_thumbnail(url=boss_image_url)

        embed.add_field(name="Status", value=f"`{status}`", inline=True)
        embed.add_field(name="👥 Competitors", value=f"`{len(participants)}`", inline=True)
        embed.add_field(name="Started", value=f"<t:{start_time}:f>", inline=True)
        embed.add_field(name="Ends", value=f"<t:{end_time}:f>", inline=True)

        last_updated = event.get("last_updated")
        embed.add_field(
            name="Last Updated",
            value=f"<t:{last_updated}:R>" if last_updated else "Not yet",
            inline=True,
        )

        embed.add_field(name="🏆 Prize Pool", value=build_prize_text(event), inline=False)
        embed.add_field(name="📈 Leaderboard", value="\n".join(lines), inline=False)

        embed.set_footer(text="NightLegion BOTW • /botw_set_rsn to update your RSN")
        return embed

    def register_participant_without_sync(self, event: dict, interaction: discord.Interaction, rsn: str) -> None:
        participants = event.setdefault("participants", {})
        participant = participants.setdefault(rsn, {})
        participant["discord_user_id"] = interaction.user.id
        participant["discord_display_name"] = interaction.user.display_name
        participant["registered_at"] = int(time.time())
        participant["sync_pending"] = True

        event.setdefault("leaderboard", {}).setdefault(rsn, 0)
        self.save_event(event)

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

        self.save_event(event)
        await self.update_public_botw_message(event)

        return starting_kc, current_kc, gained_kc

    async def sync_active_event(self, scope: str = EVENT_SCOPE_LIVE) -> tuple[dict | None, list[str]]:
        event = self.get_active_event(scope)

        if event is None:
            return None, [f"There is no active {scope} BOTW event."]

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
        self.save_event(event)
        await self.update_public_botw_message(event)

        return event, errors

    @tasks.loop(hours=1)
    async def botw_auto_update_loop(self):
        await self.bot.wait_until_ready()

        for scope in (EVENT_SCOPE_LIVE, EVENT_SCOPE_TEST):
            event = self.get_active_event(scope)

            if event is None:
                continue

            if int(time.time()) >= event["end_time"]:
                continue

            await self.sync_active_event(scope)

    @app_commands.command(
        name="botw_notify_panel",
        description="Post the BOTW notification role button.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_notify_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔔 BOTW Notifications",
            description="Click **Notify Me** to receive BOTW announcements. Click it again to remove the role.",
            color=discord.Color.green(),
        )

        await interaction.response.send_message(embed=embed, view=BotwNotifyView())

    @app_commands.command(
        name="botw_start",
        description="Start a Boss of the Week event.",
    )
    @app_commands.describe(
        boss="Boss name, example: Phantom Muspah.",
        duration_days="How many days the event lasts.",
        first_prize="1st place prize, example: Venator bow.",
        second_prize="2nd place prize, example: Pegasian boots.",
        third_prize="3rd place prize, example: Webweaver bow.",
        is_test="True = test event in bot testing channel. False = real live event. Defaults to True.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_start(
        self,
        interaction: discord.Interaction,
        boss: str,
        duration_days: int = 7,
        first_prize: str = "Bragging rights",
        second_prize: str = "",
        third_prize: str = "",
        is_test: bool = True,
    ):
        await interaction.response.defer()

        scope = event_scope_from_is_test(is_test)

        if not await self.enforce_scope_channel_rules(interaction, scope):
            return

        if duration_days < 1:
            await interaction.followup.send("Duration must be at least 1 day.", ephemeral=True)
            return

        data = load_json(BOTW_FILE, {"events": []})

        for event in data["events"]:
            if event.get("active") and event_is_scope(event, scope):
                event["active"] = False

        start_time = int(time.time())
        end_time = start_time + duration_days * 24 * 60 * 60
        final_boss_metric = boss_name_to_metric(boss)
        boss_image_url = await get_boss_image_url(boss)
        prizes = await enrich_prizes(first_prize, second_prize, third_prize)

        event = {
            "id": f"{scope}-{start_time}",
            "scope": scope,
            "is_test": is_test,
            "boss": boss,
            "boss_metric": final_boss_metric,
            "boss_image_url": boss_image_url,
            "reward": first_prize,
            "prizes": prizes,
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
        file = await build_prize_card_file(prizes, scope)

        if file:
            embed.set_image(url="attachment://botw_prizes.png")

        content = None
        allowed_mentions = discord.AllowedMentions.none()

        if scope == EVENT_SCOPE_LIVE and BOTW_NOTIFY_ROLE_ID:
            content = f"<@&{BOTW_NOTIFY_ROLE_ID}> New Boss of the Week is live!"
            allowed_mentions = discord.AllowedMentions(roles=True)
        elif scope == EVENT_SCOPE_TEST:
            content = "🧪 Test BOTW event created."

        send_kwargs = {
            "content": content,
            "embed": embed,
            "view": BotwJoinView(self),
            "allowed_mentions": allowed_mentions,
            "wait": True,
        }

        if file:
            send_kwargs["file"] = file

        message = await interaction.followup.send(**send_kwargs)

        event["channel_id"] = interaction.channel_id
        event["message_id"] = message.id
        self.save_event(event)

    @app_commands.command(
        name="botw_set_rsn",
        description="Save or update your OSRS username for BOTW.",
    )
    @app_commands.describe(rsn="Your OSRS username.")
    async def botw_set_rsn(self, interaction: discord.Interaction, rsn: str):
        cleaned_rsn = rsn.strip()

        if not cleaned_rsn:
            await interaction.response.send_message("Please enter a valid RSN.", ephemeral=True)
            return

        save_rsn(interaction.user.id, interaction.user.display_name, cleaned_rsn)
        await interaction.response.send_message(f"Saved your BOTW RSN as **{cleaned_rsn}**.", ephemeral=True)

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

        await interaction.response.send_message(f"Your saved BOTW RSN is **{saved_rsn}**.", ephemeral=True)

    @app_commands.command(
        name="botw_set_player_rsn",
        description="Mod tool: save or update another member's BOTW RSN.",
    )
    @app_commands.describe(
        member="The Discord member whose RSN should be saved.",
        rsn="That member's OSRS username.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_set_player_rsn(self, interaction: discord.Interaction, member: discord.Member, rsn: str):
        cleaned_rsn = rsn.strip()

        if not cleaned_rsn:
            await interaction.response.send_message("Please enter a valid RSN.", ephemeral=True)
            return

        save_rsn(member.id, member.display_name, cleaned_rsn)
        await interaction.response.send_message(
            f"Saved **{member.display_name}**'s BOTW RSN as **{cleaned_rsn}**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="botw_lookup_player",
        description="Mod tool: look up a member's saved BOTW RSN.",
    )
    @app_commands.describe(member="The Discord member to look up.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_lookup_player(self, interaction: discord.Interaction, member: discord.Member):
        saved_rsn = get_saved_rsn(member.id)

        if not saved_rsn:
            await interaction.response.send_message(
                f"**{member.display_name}** does not have a saved BOTW RSN yet.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"**{member.display_name}**'s saved BOTW RSN is **{saved_rsn}**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="botw_remove_player",
        description="Mod tool: remove a player from the active BOTW event without deleting their saved RSN.",
    )
    @app_commands.describe(
        player_name="The player's OSRS username as shown on the BOTW leaderboard.",
        is_test="True = test BOTW. False = live BOTW. Defaults to True.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_remove_player(self, interaction: discord.Interaction, player_name: str, is_test: bool = True):
        scope = event_scope_from_is_test(is_test)

        if not await self.enforce_scope_channel_rules(interaction, scope):
            return

        event = self.get_active_event(scope)
        if event is None:
            await interaction.response.send_message(f"There is no active {scope} BOTW event.", ephemeral=True)
            return

        participants = event.setdefault("participants", {})
        leaderboard = event.setdefault("leaderboard", {})

        matched_rsn = None
        for rsn in list(set(participants.keys()) | set(leaderboard.keys())):
            if rsn.lower() == player_name.strip().lower():
                matched_rsn = rsn
                break

        if matched_rsn is None:
            await interaction.response.send_message(
                f"I could not find **{player_name}** in the active {scope} BOTW event.",
                ephemeral=True,
            )
            return

        participants.pop(matched_rsn, None)
        leaderboard.pop(matched_rsn, None)
        self.save_event(event)
        await self.update_public_botw_message(event)

        await interaction.response.send_message(
            f"Removed **{matched_rsn}** from the active {scope} BOTW event. Their saved RSN was not deleted.",
            ephemeral=True,
        )

    @app_commands.command(
        name="botw_force_sync",
        description="Mod tool: force-sync one player in the active BOTW event from Wise Old Man.",
    )
    @app_commands.describe(
        player_name="The player's OSRS username as shown on the BOTW leaderboard.",
        is_test="True = test BOTW. False = live BOTW. Defaults to True.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_force_sync(self, interaction: discord.Interaction, player_name: str, is_test: bool = True):
        scope = event_scope_from_is_test(is_test)

        if not await self.enforce_scope_channel_rules(interaction, scope):
            return

        event = self.get_active_event(scope)
        if event is None:
            await interaction.response.send_message(f"There is no active {scope} BOTW event.", ephemeral=True)
            return

        matched_rsn = None
        for rsn in event.get("participants", {}).keys():
            if rsn.lower() == player_name.strip().lower():
                matched_rsn = rsn
                break

        if matched_rsn is None:
            await interaction.response.send_message(
                f"I could not find **{player_name}** in the active {scope} BOTW participant list.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            starting_kc, current_kc, gained_kc = await self.sync_participant(event, matched_rsn)
        except WiseOldManRateLimitError as error:
            await interaction.followup.send(f"Wise Old Man rate-limited **{matched_rsn}**: {error}", ephemeral=True)
            return
        except Exception as error:
            await interaction.followup.send(f"Could not sync **{matched_rsn}**. Error: `{error}`", ephemeral=True)
            return

        event["last_updated"] = int(time.time())
        self.save_event(event)
        await self.update_public_botw_message(event)

        await interaction.followup.send(
            (
                f"Synced **{matched_rsn}**.\n"
                f"Starting KC: **{starting_kc}**\n"
                f"Current KC: **{current_kc}**\n"
                f"Gained KC: **+{gained_kc}**"
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="botw_join",
        description="Join the active BOTW with your saved or provided OSRS username.",
    )
    @app_commands.describe(
        rsn="Optional. Leave blank to use your saved RSN.",
        is_test="True = join test BOTW. False = join live BOTW. Defaults to True.",
    )
    async def botw_join(self, interaction: discord.Interaction, rsn: str = "", is_test: bool = True):
        scope = event_scope_from_is_test(is_test)

        if not await self.enforce_scope_channel_rules(interaction, scope):
            return

        event = self.get_active_event(scope)
        if event is None:
            await interaction.response.send_message(f"There is no active {scope} BOTW event.", ephemeral=True)
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
        is_test="True = bind test BOTW. False = bind live BOTW. Defaults to True.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_bind_message(self, interaction: discord.Interaction, message_id: str, is_test: bool = True):
        scope = event_scope_from_is_test(is_test)

        if not await self.enforce_scope_channel_rules(interaction, scope):
            return

        event = self.get_active_event(scope)
        if event is None:
            await interaction.response.send_message(f"There is no active {scope} BOTW event to bind.", ephemeral=True)
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
        self.save_event(event)

        try:
            await self.update_public_botw_message(event)
        except Exception:
            pass

        await interaction.response.send_message(
            f"Bound the active {scope} BOTW to that message. Future joins/updates should edit that post automatically.",
            ephemeral=True,
        )

    @app_commands.command(
        name="botw_refresh_image",
        description="Refresh the boss/prize images for the active BOTW from the OSRS Wiki.",
    )
    @app_commands.describe(is_test="True = refresh test BOTW. False = refresh live BOTW. Defaults to True.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_refresh_image(self, interaction: discord.Interaction, is_test: bool = True):
        scope = event_scope_from_is_test(is_test)

        if not await self.enforce_scope_channel_rules(interaction, scope):
            return

        event = self.get_active_event(scope)
        if event is None:
            await interaction.response.send_message(f"There is no active {scope} BOTW event.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        boss_image_url = await get_boss_image_url(event["boss"])
        event["boss_image_url"] = boss_image_url

        old_prizes = event.get("prizes", [])
        if old_prizes:
            event["prizes"] = await enrich_prizes(
                old_prizes[0]["name"] if len(old_prizes) > 0 else "",
                old_prizes[1]["name"] if len(old_prizes) > 1 else "",
                old_prizes[2]["name"] if len(old_prizes) > 2 else "",
            )

        self.save_event(event)
        await self.update_public_botw_message(event)

        await interaction.followup.send(f"Refreshed images and prices for the active {scope} BOTW.", ephemeral=True)

    @app_commands.command(
        name="botw_update",
        description="Force-update the active BOTW leaderboard from Wise Old Man.",
    )
    @app_commands.describe(
        public="Post the update result publicly. Defaults to private.",
        is_test="True = update test BOTW. False = update live BOTW. Defaults to True.",
    )
    async def botw_update(self, interaction: discord.Interaction, public: bool = False, is_test: bool = True):
        scope = event_scope_from_is_test(is_test)

        if not await self.enforce_scope_channel_rules(interaction, scope):
            return

        await interaction.response.defer(ephemeral=not public)
        event, errors = await self.sync_active_event(scope)

        if event is None:
            await interaction.followup.send(f"There is no active {scope} BOTW event.")
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
            message = f"{scope.title()} BOTW leaderboard updated from Wise Old Man."
            if errors:
                message += f"\n{errors[0]}"
            await interaction.followup.send(message, embed=embed)

    @app_commands.command(
        name="botw_participants",
        description="Show registered BOTW participants.",
    )
    @app_commands.describe(is_test="True = test BOTW. False = live BOTW. Defaults to True.")
    async def botw_participants(self, interaction: discord.Interaction, is_test: bool = True):
        scope = event_scope_from_is_test(is_test)

        if not await self.enforce_scope_channel_rules(interaction, scope):
            return

        event = self.get_active_event(scope)
        if event is None:
            await interaction.response.send_message(f"There is no active {scope} BOTW event.", ephemeral=True)
            return

        participants = event.get("participants", {})
        if not participants:
            await interaction.response.send_message("No participants have joined BOTW yet.", ephemeral=True)
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

            lines.append(f"**{rsn}** | {user_text} | `{starting_kc} → {current_kc}`{sync_text}")

        embed = discord.Embed(
            title=f"{'🧪 TEST — ' if scope == EVENT_SCOPE_TEST else ''}BOTW Participants - {event['boss']}",
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
        is_test="True = test BOTW. False = live BOTW. Defaults to True.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_add_kc(
        self,
        interaction: discord.Interaction,
        player_name: str,
        gained_kc: int,
        is_test: bool = True,
    ):
        scope = event_scope_from_is_test(is_test)

        if not await self.enforce_scope_channel_rules(interaction, scope):
            return

        if gained_kc < 0:
            await interaction.response.send_message("KC gained cannot be negative.", ephemeral=True)
            return

        active_event = self.get_active_event(scope)
        if active_event is None:
            await interaction.response.send_message(f"There is no active {scope} BOTW event.", ephemeral=True)
            return

        active_event.setdefault("leaderboard", {})[player_name] = gained_kc
        self.save_event(active_event)
        await self.update_public_botw_message(active_event)

        embed = self.build_botw_embed(active_event)
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
        is_test="True = test BOTW. False = live BOTW. Defaults to True.",
    )
    async def botw_leaderboard(self, interaction: discord.Interaction, public: bool = False, is_test: bool = True):
        scope = event_scope_from_is_test(is_test)

        if not await self.enforce_scope_channel_rules(interaction, scope):
            return

        active_event = self.get_active_event(scope)
        if active_event is None:
            await interaction.response.send_message(f"There is no active {scope} BOTW event.", ephemeral=True)
            return

        embed = self.build_botw_embed(active_event)
        await interaction.response.send_message(embed=embed, ephemeral=not public)

    @app_commands.command(
        name="botw_end",
        description="End the active BOTW event.",
    )
    @app_commands.describe(is_test="True = end test BOTW. False = end live BOTW. Defaults to True.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def botw_end(self, interaction: discord.Interaction, is_test: bool = True):
        scope = event_scope_from_is_test(is_test)

        if not await self.enforce_scope_channel_rules(interaction, scope):
            return

        data = load_json(BOTW_FILE, {"events": []})
        active_event = None

        for event in data["events"]:
            if event.get("active") and event_is_scope(event, scope):
                active_event = event
                break

        if active_event is None:
            await interaction.response.send_message(f"There is no active {scope} BOTW event.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            await self.sync_active_event(scope)
            data = load_json(BOTW_FILE, {"events": []})
            for event in data["events"]:
                if event.get("id") == active_event.get("id"):
                    active_event = event
                    break
        except Exception:
            pass

        active_event["active"] = False

        for index, event in enumerate(data["events"]):
            if event.get("id") == active_event.get("id"):
                data["events"][index] = active_event
                break

        save_json(BOTW_FILE, data)
        await self.update_public_botw_message(active_event)

        leaderboard = active_event.get("leaderboard", {})
        sorted_players = sorted(leaderboard.items(), key=lambda item: item[1], reverse=True)

        if sorted_players:
            winner_lines = []
            medals = ["🥇", "🥈", "🥉"]
            for index, (player_name, gain) in enumerate(sorted_players[:3]):
                winner_lines.append(f"{medals[index]} **{player_name}** with **+{gain} KC**")
            winner_text = "\n".join(winner_lines)
        else:
            winner_text = "No KC was submitted."

        embed = self.build_botw_embed(active_event)
        await interaction.followup.send(
            content=f"{'🧪 Test ' if scope == EVENT_SCOPE_TEST else ''}BOTW ended!\n{winner_text}",
            embed=embed,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Botw(bot))
