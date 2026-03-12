import asyncio
import asyncio.subprocess
import re
import json
import logging
import subprocess
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from bot.progress import calculate_progress, progress_bar
from bot.utils import format_duration, format_size

logger = logging.getLogger(__name__)

async def get_video_bitrate(file_path: Path) -> int:
    """Get the average bitrate of a video file using ffprobe (in bps)."""
    try:
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=bit_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            val = stdout.decode().strip()
            return int(val) if val.isdigit() else 0
        return 0
    except Exception as e:
        logger.error(f"Error getting bitrate for {file_path}: {e}")
        return 0

async def get_video_duration(file_path: Path) -> float:
    """Get the duration of a video file using ffprobe."""
    try:
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return float(stdout.decode().strip())
        return 0.0
    except Exception as e:
        logger.error(f"Error getting duration for {file_path}: {e}")
        return 0.0

def collect_episode_files(directory: Path) -> List[Path]:
    """Collect all video files in a directory."""
    extensions = ['.mp4', '.mkv', '.avi', '.mov']
    return [p for p in directory.iterdir() if p.suffix.lower() in extensions]

def extract_episode_number(filename: str) -> int:
    """Extract episode number from filename."""
    patterns = [
        r'[Ee]p(?:isode)?[\s._-]*(\d+)',
        r'[Pp]art[\s._-]*(\d+)',
        r'(\d{1,4})'
    ]
    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
             return int(match.group(1))
    return 0

def sort_episode_order(files: List[Path]) -> List[Path]:
    """Sort files based on episode numbers extracted from filenames."""
    return sorted(files, key=lambda p: extract_episode_number(p.name))

async def generate_concat_list(files: List[Path], output_list: Path):
    """Generate a text file for ffmpeg concat demuxer."""
    content = ""
    for f in files:
        # Proper path escaping for ffmpeg concat file
        escaped_path = str(f.absolute()).replace("'", "'\\''")
        content += f"file '{escaped_path}'\n"
    
    with open(output_list, 'w', encoding='utf-8') as f:
        f.write(content)

def escape_ffmpeg_path(path_str: str) -> str:
    """Escape Windows paths for FFmpeg filter strings."""
    # Replace backslashes with forward slashes
    path_str = path_str.replace('\\', '/')
    # Escape colon (e.g., C:/ -> C\:/)
    path_str = path_str.replace(':', '\\:')
    return path_str

async def merge_video_files(list_file: Path, output_file: Path, total_duration: float, 
                        output_format: str = "mkv", sub_mode: str = "softsub", progress_callback=None):
    """
    Merge video files with custom interactive options and styling for Hardsub.
    """
    
    stderr_lines = []
    
    # Custom Subtitle Style for Hardsub
    # Font (Standard Symbols PS), White, Size 10, Bold, Outline 1 (Black), Offset (MarginV) 90
    hardsub_style = (
        "FontName=Standard Symbols PS,"
        "FontSize=10,"
        "Bold=1,"
        "PrimaryColour=&H00FFFFFF,"
        "Outline=1,"
        "OutlineColour=&H00000000,"
        "MarginV=90"
    )

    if sub_mode == "hardsub":
        # Step 1: Merge to a temporary file first (Fast Copy)
        intermediate_file = output_file.parent / f"temp_{output_file.name}.mkv"
        logger.info(f"Hardsub Phase 1: Merging into intermediate {intermediate_file}")
        
        cmd_merge = [
            'ffmpeg', '-y', '-fflags', '+genpts', '-f', 'concat', '-safe', '0', '-i', str(list_file),
            '-c', 'copy', '-avoid_negative_ts', 'make_zero', str(intermediate_file)
        ]
        
        p1 = await asyncio.create_subprocess_exec(*cmd_merge, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, e1 = await p1.communicate()
        
        if p1.returncode != 0 or not intermediate_file.exists():
            logger.error(f"Hardsub Phase 1 failed: {e1.decode() if e1 else 'Unknown'}")
            return False
            
        # Step 2: Burn subtitles with bitrate matching to keep size similar
        logger.info("Hardsub Phase 2: Burning subtitles with size optimization")
        escaped_sub_path = escape_ffmpeg_path(str(intermediate_file.absolute()))
        
        # Get original bitrate to match size
        orig_bitrate = await get_video_bitrate(intermediate_file)
        
        cmd = [
            'ffmpeg', '-y', '-i', str(intermediate_file),
            '-vf', f"subtitles='{escaped_sub_path}':force_style='{hardsub_style}'", 
            '-c:v', 'libx264', '-preset', 'fast'
        ]
        
        if orig_bitrate > 0:
            # Match original bitrate to keep file size almost identical
            cmd.extend(['-b:v', str(orig_bitrate), '-maxrate', str(int(orig_bitrate * 1.5)), '-bufsize', str(orig_bitrate * 2)])
        else:
            # Fallback to a efficient CRF if bitrate detection fails
            cmd.extend(['-crf', '24'])
            
        cmd.extend([
            '-c:a', 'aac', '-b:a', '128k',
            '-progress', 'pipe:1', str(output_file)
        ])
    else:
        # Softsub (Stream Copy)
        cmd = [
            'ffmpeg', '-y', '-fflags', '+genpts', '-f', 'concat', '-safe', '0', '-i', str(list_file),
            '-c', 'copy', '-avoid_negative_ts', 'make_zero',
            '-progress', 'pipe:1', str(output_file)
        ]

    logger.info(f"Running FFmpeg: {' '.join(cmd)}")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    if not process or not process.stdout:
        return False

    async def read_stderr(stream):
        while True:
            line = await stream.readline()
            if not line: break
            stderr_lines.append(line.decode().strip())

    stderr_task = asyncio.create_task(read_stderr(process.stderr))

    while True:
        line = await process.stdout.readline()
        if not line:
            break
        
        line_str = line.decode().strip()
        
        if progress_callback and line_str.startswith("out_time_ms="):
            try:
                time_ms = int(line_str.split("=")[1]) / 1000000
                pct = (time_ms / total_duration * 100) if total_duration > 0 else 0
                await progress_callback(pct, time_ms)
            except:
                pass
        
        if line_str == "progress=end":
            break

    await process.wait()
    await stderr_task
    
    if process.returncode != 0:
        logger.error(f"FFmpeg failed: {' | '.join(stderr_lines[-5:])}")

    # Cleanup intermediate file
    if sub_mode == "hardsub" and 'intermediate_file' in locals() and intermediate_file.exists():
        try: os.remove(intermediate_file)
        except: pass
            
    return process.returncode == 0
