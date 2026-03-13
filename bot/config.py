import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH", "")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    
    # Storage
    TEMP_DIR = os.path.join(os.getcwd(), "bot", "temp")
    
    # Binaries (Assume in PATH if not specified)
    FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")
    ARIA2_PATH = os.getenv("ARIA2_PATH", "aria2c")
    
    # Concurrent tasks
    MAX_CONCURRENT_DOWNLOADS = 3
    MAX_CONCURRENT_MERGES = 2
