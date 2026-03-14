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
    Matches: E01, Episode 1, 01, etc.
    """
    # Patterns to look for
    patterns = [
        r'E(\d+)',            # E01
        r'Episode\s*(\d+)',   # Episode 01
        r'(\d+)'              # 01
    ]
    
    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 999  # Default high number if not found

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
