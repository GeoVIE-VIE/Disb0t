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
`!phone_cookie <value>` - Set datadome cookie (owner)
`!phone_clear_cookie` - Clear saved cookie (owner)
"""
    embed.add_field(name="📞 Phone Lookup", value=phone_cmds.strip(), inline=False)

    # Stock commands
    stock_cmds = """
`!stock <symbol>` / `!st` - Get stock quote
`!chart <symbol> [timeframe]` / `!c` - Stock chart
Timeframes: 1w, 2w, 1m, 3m, 6m, 1y
"""
    embed.add_field(name="📈 Stocks", value=stock_cmds.strip(), inline=False)

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
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# Cookie file path for datadome persistence
COOKIE_FILE = Path(__file__).parent / '.datadome_cookie'


def load_datadome_cookie() -> str:
    """Load saved datadome cookie from file"""
    if COOKIE_FILE.exists():
        try:
            return COOKIE_FILE.read_text().strip()
        except:
            pass
    return None


def save_datadome_cookie(cookie_value: str):
    """Save datadome cookie to file"""
    try:
        COOKIE_FILE.write_text(cookie_value)
    except:
        pass


# Realistic browser fingerprints to rotate through
BROWSER_FINGERPRINTS = [
    {
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'viewport': {'width': 1920, 'height': 1080},
        'locale': 'en-US',
        'timezone_id': 'America/Chicago',
        'platform': 'Win32',
    },
    {
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'viewport': {'width': 1536, 'height': 864},
        'locale': 'en-US',
        'timezone_id': 'America/New_York',
        'platform': 'Win32',
    },
    {
        'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'viewport': {'width': 1440, 'height': 900},
        'locale': 'en-US',
        'timezone_id': 'America/Los_Angeles',
        'platform': 'MacIntel',
    },
    {
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'viewport': {'width': 1920, 'height': 1080},
        'locale': 'en-US',
        'timezone_id': 'America/Denver',
        'platform': 'Win32',
    },
]


def human_delay(min_ms: int = 500, max_ms: int = 2000):
    """Random human-like delay"""
    import random
    time.sleep(random.randint(min_ms, max_ms) / 1000)


def bezier_curve(start: tuple, end: tuple, control1: tuple, control2: tuple, steps: int = 50) -> list:
    """Generate points along a bezier curve for realistic mouse movement"""
    points = []
    for i in range(steps + 1):
        t = i / steps
        # Cubic bezier formula
        x = (1-t)**3 * start[0] + 3*(1-t)**2*t * control1[0] + 3*(1-t)*t**2 * control2[0] + t**3 * end[0]
        y = (1-t)**3 * start[1] + 3*(1-t)**2*t * control1[1] + 3*(1-t)*t**2 * control2[1] + t**3 * end[1]
        points.append((int(x), int(y)))
    return points


def human_mouse_move(page, start_x: int, start_y: int, end_x: int, end_y: int):
    """Move mouse along a natural bezier curve path"""
    import random

    # Generate random control points for natural curve
    mid_x = (start_x + end_x) / 2
    mid_y = (start_y + end_y) / 2

    # Add randomness to control points
    ctrl1 = (
        mid_x + random.randint(-100, 100),
        start_y + random.randint(-50, 50)
    )
    ctrl2 = (
        mid_x + random.randint(-100, 100),
        end_y + random.randint(-50, 50)
    )

    points = bezier_curve((start_x, start_y), (end_x, end_y), ctrl1, ctrl2, steps=random.randint(20, 40))

    # Move through points with variable speed
    for i, (x, y) in enumerate(points):
        page.mouse.move(x, y)
        # Variable delay - slower at start/end, faster in middle
        if i < 5 or i > len(points) - 5:
            time.sleep(random.uniform(0.01, 0.03))
        else:
            time.sleep(random.uniform(0.002, 0.01))


def human_type(page, selector: str, text: str):
    """Type text with human-like delays between keystrokes"""
    import random

    element = page.locator(selector)
    element.click()
    human_delay(100, 300)

    for char in text:
        page.keyboard.type(char)
        # Variable delay - longer for difficult keys
        if char in '!@#$%^&*()':
            time.sleep(random.uniform(0.15, 0.3))
        else:
            time.sleep(random.uniform(0.05, 0.15))


def random_scroll(page):
    """Perform random scrolling like a human reading"""
    import random

    for _ in range(random.randint(2, 4)):
        # Scroll down
        scroll_amount = random.randint(100, 400)
        page.mouse.wheel(0, scroll_amount)
        human_delay(300, 800)

        # Sometimes scroll up a bit
        if random.random() < 0.3:
            page.mouse.wheel(0, -random.randint(50, 150))
            human_delay(200, 500)


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
    """Fetch phone data using ultra-realistic human simulation"""
    import random

    # Extract phone number from URL
    phone_number = url.split('/')[-1]

    # Pick a random fingerprint
    fingerprint = random.choice(BROWSER_FINGERPRINTS)

    try:
        with sync_playwright() as p:
            # Launch with anti-detection flags
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--disable-infobars',
                    '--disable-background-networking',
                    '--disable-breakpad',
                    '--disable-component-update',
                    '--disable-domain-reliability',
                    '--disable-features=AudioServiceOutOfProcess,IsolateOrigins,site-per-process',
                    '--disable-hang-monitor',
                    '--disable-ipc-flooding-protection',
                    '--disable-popup-blocking',
                    '--disable-prompt-on-repost',
                    '--disable-renderer-backgrounding',
                    '--disable-sync',
                    '--metrics-recording-only',
                    '--no-first-run',
                    '--safebrowsing-disable-auto-update',
                    '--password-store=basic',
                    '--use-mock-keychain',
                    '--window-size=1920,1080',
                ]
            )

            # Create realistic browser context
            context = browser.new_context(
                user_agent=fingerprint['user_agent'],
                viewport=fingerprint['viewport'],
                locale=fingerprint['locale'],
                timezone_id=fingerprint['timezone_id'],
                geolocation={'latitude': 37.7749, 'longitude': -122.4194},
                permissions=['geolocation'],
                color_scheme='light',
                device_scale_factor=1,
                has_touch=False,
                is_mobile=False,
                java_script_enabled=True,
                extra_http_headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, https',
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
            )

            page = context.new_page()

            # Apply stealth patches using new Stealth API
            stealth = Stealth(
                navigator_platform_override=fingerprint['platform'],
                webgl_vendor_override='Google Inc. (NVIDIA)',
                webgl_renderer_override='ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)'
            )
            stealth.apply_stealth_sync(page)

            # Load saved datadome cookie if available
            saved_cookie = load_datadome_cookie()
            if saved_cookie:
                context.add_cookies([{
                    'name': 'datadome',
                    'value': saved_cookie,
                    'domain': '.usphonebook.com',
                    'path': '/'
                }])
                print(f"Loaded saved datadome cookie")

            # Additional stealth overrides
            page.add_init_script("""
                Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
                if (navigator.connection) {
                    Object.defineProperty(navigator.connection, 'effectiveType', { get: () => '4g' });
                }
            """)

            # === PHASE 1: Visit homepage first to establish session ===
            print("Phase 1: Visiting homepage...")
            human_delay(500, 1000)

            page.goto('https://www.usphonebook.com/', wait_until='networkidle', timeout=45000)
            human_delay(2000, 4000)

            # Check for CAPTCHA on homepage
            content = page.content()
            if 'geo.captcha-delivery.com' in content or 'datadome' in content.lower():
                page.screenshot(path='/tmp/phone_debug.png')
                with open('/tmp/phone_debug.html', 'w') as f:
                    f.write(content)
                title = page.title()
                browser.close()
                return {'captcha_detected': True, 'page_title': title}

            # === PHASE 2: Natural mouse movements on homepage ===
            print("Phase 2: Simulating human browsing...")

            # Move mouse around naturally
            viewport = fingerprint['viewport']
            current_x, current_y = viewport['width'] // 2, viewport['height'] // 2

            # Random mouse movements
            for _ in range(random.randint(2, 4)):
                target_x = random.randint(100, viewport['width'] - 100)
                target_y = random.randint(100, viewport['height'] - 200)
                human_mouse_move(page, current_x, current_y, target_x, target_y)
                current_x, current_y = target_x, target_y
                human_delay(300, 700)

            # Random scrolling
            random_scroll(page)
            human_delay(1000, 2000)

            # === PHASE 3: Find and use the search box ===
            print("Phase 3: Using search form...")

            # Try to find search input
            search_selectors = [
                'input[name="q"]',
                'input[type="search"]',
                'input[placeholder*="phone"]',
                'input[placeholder*="search"]',
                '#search',
                '.search-input',
                'input.form-control',
            ]

            search_input = None
            for selector in search_selectors:
                try:
                    el = page.locator(selector).first
                    if el.is_visible():
                        search_input = el
                        break
                except:
                    continue

            if search_input:
                # Move mouse to search box with bezier curve
                box = search_input.bounding_box()
                if box:
                    target_x = int(box['x'] + box['width'] / 2)
                    target_y = int(box['y'] + box['height'] / 2)
                    human_mouse_move(page, current_x, current_y, target_x, target_y)
                    human_delay(200, 400)

                    # Click on search box
                    search_input.click()
                    human_delay(300, 600)

                    # Type phone number with human-like delays
                    for char in phone_number:
                        page.keyboard.type(char)
                        time.sleep(random.uniform(0.05, 0.15))

                    human_delay(500, 1000)

                    # Press Enter
                    page.keyboard.press('Enter')
                    human_delay(2000, 4000)

                    # Wait for results
                    page.wait_for_load_state('networkidle', timeout=30000)
            else:
                # Fallback: direct navigation
                print("Search box not found, using direct URL...")
                page.goto(url, wait_until='networkidle', timeout=45000)

            # === PHASE 4: Get results ===
            human_delay(1500, 3000)

            # More natural behavior on results page
            random_scroll(page)

            # Get content
            content = page.content()

            # Save debug files
            page.screenshot(path='/tmp/phone_debug.png')
            with open('/tmp/phone_debug.html', 'w') as f:
                f.write(content)

            result = {}

            # Check if we hit CAPTCHA
            if 'geo.captcha-delivery.com' in content or 'datadome' in content.lower():
                result['captcha_detected'] = True
                result['page_title'] = page.title()
                browser.close()
                return result

            # Get page title before any potential issues
            page_title = page.title()

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

            # If no gResults, try DOM scraping
            if not result.get('raw_json'):
                try:
                    name_el = page.query_selector('h2 a[href*="/"], .ls_contacts-name')
                    if name_el:
                        result['name'] = name_el.inner_text().strip()
                except:
                    pass

                if not result.get('name'):
                    name_match = re.search(r'class="[^"]*name[^"]*"[^>]*>([^<]+)<', content, re.IGNORECASE)
                    if name_match:
                        result['name'] = name_match.group(1).strip()

            result['page_title'] = page_title
            browser.close()
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


class CookieInputModal(discord.ui.Modal, title="Paste DataDome Cookie"):
    """Modal for entering the datadome cookie"""

    cookie = discord.ui.TextInput(
        label="DataDome Cookie Value",
        placeholder="Paste the 'datadome' cookie value here...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

    def __init__(self, phone_number: str, original_ctx):
        super().__init__()
        self.phone_number = phone_number
        self.original_ctx = original_ctx

    async def on_submit(self, interaction: discord.Interaction):
        # Save the cookie
        cookie_value = self.cookie.value.strip()
        save_datadome_cookie(cookie_value)

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
                    f"4. Find the `datadome` cookie and copy its value\n"
                    f"5. Click **I Solved It - Paste Cookie** and enter the value\n\n"
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
    """Set the datadome cookie for phone lookups (owner only). Usage: !phone_cookie <value>"""
    if not cookie_value:
        # Check if cookie exists
        current = load_datadome_cookie()
        if current:
            return await ctx.send(f"Cookie is set (length: {len(current)} chars)")
        else:
            return await ctx.send("No cookie set. Usage: `!phone_cookie <value>`")

    # Save the cookie
    save_datadome_cookie(cookie_value.strip())
    await ctx.send(f"Cookie saved! ({len(cookie_value)} chars)")


@bot.command(name='phone_clear_cookie')
@commands.is_owner()
async def phone_clear_cookie(ctx):
    """Clear the saved datadome cookie (owner only)"""
    if COOKIE_FILE.exists():
        COOKIE_FILE.unlink()
        await ctx.send("Cookie cleared!")
    else:
        await ctx.send("No cookie to clear.")


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
