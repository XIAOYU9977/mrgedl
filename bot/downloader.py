import os
import time
import asyncio
from pathlib import Path
from pyrogram import Client
from bot.progress import calculate_progress, get_progress_text

class Downloader:
    def __init__(self, client: Client):
        self.client = client

    async def download_video(self, message, file_path: Path, progress_callback=None):
        """
        Download a video from a Telegram message with progress tracking and throttling.
        """
        start_time = time.time()
        last_update = 0
        
        async def progress_wrapper(current, total):
            nonlocal last_update
            now = time.time()
            # Throttling to 2 seconds to improve speed and reduce overhead
            if progress_callback and (now - last_update > 2 or current == total):
                last_update = now
                pct = calculate_progress(current, total)
                text = await get_progress_text(current, total, start_time, "Downloading Video")
                await progress_callback(current, total, pct, text)

        try:
            await self.client.download_media(
                message,
                file_name=str(file_path),
                progress=progress_wrapper
            )
            return True
        except Exception as e:
            raise e
