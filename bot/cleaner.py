import asyncio
import os
import time
import shutil
from bot.config import Config

async def auto_cleaner():
    """Background task to clean up old temp files every 5 minutes."""
    while True:
        try:
            now = time.time()
            if os.path.exists(Config.TEMP_DIR):
                for user_folder in os.listdir(Config.TEMP_DIR):
                    folder_path = os.path.join(Config.TEMP_DIR, user_folder)
                    if os.path.isdir(folder_path):
                        # If folder hasn't been modified for 1 hour, delete it
                        if now - os.path.getmtime(folder_path) > 3600:
                            shutil.rmtree(folder_path)
        except Exception as e:
            print(f"Cleaner error: {e}")
        
        await asyncio.sleep(300) # 5 minutes

def delete_user_data(user_id):
    path = os.path.join(Config.TEMP_DIR, str(user_id))
    if os.path.exists(path):
        shutil.rmtree(path)
