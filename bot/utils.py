import re
import os
import shutil
import logging
from bot.config import Config

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_safe_percentage(current, total):
    """Calculates percentage safely to avoid ZeroDivisionError."""
    if total <= 0:
        return 0.0
    return min(100.0, (current / total) * 100.0)

def get_episode_number(filename):
    """
    Extract episode number from filename.
    Supports: E01, Ep01, Ep 01, Episode 01, S01E01, etc.
    """
    # Remove file extension to avoid matching numbers in it
    name, _ = os.path.splitext(filename)
    
    # Priority patterns
    patterns = [
        r'S\d+E(\d+)',         # S01E01
        r'Episode\s*(\d+)',    # Episode 01
        r'Ep\s*(\d+)',         # Ep 01, Ep01
        r'[Ee](\d+)',          # E01, e01
        r'#\s*(\d+)',          # #01, # 01
        r'\[(\d+)\]',          # [01]
        r'\((\d+)\)',          # (01)
        r'-\s*(\d+)\s*-',      # - 01 -
        r'\b0*(\d+)\b'          # Any standalone number (fallback)
    ]
    
    for pattern in patterns:
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            try:
                num = int(match.group(1))
                if 1 <= num <= 2000:
                    return num
            except ValueError:
                continue
    
    # Last resort: find any digits
    digits = re.findall(r'\d+', name)
    if digits:
        for d in reversed(digits): # Often episode is towards the end
             num = int(d)
             if 1 <= num <= 2000:
                 return num

    return 9999  # Default high number for files without clear numbering

def sort_episodes(file_list):
    """Sorts a list of files based on extracted episode number."""
    return sorted(file_list, key=lambda x: get_episode_number(x))

def get_user_temp_dir(user_id):
    path = os.path.join(Config.TEMP_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path

def clean_user_dir(user_id):
    path = os.path.join(Config.TEMP_DIR, str(user_id))
    if os.path.exists(path):
        shutil.rmtree(path)

def format_bytes(size):
    # 2**10 = 1024
    power = 2**10
    n = 0
    power_labels = {0 : '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}B"
