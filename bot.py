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


@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


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


# ============== Stock Feature (Alpha Vantage) ==============

ALPHAVANTAGE_API_KEY = os.getenv('ALPHAVANTAGE_API_KEY')


@bot.command(name='stock', aliases=['s', 'stonk'])
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
    timeframe_config = {
        '1d': ('TIME_SERIES_INTRADAY', 'Time Series (5min)', '5min', 78),      # 1 day = ~78 5-min candles
        '5d': ('TIME_SERIES_INTRADAY', 'Time Series (60min)', '60min', 40),    # 5 days
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


@bot.command(name='chart', aliases=['c'])
async def chart(ctx, symbol: str = None, timeframe: str = '1m'):
    """Get stock chart with hollow candles. Usage: !chart <symbol> [timeframe]
    Timeframes: 1d, 5d, 1m, 3m, 6m, 1y"""

    if not ALPHAVANTAGE_API_KEY:
        return await ctx.send("Alpha Vantage API key not configured!")

    if not symbol:
        return await ctx.send("Usage: `!chart <symbol> [timeframe]`\nTimeframes: 1d, 5d, 1m, 3m, 6m, 1y")

    symbol = symbol.upper().strip()
    timeframe = timeframe.lower().strip()

    valid_timeframes = ['1d', '5d', '1m', '3m', '6m', '1y']
    if timeframe not in valid_timeframes:
        return await ctx.send(f"Invalid timeframe! Use: {', '.join(valid_timeframes)}")

    async with ctx.typing():
        try:
            buf = await generate_stock_chart(symbol, timeframe, ALPHAVANTAGE_API_KEY)

            if buf is None:
                return await ctx.send(f"Could not generate chart for **{symbol}**. Check symbol or try again later.")

            file = discord.File(buf, filename=f"{symbol}_{timeframe}_chart.png")
            await ctx.send(file=file)

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
