import discord
from discord.ext import commands
from discord import app_commands
import requests
import os
import json
import dotenv
import asyncio

from keep_alive import keep_alive  # Import the keep_alive function to run the bot on Render.com

# Load environment variables from .env if present (for local development)
dotenv.load_dotenv()

# Load tokens from environment variables (set in .env or Render.com dashboard)
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')  # Discord bot token from environment
FACEIT_API_KEY = os.getenv('FACEIT_API_KEY')  # FACEIT API key from environment

class FaceitBot(commands.Bot):
    async def setup_hook(self):
        # Sync commands globally instead of just to a guild
        await self.tree.sync()
        print("Slash commands synced globally. It may take up to 1 hour to appear in Discord UI.")

# Set up Discord bot with required intents
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent for command processing
bot = FaceitBot(command_prefix=commands.when_mentioned_or('/'), intents=intents)
tree = bot.tree  # Use the built-in tree attribute

# Path to the file storing Discord user to FACEIT username links
LINKS_FILE = os.path.join(os.path.dirname(__file__), 'faceit_links.json')

def load_links():
    """Load Discord user to FACEIT username links from file."""
    try:
        with open(LINKS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_links(links):
    """Save Discord user to FACEIT username links to file."""
    with open(LINKS_FILE, 'w') as f:
        json.dump(links, f)

# Default sync interval in minutes
SYNC_INTERVAL_MINUTES = 360
sync_task = None

async def faceit_sync_task():
    await bot.wait_until_ready()
    global SYNC_INTERVAL_MINUTES
    while not bot.is_closed():
        print(f"[FACEIT SYNC] Running periodic FACEIT level sync for all linked users (every {SYNC_INTERVAL_MINUTES} min)... (Next: {SYNC_INTERVAL_MINUTES} min)")
        guilds = bot.guilds
        links = load_links()
        headers = {"Authorization": f"Bearer {FACEIT_API_KEY}"}
        for guild in guilds:
            print(f"[FACEIT SYNC] Checking guild: {guild.name} (ID: {guild.id})")
            for user_id, username in links.items():
                member = guild.get_member(int(user_id))
                if not member:
                    print(f"[FACEIT SYNC] User ID {user_id} not found in guild {guild.name}")
                    continue
                print(f"[FACEIT SYNC] Checking {member.display_name} (Discord ID: {user_id}) for FACEIT username: {username}")
                user_url = f"https://open.faceit.com/data/v4/players?nickname={username}"
                user_resp = requests.get(user_url, headers=headers)
                if user_resp.status_code != 200:
                    print(f"[FACEIT SYNC] Could not fetch FACEIT user: {username} (HTTP {user_resp.status_code})")
                    continue
                user_data = user_resp.json()
                faceit_level = None
                try:
                    faceit_level = user_data['games']['cs2']['skill_level']
                except (KeyError, TypeError):
                    print(f"[FACEIT SYNC] Could not determine FACEIT level for {username}")
                    continue
                if not faceit_level:
                    print(f"[FACEIT SYNC] No FACEIT level found for {username}")
                    continue
                role_name = f"FACEIT Level {faceit_level}"
                role = discord.utils.get(guild.roles, name=role_name)
                if not role:
                    print(f"[FACEIT SYNC] Creating role: {role_name} in guild {guild.name}")
                    role = await guild.create_role(name=role_name, colour=discord.Colour.green())
                # Remove old FACEIT Level roles from the member
                for r in member.roles:
                    if r.name.startswith("FACEIT Level ") and r != role:
                        print(f"[FACEIT SYNC] Removing old role {r.name} from {member.display_name}")
                        await member.remove_roles(r)
                if role not in member.roles:
                    print(f"[FACEIT SYNC] Adding role {role_name} to {member.display_name}")
                    await member.add_roles(role)
                else:
                    print(f"[FACEIT SYNC] {member.display_name} already has role {role_name}")
        print(f"[FACEIT SYNC] Sync cycle complete. Next sync in {SYNC_INTERVAL_MINUTES} minutes.\n")
        await asyncio.sleep(SYNC_INTERVAL_MINUTES * 60)

# Slash command: /faceitsearch
@tree.command(name="faceitsearch", description="Search FACEIT stats for a given username and display them in an embed.")
@app_commands.describe(username="FACEIT username to search for")
async def faceitsearch(interaction: discord.Interaction, username: str):
    """Search FACEIT stats for a given username and display them in an embed."""
    # Validação básica do nickname
    if not username or " " in username:
        await interaction.response.send_message(
            "Nickname inválido. Certifique-se de digitar exatamente como aparece na FACEIT, sem espaços.",
            ephemeral=True
        )
        return
    headers = {"Authorization": f"Bearer {FACEIT_API_KEY}"}
    user_url = f"https://open.faceit.com/data/v4/players?nickname={username}"
    user_resp = requests.get(user_url, headers=headers)
    if user_resp.status_code != 200:
        try:
            api_error = user_resp.json().get('message', 'No error message from FACEIT API.')
        except Exception:
            api_error = 'No error message from FACEIT API.'
        # Mensagem especial para erro 400
        if user_resp.status_code == 400:
            error_msg = (
                f"Não foi possível encontrar o usuário FACEIT: {username}\n"
                f"HTTP Status: 400 (Bad Request)\n"
                f"FACEIT API message: {api_error}\n"
                f"Possíveis causas: nickname incorreto, caracteres inválidos, ou usuário não existe.\n"
                f"Dica: Verifique o nickname exato no site da FACEIT."
            )
        else:
            error_msg = (
                f"Could not find FACEIT user: {username}\n"
                f"HTTP Status: {user_resp.status_code}\n"
                f"FACEIT API message: {api_error}\n"
                f"Possible causes: misspelled username, user does not exist, or FACEIT API is down."
            )
        await interaction.response.send_message(error_msg, ephemeral=True)
        print(f"[FACEIT SEARCH ERROR] {error_msg}")
        return
    user_data = user_resp.json()
    player_id = user_data.get('player_id')
    elo = 'N/A'
    try:
        elo = user_data['games']['cs2']['faceit_elo']
    except (KeyError, TypeError):
        pass
    avatar_url = user_data.get('avatar', None)
    faceit_level = None
    try:
        faceit_level = user_data['games']['cs2']['skill_level']
    except (KeyError, TypeError):
        pass
    level_img_url = None
    if faceit_level:
        level_img_url = f"https://cdn.faceit.com/images/levels/csgo/level_{faceit_level}_svg.svg"
    stats_url = f"https://open.faceit.com/data/v4/players/{player_id}/stats/cs2"
    stats_resp = requests.get(stats_url, headers=headers)
    if stats_resp.status_code != 200:
        await interaction.response.send_message(f"Could not fetch stats for: {username}", ephemeral=True)
        return
    stats = stats_resp.json()
    lifetime = stats.get('lifetime', {})
    matches = lifetime.get('Matches', 'N/A')
    winrate = lifetime.get('Win Rate %', 'N/A')
    kd = lifetime.get('Average K/D Ratio', 'N/A')
    embed = discord.Embed(title=f"FACEIT Stats for {username}", color=0x00ff00)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    if level_img_url:
        embed.set_image(url=level_img_url)
    embed.add_field(name="ELO", value=elo, inline=True)
    embed.add_field(name="Matches", value=matches, inline=True)
    embed.add_field(name="Win Rate %", value=winrate, inline=True)
    embed.add_field(name="K/D Ratio", value=kd, inline=True)
    await interaction.response.send_message(embed=embed)

# Slash command: /linkfaceit
@tree.command(name="linkfaceit", description="Link a Discord account to a FACEIT username.")
@app_commands.describe(discord_user="The Discord user to link (mention or ID)", username="FACEIT username to link")
async def linkfaceit(interaction: discord.Interaction, discord_user: discord.Member, username: str):
    """Link a Discord account to a FACEIT username. Only server admins can link other users."""
    # Only allow linking other users if the invoker has manage_guild permission
    if interaction.user != discord_user and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You do not have permission to link other users. Only server admins can do this.", ephemeral=True)
        return
    links = load_links()
    links[str(discord_user.id)] = username
    save_links(links)
    await interaction.response.send_message(f"Linked {discord_user.mention} to FACEIT username: {username}", ephemeral=True)

# Slash command: /faceitupdate
@tree.command(name="faceitupdate", description="Update your Discord role based on your FACEIT level.")
async def faceitupdate(interaction: discord.Interaction, user: discord.Member = None):
    """Update a Discord user's role based on their FACEIT level. Admins can update others; users can update themselves."""
    # If no user is provided, default to the command invoker
    if user is None:
        user = interaction.user
    # Only allow updating other users if the invoker has manage_guild permission
    if user != interaction.user and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You do not have permission to update other users. Only server admins can do this.", ephemeral=True)
        return
    links = load_links()
    user_id = str(user.id)
    if user_id not in links:
        await interaction.response.send_message(f"{user.mention} needs to link their FACEIT account first using /linkfaceit.", ephemeral=True)
        return
    username = links[user_id]
    headers = {"Authorization": f"Bearer {FACEIT_API_KEY}"}
    user_url = f"https://open.faceit.com/data/v4/players?nickname={username}"
    user_resp = requests.get(user_url, headers=headers)
    if user_resp.status_code != 200:
        await interaction.response.send_message(f"Could not find FACEIT user: {username}", ephemeral=True)
        return
    user_data = user_resp.json()
    faceit_level = None
    try:
        faceit_level = user_data['games']['cs2']['skill_level']
    except (KeyError, TypeError):
        pass
    if not faceit_level:
        await interaction.response.send_message(f"Could not determine FACEIT level for {user.mention}.", ephemeral=True)
        return
    role_name = f"FACEIT Level {faceit_level}"
    guild = interaction.guild
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        role = await guild.create_role(name=role_name, colour=discord.Colour.green())
    # Remove old FACEIT Level roles from the user
    for r in user.roles:
        if r.name.startswith("FACEIT Level ") and r != role:
            await user.remove_roles(r)
    await user.add_roles(role)
    await interaction.response.send_message(f"{user.mention}'s role has been updated to {role_name}!", ephemeral=True)

# Slash command: /faceitupdateall
@tree.command(name="faceitupdateall", description="(Admin) Update FACEIT roles for all linked users in the server.")
async def faceitupdateall(interaction: discord.Interaction):
    """(Admin) Update FACEIT roles for all linked users in the server."""
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    links = load_links()
    headers = {"Authorization": f"Bearer {FACEIT_API_KEY}"}
    updated = 0
    for user_id, username in links.items():
        member = interaction.guild.get_member(int(user_id))
        if not member:
            continue
        user_url = f"https://open.faceit.com/data/v4/players?nickname={username}"
        user_resp = requests.get(user_url, headers=headers)
        if user_resp.status_code != 200:
            continue
        user_data = user_resp.json()
        faceit_level = None
        try:
            faceit_level = user_data['games']['cs2']['skill_level']
        except (KeyError, TypeError):
            continue
        if not faceit_level:
            continue
        role_name = f"FACEIT Level {faceit_level}"
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            role = await interaction.guild.create_role(name=role_name, colour=discord.Colour.green())
        # Remove old FACEIT Level roles from the member
        for r in member.roles:
            if r.name.startswith("FACEIT Level ") and r != role:
                await member.remove_roles(r)
        await member.add_roles(role)
        updated += 1
    await interaction.response.send_message(f"Updated FACEIT roles for {updated} members.", ephemeral=True)

# Slash command: /help
@tree.command(name="help", description="Show all available commands and their descriptions.")
async def help_command(interaction: discord.Interaction):
    """Show all available commands and their descriptions."""
    help_text = (
        "**Available Commands:**\n"
        "/faceitsearch <username> - Search FACEIT stats for a given username.\n"
        "/linkfaceit <username> - Link your Discord account to your FACEIT username.\n"
        "/faceitupdate - Update your Discord role based on your FACEIT level.\n"
        "/faceitupdateall - (Admin) Update FACEIT roles for all linked users in the server.\n"
        "/help - Show this help message."
    )
    await interaction.response.send_message(help_text, ephemeral=True)

@tree.command(name="faceitsync", description="Set the interval (in minutes) for automatic FACEIT level sync.")
@app_commands.describe(minutes="Interval in minutes between each sync (minimum 1)")
@commands.has_guild_permissions(manage_guild=True)
async def faceitsync(interaction: discord.Interaction, minutes: int):
    """Set the interval (in minutes) for automatic FACEIT level sync."""
    global SYNC_INTERVAL_MINUTES
    if minutes < 1:
        await interaction.response.send_message("Sync interval must be at least 1 minute.", ephemeral=True)
        return
    SYNC_INTERVAL_MINUTES = minutes
    print(f"[FACEIT SYNC] Interval changed! Next sync will run every {SYNC_INTERVAL_MINUTES} minutes.")
    await interaction.response.send_message(f"FACEIT level sync interval set to {minutes} minutes.", ephemeral=True)

if __name__ == "__main__":
    from keep_alive import keep_alive
    keep_alive()
    bot.run(DISCORD_TOKEN)
