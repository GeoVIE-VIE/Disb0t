# Disb0t - Discord YouTube Music Bot

A Discord bot that plays YouTube videos in voice channels.

## Features

- Play YouTube videos by URL or search query
- Queue system for multiple songs
- Pause, resume, skip, and stop controls
- Volume control
- Loop mode
- Now playing and queue display

## Prerequisites

- Python 3.8+
- FFmpeg installed on your system
- A Discord bot token

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/Disb0t.git
   cd Disb0t
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Install FFmpeg:
   - **Ubuntu/Debian**: `sudo apt install ffmpeg`
   - **macOS**: `brew install ffmpeg`
   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

4. Create a `.env` file with your Discord bot token:
   ```bash
   cp .env.example .env
   # Edit .env and add your token
   ```

5. Run the bot:
   ```bash
   python bot.py
   ```

## Commands

| Command | Aliases | Description |
|---------|---------|-------------|
| `!play <url/search>` | `!p` | Play a YouTube video or search |
| `!skip` | `!s` | Skip the current song |
| `!stop` | - | Stop playing and clear queue |
| `!pause` | - | Pause the current song |
| `!resume` | `!r` | Resume playback |
| `!queue` | `!q` | Show the queue |
| `!nowplaying` | `!np` | Show current song |
| `!loop` | - | Toggle loop mode |
| `!volume <0-100>` | `!vol` | Set volume |
| `!clear` | - | Clear the queue |
| `!leave` | `!disconnect`, `!dc` | Leave voice channel |

## Getting a Discord Bot Token

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section and click "Add Bot"
4. Copy the token and add it to your `.env` file
5. Enable "Message Content Intent" under Privileged Gateway Intents
6. Go to OAuth2 > URL Generator, select "bot" and "applications.commands"
7. Select permissions: Send Messages, Connect, Speak, Use Voice Activity
8. Use the generated URL to invite the bot to your server

## License

MIT
