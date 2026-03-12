import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def cleanup_temp_files(uid, base_temp_dir: Path):
    """Clean up temporary directory for a specific user."""
    user_dir = base_temp_dir / f"user_{uid}"
    if user_dir.exists():
        try:
            shutil.rmtree(user_dir)
            logger.info(f"Successfully cleaned up temp files for user {uid}")
            return True
        except Exception as e:
            logger.error(f"Failed to cleanup temp files for {uid}: {e}")
            return False
    return True
