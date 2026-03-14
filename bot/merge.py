import asyncio
import os
import re
import logging
import shutil
from asyncio import subprocess
from bot.config import Config
from bot.utils import get_safe_percentage, sort_episodes

logger = logging.getLogger(__name__)

# Global tracker for active merge processes
active_processes = {}

async def get_best_encoder():
    """
    Detects the best available H.264 encoder.
    """
    cmd = [Config.FFMPEG_PATH, "-encoders"]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        encoders_str = stdout.decode().lower()
        
        if "h264_nvenc" in encoders_str:
            return "h264_nvenc"
        elif "h264_qsv" in encoders_str:
            return "h264_qsv"
        elif "h264_amf" in encoders_str:
            return "h264_amf"
        else:
            return "libx264"
    except Exception as e:
        logger.warning(f"Error detecting encoders: {e}. Falling back to libx264")
        return "libx264"

async def merge_video_files(file_list, user_id, mode, message, settings=None):
    """
    Main function to merge video files using FFmpeg.
    """
    if not file_list:
        raise Exception("Daftar file kosong.")

    if settings is None:
        settings = {}

    temp_dir = os.path.join(Config.TEMP_DIR, str(user_id))
    output_filename = f"merged_{user_id}.mkv"
    output_path = os.path.join(temp_dir, output_filename)
    
    # Generate concat list
    list_file_path = os.path.join(temp_dir, "concat_list.txt")
    with open(list_file_path, "w", encoding="utf-8") as f:
        for file in file_list:
            abs_path = os.path.abspath(file).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")

    # Command construction
    cmd = [Config.FFMPEG_PATH, "-f", "concat", "-safe", "0", "-i", list_file_path]
    
    if mode == 1:
        logger.info(f"User {user_id}: Starting Softsub Merge (Stream Copy)")
        cmd += ["-c", "copy", "-y", output_path]
    else:
        logger.info(f"User {user_id}: Starting Hardsub Merge (Encoding Custom)")
        
        # Video Encoder
        v_enc = settings.get("video_encoder", "Default")
        if v_enc == "Default":
            v_enc = await get_best_encoder()
        cmd += ["-c:v", v_enc]
        
        # Video Bitrate
        v_bit = settings.get("video_bitrate", "Default")
        if v_bit != "Default":
            cmd += ["-b:v", v_bit]
            
        # CRF
        crf = settings.get("crf", "Default")
        if crf != "Default":
            cmd += ["-crf", crf]
            
        # Preset
        preset = settings.get("preset", "Default")
        if preset != "Default":
            cmd += ["-preset", preset.lower()]
            
        # Audio Encoder
        a_enc = settings.get("audio_encoder", "Default")
        if a_enc != "Default":
            cmd += ["-c:a", a_enc]
        else:
            cmd += ["-c:a", "copy"] # Default to copy if not specified
            
        # Audio Bitrate
        a_bit = settings.get("audio_bitrate", "Default")
        if a_bit != "Default" and a_enc != "Default":
            # Convert "128 kbps" to "128k"
            a_bit_clean = a_bit.lower().replace(" kbps", "k").replace(" ", "")
            cmd += ["-b:a", a_bit_clean]
            
        cmd += ["-y", output_path]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    
    # Store for cancellation
    active_processes[user_id] = process

    # Parsing patterns
    duration_pattern = re.compile(r"Duration: (\d+):(\d+):(\d+).(\d+)")
    time_pattern = re.compile(r"time=(\d+):(\d+):(\d+).(\d+)")
    
    total_seconds = 0
    
    try:
        while True:
            if not process.stdout:
                break
            line = await process.stdout.readline()
            if not line:
                break
            
            line_str = line.decode().strip()
            
            # Parse total duration
            if total_seconds == 0:
                dur_match = duration_pattern.search(line_str)
                if dur_match:
                    total_seconds = int(dur_match.group(1)) * 3600 + int(dur_match.group(2)) * 60 + int(dur_match.group(3))
                    logger.debug(f"Merge Duration: {total_seconds}s")
            
            # Parse current progress time
            time_match = time_pattern.search(line_str)
            if time_match:
                current_seconds = int(time_match.group(1)) * 3600 + int(time_match.group(2)) * 60 + int(time_match.group(3))
                
                percentage = get_safe_percentage(current_seconds, total_seconds)
                
                # Fallback if duration is unknown
                if total_seconds <= 0:
                    progress_text = f"Merging... (processed {current_seconds}s)"
                else:
                    bar = "█" * int(percentage / 10) + "░" * (10 - int(percentage / 10))
                    progress_text = f"**Merging Videos...**\n`[{bar}]` {percentage:.2f}%"
                
                try:
                    await message.edit(progress_text)
                except:
                    pass
    finally:
        if user_id in active_processes:
            del active_processes[user_id]
            
    await process.wait()
    
    if process.returncode == 0 and os.path.exists(output_path):
        logger.info(f"User {user_id}: Merge completed successfully.")
        return output_path
    else:
        if process.returncode == -9 or process.returncode == 15 or process.returncode == 1: 
             # Check if it was manually terminated
             logger.info(f"User {user_id}: Merge process finished with code {process.returncode}")
             if not os.path.exists(output_path):
                 return None
        logger.error(f"User {user_id}: FFmpeg failed with code {process.returncode}")
        raise Exception("FFmpeg merge gagal. Silakan periksa format file.")

def cancel_merge(user_id):
    """
    Kills the active merge process for a user.
    """
    if user_id in active_processes:
        process = active_processes[user_id]
        try:
            process.terminate()
            logger.info(f"Terminated merge process for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error terminating process for user {user_id}: {e}")
            try:
                process.kill()
                return True
            except:
                pass
    return False

def cleanup_temp_files(user_id):
    """Removes user's temporary directory."""
    path = os.path.join(Config.TEMP_DIR, str(user_id))
    if os.path.exists(path):
        try:
            shutil.rmtree(path)
            logger.info(f"Cleaned up temp files for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to cleanup user {user_id}: {e}")
