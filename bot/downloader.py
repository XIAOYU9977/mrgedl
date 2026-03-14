import asyncio
import os
import time
import logging
from asyncio import subprocess
from bot.config import Config
from bot.progress import progress_for_pyrogram

logger = logging.getLogger(__name__)

async def download_tg(client, message, path):
    """Download file from Telegram message."""
    start_time = time.time()
    video = message.video or message.document
    if not video:
        raise Exception("Pesan tidak berisi file video/dokumen.")
        
    file_name = video.file_name or f"file_{message.id}.mkv"
    file_path = os.path.join(path, file_name)
    
    logger.info(f"Downloading TG file: {file_name}")
    
    await client.download_media(
        message=message,
        file_name=file_path,
        progress=progress_for_pyrogram,
        progress_args=("Downloading from Telegram...", message, start_time)
    )
    return file_path

async def download_aria2(url, path, filename, message):
    """Download file using aria2c."""
    cmd = [
        Config.ARIA2_PATH,
        "-x16", "-s16", "-k1M",
        "-d", path,
        "-o", filename,
        url
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    await message.edit(f"Downloading via aria2: {filename}")
    
    stdout, stderr = await process.communicate()
    
    if process.returncode == 0:
        return os.path.join(path, filename)
    else:
        raise Exception(f"Aria2 download failed: {stderr.decode()}")
