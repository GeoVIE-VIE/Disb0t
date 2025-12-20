import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import aiohttp
import random
import re
import os
from pathlib import Path
from dotenv import load_dotenv
from collections import deque

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


async def get_pubg_player_id(username: str, platform: str) -> str:
    """Get player ID from username"""
    data = await pubg_api_request(f"players?filter[playerNames]={username}", platform)

    if 'error' in data:
        return None

    if 'data' in data and len(data['data']) > 0:
        return data['data'][0]['id']
    return None


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

        # Scoring system
        score = 0
        if kd >= 2.0:
            score += 3
        elif kd >= 1.0:
            score += 2
        elif kd >= 0.5:
            score += 1

        if avg_damage >= 300:
            score += 3
        elif avg_damage >= 150:
            score += 2
        elif avg_damage >= 100:
            score += 1

        if win_rate >= 10:
            score += 3
        elif win_rate >= 5:
            score += 2
        elif win_rate >= 2:
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
        player_id = await get_pubg_player_id(username, platform)

        if not player_id:
            return await ctx.send(f"Player **{username}** not found on **{platform}**!")

        # Get season stats
        stats_data = await get_pubg_season_stats(player_id, platform)

        # Format and send
        embed = format_pubg_stats(stats_data, username, platform)
        await ctx.send(embed=embed)


# Run the bot
if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("Error: DISCORD_TOKEN not found in environment variables!")
        print("Please create a .env file with your Discord bot token.")
    else:
        bot.run(token)
