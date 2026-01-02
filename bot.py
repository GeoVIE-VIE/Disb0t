import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import aiohttp
import random
import re
import os
import io
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv
from collections import deque
from datetime import datetime, timedelta

import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import pandas as pd

# Load .env from the same directory as this script
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# YouTube DL options
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.webpage_url = data.get('webpage_url')
        self.duration = data.get('duration')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)


class MusicPlayer:
    def __init__(self):
        self.queue = deque()
        self.current = None
        self.voice_client = None
        self.loop = False

    def add_to_queue(self, song):
        self.queue.append(song)

    def get_next(self):
        if self.queue:
            return self.queue.popleft()
        return None

    def clear_queue(self):
        self.queue.clear()


# Store music players per guild
players = {}


def get_player(guild_id):
    if guild_id not in players:
        players[guild_id] = MusicPlayer()
    return players[guild_id]


async def play_next(ctx):
    player = get_player(ctx.guild.id)

    if player.loop and player.current:
        player.queue.appendleft(player.current)

    next_song = player.get_next()

    if next_song:
        player.current = next_song
        try:
            source = await YTDLSource.from_url(next_song['url'], loop=bot.loop, stream=True)

            def after_playing(error):
                if error:
                    print(f'Player error: {error}')
                asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)

            ctx.voice_client.play(source, after=after_playing)
            await ctx.send(f"Now playing: **{source.title}**")
        except Exception as e:
            await ctx.send(f"Error playing song: {e}")
            asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
    else:
        player.current = None


# Channel to post command updates
COMMAND_CHANNEL = "bidenbot"

# Store last posted command list to detect changes
last_command_hash = None


def generate_command_table() -> discord.Embed:
    """Generate an embed with all bot commands"""
    embed = discord.Embed(
        title="🤖 Bot Commands",
        description="All available commands for the bot",
        color=discord.Color.blue()
    )

    # Music commands
    music_cmds = """
`!play <url/search>` - Play YouTube audio
`!skip` / `!s` - Skip current song
`!stop` - Stop and clear queue
`!pause` - Pause playback
`!resume` / `!r` - Resume playback
`!queue` / `!q` - Show queue
`!nowplaying` / `!np` - Current song
`!loop` - Toggle loop mode
`!volume <0-100>` - Set volume
`!clear` - Clear queue
`!leave` / `!dc` - Disconnect
"""
    embed.add_field(name="🎵 Music", value=music_cmds.strip(), inline=False)

    # 4chan commands
    chan_cmds = """
`!ylyl [count]` - Get YLYL images (max 5)
`!ylyl_boards` - Show searched boards
"""
    embed.add_field(name="😂 YLYL", value=chan_cmds.strip(), inline=False)

    # PUBG commands
    pubg_cmds = """
`!pubg <username> [platform]` - Get PUBG stats
Platforms: steam, psn, xbox, stadia
"""
    embed.add_field(name="🎮 PUBG", value=pubg_cmds.strip(), inline=False)

    # Dictionary commands
    dict_cmds = """
`!define <word>` / `!d` - Look up word definition
"""
    embed.add_field(name="📖 Dictionary", value=dict_cmds.strip(), inline=False)

    # Phone lookup commands
    phone_cmds = """
`!phone <number>` - Look up phone number
`!phone_solve` - Interactive CAPTCHA solver (owner)
`!phone_cookie <value>` - Set cookies manually (owner)
`!phone_clear_cookie` - Clear saved cookies (owner)
"""
    embed.add_field(name="📞 Phone Lookup", value=phone_cmds.strip(), inline=False)

    # Stock commands
    stock_cmds = """
`!stock <symbol>` / `!st` - Get stock quote
`!chart <symbol> [timeframe]` / `!c` - Stock chart
Timeframes: 1w, 2w, 1m, 3m, 6m, 1y
"""
    embed.add_field(name="📈 Stocks", value=stock_cmds.strip(), inline=False)

    # Ashes of Creation commands
    aoc_cmds = """
`!aoc item <name>` / `!item` - Look up items
`!aoc mob <name>` / `!mob` - Look up mobs
`!aoc search <query>` - Search all data
"""
    embed.add_field(name="⚔️ Ashes of Creation", value=aoc_cmds.strip(), inline=False)

    # Utility commands
    util_cmds = """
`!commands` / `!cmds` - Show this help table
"""
    embed.add_field(name="🔧 Utility", value=util_cmds.strip(), inline=False)

    embed.set_footer(text=f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return embed


def get_command_hash() -> str:
    """Get a hash of current commands to detect changes"""
    cmd_list = sorted([cmd.name for cmd in bot.commands])
    return str(hash(tuple(cmd_list)))


@bot.event
async def on_ready():
    global last_command_hash
    print(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # Check if commands changed and post to #bidenbot
    current_hash = get_command_hash()
    if current_hash != last_command_hash:
        last_command_hash = current_hash
        # Find and post to #bidenbot in all guilds
        for guild in bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=COMMAND_CHANNEL)
            if channel:
                try:
                    embed = generate_command_table()
                    await channel.send(embed=embed)
                    print(f"Posted command table to #{COMMAND_CHANNEL} in {guild.name}")
                except Exception as e:
                    print(f"Failed to post to #{COMMAND_CHANNEL} in {guild.name}: {e}")


@bot.command(name='commands', aliases=['cmds'])
async def commands_list(ctx):
    """Show all available commands"""
    embed = generate_command_table()
    await ctx.send(embed=embed)


@bot.command(name='play', aliases=['p'])
async def play(ctx, *, search: str):
    """Play a YouTube video by URL or search query"""
    if not ctx.author.voice:
        return await ctx.send("You need to be in a voice channel!")

    channel = ctx.author.voice.channel

    if ctx.voice_client is None:
        await channel.connect()
    elif ctx.voice_client.channel != channel:
        await ctx.voice_client.move_to(channel)

    player = get_player(ctx.guild.id)
    player.voice_client = ctx.voice_client

    async with ctx.typing():
        try:
            # Check if it's a URL or search query
            if not search.startswith('http'):
                search = f'ytsearch:{search}'

            data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))

            if 'entries' in data:
                data = data['entries'][0]

            song = {
                'url': data['webpage_url'],
                'title': data['title'],
                'duration': data.get('duration', 0)
            }

            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                player.add_to_queue(song)
                await ctx.send(f"Added to queue: **{song['title']}**")
            else:
                player.add_to_queue(song)
                await play_next(ctx)

        except Exception as e:
            await ctx.send(f"Error: {e}")


@bot.command(name='skip', aliases=['s'])
async def skip(ctx):
    """Skip the current song"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Skipped!")
    else:
        await ctx.send("Nothing is playing!")


@bot.command(name='stop')
async def stop(ctx):
    """Stop playing and clear the queue"""
    player = get_player(ctx.guild.id)
    player.clear_queue()
    player.current = None

    if ctx.voice_client:
        ctx.voice_client.stop()
        await ctx.send("Stopped and cleared the queue!")


@bot.command(name='pause')
async def pause(ctx):
    """Pause the current song"""
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("Paused!")
    else:
        await ctx.send("Nothing is playing!")


@bot.command(name='resume', aliases=['r'])
async def resume(ctx):
    """Resume the paused song"""
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("Resumed!")
    else:
        await ctx.send("Nothing is paused!")


@bot.command(name='queue', aliases=['q'])
async def queue(ctx):
    """Show the current queue"""
    player = get_player(ctx.guild.id)

    if not player.current and not player.queue:
        return await ctx.send("The queue is empty!")

    embed = discord.Embed(title="Music Queue", color=discord.Color.blue())

    if player.current:
        embed.add_field(name="Now Playing", value=player.current['title'], inline=False)

    if player.queue:
        queue_list = "\n".join([f"{i+1}. {song['title']}" for i, song in enumerate(list(player.queue)[:10])])
        if len(player.queue) > 10:
            queue_list += f"\n... and {len(player.queue) - 10} more"
        embed.add_field(name="Up Next", value=queue_list, inline=False)

    await ctx.send(embed=embed)


@bot.command(name='nowplaying', aliases=['np'])
async def nowplaying(ctx):
    """Show the currently playing song"""
    player = get_player(ctx.guild.id)

    if player.current:
        await ctx.send(f"Now playing: **{player.current['title']}**")
    else:
        await ctx.send("Nothing is playing!")


@bot.command(name='loop')
async def loop(ctx):
    """Toggle loop mode for the current song"""
    player = get_player(ctx.guild.id)
    player.loop = not player.loop
    await ctx.send(f"Loop mode: **{'On' if player.loop else 'Off'}**")


@bot.command(name='leave', aliases=['disconnect', 'dc'])
async def leave(ctx):
    """Leave the voice channel"""
    if ctx.voice_client:
        player = get_player(ctx.guild.id)
        player.clear_queue()
        player.current = None
        await ctx.voice_client.disconnect()
        await ctx.send("Disconnected!")
    else:
        await ctx.send("I'm not in a voice channel!")


@bot.command(name='volume', aliases=['vol'])
async def volume(ctx, vol: int = None):
    """Set the volume (0-100)"""
    if vol is None:
        if ctx.voice_client and ctx.voice_client.source:
            current_vol = int(ctx.voice_client.source.volume * 100)
            return await ctx.send(f"Current volume: **{current_vol}%**")
        return await ctx.send("Nothing is playing!")

    if not 0 <= vol <= 100:
        return await ctx.send("Volume must be between 0 and 100!")

    if ctx.voice_client and ctx.voice_client.source:
        ctx.voice_client.source.volume = vol / 100
        await ctx.send(f"Volume set to **{vol}%**")
    else:
        await ctx.send("Nothing is playing!")


@bot.command(name='clear')
async def clear(ctx):
    """Clear the queue but keep playing current song"""
    player = get_player(ctx.guild.id)
    player.clear_queue()
    await ctx.send("Queue cleared!")


# ============== 4chan YLYL Feature ==============

# Boards to search for YLYL threads
YLYL_BOARDS = ['b', 'wsg', 'gif']

async def find_ylyl_threads(board: str) -> list:
    """Find YLYL threads on a given board"""
    url = f"https://boards.4chan.org/{board}/catalog.json"
    threads = []

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return []
                data = await response.json()

                for page in data:
                    for thread in page.get('threads', []):
                        subject = thread.get('sub', '').lower()
                        comment = thread.get('com', '').lower()

                        # Look for YLYL patterns
                        if any(pattern in subject or pattern in comment for pattern in
                               ['ylyl', 'you laugh you lose', 'you lose you laugh', 'you laugh, you lose']):
                            threads.append({
                                'no': thread['no'],
                                'board': board,
                                'subject': thread.get('sub', 'YLYL Thread')
                            })
        except Exception as e:
            print(f"Error fetching catalog for /{board}/: {e}")

    return threads


async def get_thread_media(board: str, thread_no: int) -> list:
    """Get all images/webms from a thread"""
    url = f"https://boards.4chan.org/{board}/thread/{thread_no}.json"
    media = []

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return []
                data = await response.json()

                for post in data.get('posts', []):
                    if 'tim' in post and 'ext' in post:
                        ext = post['ext']
                        # Only get images and webms
                        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webm', '.mp4']:
                            media.append({
                                'url': f"https://i.4cdn.org/{board}/{post['tim']}{ext}",
                                'filename': f"{post.get('filename', 'image')}{ext}",
                                'ext': ext
                            })
        except Exception as e:
            print(f"Error fetching thread {thread_no}: {e}")

    return media


@bot.command(name='ylyl')
async def ylyl(ctx, count: int = 1):
    """Get random images/webms from 4chan YLYL threads. Usage: !ylyl [count]"""
    if count > 5:
        count = 5
        await ctx.send("Max 5 images at a time!")

    if count < 1:
        count = 1

    async with ctx.typing():
        # Find YLYL threads across boards
        all_threads = []
        for board in YLYL_BOARDS:
            threads = await find_ylyl_threads(board)
            all_threads.extend(threads)

        if not all_threads:
            return await ctx.send("No YLYL threads found!")

        # Get media from random threads
        all_media = []
        random.shuffle(all_threads)

        for thread in all_threads[:3]:  # Check up to 3 threads
            media = await get_thread_media(thread['board'], thread['no'])
            all_media.extend(media)
            if len(all_media) >= 50:  # Enough to pick from
                break

        if not all_media:
            return await ctx.send("No media found in YLYL threads!")

        # Pick random media
        selected = random.sample(all_media, min(count, len(all_media)))

        for item in selected:
            if item['ext'] in ['.webm', '.mp4']:
                # Discord can't embed webm/mp4, send as link
                await ctx.send(f"**{item['filename']}**\n{item['url']}")
            else:
                # Send image as embed
                embed = discord.Embed(color=discord.Color.green())
                embed.set_image(url=item['url'])
                await ctx.send(embed=embed)


@bot.command(name='ylyl_boards')
async def ylyl_boards(ctx):
    """Show which boards are being searched for YLYL"""
    boards = ", ".join([f"/{b}/" for b in YLYL_BOARDS])
    await ctx.send(f"Searching for YLYL on: {boards}")


# ============== PUBG Stats Feature ==============

PUBG_API_KEY = os.getenv('PUBG_API_KEY')
PUBG_PLATFORMS = ['steam', 'psn', 'xbox', 'stadia']


async def pubg_api_request(endpoint: str, shard: str = 'steam') -> dict:
    """Make a request to the PUBG API"""
    url = f"https://api.pubg.com/shards/{shard}/{endpoint}"
    headers = {
        'Authorization': f'Bearer {PUBG_API_KEY}',
        'Accept': 'application/vnd.api+json'
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                return await response.json()
            elif response.status == 404:
                return {'error': 'Player not found'}
            elif response.status == 401:
                return {'error': 'Invalid API key'}
            elif response.status == 429:
                return {'error': 'Rate limited - try again later'}
            else:
                return {'error': f'API error: {response.status}'}


async def get_pubg_player_id(username: str, platform: str) -> tuple:
    """Get player ID from username or Steam ID. Returns (player_id, display_name, error_msg)"""
    # URL encode the username
    encoded_name = urllib.parse.quote(username)

    # First try by player name
    data = await pubg_api_request(f"players?filter[playerNames]={encoded_name}", platform)

    if 'data' in data and len(data['data']) > 0:
        player = data['data'][0]
        return (player['id'], player.get('attributes', {}).get('name', username), None)

    # If that fails and it looks like a Steam ID (all numbers, 17 digits), try that
    if platform == 'steam' and username.isdigit() and len(username) == 17:
        data = await pubg_api_request(f"players?filter[steamIds]={username}", platform)
        if 'data' in data and len(data['data']) > 0:
            player = data['data'][0]
            return (player['id'], player.get('attributes', {}).get('name', username), None)

    # Return error info for debugging
    error_msg = data.get('error', 'Unknown error')
    return (None, None, error_msg)


async def get_pubg_season_stats(player_id: str, platform: str) -> dict:
    """Get current season stats for a player"""
    # First get the current season
    seasons_data = await pubg_api_request("seasons", platform)

    if 'error' in seasons_data:
        return seasons_data

    # Find current season
    current_season = None
    for season in seasons_data.get('data', []):
        if season.get('attributes', {}).get('isCurrentSeason'):
            current_season = season['id']
            break

    if not current_season:
        return {'error': 'Could not find current season'}

    # Get player stats for this season
    stats_data = await pubg_api_request(f"players/{player_id}/seasons/{current_season}", platform)
    return stats_data


def format_pubg_stats(stats_data: dict, username: str, platform: str) -> discord.Embed:
    """Format PUBG stats into a Discord embed"""
    embed = discord.Embed(
        title=f"PUBG Stats: {username}",
        color=discord.Color.orange()
    )
    embed.set_footer(text=f"Platform: {platform.upper()}")

    if 'error' in stats_data:
        embed.description = f"Error: {stats_data['error']}"
        return embed

    try:
        attributes = stats_data.get('data', {}).get('attributes', {})
        game_modes = attributes.get('gameModeStats', {})

        # Combine stats from different modes
        total_stats = {
            'wins': 0, 'top10s': 0, 'kills': 0, 'deaths': 0,
            'headshots': 0, 'damage': 0, 'matches': 0, 'time': 0
        }

        modes_played = []
        for mode, stats in game_modes.items():
            if stats.get('roundsPlayed', 0) > 0:
                modes_played.append(mode)
                total_stats['wins'] += stats.get('wins', 0)
                total_stats['top10s'] += stats.get('top10s', 0)
                total_stats['kills'] += stats.get('kills', 0)
                total_stats['deaths'] += stats.get('losses', 0)
                total_stats['headshots'] += stats.get('headshotKills', 0)
                total_stats['damage'] += stats.get('damageDealt', 0)
                total_stats['matches'] += stats.get('roundsPlayed', 0)
                total_stats['time'] += stats.get('timeSurvived', 0)

        if total_stats['matches'] == 0:
            embed.description = "No matches played this season!"
            return embed

        # Calculate ratios
        kd = total_stats['kills'] / max(total_stats['deaths'], 1)
        hs_percent = (total_stats['headshots'] / max(total_stats['kills'], 1)) * 100
        avg_damage = total_stats['damage'] / max(total_stats['matches'], 1)
        avg_survival = total_stats['time'] / max(total_stats['matches'], 1) / 60  # minutes

        # Add fields
        embed.add_field(name="🏆 Wins", value=str(total_stats['wins']), inline=True)
        embed.add_field(name="🔟 Top 10s", value=str(total_stats['top10s']), inline=True)
        embed.add_field(name="🎮 Matches", value=str(total_stats['matches']), inline=True)

        embed.add_field(name="💀 Kills", value=str(total_stats['kills']), inline=True)
        embed.add_field(name="📊 K/D", value=f"{kd:.2f}", inline=True)
        embed.add_field(name="🎯 Headshot %", value=f"{hs_percent:.1f}%", inline=True)

        embed.add_field(name="💥 Avg Damage", value=f"{avg_damage:.0f}", inline=True)
        embed.add_field(name="⏱️ Avg Survival", value=f"{avg_survival:.1f} min", inline=True)
        embed.add_field(name="🎲 Modes", value=str(len(modes_played)), inline=True)

        # Rate the player
        win_rate = (total_stats['wins'] / max(total_stats['matches'], 1)) * 100

        # Scoring system (harsher thresholds)
        score = 0
        if kd >= 3.0:
            score += 3
        elif kd >= 2.0:
            score += 2
        elif kd >= 1.5:
            score += 1

        if avg_damage >= 400:
            score += 3
        elif avg_damage >= 250:
            score += 2
        elif avg_damage >= 150:
            score += 1

        if win_rate >= 15:
            score += 3
        elif win_rate >= 8:
            score += 2
        elif win_rate >= 4:
            score += 1

        # Verdict
        if score >= 7:
            verdict = "🔥 **CERTIFIED GAMER** 🔥"
            embed.color = discord.Color.gold()
        elif score >= 5:
            verdict = "✅ **NOT A SHITTER**"
            embed.color = discord.Color.green()
        elif score >= 3:
            verdict = "😐 **MID**"
            embed.color = discord.Color.orange()
        else:
            verdict = "💩 **SHITTER**"
            embed.color = discord.Color.red()

        embed.add_field(name="📋 VERDICT", value=verdict, inline=False)

    except Exception as e:
        embed.description = f"Error parsing stats: {e}"

    return embed


@bot.command(name='pubg')
async def pubg(ctx, username: str = None, platform: str = 'steam'):
    """Get PUBG player stats. Usage: !pubg <username> [platform]
    Platforms: steam, psn, xbox, stadia"""

    if not PUBG_API_KEY:
        return await ctx.send("PUBG API key not configured!")

    if not username:
        return await ctx.send("Usage: `!pubg <username> [platform]`\nPlatforms: steam, psn, xbox, stadia")

    platform = platform.lower()
    if platform not in PUBG_PLATFORMS:
        return await ctx.send(f"Invalid platform! Use: {', '.join(PUBG_PLATFORMS)}")

    async with ctx.typing():
        # Get player ID
        player_id, display_name, error_msg = await get_pubg_player_id(username, platform)

        if not player_id:
            return await ctx.send(f"Player **{username}** not found on **{platform}**!\nPlayer must have played in the last 14 days.")

        # Get season stats
        stats_data = await get_pubg_season_stats(player_id, platform)

        # Format and send
        embed = format_pubg_stats(stats_data, display_name, platform)
        await ctx.send(embed=embed)


# ============== Dictionary Feature ==============

@bot.command(name='define', aliases=['dict', 'd'])
async def define(ctx, *, word: str = None):
    """Look up the definition of a word. Usage: !define <word>"""
    if not word:
        return await ctx.send("Usage: `!define <word>`")

    word = word.strip().lower()

    async with ctx.typing():
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 404:
                        return await ctx.send(f"No definition found for **{word}**")

                    if response.status != 200:
                        return await ctx.send(f"Error looking up word: {response.status}")

                    data = await response.json()

                    if not data or len(data) == 0:
                        return await ctx.send(f"No definition found for **{word}**")

                    entry = data[0]
                    embed = discord.Embed(
                        title=f"📖 {entry.get('word', word)}",
                        color=discord.Color.blue()
                    )

                    # Add phonetic if available
                    phonetic = entry.get('phonetic', '')
                    if phonetic:
                        embed.description = f"*{phonetic}*"

                    # Add meanings (limit to first 3)
                    meanings = entry.get('meanings', [])[:3]
                    for meaning in meanings:
                        part_of_speech = meaning.get('partOfSpeech', 'unknown')
                        definitions = meaning.get('definitions', [])[:2]

                        def_text = ""
                        for i, d in enumerate(definitions, 1):
                            def_text += f"{i}. {d.get('definition', 'N/A')}\n"
                            example = d.get('example')
                            if example:
                                def_text += f"   *\"{example}\"*\n"

                        if def_text:
                            embed.add_field(
                                name=f"**{part_of_speech}**",
                                value=def_text[:1024],
                                inline=False
                            )

                    await ctx.send(embed=embed)

            except Exception as e:
                await ctx.send(f"Error: {e}")


# ============== Phone Lookup Feature ==============

import html
import json
import time
import threading
from curl_cffi import requests as curl_requests
from playwright.sync_api import sync_playwright

# Cookie file path for persistence (now stores ALL cookies as JSON)
COOKIE_FILE = Path(__file__).parent / '.phone_cookies.json'

# Global browser session for CAPTCHA solving
_captcha_browser = None
_captcha_page = None
_captcha_context = None
_captcha_playwright = None
_browser_lock = threading.Lock()


def load_cookies() -> dict:
    """Load saved cookies from file (JSON format)"""
    if COOKIE_FILE.exists():
        try:
            return json.loads(COOKIE_FILE.read_text())
        except:
            pass
    return {}


def save_cookies(cookies: dict):
    """Save cookies to file as JSON"""
    try:
        COOKIE_FILE.write_text(json.dumps(cookies, indent=2))
    except:
        pass


def parse_cookie_string(cookie_str: str) -> dict:
    """Parse cookie string from browser (name=value; name2=value2 format)"""
    cookies = {}
    # Handle both semicolon-separated and newline-separated formats
    parts = re.split(r'[;\n]', cookie_str)
    for part in parts:
        part = part.strip()
        if '=' in part:
            name, value = part.split('=', 1)
            cookies[name.strip()] = value.strip()
    return cookies


# ============== Interactive CAPTCHA Solving ==============

def start_captcha_browser(url: str = "https://www.usphonebook.com/", headless: bool = True) -> str:
    """Start a browser session for CAPTCHA solving. Returns screenshot path."""
    global _captcha_browser, _captcha_page, _captcha_context, _captcha_playwright

    with _browser_lock:
        # Close existing session if any
        close_captcha_browser_internal()

        _captcha_playwright = sync_playwright().start()

        # Launch browser - headless by default, use Xvfb if headless=False
        _captcha_browser = _captcha_playwright.chromium.launch(
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--window-size=1280,720',
            ]
        )

        _captcha_context = _captcha_browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )

        _captcha_page = _captcha_context.new_page()
        _captcha_page.goto(url, wait_until='networkidle', timeout=30000)

        # Take screenshot
        screenshot_path = '/tmp/captcha_session.png'
        _captcha_page.screenshot(path=screenshot_path)
        return screenshot_path


def captcha_browser_click(x: int, y: int) -> str:
    """Click at coordinates in the CAPTCHA browser. Returns new screenshot path."""
    global _captcha_page

    if not _captcha_page:
        return None

    with _browser_lock:
        _captcha_page.mouse.click(x, y)
        time.sleep(1)  # Wait for any animations/loads
        screenshot_path = '/tmp/captcha_session.png'
        _captcha_page.screenshot(path=screenshot_path)
        return screenshot_path


def captcha_browser_type(text: str) -> str:
    """Type text in the CAPTCHA browser. Returns new screenshot path."""
    global _captcha_page

    if not _captcha_page:
        return None

    with _browser_lock:
        _captcha_page.keyboard.type(text, delay=50)
        time.sleep(0.5)
        screenshot_path = '/tmp/captcha_session.png'
        _captcha_page.screenshot(path=screenshot_path)
        return screenshot_path


def captcha_browser_refresh() -> str:
    """Refresh the CAPTCHA browser page. Returns new screenshot path."""
    global _captcha_page

    if not _captcha_page:
        return None

    with _browser_lock:
        _captcha_page.reload(wait_until='networkidle', timeout=30000)
        screenshot_path = '/tmp/captcha_session.png'
        _captcha_page.screenshot(path=screenshot_path)
        return screenshot_path


def captcha_browser_extract_cookies() -> dict:
    """Extract all cookies from the CAPTCHA browser session."""
    global _captcha_context

    if not _captcha_context:
        return {}

    with _browser_lock:
        cookies = _captcha_context.cookies()
        result = {}
        for cookie in cookies:
            if 'usphonebook' in cookie.get('domain', ''):
                result[cookie['name']] = cookie['value']
        return result


def close_captcha_browser_internal():
    """Internal function to close browser (must hold lock)."""
    global _captcha_browser, _captcha_page, _captcha_context, _captcha_playwright

    if _captcha_page:
        try:
            _captcha_page.close()
        except:
            pass
        _captcha_page = None

    if _captcha_context:
        try:
            _captcha_context.close()
        except:
            pass
        _captcha_context = None

    if _captcha_browser:
        try:
            _captcha_browser.close()
        except:
            pass
        _captcha_browser = None

    if _captcha_playwright:
        try:
            _captcha_playwright.stop()
        except:
            pass
        _captcha_playwright = None


def close_captcha_browser():
    """Close the CAPTCHA browser session."""
    with _browser_lock:
        close_captcha_browser_internal()


def captcha_browser_screenshot() -> str:
    """Take a fresh screenshot without any action."""
    global _captcha_page

    if not _captcha_page:
        return None

    with _browser_lock:
        screenshot_path = '/tmp/captcha_session.png'
        _captcha_page.screenshot(path=screenshot_path)
        return screenshot_path


class CaptchaSolverView(discord.ui.View):
    """Interactive view for solving CAPTCHA via Discord"""

    def __init__(self, ctx):
        super().__init__(timeout=600)  # 10 minute timeout
        self.ctx = ctx
        self.click_mode = False
        self.last_message = None

    async def send_screenshot(self, interaction_or_ctx, message: str = None):
        """Send current screenshot to Discord"""
        screenshot_path = Path('/tmp/captcha_session.png')
        if screenshot_path.exists():
            file = discord.File(screenshot_path, filename='captcha.png')
            content = message or "**CAPTCHA Browser** - Send `click X Y` coordinates"
            if hasattr(interaction_or_ctx, 'followup'):
                await interaction_or_ctx.followup.send(content, file=file, view=self)
            else:
                self.last_message = await interaction_or_ctx.send(content, file=file, view=self)

    @discord.ui.button(label="📸 Screenshot", style=discord.ButtonStyle.secondary, row=0)
    async def screenshot_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await bot.loop.run_in_executor(None, captcha_browser_screenshot)
        await self.send_screenshot(interaction, "Current page state:")

    @discord.ui.button(label="🔄 Refresh Page", style=discord.ButtonStyle.secondary, row=0)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await bot.loop.run_in_executor(None, captcha_browser_refresh)
        await self.send_screenshot(interaction, "Page refreshed!")

    @discord.ui.button(label="⌨️ Type Text", style=discord.ButtonStyle.primary, row=0)
    async def type_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = TypeTextModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="✅ Done - Save Cookies", style=discord.ButtonStyle.success, row=1)
    async def done_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        # Extract cookies
        cookies = await bot.loop.run_in_executor(None, captcha_browser_extract_cookies)

        if cookies:
            save_cookies(cookies)
            await interaction.followup.send(
                f"**Cookies saved!** ({len(cookies)} cookies: {list(cookies.keys())})\n"
                f"You can now use `!phone <number>` to look up numbers.",
                ephemeral=False
            )
        else:
            await interaction.followup.send("No cookies found. Make sure you solved the CAPTCHA first.", ephemeral=True)

        # Close browser
        await bot.loop.run_in_executor(None, close_captcha_browser)
        self.stop()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger, row=1)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await bot.loop.run_in_executor(None, close_captcha_browser)
        await interaction.followup.send("CAPTCHA session cancelled.", ephemeral=True)
        self.stop()


class TypeTextModal(discord.ui.Modal, title="Type Text"):
    """Modal for typing text in CAPTCHA browser"""

    text = discord.ui.TextInput(
        label="Text to type",
        placeholder="Enter text to type in the browser...",
        style=discord.TextStyle.short,
        required=True,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await bot.loop.run_in_executor(None, captcha_browser_type, self.text.value)

        # Send updated screenshot
        screenshot_path = Path('/tmp/captcha_session.png')
        if screenshot_path.exists():
            file = discord.File(screenshot_path, filename='captcha.png')
            await interaction.followup.send(f"Typed: `{self.text.value}`", file=file)


def format_phone_number(phone: str) -> str:
    """Format phone number to XXX-XXX-XXXX"""
    # Remove all non-digits
    digits = re.sub(r'\D', '', phone)

    # Handle 11-digit numbers starting with 1
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]

    if len(digits) != 10:
        return None

    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def fetch_phone_data(url: str) -> dict:
    """Fetch phone data using curl_cffi with Chrome TLS impersonation"""

    # Load ALL saved cookies
    cookies = load_cookies()
    if cookies:
        print(f"Using {len(cookies)} saved cookies: {list(cookies.keys())}")

    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Cache-Control': 'max-age=0',
        'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
    }

    try:
        # Use curl_cffi with Chrome impersonation (mimics Chrome's TLS fingerprint)
        response = curl_requests.get(
            url,
            headers=headers,
            cookies=cookies if cookies else None,
            impersonate="chrome120",  # Impersonate Chrome 120
            timeout=30
        )

        content = response.text

        # Save debug files
        with open('/tmp/phone_debug.html', 'w') as f:
            f.write(content)

        result = {}

        # Check if we hit CAPTCHA/DataDome block
        if 'geo.captcha-delivery.com' in content or 'DataDome' in content or response.status_code == 403:
            result['captcha_detected'] = True
            result['page_title'] = 'DataDome CAPTCHA'
            return result

        # Look for gResults - try multiple patterns
        patterns = [
            r"gResults:'(\[[\s\S]+?\])'",
            r'gResults:"(\[[\s\S]+?\])"',
            r"gResults:\s*'(\[[\s\S]+?\])'",
            r'gResults\s*=\s*(\[[\s\S]+?\]);',
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                result['raw_json'] = match.group(1)
                break

        # Try to extract name from HTML if no gResults
        if not result.get('raw_json'):
            name_match = re.search(r'class="[^"]*name[^"]*"[^>]*>([^<]+)<', content, re.IGNORECASE)
            if name_match:
                result['name'] = name_match.group(1).strip()

        # Extract page title
        title_match = re.search(r'<title>([^<]+)</title>', content)
        result['page_title'] = title_match.group(1) if title_match else 'Unknown'

        return result

    except Exception as e:
        return {'error': str(e)}


class CaptchaSolveView(discord.ui.View):
    """Interactive view for solving CAPTCHA"""

    def __init__(self, phone_number: str, original_ctx):
        super().__init__(timeout=300)  # 5 minute timeout
        self.phone_number = phone_number
        self.original_ctx = original_ctx

        # Add link button manually (can't use decorator for link buttons)
        link_button = discord.ui.Button(
            label="Open Site",
            style=discord.ButtonStyle.link,
            url="https://www.usphonebook.com/"
        )
        self.add_item(link_button)

    @discord.ui.button(label="I Solved It - Paste Cookie", style=discord.ButtonStyle.success, emoji="✅")
    async def solved_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Create a modal to get the cookie
        modal = CookieInputModal(self.phone_number, self.original_ctx)
        await interaction.response.send_modal(modal)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Lookup cancelled.", ephemeral=True)
        self.stop()


class CookieInputModal(discord.ui.Modal, title="Paste ALL Cookies"):
    """Modal for entering cookies from browser"""

    cookie = discord.ui.TextInput(
        label="All Cookies (copy from DevTools)",
        placeholder="datadome=xxx; cf_clearance=xxx; laravel_session=xxx",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000
    )

    def __init__(self, phone_number: str, original_ctx):
        super().__init__()
        self.phone_number = phone_number
        self.original_ctx = original_ctx

    async def on_submit(self, interaction: discord.Interaction):
        # Parse and save ALL cookies
        cookie_str = self.cookie.value.strip()
        cookies = parse_cookie_string(cookie_str)

        if not cookies:
            await interaction.response.send_message("Could not parse cookies. Use format: name=value; name2=value2", ephemeral=True)
            return

        save_cookies(cookies)

        await interaction.response.send_message(
            f"Cookie saved! Retrying lookup for **{self.phone_number}**...",
            ephemeral=True
        )

        # Retry the lookup
        url = f"https://www.usphonebook.com/phone-search/{self.phone_number}"

        async with self.original_ctx.typing():
            data = await bot.loop.run_in_executor(None, fetch_phone_data, url)

            if data.get('captcha_detected'):
                await self.original_ctx.send("Still getting CAPTCHA. The cookie might be invalid or expired. Try getting a fresh one.")
                return

            if 'error' in data:
                await self.original_ctx.send(f"Error: {data['error']}")
                return

            # Process results
            if 'raw_json' in data:
                json_str = html.unescape(data['raw_json'])
                results = json.loads(json_str)
                if results:
                    person = results[0]
                    data['name'] = person.get('fullName', 'Unknown')
                    data['age'] = person.get('age')
                    city = person.get('city', '')
                    state = person.get('state', '')
                    if city and state:
                        data['location'] = f"{city}, {state}"
                    current_addr = person.get('currentAddress', {})
                    if current_addr:
                        data['address'] = current_addr.get('fullAddressDisplay', '')
                    relatives = person.get('relatives', [])
                    if relatives:
                        data['relatives'] = [r.get('name', '') for r in relatives[:5] if r.get('name')]

            if not data.get('name') and not data.get('raw_json'):
                await self.original_ctx.send(f"No results found for **{self.phone_number}**")
                return

            # Create embed with results
            embed = discord.Embed(title=f"📞 {self.phone_number}", color=discord.Color.green())

            if data.get('name'):
                embed.add_field(name="👤 Name", value=data['name'], inline=True)
            if data.get('age'):
                embed.add_field(name="🎂 Age", value=str(data['age']), inline=True)
            if data.get('location'):
                embed.add_field(name="📍 Location", value=data['location'], inline=True)
            if data.get('address'):
                embed.add_field(name="🏠 Address", value=data['address'], inline=False)
            if data.get('relatives'):
                embed.add_field(name="👨‍👩‍👧‍👦 Relatives", value=", ".join(data['relatives']), inline=False)

            await self.original_ctx.send(embed=embed)


@bot.command(name='phone', aliases=['lookup', 'whois'])
async def phone_lookup(ctx, *, phone: str = None):
    """Look up a phone number. Usage: !phone <number>"""
    if not phone:
        return await ctx.send("Usage: `!phone <number>` (e.g. `!phone 555-123-4567`)")

    formatted = format_phone_number(phone)
    if not formatted:
        return await ctx.send("Invalid phone number! Use 10 digits (e.g. `555-123-4567` or `5551234567`)")

    async with ctx.typing():
        url = f"https://www.usphonebook.com/phone-search/{formatted}"

        try:
            # Run playwright in executor (it's synchronous)
            data = await bot.loop.run_in_executor(
                None, fetch_phone_data, url
            )

            if 'error' in data:
                return await ctx.send(f"Error fetching data: {data['error']}")

            # Check if CAPTCHA was detected
            if data.get('captcha_detected'):
                # Create interactive view for solving CAPTCHA
                view = CaptchaSolveView(formatted, ctx)

                # Send the screenshot so user can see what's happening
                screenshot_path = Path('/tmp/phone_debug.png')

                instructions = (
                    f"**🔒 CAPTCHA detected!** DataDome is blocking the request.\n\n"
                    f"**To solve:**\n"
                    f"1. Click **Open Site** to visit usphonebook.com\n"
                    f"2. Solve the CAPTCHA if shown\n"
                    f"3. Open DevTools (F12) → Application → Cookies\n"
                    f"4. Copy **ALL** cookies for usphonebook.com\n"
                    f"   Format: `datadome=xxx; cf_clearance=xxx; laravel_session=xxx`\n"
                    f"5. Click **I Solved It - Paste Cookie** and paste all cookies\n\n"
                    f"_The lookup will retry automatically!_"
                )

                if screenshot_path.exists():
                    file = discord.File(screenshot_path, filename='captcha.png')
                    await ctx.send(instructions, file=file, view=view)
                else:
                    await ctx.send(instructions, view=view)
                return

            # Check if we got raw JSON data
            if 'raw_json' in data:
                json_str = html.unescape(data['raw_json'])
                results = json.loads(json_str)
                if results:
                    person = results[0]
                    data['name'] = person.get('fullName', 'Unknown')
                    data['age'] = person.get('age')
                    city = person.get('city', '')
                    state = person.get('state', '')
                    if city and state:
                        data['location'] = f"{city}, {state}"
                    current_addr = person.get('currentAddress', {})
                    if current_addr:
                        data['address'] = current_addr.get('fullAddressDisplay', '')
                    relatives = person.get('relatives', [])
                    if relatives:
                        data['relatives'] = [r.get('name', '') for r in relatives[:5] if r.get('name')]

            # Check if we have any useful data
            if not data.get('name') and not data.get('raw_json'):
                # Debug: show page title to see what we got
                page_title = data.get('page_title', 'Unknown')
                return await ctx.send(f"Could not parse results for **{formatted}**\nPage title: {page_title}\nCheck /tmp/phone_debug.png and /tmp/phone_debug.html for details")

            # Create embed
            embed = discord.Embed(
                title=f"📞 {formatted}",
                color=discord.Color.blue()
            )

            # Name
            if data.get('name'):
                embed.add_field(name="👤 Name", value=data['name'], inline=True)

            # Age
            if data.get('age'):
                embed.add_field(name="🎂 Age", value=str(data['age']), inline=True)

            # Location
            if data.get('location'):
                embed.add_field(name="📍 Location", value=data['location'], inline=True)

            # Address
            if data.get('address'):
                embed.add_field(name="🏠 Address", value=data['address'], inline=False)

            # Relatives
            if data.get('relatives'):
                embed.add_field(name="👨‍👩‍👧‍👦 Relatives", value=", ".join(data['relatives']), inline=False)

            await ctx.send(embed=embed)

        except json.JSONDecodeError:
            await ctx.send(f"Error parsing results for **{formatted}**")
        except Exception as e:
            await ctx.send(f"Error: {e}")


@bot.command(name='phone_cookie')
@commands.is_owner()
async def phone_cookie(ctx, *, cookie_value: str = None):
    """Set cookies for phone lookups (owner only). Usage: !phone_cookie name=value; name2=value2"""
    if not cookie_value:
        # Check if cookies exist
        current = load_cookies()
        if current:
            return await ctx.send(f"Cookies set: {list(current.keys())}")
        else:
            return await ctx.send("No cookies set. Usage: `!phone_cookie name=value; name2=value2`")

    # Parse and save ALL cookies
    cookies = parse_cookie_string(cookie_value.strip())
    if not cookies:
        return await ctx.send("Could not parse cookies. Use format: `name=value; name2=value2`")

    save_cookies(cookies)
    await ctx.send(f"Saved {len(cookies)} cookies: {list(cookies.keys())}")


@bot.command(name='phone_clear_cookie')
@commands.is_owner()
async def phone_clear_cookie(ctx):
    """Clear the saved datadome cookie (owner only)"""
    if COOKIE_FILE.exists():
        COOKIE_FILE.unlink()
        await ctx.send("Cookie cleared!")
    else:
        await ctx.send("No cookie to clear.")


@bot.command(name='phone_solve')
@commands.is_owner()
async def phone_solve(ctx):
    """Start interactive CAPTCHA solving session (owner only).

    This opens a browser on the server (requires Xvfb for headless servers).
    You can interact with the page through Discord to solve CAPTCHAs.

    Prerequisites for headless server:
    - Install Xvfb: sudo apt install xvfb
    - Run bot with: xvfb-run -a python bot.py
    """
    await ctx.send("Starting CAPTCHA solving browser... This may take a moment.")

    async with ctx.typing():
        try:
            # Start browser in executor (blocking) - headless mode works without Xvfb
            screenshot_path = await bot.loop.run_in_executor(
                None, lambda: start_captcha_browser("https://www.usphonebook.com/", headless=True)
            )

            if screenshot_path and Path(screenshot_path).exists():
                view = CaptchaSolverView(ctx)
                file = discord.File(screenshot_path, filename='captcha.png')

                instructions = (
                    "**🌐 CAPTCHA Browser Started!**\n\n"
                    "**Screen size:** 1280x720 pixels\n"
                    "**How to interact:**\n"
                    "• Send `click X Y` to click (e.g. `click 640 360` for center)\n"
                    "• Use **Type Text** button to enter text\n"
                    "• Use **Refresh** to reload the page\n"
                    "• Click **Done** when CAPTCHA is solved to save cookies\n\n"
                    "_Tip: CAPTCHA checkbox is usually around `click 580 400`_"
                )

                await ctx.send(instructions, file=file, view=view)

                # Set up message listener for click commands
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel

                # Listen for click commands in background
                async def listen_for_clicks():
                    while True:
                        try:
                            msg = await bot.wait_for('message', check=check, timeout=600)
                            content = msg.content.lower().strip()

                            # Parse click command
                            if content.startswith('click '):
                                parts = content.split()
                                if len(parts) >= 3:
                                    try:
                                        x = int(parts[1])
                                        y = int(parts[2])
                                        await msg.add_reaction('👆')
                                        await bot.loop.run_in_executor(None, captcha_browser_click, x, y)

                                        # Send new screenshot
                                        screenshot_path = Path('/tmp/captcha_session.png')
                                        if screenshot_path.exists():
                                            file = discord.File(screenshot_path, filename='captcha.png')
                                            await ctx.send(f"Clicked at ({x}, {y})", file=file, view=view)
                                    except ValueError:
                                        await msg.add_reaction('❌')

                            # Also accept just coordinates like "640 360"
                            elif re.match(r'^\d+\s+\d+$', content):
                                parts = content.split()
                                x, y = int(parts[0]), int(parts[1])
                                await msg.add_reaction('👆')
                                await bot.loop.run_in_executor(None, captcha_browser_click, x, y)

                                screenshot_path = Path('/tmp/captcha_session.png')
                                if screenshot_path.exists():
                                    file = discord.File(screenshot_path, filename='captcha.png')
                                    await ctx.send(f"Clicked at ({x}, {y})", file=file, view=view)

                        except asyncio.TimeoutError:
                            break
                        except Exception as e:
                            print(f"Click listener error: {e}")
                            break

                # Start click listener in background
                bot.loop.create_task(listen_for_clicks())

            else:
                await ctx.send("Failed to start browser. Make sure Xvfb is running:\n`xvfb-run -a python bot.py`")

        except Exception as e:
            await ctx.send(f"Error starting browser: {e}\n\nMake sure you have Xvfb installed and run:\n`xvfb-run -a python bot.py`")


# ============== Stock Feature (Alpha Vantage) ==============

ALPHAVANTAGE_API_KEY = os.getenv('ALPHAVANTAGE_API_KEY')


@bot.command(name='stock', aliases=['stonk', 'st'])
async def stock(ctx, symbol: str = None):
    """Get stock quote. Usage: !s <symbol>"""
    if not ALPHAVANTAGE_API_KEY:
        return await ctx.send("Alpha Vantage API key not configured!")

    if not symbol:
        return await ctx.send("Usage: `!s <symbol>` (e.g. `!s INTC`)")

    symbol = symbol.upper().strip()

    async with ctx.typing():
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={ALPHAVANTAGE_API_KEY}"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        return await ctx.send(f"API error: {response.status}")

                    data = await response.json()

                    # Check for errors
                    if "Error Message" in data:
                        return await ctx.send(f"Invalid symbol: **{symbol}**")

                    if "Note" in data:
                        return await ctx.send("API rate limit reached. Try again in a minute.")

                    quote = data.get("Global Quote", {})

                    if not quote:
                        return await ctx.send(f"No data found for **{symbol}**")

                    # Parse the data
                    price = float(quote.get("05. price", 0))
                    change = float(quote.get("09. change", 0))
                    change_pct = quote.get("10. change percent", "0%").replace("%", "")
                    change_pct = float(change_pct)
                    open_price = float(quote.get("02. open", 0))
                    high = float(quote.get("03. high", 0))
                    low = float(quote.get("04. low", 0))
                    volume = int(quote.get("06. volume", 0))
                    prev_close = float(quote.get("08. previous close", 0))

                    # Determine color based on change
                    if change > 0:
                        color = discord.Color.green()
                        arrow = "📈"
                        change_str = f"+${change:.2f} (+{change_pct:.2f}%)"
                    elif change < 0:
                        color = discord.Color.red()
                        arrow = "📉"
                        change_str = f"-${abs(change):.2f} ({change_pct:.2f}%)"
                    else:
                        color = discord.Color.greyple()
                        arrow = "➡️"
                        change_str = f"$0.00 (0.00%)"

                    embed = discord.Embed(
                        title=f"{arrow} {symbol}",
                        description=f"**${price:.2f}**\n{change_str}",
                        color=color
                    )

                    embed.add_field(name="Open", value=f"${open_price:.2f}", inline=True)
                    embed.add_field(name="Prev Close", value=f"${prev_close:.2f}", inline=True)
                    embed.add_field(name="Volume", value=f"{volume:,}", inline=True)

                    embed.add_field(name="High", value=f"${high:.2f}", inline=True)
                    embed.add_field(name="Low", value=f"${low:.2f}", inline=True)
                    embed.add_field(name="Range", value=f"${low:.2f} - ${high:.2f}", inline=True)

                    embed.set_footer(text="Data from Alpha Vantage")

                    await ctx.send(embed=embed)

            except Exception as e:
                await ctx.send(f"Error: {e}")


def draw_hollow_candles(ax, df):
    """Draw hollow candlestick chart"""
    width = 0.6

    for i, (idx, row) in enumerate(df.iterrows()):
        open_price = row['Open']
        close_price = row['Close']
        high_price = row['High']
        low_price = row['Low']

        # Determine if bullish (up) or bearish (down)
        is_bullish = close_price >= open_price

        # Colors: hollow green for up, filled red for down
        if is_bullish:
            color = '#00ff00'  # Green
            body_color = 'none'  # Hollow
            edge_color = '#00ff00'
        else:
            color = '#ff0000'  # Red
            body_color = '#ff0000'  # Filled
            edge_color = '#ff0000'

        # Draw the wick (high-low line)
        ax.plot([i, i], [low_price, high_price], color=color, linewidth=1)

        # Draw the body
        body_bottom = min(open_price, close_price)
        body_height = abs(close_price - open_price)

        if body_height == 0:
            body_height = 0.01  # Minimum height for doji

        rect = Rectangle(
            (i - width/2, body_bottom),
            width, body_height,
            facecolor=body_color,
            edgecolor=edge_color,
            linewidth=1.5
        )
        ax.add_patch(rect)


async def generate_stock_chart(symbol: str, timeframe: str, api_key: str) -> io.BytesIO:
    """Generate a candlestick chart for a stock"""

    # Determine API function and parameters based on timeframe
    # Note: Intraday data requires premium API - using daily data for all timeframes
    timeframe_config = {
        '1w': ('TIME_SERIES_DAILY', 'Time Series (Daily)', None, 5),            # 1 week
        '2w': ('TIME_SERIES_DAILY', 'Time Series (Daily)', None, 10),           # 2 weeks
        '1m': ('TIME_SERIES_DAILY', 'Time Series (Daily)', None, 22),           # 1 month
        '3m': ('TIME_SERIES_DAILY', 'Time Series (Daily)', None, 66),           # 3 months
        '6m': ('TIME_SERIES_DAILY', 'Time Series (Daily)', None, 132),          # 6 months
        '1y': ('TIME_SERIES_WEEKLY', 'Weekly Time Series', None, 52),           # 1 year
    }

    if timeframe not in timeframe_config:
        return None

    func, series_key, interval, limit = timeframe_config[timeframe]

    # Build URL
    if interval:
        url = f"https://www.alphavantage.co/query?function={func}&symbol={symbol}&interval={interval}&apikey={api_key}&outputsize=compact"
    else:
        url = f"https://www.alphavantage.co/query?function={func}&symbol={symbol}&apikey={api_key}&outputsize=compact"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                return None

            data = await response.json()

            if "Error Message" in data or "Note" in data:
                return None

            time_series = data.get(series_key, {})

            if not time_series:
                return None

            # Parse data into DataFrame
            rows = []
            for date_str, values in list(time_series.items())[:limit]:
                rows.append({
                    'Date': date_str,
                    'Open': float(values.get('1. open', 0)),
                    'High': float(values.get('2. high', 0)),
                    'Low': float(values.get('3. low', 0)),
                    'Close': float(values.get('4. close', 0)),
                    'Volume': int(values.get('5. volume', 0))
                })

            if not rows:
                return None

            df = pd.DataFrame(rows)
            df = df.iloc[::-1]  # Reverse to chronological order
            df.reset_index(drop=True, inplace=True)

            # Create chart
            fig, ax = plt.subplots(figsize=(12, 6), facecolor='#1a1a2e')
            ax.set_facecolor('#1a1a2e')

            # Draw hollow candles
            draw_hollow_candles(ax, df)

            # Style the chart
            ax.set_xlim(-1, len(df))
            ax.set_ylabel('Price ($)', color='white', fontsize=12)
            ax.tick_params(colors='white')
            ax.grid(True, alpha=0.3, color='gray')

            # X-axis labels (show every nth label)
            n = max(1, len(df) // 8)
            ax.set_xticks(range(0, len(df), n))
            ax.set_xticklabels([df.iloc[i]['Date'].split()[0] if i < len(df) else '' for i in range(0, len(df), n)],
                              rotation=45, ha='right', color='white', fontsize=8)

            # Title
            latest_price = df.iloc[-1]['Close']
            first_price = df.iloc[0]['Open']
            change = latest_price - first_price
            change_pct = (change / first_price) * 100 if first_price else 0

            if change >= 0:
                title_color = '#00ff00'
                change_str = f"+${change:.2f} (+{change_pct:.2f}%)"
            else:
                title_color = '#ff0000'
                change_str = f"-${abs(change):.2f} ({change_pct:.2f}%)"

            ax.set_title(f"{symbol} - {timeframe.upper()} | ${latest_price:.2f} {change_str}",
                        color=title_color, fontsize=14, fontweight='bold')

            # Spine colors
            for spine in ax.spines.values():
                spine.set_color('gray')

            plt.tight_layout()

            # Save to BytesIO
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, facecolor='#1a1a2e', edgecolor='none')
            buf.seek(0)
            plt.close(fig)

            return buf


class ChartTimeframeView(discord.ui.View):
    """View with buttons to switch chart timeframes"""

    def __init__(self, symbol: str, current_timeframe: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.symbol = symbol
        self.current_timeframe = current_timeframe

        # Add buttons for each timeframe
        timeframes = ['1w', '2w', '1m', '3m', '6m', '1y']
        for tf in timeframes:
            button = discord.ui.Button(
                label=tf.upper(),
                style=discord.ButtonStyle.primary if tf == current_timeframe else discord.ButtonStyle.secondary,
                custom_id=f"chart_{tf}"
            )
            button.callback = self.make_callback(tf)
            self.add_item(button)

    def make_callback(self, timeframe: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()

            # Generate new chart
            buf = await generate_stock_chart(self.symbol, timeframe, ALPHAVANTAGE_API_KEY)

            if buf is None:
                await interaction.followup.send(
                    f"Could not generate chart for **{self.symbol}**. Try again later.",
                    ephemeral=True
                )
                return

            # Create new view with updated current timeframe
            new_view = ChartTimeframeView(self.symbol, timeframe)

            file = discord.File(buf, filename=f"{self.symbol}_{timeframe}_chart.png")
            await interaction.message.edit(attachments=[file], view=new_view)

        return callback


# ============== Ashes of Creation (Ashes Codex) Feature ==============

# Cache for AOC data to avoid repeated API calls
_aoc_cache = {
    'items': None,
    'mobs': None,
    'abilities': None,
    'npcs': None,
    'last_fetch': None
}
AOC_CACHE_DURATION = 3600  # 1 hour cache


def _fetch_aoc_page(url: str):
    """Synchronous function to fetch a single AOC API page"""
    return curl_requests.get(
        url,
        impersonate="chrome120",
        timeout=30,
        headers={
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    )


async def fetch_aoc_data(endpoint: str) -> list:
    """Fetch data from Ashes Codex API using curl_cffi for TLS impersonation"""

    all_data = []
    page = 1
    max_pages = 200  # Safety limit
    total_pages = None

    while page <= max_pages:
        url = f"https://api.ashescodex.com/{endpoint}?page={page}"

        try:
            # Use curl_cffi with Chrome impersonation (same as phone lookup)
            response = await bot.loop.run_in_executor(
                None,
                _fetch_aoc_page,
                url
            )

            if response.status_code != 200:
                print(f"AOC API returned status {response.status_code} for {endpoint}")
                break

            response_data = response.json()

            # Check for meta pagination info
            if isinstance(response_data, dict):
                meta = response_data.get('meta', {})
                if meta and total_pages is None:
                    total_pages = meta.get('totalPages') or meta.get('last_page') or meta.get('pages')
                    print(f"AOC API {endpoint}: total_pages from meta = {total_pages}")

                # Extract the data array
                data = response_data.get('data', [])
            else:
                data = response_data

            print(f"AOC API {endpoint} page {page}/{total_pages or '?'}: got {len(data) if isinstance(data, list) else 0} items")

            if not data or not isinstance(data, list) or len(data) == 0:
                print(f"  No more data, stopping")
                break

            # Filter to only include dict items
            valid_items = [item for item in data if isinstance(item, dict)]
            all_data.extend(valid_items)

            # Check if we've fetched all pages
            if total_pages and page >= total_pages:
                print(f"  Reached last page ({total_pages})")
                break

            page += 1

        except Exception as e:
            print(f"Error fetching AOC {endpoint} page {page}: {e}")
            import traceback
            traceback.print_exc()
            break

    print(f"AOC API {endpoint}: total items fetched = {len(all_data)}")
    return all_data


async def get_aoc_items() -> list:
    """Get cached or fresh items data"""
    global _aoc_cache

    now = time.time()
    if _aoc_cache['items'] and _aoc_cache['last_fetch']:
        if now - _aoc_cache['last_fetch'] < AOC_CACHE_DURATION:
            return _aoc_cache['items']

    items = await fetch_aoc_data('items')
    if items:
        _aoc_cache['items'] = items
        _aoc_cache['last_fetch'] = now

    return items or []


async def get_aoc_mobs() -> list:
    """Get cached or fresh mobs data"""
    global _aoc_cache

    now = time.time()
    if _aoc_cache['mobs'] and _aoc_cache['last_fetch']:
        if now - _aoc_cache['last_fetch'] < AOC_CACHE_DURATION:
            return _aoc_cache['mobs']

    mobs = await fetch_aoc_data('mobs')
    if mobs:
        _aoc_cache['mobs'] = mobs

    return mobs or []


def get_item_name(item: dict) -> str:
    """Get item name from various possible field names"""
    if not isinstance(item, dict):
        return str(item)
    return item.get('itemName') or item.get('name') or item.get('displayName', 'Unknown')


def search_aoc_items(items: list, query: str, limit: int = 5) -> list:
    """Search items by name, return top matches"""
    query_lower = query.lower()

    # Filter to only dict items
    valid_items = [i for i in items if isinstance(i, dict)]

    # Exact match first
    exact = [i for i in valid_items if get_item_name(i).lower() == query_lower]
    if exact:
        return exact[:limit]

    # Starts with query
    starts_with = [i for i in valid_items if get_item_name(i).lower().startswith(query_lower)]
    if starts_with:
        return starts_with[:limit]

    # Contains query
    contains = [i for i in valid_items if query_lower in get_item_name(i).lower()]
    return contains[:limit]


def format_aoc_item_embed(item: dict) -> discord.Embed:
    """Format an AOC item into a Discord embed"""
    if not isinstance(item, dict):
        return discord.Embed(title="Error", description="Invalid item data", color=discord.Color.red())

    # Get name from various possible fields
    name = get_item_name(item)
    description = item.get('description') or item.get('flavorText', '')

    # Clean HTML from description
    if description:
        description = re.sub(r'<[^>]+>', '', str(description))
        if len(description) > 500:
            description = description[:497] + "..."
    else:
        description = ""

    # Color based on rarity
    rarity_max = str(item.get('rarityMax', '') or item.get('grade', '')).lower()
    color_map = {
        'legendary': discord.Color.gold(),
        'epic': discord.Color.purple(),
        'rare': discord.Color.blue(),
        'uncommon': discord.Color.green(),
        'common': discord.Color.light_grey()
    }
    color = color_map.get(rarity_max, discord.Color.blue())

    embed = discord.Embed(
        title=f"⚔️ {name}",
        description=description if description else None,
        color=color
    )

    # Item subtype
    sub_type = item.get('subType', '')
    if sub_type:
        type_str = str(sub_type).split('.')[-1].replace('_', ' ').title()
        embed.add_field(name="Type", value=type_str, inline=True)

    # Level requirement
    level = item.get('level') or item.get('levelRequirement')
    if level:
        embed.add_field(name="Level", value=str(level), inline=True)

    # Rarity range
    rarity_min = item.get('rarityMin', '')
    rarity_max = item.get('rarityMax', '')
    if rarity_min and rarity_max:
        min_str = str(rarity_min).split('.')[-1].replace('_', ' ').title()
        max_str = str(rarity_max).split('.')[-1].replace('_', ' ').title()
        if min_str != max_str:
            embed.add_field(name="Rarity", value=f"{min_str} - {max_str}", inline=True)
        else:
            embed.add_field(name="Rarity", value=min_str, inline=True)
    elif rarity_max:
        max_str = str(rarity_max).split('.')[-1].replace('_', ' ').title()
        embed.add_field(name="Rarity", value=max_str, inline=True)

    # Equipment slots
    equip_slots = item.get('equipSlots', [])
    if equip_slots and isinstance(equip_slots, list):
        slots = [str(s).split('.')[-1].replace('_', ' ').title() for s in equip_slots[:3]]
        embed.add_field(name="Slot", value=', '.join(slots), inline=True)

    # Crafting info
    profession = item.get('professionTag') or item.get('requiredProfessionId')
    if profession:
        prof_name = str(profession).split('.')[-1].replace('_', ' ').title()
        embed.add_field(name="Crafting", value=prof_name, inline=True)

    # Dropped by - format nicely
    dropped_by = item.get('_droppedBy', [])
    if dropped_by and isinstance(dropped_by, list) and len(dropped_by) > 0:
        drop_names = []
        for d in dropped_by[:5]:
            if isinstance(d, dict):
                display_name = d.get('_displayName') or d.get('name') or d.get('_slug', '')
                level_range = d.get('_levelRange', '')
                if display_name:
                    if level_range and level_range != '?':
                        drop_names.append(f"{display_name} (Lv.{level_range})")
                    else:
                        drop_names.append(display_name)
            elif isinstance(d, str):
                drop_names.append(d)
        if drop_names:
            drops_text = '\n'.join(drop_names)
            if len(drops_text) > 1000:
                drops_text = drops_text[:997] + "..."
            embed.add_field(name="Dropped By", value=drops_text, inline=False)

    # Link to website
    slug = item.get('_slug') or item.get('slug', '')
    if slug:
        embed.url = f"https://ashescodex.com/item/{slug}"

    embed.set_footer(text="Ashes of Creation | ashescodex.com")

    return embed


def get_mob_name(mob: dict) -> str:
    """Get mob name from various possible field names"""
    if not isinstance(mob, dict):
        return str(mob)
    return mob.get('name') or mob.get('mobName') or mob.get('displayName', 'Unknown Creature')


def format_aoc_mob_embed(mob: dict) -> discord.Embed:
    """Format an AOC mob into a Discord embed"""
    if not isinstance(mob, dict):
        return discord.Embed(title="Error", description="Invalid mob data", color=discord.Color.red())

    name = get_mob_name(mob)
    description = mob.get('description', 'No description available.')

    # Clean HTML
    if description:
        description = re.sub(r'<[^>]+>', '', str(description))
        if len(description) > 500:
            description = description[:497] + "..."
    else:
        description = "No description available."

    embed = discord.Embed(
        title=f"👹 {name}",
        description=description,
        color=discord.Color.red()
    )

    # Level
    level = mob.get('level') or mob.get('levelRange') or mob.get('minLevel')
    if level:
        max_level = mob.get('maxLevel')
        if max_level and max_level != level:
            embed.add_field(name="Level", value=f"{level}-{max_level}", inline=True)
        else:
            embed.add_field(name="Level", value=str(level), inline=True)

    # Mob type
    mob_type = mob.get('type') or mob.get('creatureType') or mob.get('category')
    if mob_type:
        type_str = str(mob_type).split('.')[-1].replace('_', ' ').title()
        embed.add_field(name="Type", value=type_str, inline=True)

    # Location/Zone
    location = mob.get('location') or mob.get('zone') or mob.get('area')
    if location:
        embed.add_field(name="Location", value=str(location), inline=True)

    # Health if available
    health = mob.get('health') or mob.get('hp') or mob.get('baseHealth')
    if health:
        try:
            embed.add_field(name="Health", value=f"{int(health):,}", inline=True)
        except (ValueError, TypeError):
            embed.add_field(name="Health", value=str(health), inline=True)

    # Drops
    drops = mob.get('drops', []) or mob.get('_drops', []) or mob.get('loot', [])
    if drops and isinstance(drops, list):
        drop_names = []
        for d in drops[:5]:
            if isinstance(d, dict):
                drop_names.append(d.get('itemName') or d.get('name') or str(d))
            else:
                drop_names.append(str(d))
        if drop_names:
            embed.add_field(name="Drops", value=", ".join(drop_names), inline=False)

    embed.set_footer(text="Ashes of Creation | ashescodex.com")

    return embed


class AocSearchView(discord.ui.View):
    """View with buttons to select from multiple search results"""

    def __init__(self, results: list, result_type: str):
        super().__init__(timeout=120)
        self.results = results
        self.result_type = result_type

        # Add a button for each result (max 5)
        for i, item in enumerate(results[:5]):
            if result_type == 'item':
                name = get_item_name(item) if isinstance(item, dict) else str(item)
            else:
                name = get_mob_name(item) if isinstance(item, dict) else str(item)

            if len(name) > 50:
                name = name[:47] + "..."

            button = discord.ui.Button(
                label=f"{i+1}. {name}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"aoc_select_{i}",
                row=i // 3
            )
            button.callback = self.make_callback(i)
            self.add_item(button)

    def make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()

            item = self.results[index]
            if self.result_type == 'item':
                embed = format_aoc_item_embed(item)
            else:
                embed = format_aoc_mob_embed(item)

            await interaction.followup.send(embed=embed)
            self.stop()

        return callback


@bot.command(name='aoc')
async def aoc(ctx, category: str = None, *, query: str = None):
    """Look up Ashes of Creation data. Usage: !aoc <item|mob|search> <name>

    Examples:
    !aoc item sword
    !aoc mob wolf
    !aoc search health potion
    """
    if not category:
        embed = discord.Embed(
            title="⚔️ Ashes of Creation Lookup",
            description="Look up items, mobs, and more from Ashes of Creation!",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Commands",
            value=(
                "`!aoc item <name>` - Search for items\n"
                "`!aoc mob <name>` - Search for mobs/creatures\n"
                "`!aoc search <query>` - Search all categories"
            ),
            inline=False
        )
        embed.add_field(
            name="Examples",
            value=(
                "`!aoc item sword`\n"
                "`!aoc mob wolf`\n"
                "`!aoc search healing potion`"
            ),
            inline=False
        )
        embed.set_footer(text="Data from ashescodex.com")
        return await ctx.send(embed=embed)

    category = category.lower()

    if category not in ['item', 'items', 'mob', 'mobs', 'creature', 'search']:
        return await ctx.send("Invalid category! Use: `item`, `mob`, or `search`")

    if not query:
        return await ctx.send(f"Usage: `!aoc {category} <name>`")

    async with ctx.typing():
        try:
            if category in ['item', 'items', 'search']:
                items = await get_aoc_items()

                if not items:
                    return await ctx.send("Could not fetch item data. The API may be unavailable.")

                # Debug: check what we got
                print(f"Got {len(items)} items, first item type: {type(items[0]).__name__ if items else 'N/A'}")

                results = search_aoc_items(items, query)

                if not results:
                    return await ctx.send(f"No items found matching **{query}**")

                # Debug: check results
                print(f"Found {len(results)} results, first result type: {type(results[0]).__name__ if results else 'N/A'}")

                if len(results) == 1:
                    embed = format_aoc_item_embed(results[0])
                    await ctx.send(embed=embed)
                else:
                    # Multiple results - show selection
                    embed = discord.Embed(
                        title=f"🔍 Found {len(results)} items matching '{query}'",
                        description="Select an item to view details:",
                        color=discord.Color.blue()
                    )

                    for i, item in enumerate(results[:5]):
                        try:
                            name = get_item_name(item)
                            type_tags = item.get('itemTypeTags', []) if isinstance(item, dict) else []
                            if type_tags and isinstance(type_tags, list) and len(type_tags) > 0:
                                first_tag = type_tags[0]
                                type_str = str(first_tag).split('.')[-1].replace('_', ' ').title() if isinstance(first_tag, str) else 'Item'
                            else:
                                type_str = 'Item'
                            grade = (item.get('grade', '') or item.get('rarity', '')) if isinstance(item, dict) else ''
                            embed.add_field(
                                name=f"{i+1}. {name}",
                                value=f"{type_str} {f'({grade})' if grade else ''}",
                                inline=False
                            )
                        except Exception as item_err:
                            print(f"Error processing item {i}: {item_err}, item type: {type(item)}")
                            embed.add_field(name=f"{i+1}. Item", value="Error loading", inline=False)

                    view = AocSearchView(results, 'item')
                    await ctx.send(embed=embed, view=view)

            elif category in ['mob', 'mobs', 'creature']:
                mobs = await get_aoc_mobs()

                if not mobs:
                    return await ctx.send("Could not fetch mob data. The API may be unavailable.")

                # Search mobs - filter to valid dicts first
                query_lower = query.lower()
                valid_mobs = [m for m in mobs if isinstance(m, dict)]
                results = [m for m in valid_mobs if query_lower in get_mob_name(m).lower()][:5]

                if not results:
                    return await ctx.send(f"No mobs found matching **{query}**")

                if len(results) == 1:
                    embed = format_aoc_mob_embed(results[0])
                    await ctx.send(embed=embed)
                else:
                    embed = discord.Embed(
                        title=f"🔍 Found {len(results)} mobs matching '{query}'",
                        description="Select a mob to view details:",
                        color=discord.Color.red()
                    )

                    for i, mob in enumerate(results[:5]):
                        name = get_mob_name(mob)
                        level = mob.get('level') or mob.get('minLevel') or '?'
                        mob_type = mob.get('type') or mob.get('category') or 'Creature'
                        if isinstance(mob_type, str):
                            mob_type = mob_type.split('.')[-1].replace('_', ' ').title()
                        embed.add_field(
                            name=f"{i+1}. {name}",
                            value=f"Level {level} {mob_type}",
                            inline=False
                        )

                    view = AocSearchView(results, 'mob')
                    await ctx.send(embed=embed, view=view)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"AOC ERROR:\n{tb}")
            # Show last part of traceback in Discord
            await ctx.send(f"Error searching: `{e}`\n```py\n{tb[-800:]}\n```")


@bot.command(name='aoc_debug')
@commands.is_owner()
async def aoc_debug(ctx, *, search_term: str = None):
    """Debug AOC API response (owner only). Usage: !aoc_debug [search term]"""
    global _aoc_cache

    # Clear cache first
    _aoc_cache = {'items': None, 'mobs': None, 'abilities': None, 'npcs': None, 'last_fetch': None}

    await ctx.send("Cache cleared. Fetching ALL items from API (this may take a moment)...")

    async with ctx.typing():
        try:
            # Fetch all items using the regular function
            items = await get_aoc_items()

            info = f"**Total items fetched:** {len(items)}\n"

            if items:
                # Show some sample item names
                sample_names = [get_item_name(i) for i in items[:5]]
                info += f"**Sample items:** {', '.join(sample_names)}\n"

                # If search term provided, test the search
                if search_term:
                    results = search_aoc_items(items, search_term)
                    info += f"\n**Search for '{search_term}':** {len(results)} results\n"
                    if results:
                        for r in results[:5]:
                            info += f"  - {get_item_name(r)}\n"
                    else:
                        # Show items that contain parts of the search
                        partial = [i for i in items if search_term.lower()[:3] in get_item_name(i).lower()][:5]
                        if partial:
                            info += f"**Partial matches ({search_term[:3]}):** "
                            info += ", ".join([get_item_name(i) for i in partial]) + "\n"
            else:
                info += "**No items fetched!**\n"

            await ctx.send(info)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            await ctx.send(f"Error: {e}\n```\n{tb[-500:]}\n```")


@bot.command(name='aoc_item', aliases=['item'])
async def aoc_item(ctx, *, query: str = None):
    """Shortcut for !aoc item <name>"""
    if not query:
        return await ctx.send("Usage: `!item <name>` (e.g. `!item sword`)")
    await aoc(ctx, 'item', query=query)


@bot.command(name='aoc_mob', aliases=['mob', 'creature'])
async def aoc_mob(ctx, *, query: str = None):
    """Shortcut for !aoc mob <name>"""
    if not query:
        return await ctx.send("Usage: `!mob <name>` (e.g. `!mob wolf`)")
    await aoc(ctx, 'mob', query=query)


@bot.command(name='chart', aliases=['c'])
async def chart(ctx, symbol: str = None, timeframe: str = '1m'):
    """Get stock chart with hollow candles. Usage: !chart <symbol> [timeframe]
    Timeframes: 1w, 2w, 1m, 3m, 6m, 1y"""

    if not ALPHAVANTAGE_API_KEY:
        return await ctx.send("Alpha Vantage API key not configured!")

    if not symbol:
        return await ctx.send("Usage: `!chart <symbol> [timeframe]`\nTimeframes: 1w, 2w, 1m, 3m, 6m, 1y")

    symbol = symbol.upper().strip()
    timeframe = timeframe.lower().strip()

    valid_timeframes = ['1w', '2w', '1m', '3m', '6m', '1y']
    if timeframe not in valid_timeframes:
        return await ctx.send(f"Invalid timeframe! Use: {', '.join(valid_timeframes)}")

    async with ctx.typing():
        try:
            buf = await generate_stock_chart(symbol, timeframe, ALPHAVANTAGE_API_KEY)

            if buf is None:
                return await ctx.send(f"Could not generate chart for **{symbol}**. Check symbol or try again later.")

            # Create view with timeframe buttons
            view = ChartTimeframeView(symbol, timeframe)
            file = discord.File(buf, filename=f"{symbol}_{timeframe}_chart.png")
            await ctx.send(file=file, view=view)

        except Exception as e:
            await ctx.send(f"Error generating chart: {e}")


# Run the bot
if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("Error: DISCORD_TOKEN not found in environment variables!")
        print("Please create a .env file with your Discord bot token.")
    else:
        bot.run(token)
