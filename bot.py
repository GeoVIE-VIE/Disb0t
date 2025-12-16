import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
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


# Run the bot
if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("Error: DISCORD_TOKEN not found in environment variables!")
        print("Please create a .env file with your Discord bot token.")
    else:
        bot.run(token)
