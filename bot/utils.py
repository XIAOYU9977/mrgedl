import logging
import sys
import psutil
import shutil
from pathlib import Path

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("bot.log", encoding='utf-8')
        ]
    )
    return logging.getLogger("MergeBot")

def format_size(size_bytes):
    if size_bytes == 0: return "0B"
    units = ("B", "KB", "MB", "GB", "TB")
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {units[i]}"

def format_duration(seconds):
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def get_available_ram_gb():
    return psutil.virtual_memory().available / (1024**3)

def get_disk_free_gb(path):
    return shutil.disk_usage(path).free / (1024**3)

async def get_mediainfo(file_path: Path) -> str:
    """Get technical info of a video file."""
    import asyncio
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', str(file_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout.decode())
        
        format_info = data.get('format', {})
        streams = data.get('streams', [])
        
        v_stream = next((s for s in streams if s['codec_type'] == 'video'), {})
        a_stream = next((s for s in streams if s['codec_type'] == 'audio'), {})
        
        res = f"{v_stream.get('width', 'N/A')}x{v_stream.get('height', 'N/A')}"
        v_codec = v_stream.get('codec_name', 'N/A')
        a_codec = a_stream.get('codec_name', 'N/A')
        size = format_size(int(format_info.get('size', 0)))
        dur = format_duration(float(format_info.get('duration', 0)))
        
        info = (
            f"📊 **Media Info**\n\n"
            f"📁 **File:** `{file_path.name}`\n"
            f"🎬 **Format:** {format_info.get('format_long_name', 'N/A')}\n"
            f"📏 **Resolution:** {res}\n"
            f"📹 **Video:** {v_codec.upper()}\n"
            f"🎵 **Audio:** {a_codec.upper()}\n"
            f"⚖️ **Size:** {size}\n"
            f"⏳ **Duration:** {dur}"
        )
        return info
    except Exception as e:
        return f"❌ Error getting MediaInfo: {str(e)}"
