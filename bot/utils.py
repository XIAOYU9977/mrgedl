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
    import json
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
        subs = [s for s in streams if s['codec_type'] == 'subtitle']
        
        # Details
        res = f"{v_stream.get('width', 'N/A')}x{v_stream.get('height', 'N/A')}"
        v_codec = v_stream.get('codec_name', 'N/A').upper()
        a_codec = a_stream.get('codec_name', 'N/A').upper()
        
        # Bitrates
        v_bitrate = int(v_stream.get('bit_rate', 0)) or int(format_info.get('bit_rate', 0))
        a_bitrate = int(a_stream.get('bit_rate', 0))
        v_bitrate_str = f"{v_bitrate // 1000} kbps" if v_bitrate else "N/A"
        a_bitrate_str = f"{a_bitrate // 1000} kbps" if a_bitrate else "N/A"
        
        # Frame rate
        fps_base = v_stream.get('r_frame_rate', '0/0').split('/')
        fps = round(int(fps_base[0]) / int(fps_base[1]), 2) if len(fps_base) == 2 and int(fps_base[1]) != 0 else "N/A"
        
        size = format_size(int(format_info.get('size', 0)))
        dur = format_duration(float(format_info.get('duration', 0)))
        
        info = (
            f"📊 **Media Info Details**\n\n"
            f"📁 **File:** `{file_path.name}`\n"
            f"⚖️ **Size:** {size}\n"
            f"⏳ **Duration:** {dur}\n"
            f"📏 **Resolution:** {res}\n"
            f"🎥 **Video Codec:** {v_codec}\n"
            f"🎞 **Frame Rate:** {fps} FPS\n"
            f"📈 **Video Bitrate:** {v_bitrate_str}\n"
            f"🔊 **Audio Codec:** {a_codec}\n"
            f"🎵 **Audio Bitrate:** {a_bitrate_str}\n"
            f"💬 **Subtitle Tracks:** {len(subs)}\n"
        )
        return info
    except Exception as e:
        return f"❌ Error getting MediaInfo: {str(e)}"
