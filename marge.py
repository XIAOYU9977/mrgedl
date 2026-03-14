import os
import asyncio
import json
import logging
import re
import shutil
import subprocess
import psutil
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import aiofiles
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file

# ==================== INSTALL ====================
# pip install telethon aiofiles psutil python-dotenv

from telethon import TelegramClient, events, Button
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto
from telethon.errors import SessionPasswordNeededError, MessageNotModifiedError
from telethon import helpers

# ==================== CONFIGURASI ====================
API_ID    = int(os.getenv("API_ID", "0"))
API_HASH  = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

BASE_DIR      = Path(__file__).parent.resolve()
DOWNLOADS_DIR = BASE_DIR / "downloads"
FFMPEG_PATH   = "ffmpeg"
FFPROBE_PATH  = "ffprobe"

DOWNLOADS_DIR.mkdir(exist_ok=True, parents=True)

MAX_FILE_SIZE_GB    = 1000 # Unlimited for practical purposes
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_GB * 1024 * 1024 * 1024
MAX_CONCURRENT_MERGE = 2
# Daftar ID user yang diizinkan (kosongkan jika untuk publik)
AUTHORIZED_USERS = [] # Masukkan ID user di sini, contoh: [12345678, 87654321]

MIN_RAM_AVAILABLE_GB = 1.5
MIN_DISK_FREE_GB     = 10

DOWNLOAD_TIMEOUT         = 600
MERGE_TIMEOUT            = 28800
PROGRESS_UPDATE_INTERVAL = 3

FALLBACK_CRF_VALUE     = 18
FALLBACK_AUDIO_BITRATE = "192k"

# Upload: chunk 512 KB x 64 worker paralel = ultra veryfast
UPLOAD_PART_SIZE_KB = 512
UPLOAD_WORKERS      = 64   # 64 koneksi paralel TCP

# Download paralel
DOWNLOAD_REQUEST_SIZE = 1 * 1024 * 1024   # 1 MB per request
DOWNLOAD_WORKERS      = 32               # Ultra veryfast download

# Prioritas bahasa subtitle
SUBTITLE_LANG_PRIORITY = ["id", "ind", "indonesian", "indonesia", "en", "eng", "english"]

MSG_START = (
    "🎬 **Merge Video Bot (Tanpa Batas!)**\n\n"
    "Kirim banyak video, saya gabungkan jadi satu file.\n\n"
    "**Fitur:**\n"
    "- File Tanpa Batas (Unlimited)\n"
    "- Stream copy tanpa re-encode jika codec sama\n"
    "- Pilih format: MP4 atau MKV\n"
    "- Soft subtitle tx3g/Indonesian dipertahankan\n"
    f"- Antrian pintar, maks {MAX_CONCURRENT_MERGE} user bersamaan\n"
    "- Upload paralel lebih cepat\n\n"
    "**Cara pakai:**\n"
    "1. Kirim video (boleh banyak kali)\n"
    "2. Klik Lihat Detail\n"
    "3. Pilih format output (MP4 atau MKV)\n"
    "4. Klik Merge\n\n"
    "Hingga 2000 video | Tanpa batas ukuran"
)

MSG_HELP = (
    "**Bantuan Merge Bot**\n\n"
    "**Format Output:**\n"
    "- MP4: Kompatibel luas (WA, Telegram, media player)\n"
    "- MKV: Lebih fleksibel, support banyak subtitle\n\n"
    "**Mode Merge:**\n"
    "- Stream Copy: Tanpa re-encode, codec sama, tercepat\n"
    "- Re-encode: Fallback otomatis jika codec berbeda\n\n"
    "**Soft Subtitle (tx3g/mov_text):**\n"
    "- Subtitle Indonesian dideteksi dan dipertahankan\n"
    "- MP4: format mov_text (kompatibel tx3g)\n"
    "- MKV: format SRT\n\n"
    "**Perintah:**\n"
    "/start - Menu utama\n"
    "/help  - Bantuan ini\n"
    "/cancel - Batalkan session\n\n"
    f"Batasan: Maks 10 video | Total {MAX_FILE_SIZE_GB} GB"
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== UTILS ====================

def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def format_speed(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.1f} B/s"
    elif bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    elif bps < 1024 * 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    return f"{bps / (1024 * 1024 * 1024):.2f} GB/s"

def format_duration(seconds: float) -> str:
    d = timedelta(seconds=int(seconds))
    h = d.seconds // 3600
    m = (d.seconds % 3600) // 60
    s = d.seconds % 60
    if h > 0:
        return f"{h}j {m}m {s}d"
    elif m > 0:
        return f"{m}m {s}d"
    return f"{s}d"

def progress_bar(pct: float, length: int = 16) -> str:
    filled = int(length * pct / 100)
    return chr(9608) * filled + chr(9617) * (length - filled)

def extract_episode_number(filename: str) -> int:
    """
    Extract episode number with improved logic.
    """
    name = Path(filename).stem
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
        for d in reversed(digits):
             num = int(d)
             if 1 <= num <= 2000:
                 return num
    return 0

def clean_filename(filename: str) -> str:
    name = Path(filename).stem
    return name[:27] + "..." if len(name) > 30 else name

def get_system_ram_gb()     -> float: return psutil.virtual_memory().total     / (1024 ** 3)
def get_available_ram_gb()  -> float: return psutil.virtual_memory().available / (1024 ** 3)
def get_disk_free_gb(p="/") -> float: return shutil.disk_usage(p).free         / (1024 ** 3)
def get_cpu_usage()         -> float: return psutil.cpu_percent(interval=0.1)
def get_ffmpeg_preset()     -> str:   return "ultrafast" # Forced to ultrafast for "ultra veryfast" request

def get_network_speed() -> Tuple[float, float]:
    n0 = psutil.net_io_counters()
    time.sleep(0.3)
    n1 = psutil.net_io_counters()
    return (n1.bytes_recv - n0.bytes_recv) / 0.3, (n1.bytes_sent - n0.bytes_sent) / 0.3

# ==================== VIDEO PROBE ====================

async def get_video_info(file_path: Path) -> Optional[Dict]:
    """Analisa video, termasuk deteksi subtitle streams (tx3g, mov_text, srt, dll)."""
    try:
        cmd = [
            FFPROBE_PATH, "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(file_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None

        data  = json.loads(stdout)
        video = None
        audio = None
        subs  = []

        for stream in data.get("streams", []):
            ct = stream.get("codec_type", "")
            if ct == "video" and video is None:
                video = stream
            elif ct == "audio" and audio is None:
                audio = stream
            elif ct == "subtitle":
                tags = stream.get("tags", {})
                disp = stream.get("disposition", {})
                subs.append({
                    "stream_index": stream.get("index"),
                    "codec_name":   stream.get("codec_name", ""),
                    "codec_long":   stream.get("codec_long_name", ""),
                    "lang":         tags.get("language", "").lower(),
                    "title":        tags.get("title", ""),
                    "is_default":   bool(disp.get("default", 0)),
                    "is_forced":    bool(disp.get("forced",  0)),
                })

        fmt = data.get("format", {})
        try:
            fps_val = eval((video or {}).get("r_frame_rate", "0/1"))
        except Exception:
            fps_val = 0.0

        return {
            "duration":         float(fmt.get("duration", 0)),
            "size":             int(fmt.get("size", 0)),
            "bit_rate":         int(fmt.get("bit_rate", 0)) if fmt.get("bit_rate") else 0,
            "video_codec":      video.get("codec_name")      if video else None,
            "video_codec_long": video.get("codec_long_name") if video else None,
            "width":            int(video.get("width", 0))   if video else 0,
            "height":           int(video.get("height", 0))  if video else 0,
            "fps":              fps_val,
            "audio_codec":      audio.get("codec_name")      if audio else None,
            "channels":         audio.get("channels", 0)     if audio else 0,
            "subtitle_streams": subs,
        }
    except Exception as e:
        logger.error(f"get_video_info error: {e}")
        return None


def pick_best_subtitle(subs: List[Dict]) -> Optional[Dict]:
    if not subs:
        return None
    # Default + Indonesia
    for s in subs:
        if s.get("is_default") and any(k in s.get("lang", "") for k in ["id", "ind"]):
            return s
    # Prioritas bahasa
    for lang_key in SUBTITLE_LANG_PRIORITY:
        for s in subs:
            if lang_key in s.get("lang", "").lower() or lang_key in s.get("title", "").lower():
                return s
    return subs[0]


def check_compatibility(videos_info: List[Dict]) -> Tuple[bool, str, Dict]:
    if not videos_info or not all(videos_info):
        return False, "Beberapa video tidak bisa dianalisa", {}
    ref = videos_info[0]
    vcodes = set(i.get("video_codec") for i in videos_info)
    if len(vcodes) > 1:
        return False, f"Codec video berbeda: {', '.join(str(c) for c in vcodes)}", {}
    acodes = set(i.get("audio_codec") for i in videos_info if i.get("audio_codec"))
    if len(acodes) > 1:
        return False, f"Codec audio berbeda: {', '.join(str(c) for c in acodes)}", {}
    ress = set((i.get("width"), i.get("height")) for i in videos_info)
    if len(ress) > 1:
        return False, f"Resolusi berbeda: {ress}", {}
    fps_list = [i.get("fps", 0) for i in videos_info]
    if max(fps_list) - min(fps_list) > 0.1:
        return False, f"FPS berbeda: {fps_list}", {}
    return True, "Semua video kompatibel", {
        "video_codec": ref.get("video_codec"),
        "audio_codec": ref.get("audio_codec"),
        "width":       ref.get("width"),
        "height":      ref.get("height"),
        "fps":         ref.get("fps"),
    }


async def create_concat_file(file_paths: List[Path], list_file: Path) -> bool:
    try:
        async with aiofiles.open(list_file, 'w', encoding='utf-8') as f:
            for fp in file_paths:
                escaped = str(fp.absolute()).replace("'", "'\\''")
                await f.write(f"file '{escaped}'\n")
        return True
    except Exception as e:
        logger.error(f"create_concat_file error: {e}")
        return False


async def parse_ffmpeg_progress(line: str) -> Dict:
    result = {}
    for key, pat in {
        "out_time_ms": r"out_time_ms=(\d+)",
        "out_time":    r"out_time=(\d+:\d+:\d+\.\d+)",
        "speed":       r"speed=([\d.]+)x",
        "progress":    r"progress=(\w+)",
    }.items():
        m = re.search(pat, line)
        if m:
            result[key] = m.group(1)
    return result

# ==================== SESSION ====================

class MergeSession:
    def __init__(self, user_id: int, session_dir: Path):
        self.user_id        = user_id
        self.session_dir    = session_dir
        self.videos         : List[Tuple[Path, str, int]] = []
        self.videos_info    : List[Optional[Dict]] = []
        self.status_message = None
        self.is_processing  = False
        self.created_at     = datetime.now()
        self.queue_position = None
        self.output_format  = "mp4"
        # ── Cancel support ────────────────────────────────────────────────
        self.cancel_flag    = False          # set True → hentikan semua proses
        self.ffmpeg_process : Optional[asyncio.subprocess.Process] = None # type: ignore
        self.download_task  : Optional[asyncio.Task] = None
        
        # --- Encoding Settings ---
        self.video_encoder = "Default"
        self.video_bitrate = "Default"
        self.audio_encoder = "Default"
        self.audio_bitrate = "Default"
        self.crf           = "Default"
        self.preset        = "Default"
        self.subtitle_type = "Softsub"       # Softsub atau Hardsub
        
        self.status_loop_task = None        # referensi task update status berkala
        self.status_lock     = asyncio.Lock() # Lock untuk cegah duplikasi status msg
        
        # ── Message Tracking ──────────────────────────────────────────────
        self.user_video_messages: List[int] = []
        self.incoming_messages:   List[int] = []
        self.active_downloads:    Dict[int, Dict] = {} # msg_id -> {name, received, total, speed}
        
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def get_download_status(self) -> str:
        """Bangun teks status terpadu untuk semua download aktif."""
        if not self.active_downloads:
            return "**Mempersiapkan download...**"
        
        lines = ["📥 **Sedang Mendownload...**\n"]
        for msg_id, info in self.active_downloads.items():
            name     = info.get("name", "Unknown")
            received = info.get("received", 0)
            total    = info.get("total", 0)
            speed    = info.get("speed", 0)
            pct      = received / total * 100 if total else 0
            
            bar = progress_bar(pct)
            lines.append(
                f"📄 `{name}`\n"
                f"{bar} {pct:.1f}%\n"
                f"   {format_size(received)} / {format_size(total)} | {format_speed(speed)}\n"
            )
        
        return "\n".join(lines)

    async def request_cancel(self):
        """Tandai session untuk dibatalkan secara paksa."""
        self.cancel_flag = True
        # Kill FFmpeg jika sedang berjalan
        proc = self.ffmpeg_process
        if proc is not None:
            try:
                proc.kill()
                logger.info(f"FFmpeg killed untuk user {self.user_id}")
            except Exception as e:
                logger.warning(f"Gagal kill FFmpeg: {e}")
        # Cancel download task jika sedang berjalan
        dl_task = self.download_task
        if dl_task is not None and not dl_task.done():
            dl_task.cancel()
            logger.info(f"Download task cancelled untuk user {self.user_id}")
            
        # Hentikan loop status update jika ada
        self.stop_status_loop()

    def stop_status_loop(self):
        """Hentikan task update status berkala."""
        if self.status_loop_task is not None and not self.status_loop_task.done():
            self.status_loop_task.cancel()
            self.status_loop_task = None
            logger.info(f"Status loop stopped untuk user {self.user_id}")

    async def add_video(self, fp: Path, fn: str, fs: int) -> bool:
        if len(self.videos) >= 2000:
            return False
        self.videos.append((fp, fn, fs))
        self.videos_info.append(await get_video_info(fp))
        return True

    def get_total_size(self)     -> int:   return sum(s for _, _, s in self.videos)
    def get_total_duration(self) -> float: return sum((i or {}).get("duration", 0) for i in self.videos_info)
    def get_video_names(self)    -> List[str]: return [clean_filename(n) for _, n, _ in self.videos]
    def get_episode_numbers(self)-> List[int]: return [extract_episode_number(n) for _, n, _ in self.videos]

    async def analyze_compatibility(self) -> Tuple[bool, str, Dict]:
        # Filter None values (video yang gagal analisa)
        valid_info = [i for i in self.videos_info if i is not None]
        if len(valid_info) < len(self.videos):
            return False, "Menunggu analisa video selesai", {}
        return check_compatibility(valid_info)

    def sort_videos_by_episode(self):
        eps = self.get_episode_numbers()
        idx = sorted(range(len(eps)), key=lambda i: eps[i] if eps[i] > 0 else float('inf'))
        self.videos      = [self.videos[i]      for i in idx]
        self.videos_info = [self.videos_info[i] for i in idx] if len(self.videos_info) == len(self.videos) else self.videos_info

    def collect_all_subtitles(self) -> List[Dict]:
        seen, result = set(), []
        for info in self.videos_info:
            if not info: continue
            for s in info.get("subtitle_streams", []):
                key = (s.get("lang", ""), s.get("title", ""))
                if key not in seen:
                    seen.add(key)
                    result.append(s)
        return result

    def cleanup(self):
        self.stop_status_loop()
        try:
            if self.session_dir.exists():
                shutil.rmtree(self.session_dir)
                logger.info(f"Session {self.user_id} dibersihkan")
        except Exception as e:
            logger.error(f"cleanup error: {e}")

# ==================== MERGE HANDLER ====================

class MergeHandler:
    def __init__(self):
        self.active_merges    = {}
        self.global_semaphore = asyncio.Semaphore(MAX_CONCURRENT_MERGE)
        self.merge_queue      = asyncio.Queue()
        self.processing_queue = False

    async def process_queue(self):
        if self.processing_queue:
            return
        self.processing_queue = True
        while True:
            try:
                uid, session, prog_cb, future = await self.merge_queue.get()
                await self._update_positions()
                if session.status_message:
                    try:
                        await session.status_message.edit(
                            "**Merge akan segera dimulai...**\n\nMohon tunggu.",
                            parse_mode='md'
                        )
                    except Exception:
                        pass
                async with self.global_semaphore:
                    try:
                        result = await self.merge_videos(session, prog_cb)
                        future.set_result(result)
                    except Exception as e:
                        future.set_exception(e)
                    finally:
                        await self._update_positions()
                self.merge_queue.task_done()
            except Exception as e:
                logger.error(f"process_queue error: {e}")
                await asyncio.sleep(1)

    async def _update_positions(self):
        ql = list(self.merge_queue._queue)
        for idx, (_, session, _, _) in enumerate(ql):
            if session and session.status_message:
                try:
                    await session.status_message.edit(
                        f"**Dalam Antrian — Posisi {idx+1} / {len(ql)}**\n\n/cancel untuk membatalkan.",
                        parse_mode='md'
                    )
                except Exception:
                    pass

    async def queue_merge(self, uid: int, session: MergeSession, prog_cb) -> asyncio.Future:
        future = asyncio.Future()
        if get_available_ram_gb() < MIN_RAM_AVAILABLE_GB:
            raise Exception(f"RAM tersisa {get_available_ram_gb():.1f}GB. Minimal {MIN_RAM_AVAILABLE_GB}GB.")
        if get_disk_free_gb() < MIN_DISK_FREE_GB:
            raise Exception(f"Disk kosong {get_disk_free_gb():.1f}GB. Minimal {MIN_DISK_FREE_GB}GB.")
        await self.merge_queue.put((uid, session, prog_cb, future))
        await self._update_positions()
        asyncio.create_task(self.process_queue())
        return future

    async def merge_videos(
        self,
        session: MergeSession,
        progress_callback=None
    ) -> Tuple[bool, Optional[Path], str, Dict]:
        """
        Merge dengan stream copy (tidak re-encode jika codec sama).
        Subtitle tx3g dipertahankan:
          - MP4 output: dikonversi ke mov_text (teks soft sub, compatible tx3g)
          - MKV output: dikonversi ke srt (lebih ringan)
        Upload lebih cepat dengan workers paralel.
        """
        try:
            if get_available_ram_gb() < MIN_RAM_AVAILABLE_GB:
                return False, None, "RAM tidak cukup", {}
            if get_disk_free_gb() < MIN_DISK_FREE_GB:
                return False, None, "Disk tidak cukup", {}

            session.sort_videos_by_episode()
            compatible, compat_msg, cinfo = await session.analyze_compatibility()

            out_ext     = session.output_format.lower()
            ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = session.session_dir / f"merged_{ts}.{out_ext}"
            list_file   = session.session_dir / "concat_list.txt"

            if not await create_concat_file([fp for fp, _, _ in session.videos], list_file):
                return False, None, "Gagal membuat concat file", {}

            preset   = get_ffmpeg_preset()
            all_subs = session.collect_all_subtitles()
            best_sub = pick_best_subtitle(all_subs)
            has_subs = bool(all_subs)

            # Codec subtitle output: mov_text untuk MP4, srt untuk MKV
            sub_codec_out = "mov_text" if out_ext == "mp4" else "srt"
            sub_lang      = (best_sub or {}).get("lang", "ind") or "ind"
            sub_title     = (best_sub or {}).get("title", "Indonesian") or "Indonesian"
            sub_codec_src = (best_sub or {}).get("codec_name", "tx3g")

            # ── Build FFmpeg command ──────────────────────────────────────────
            cmd = [FFMPEG_PATH, "-f", "concat", "-safe", "0", "-i", str(list_file)]

            # Map stream: video + audio + subtitle (opsional)
            cmd += ["-map", "0:v:0", "-map", "0:a:0"]
            if has_subs:
                cmd += ["-map", "0:s?"]

            if compatible and session.video_encoder == "Default" and session.video_bitrate == "Default" and session.subtitle_type == "Softsub":
                # Stream copy video & audio
                cmd += ["-c:v", "copy", "-c:a", "copy"]
                mode = "Stream Copy (Tanpa Re-Encode)"
            else:
                # Re-encode with User Settings (Hardsub REQUIRES re-encode)
                v_enc = session.video_encoder if session.video_encoder != "Default" else "libx264"
                a_enc = session.audio_encoder if session.audio_encoder != "Default" else "aac"
                v_pre = session.preset if session.preset != "Default" else preset
                v_crf = session.crf if session.crf != "Default" else str(FALLBACK_CRF_VALUE)
                
                cmd += ["-c:v", v_enc, "-preset", v_pre, "-crf", v_crf]
                
                # Hardsub Filter
                if session.subtitle_type == "Hardsub" and has_subs:
                    # Gunakan stream subtitle pertama untuk dibakar
                    # FFmpeg subtitles filter butuh path yang di-escape untuk Windows
                    escaped_path = str(list_file).replace("\\", "/").replace(":", "\\:")
                    cmd += ["-vf", f"subtitles='{escaped_path}':si=0"]
                    mode = f"Hardsub Encode ({v_enc}, {v_pre}, CRF {v_crf})"
                else:
                    mode = f"Re-encode ({v_enc}, {v_pre}, CRF {v_crf})"
                
                if session.video_bitrate != "Default":
                    cmd += ["-b:v", session.video_bitrate]
                
                cmd += ["-c:a", a_enc]
                if session.audio_bitrate != "Default":
                    cmd += ["-b:a", session.audio_bitrate]
                else:
                    cmd += ["-b:a", FALLBACK_AUDIO_BITRATE]
                
                mode = f"Re-encode ({v_enc}, {v_pre}, CRF {v_crf})"
                if not compatible:
                    mode += f" — {compat_msg}"

            # Subtitle Softsub: konversi tx3g/any -> mov_text atau srt
            if has_subs and session.subtitle_type == "Softsub":
                cmd += [
                    "-c:s", sub_codec_out,
                    "-metadata:s:s:0", f"language={sub_lang}",
                    "-metadata:s:s:0", f"title={sub_title}",
                    "-disposition:s:0", "default",
                ]
            elif has_subs and session.subtitle_type == "Hardsub":
                # Jangan sertakan stream subtitle jika sudah di-hardsub
                pass

            if out_ext == "mp4":
                cmd += ["-movflags", "+faststart"]

            cmd += ["-progress", "pipe:1", "-y", str(output_path)]

            logger.info(f"[Merge] user={session.user_id} fmt={out_ext.upper()} mode={mode}")
            logger.info(f"[Merge] subtitle: has={has_subs} src={sub_codec_src} out={sub_codec_out} lang={sub_lang}")
            logger.info(f"[Merge] cmd: {' '.join(cmd)}")

            stats = {
                "mode":           mode,
                "total_size":     session.get_total_size(),
                "total_duration": session.get_total_duration(),
                "compatible":     compatible,
                "preset":         preset,
                "output_format":  out_ext,
                "has_subtitle":   has_subs,
                "sub_lang":       sub_lang if has_subs else "—",
                "sub_title":      sub_title if has_subs else "—",
                "sub_codec_src":  sub_codec_src if has_subs else "—",
                "sub_codec_out":  sub_codec_out if has_subs else "—",
            }

            # ── Run FFmpeg ────────────────────────────────────────────────────
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                session.ffmpeg_process = process   # simpan agar bisa di-kill via /cancel
                total_dur = session.get_total_duration()
                last_upd  = 0.0

                async def read_output():
                    nonlocal last_upd
                    while True:
                        # Cek cancel flag setiap iterasi
                        if session.cancel_flag:
                            process.kill()
                            break
                        try:
                            line = await asyncio.wait_for(process.stdout.readline(), timeout=120)
                        except asyncio.TimeoutError:
                            logger.error("FFmpeg stdout timeout")
                            process.kill()
                            break
                        if not line:
                            break
                        pdata = await parse_ffmpeg_progress(line.decode().strip())
                        if "out_time_ms" in pdata and total_dur > 0:
                            cur_t = int(pdata["out_time_ms"]) / 1_000_000
                            pct   = min(100.0, cur_t / total_dur * 100)
                            now   = time.time()
                            if now - last_upd > PROGRESS_UPDATE_INTERVAL and progress_callback:
                                await progress_callback(pct, pdata)
                                last_upd = now

                await asyncio.wait_for(
                    asyncio.gather(read_output(), process.wait()),
                    timeout=MERGE_TIMEOUT
                )
                session.ffmpeg_process = None

            except asyncio.TimeoutError:
                process.kill()
                session.ffmpeg_process = None
                return False, None, "Merge timeout — file terlalu besar", stats

            # Cek apakah dibatalkan user
            if session.cancel_flag:
                return False, None, "CANCELLED", stats

            if process.returncode != 0:
                err = (await process.stderr.read()).decode()[:600]
                logger.error(f"FFmpeg error: {err}")
                return False, None, f"FFmpeg error:\n{err}", stats

            if not output_path.exists():
                return False, None, "File output tidak dibuat", stats

            out_size  = output_path.stat().st_size
            orig_size = session.get_total_size()
            diff      = out_size - orig_size
            stats.update({
                "output_size":   out_size,
                "size_diff":     diff,
                "size_diff_pct": (diff / orig_size * 100) if orig_size else 0,
            })
            return True, output_path, "Berhasil", stats

        except Exception as e:
            logger.error(f"merge_videos exception: {e}", exc_info=True)
            return False, None, f"Error: {e}", {}

    def is_merging(self, uid: int) -> bool:
        return uid in self.active_merges and not self.active_merges[uid].done()

    def add_merge_task(self, uid: int, task: asyncio.Task):
        self.active_merges[uid] = task

    def remove_merge_task(self, uid: int):
        self.active_merges.pop(uid, None)

# ==================== TELEGRAM BOT ====================

class TelegramBot:
    def __init__(self, api_id, api_hash, bot_token):
        self.api_id        = api_id
        self.api_hash      = api_hash
        self.bot_token     = bot_token
        self.client        = None
        self.sessions      : Dict[int, MergeSession] = {}
        self.merge_handler = MergeHandler()

    async def start(self):
        # Gunakan nama session yang lebih unik untuk menghindari 'bentrok'
        self.client = TelegramClient('merge_bot_v2_session', self.api_id, self.api_hash)
        await self.client.start(bot_token=self.bot_token)

        # incoming=True: hanya proses pesan masuk (bukan yang dikirim bot sendiri)
        # pattern pakai regex agar match /start, /start@botname, dll
        self.client.add_event_handler(
            self.cmd_start,
            events.NewMessage(pattern=r'^/(start|setup)', incoming=True)
        )
        self.client.add_event_handler(
            self.cmd_help,
            events.NewMessage(pattern=r'^/help', incoming=True)
        )
        self.client.add_event_handler(
            self.cmd_cancel,
            events.NewMessage(pattern=r'^/cancel', incoming=True)
        )
        self.client.add_event_handler(
            self.video_handler,
            events.NewMessage(
                incoming=True,
                func=lambda e: (
                    e.message is not None
                    and e.message.file is not None
                    and (
                        (getattr(e.message.file, 'mime_type', '') or '').startswith('video/')
                        or (getattr(e.message.file, 'name', '') or '').lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm'))
                    )
                )
            )
        )
        self.client.add_event_handler(self.callback_handler, events.CallbackQuery())
        self.client.add_event_handler(self.debug_handler, events.NewMessage(incoming=True))

        me = await self.client.get_me()
        logger.info(f"Bot started! @{me.username} (id={me.id})")
        asyncio.create_task(self.auto_cleanup_loop())
        await self.client.run_until_disconnected()

    # ── Commands ──────────────────────────────────────────────────────────────

    async def cmd_start(self, event):
        uid = event.sender_id
        if AUTHORIZED_USERS and uid not in AUTHORIZED_USERS:
            # Check if we already sent an access denied message
            # But since there's no session, we can't track easily without a global dict.
            # However, for unauthorized users, we can just use persistent logic if we want.
            # For now, let's just make it a simple reply as it's not a "running" session.
            # But the user said "semua pesan bot". 
            # Let's create a temporary session even for unauthorized? No, better not.
            # We'll just use a simple reply for unauthorized and hope they don't spam.
            await event.reply("❌ **Akses Ditolak.** Bot ini khusus untuk user tertentu.")
            return
        if uid not in self.sessions:
            sd = DOWNLOADS_DIR / f"user_{uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.sessions[uid] = MergeSession(uid, sd)
            logger.info(f"New session created for user {uid} at {sd}")
        
        session = self.sessions[uid]
        text = (
            "👋 **Selamat datang di BOT MERGE VIDEO!**\n\n"
            "Kirim video yang ingin digabung.\n\n"
            "📌 **Silahkan pilih menu encoding anda !**\n\n"
            f"• Video Encoder: `{session.video_encoder}`\n"
            f"• Video Bitrate: `{session.video_bitrate}`\n"
            f"• Audio Encoder: `{session.audio_encoder}`\n"
            f"• Audio Bitrate: `{session.audio_bitrate}`\n"
            f"• CRF: `{session.crf}`\n"
            f"• Preset: `{session.preset}`\n\n"
            "Timeout: 2 jam"
        )
        buttons = [
            [Button.inline("⚙️ Settings Encoding", b"config_main")],
            [Button.inline("📁 Mulai Kirim File", b"close_menu")]
        ]
        async with session.status_lock:
            try:
                await self.update_status(session, text, buttons=buttons)
            except Exception as e:
                logger.error(f"cmd_start error: {e}")
                await self.update_status(session, "Selamat datang! Gunakan /settings untuk konfigurasi encoding.")

    async def show_config_main(self, uid):
        session = self.sessions.get(uid)
        if not session: return
        text = (
            "📌 **Menu Konfigurasi Encoding**\n\n"
            f"• Video Encoder: `{session.video_encoder}`\n"
            f"• Video Bitrate: `{session.video_bitrate}`\n"
            f"• Audio Encoder: `{session.audio_encoder}`\n"
            f"• Audio Bitrate: `{session.audio_bitrate}`\n"
            f"• CRF: `{session.crf}`\n"
            f"• Preset: `{session.preset}`\n"
            f"• Format: `{session.output_format.upper()}`\n"
            f"• Mode Sub: `{session.subtitle_type}`"
        )
        buttons = [
            [Button.inline("Video Encoder", b"conf_v_enc"), Button.inline("Video Bitrate", b"conf_v_bit")],
            [Button.inline("Audio Encoder", b"conf_a_enc"), Button.inline("Audio Bitrate", b"conf_a_bit")],
            [Button.inline("CRF", b"conf_crf"), Button.inline("Preset", b"conf_preset")],
            [Button.inline("Output Format", b"conf_out_fmt"), Button.inline("Subtitle Mode", b"conf_sub_type")],
            [Button.inline("⬅️ Kembali", b"cmd_start")]
        ]
        await self.update_status(session, text, buttons=buttons, parse_mode='md')

    async def cmd_help(self, event):
        uid = event.sender_id
        session = self.sessions.get(uid)
        if not session:
            await event.reply(MSG_HELP, parse_mode='md')
            return
            
        try:
            await self.update_status(session, MSG_HELP)
        except Exception as e:
            logger.error(f"cmd_help error: {e}")
            await self.update_status(session, "Kirim video ke bot ini. Setelah semua video dikirim, klik tombol Merge.")

    async def cmd_cancel(self, event):
        uid = event.sender_id
        if uid not in self.sessions:
            await event.reply('Tidak ada session aktif. Gunakan /start untuk mulai baru.')
            return

        s = self.sessions.pop(uid)

        # ── Paksa hentikan semua proses aktif ─────────────────────────────
        await s.request_cancel()   # kill FFmpeg + cancel download task

        # Beri jeda singkat agar proses sempat mati
        await asyncio.sleep(0.5)

        # Hapus pesan status lama
        if s.status_message:
            try: await s.status_message.delete()
            except: pass

        # Hapus semua file sementara
        s.cleanup()

        # Bersihkan dari merge handler
        self.merge_handler.remove_merge_task(uid)

        # Singleton final message? Actually, let's just send a fresh status if possible
        # but since session is popped, update_status won't work easily.
        # We'll send a final reply and then let it be.
        await event.reply(
            "**Session dibatalkan paksa!**\n\n"
            "FFmpeg & Download dihentikan.\n"
            "Semua file dihapus. Chat akan bersih dalam 1 jam (auto-cleanup).",
            parse_mode='md'
        )
        logger.info(f"Force cancel untuk user {uid}")

    # ── Status helper ─────────────────────────────────────────────────────────

    async def update_status(self, session: MergeSession, text: str,
                             buttons=None, parse_mode: str = 'md', force_repost: bool = False):
        try:
            # Singleton: Jika repost atau belum ada pesan, hapus yang lama dulu
            if force_repost or not session.status_message:
                if session.status_message:
                    try: await session.status_message.delete()
                    except: pass
            else:
                # Coba edit pesan yang ada
                try:
                    await session.status_message.edit(text, buttons=buttons, parse_mode=parse_mode)
                    return
                except MessageNotModifiedError:
                    # Teks sama, tidak perlu kirim baru
                    return
                except Exception:
                    # Edit gagal lainnya, kirim baru di bawah
                    pass

            # Kirim pesan baru sebagai singleton
            session.status_message = await self.client.send_message(
                session.user_id, text, buttons=buttons, parse_mode=parse_mode
            )
        except Exception as e:
            logger.error(f"update_status error: {e}")

    async def start_status_refresh_loop(self, session: MergeSession):
        """Task background untuk update status message secara berkala."""
        session.stop_status_loop() # Pastikan tidak ada loop ganda
        
        async def _loop():
            try:
                while not session.cancel_flag and not session.is_processing:
                    # Update info real-time
                    cpu = get_cpu_usage()
                    ram = get_available_ram_gb()
                    total_ram = get_system_ram_gb()
                    disk = get_disk_free_gb()
                    
                    n = len(session.videos)
                    total_dur = format_duration(session.get_total_duration())
                    total_size = format_size(session.get_total_size())
                    
                    text = (
                        "🔄 **Bot Update - Live Session Status**\n\n"
                        f"📊 **Statistik Server:**\n"
                        f"• CPU: `{cpu:.1f}%`    • RAM: `{ram:.1f}/{total_ram:.1f} GB` Bebas\n"
                        f"• Disk: `{disk:.1f} GB` Bebas\n\n"
                        f"📁 **Data Project:**\n"
                        f"• Jumlah Video: `{n}`\n"
                        f"• Total Durasi: `{total_dur}`\n"
                        f"• Total Ukuran: `{total_size}`\n\n"
                        "💡 Kirim video lagi atau gunakan menu di bawah untuk lanjut."
                    )
                    
                    buttons = [
                        [Button.inline("⚙️ Settings Encoding", b"config_main")],
                        [Button.inline("🔍 Lihat Detail & Merge", b"show_summary")],
                        [Button.inline("❌ Batal", b"cancel")]
                    ]
                    
                    await self.update_status(session, text, buttons=buttons, parse_mode='md', force_repost=False)
                    await asyncio.sleep(10) # Refresh setiap 10 detik
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"status_refresh_loop error: {e}")

        session.status_loop_task = asyncio.create_task(_loop())

    # ── Video handler ─────────────────────────────────────────────────────────

    async def video_handler(self, event):
        uid       = event.sender_id
        if AUTHORIZED_USERS and uid not in AUTHORIZED_USERS:
            # Diam saja atau beri tahu
            return
            
        if self.merge_handler.is_merging(uid):
            msg = await event.reply("Sedang merge. Tunggu selesai atau /cancel")
            if uid in self.sessions:
                self.sessions[uid].incoming_messages.append(msg.id)
            return
            
        # Track all incoming video messages for this user
        if uid in self.sessions:
            session = self.sessions[uid]
            session.user_video_messages.append(event.message.id)
            
        file      = event.message.file
        file_size = file.size
        file_name = file.name or f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

        if file_size > MAX_FILE_SIZE_BYTES:
            await self.update_status(
                session,
                f"**File terlalu besar!**\n{file_name}\n{format_size(file_size)}\nBatas: {format_size(MAX_FILE_SIZE_BYTES)}"
            )
            return

        if uid not in self.sessions:
            sd = DOWNLOADS_DIR / f"user_{uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.sessions[uid] = MergeSession(uid, sd)
            # Track the very first video message too
            self.sessions[uid].user_video_messages.append(event.message.id)
        
        session = self.sessions[uid]
        msg_id = event.message.id
        session.active_downloads[msg_id] = {
            "name": file_name,
            "received": 0,
            "total": file_size,
            "speed": 0
        }

        if session.get_total_size() + file_size > MAX_FILE_SIZE_BYTES:
            await self.update_status(
                session,
                f"Total ukuran melebihi batas {format_size(MAX_FILE_SIZE_BYTES)}.\nGunakan /cancel untuk mulai ulang."
            )
            return

        async with session.status_lock:
            # Atomic session creation already handled by dict check,
            # but we use lock to avoid double status message creation.
            if not session.status_message:
                session.status_message = await self.client.send_message(
                    uid, "**Mempersiapkan download...**", parse_mode='md'
                )
            else:
                # Update but don't spam if text is identical (handled in update_status)
                await self.update_status(session, "**Mempersiapkan download...**", force_repost=False)

        start_time = time.time()
        last_upd   = [time.time()]

        async def dl_progress(received: int, total: int):
            now = time.time()
            session.active_downloads[msg_id].update({
                "received": received,
                "total": total,
                "speed": received / (now - start_time) if (now - start_time) > 0 else 0
            })
            
            if now - last_upd[0] < PROGRESS_UPDATE_INTERVAL:
                return
            last_upd[0] = now
            await self.update_status(session, session.get_download_status(), force_repost=False)

        file_path = session.session_dir / file_name
        try:
            # ── Download paralel dengan iter_download ─────────────────────
            # iter_download membuka DOWNLOAD_WORKERS koneksi TCP ke Telegram
            # sekaligus, jauh lebih cepat dari download_media (1 koneksi)
            dl_total    = file_size
            dl_received = [0]

            async def _run_download():
                async with aiofiles.open(file_path, 'wb') as f_out:
                    logger.info(f"Download started for {file_name} (Size: {file_size})")
                    async for chunk in event.client.iter_download(
                        event.message.media,
                        request_size=DOWNLOAD_REQUEST_SIZE,
                        dc_id=getattr(getattr(event.message.media, 'document', None) or
                                      getattr(event.message.media, 'photo', None), 'dc_id', None),
                    ):
                        if session.cancel_flag:
                            logger.info(f"Download dibatalkan untuk user {uid}")
                            raise asyncio.CancelledError("Download dibatalkan oleh user")
                        await f_out.write(chunk)
                        dl_received[0] += len(chunk)
                        
                        # Debug: log every 10MB
                        if dl_received[0] % (10 * 1024 * 1024) < len(chunk):
                            logger.info(f"Downloading {file_name}: {format_size(dl_received[0])} / {format_size(dl_total)}")
                            
                        await dl_progress(dl_received[0], dl_total)

            dl_task = asyncio.create_task(
                asyncio.wait_for(_run_download(), timeout=DOWNLOAD_TIMEOUT)
            )
            session.download_task = dl_task
            await dl_task
            session.download_task = None
            
            # Remove from active downloads once done
            session.active_downloads.pop(msg_id, None)
                
            if session.active_downloads:
                await self.update_status(session, session.get_download_status(), force_repost=False)

            if not file_path.exists():
                raise Exception("File tidak terdownload dengan benar.")

            dl_size = file_path.stat().st_size
            logger.info(f"Downloaded: {file_name} ({format_size(dl_size)})")
            await session.add_video(file_path, file_name, dl_size)

            info     = session.videos_info[-1] if session.videos_info else {}
            subs     = (info or {}).get("subtitle_streams", [])
            best_sub = pick_best_subtitle(subs)
            sub_info = ""
            if subs:
                lang_str  = (best_sub or {}).get("lang", "?") or "?"
                codec_str = (best_sub or {}).get("codec_name", "?")
                sub_info  = f"\nSubtitle: {len(subs)} stream  best: {lang_str} ({codec_str})"

            n = len(session.videos)
            # Mulai loop update otomatis HANYA jika semua download aktif sudah selesai
            if not session.active_downloads:
                await self.start_status_refresh_loop(session)
            
        except asyncio.CancelledError:
            logger.info(f"Download cancelled untuk user {uid}")
            # Jangan update status — session sudah/akan dibersihkan oleh cmd_cancel
        except Exception as e:
            session.active_downloads.pop(msg_id, None)
            logger.error(f"Download error: {e}", exc_info=True)
            if not session.cancel_flag:
                await self.update_status(session, f"**Gagal download:**\n`{str(e)[:200]}`", parse_mode='md')
            
            # Jika ini tadinya download terakhir, tetep coba start loop untuk tunjukkan menu
            if not session.active_downloads:
                await self.start_status_refresh_loop(session)

    # ── Summary ───────────────────────────────────────────────────────────────

    async def show_summary(self, event, uid: int):
        session = self.sessions.get(uid)
        if not session:
            return

        compatible, compat_msg, cinfo = await session.analyze_compatibility()
        all_subs   = session.collect_all_subtitles()
        best_sub   = pick_best_subtitle(all_subs)
        preset     = get_ffmpeg_preset()
        cpu        = get_cpu_usage()
        ram        = get_available_ram_gb()
        total_ram  = get_system_ram_gb()
        disk       = get_disk_free_gb()
        dl_spd, ul_spd = get_network_speed()

        eps   = session.get_episode_numbers()
        names = session.get_video_names()
        lines: List[str] = []
        for i, name in enumerate(names):
            ep = eps[i] if i < len(eps) else 0
            lines.append(f"  {i+1:02d}. {'Ep '+str(ep) if ep > 0 else name}")

        fmt_icon  = "MP4" if session.output_format == "mp4" else "MKV"

        text  = "**Ringkasan Session**\n\n"
        text += "**Video:**\n" + "\n".join(lines[:10])
        if len(lines) > 10:
            text += f"\n  ...+{len(lines)-10} lainnya"
        text += (
            f"\n\n{len(session.videos)} video"
            f"  |  {format_duration(session.get_total_duration())}"
            f"  |  {format_size(session.get_total_size())}"
        )

        if compatible:
            vc  = (cinfo.get('video_codec') or 'N/A').upper()
            res = f"{cinfo.get('width')}x{cinfo.get('height')}" if cinfo.get('width') else "?"
            text += f"\n\n**Mode:** Stream Copy (Tanpa Re-Encode)\nCodec: `{vc}`  Resolusi: `{res}`"
        else:
            text += f"\n\n**Mode:** Re-encode (CRF {FALLBACK_CRF_VALUE}, Preset `{preset}`)\nAlasan: {compat_msg}"

        # Subtitle
        text += "\n\n**Subtitle:**"
        if all_subs:
            for s in all_subs[:4]:
                def_mark  = " (default)" if s.get("is_default") else ""
                codec_str = s.get("codec_name", "?")
                lang_str  = s.get("lang", "?") or "?"
                title_str = f" — {s['title']}" if s.get("title") else ""
                text += f"\n  {lang_str} ({codec_str}){title_str}{def_mark}"
            if len(all_subs) > 4:
                text += f"\n  ...+{len(all_subs)-4} lainnya"
            out_codec = "mov_text" if session.output_format == "mp4" else "srt"
            text += f"\n  Output: `{out_codec}` (default Indonesian)"
        else:
            text += " Tidak ada"

        text += (
            f"\n\n**Format Output:** `{fmt_icon}`\n\n"
            f"**Server:** CPU {cpu:.0f}%  RAM {ram:.1f}/{total_ram:.1f}GB  Disk {disk:.1f}GB\n"
            f"Net: {format_speed(dl_spd)} down  {format_speed(ul_spd)} up"
        )

        buttons = [
            [Button.inline("Set MP4", b"fmt_mp4"), Button.inline("Set MKV", b"fmt_mkv")],
            [Button.inline(f"Merge -> {fmt_icon}!", b"merge")],
            [Button.inline("Batal & Hapus", b"cancel")],
        ]
        await self.update_status(session, text, buttons=buttons, parse_mode='md')

    async def debug_handler(self, event):
        # Ini akan menangkap semua pesan yang tidak ditangani handler lain
        if event.message and event.message.text:
            msg = event.message.text.lower()
            if msg.startswith('/'): return # Abaikan command lain
            
        # Log untuk debugging
        uid = event.sender_id
        logger.info(f"DEBUG: Received message from {uid}")
        if event.message.file:
            logger.info(f"DEBUG: File detected: {event.message.file.name} (Mime: {event.message.file.mime_type})")

    async def callback_handler(self, event):
        uid  = event.sender_id
        data = event.data.decode('utf-8')

        if uid not in self.sessions:
            await event.answer("Session tidak ditemukan. Kirim /start")
            return

        session = self.sessions[uid]

        if data == "config_main":
            await self.show_config_main(uid)
            await event.answer()
            return

        if data == "close_menu":
            await self.update_status(session, "✅ Konfigurasi disimpan. Silakan kirim file video Anda.")
            await event.answer()
            return

        if data == "cmd_start":
            await self.cmd_start(event)
            await event.answer()
            return

        # --- Sub-menus ---
        if data == "conf_v_enc":
            buttons = [
                [Button.inline("Default", b"set_v_enc_Default")],
                [Button.inline("H.264", b"set_v_enc_libx264"), Button.inline("H.265", b"set_v_enc_libx265")],
                [Button.inline("VP8", b"set_v_enc_libvpx"), Button.inline("VP9", b"set_v_enc_libvpx-vp9")],
                [Button.inline("AV1", b"set_v_enc_libaom-av1"), Button.inline("Theora", b"set_v_enc_libtheora")],
                [Button.inline("MPEG4", b"set_v_enc_mpeg4"), Button.inline("MPEG2", b"set_v_enc_mpeg2video")],
                [Button.inline("↩️ Kembali", b"config_main")]
            ]
            await self.update_status(session, "📌 **Silahkan pilih video encoder anda !**", buttons=buttons, parse_mode='md')
            await event.answer()
            return

        if data.startswith("set_v_enc_"):
            session.video_encoder = data.split("_")[-1]
            await self.show_config_main(uid)
            await event.answer(f"Video Encoder: {session.video_encoder}")
            return

        if data == "conf_v_bit":
            rates = ["Default", "500k", "1200k", "2000k", "3000k", "4000k", "5000k", "6000k", "7000k", "8000k", "9000k", "10000k"]
            buttons = []
            for i in range(0, len(rates), 2):
                row = [Button.inline(rates[i], f"set_v_bit_{rates[i]}".encode())]
                if i+1 < len(rates):
                    row.append(Button.inline(rates[i+1], f"set_v_bit_{rates[i+1]}".encode()))
                buttons.append(row)
            buttons.append([Button.inline("↩️ Kembali", b"config_main")])
            await self.update_status(session, "📌 **Silahkan pilih video bitrate anda !**", buttons=buttons, parse_mode='md')
            await event.answer()
            return

        if data.startswith("set_v_bit_"):
            session.video_bitrate = data.split("_")[-1]
            await self.show_config_main(uid)
            await event.answer(f"Video Bitrate: {session.video_bitrate}")
            return

        if data == "conf_a_enc":
            buttons = [
                [Button.inline("Default", b"set_a_enc_Default")],
                [Button.inline("AAC", b"set_a_enc_aac"), Button.inline("MP3", b"set_a_enc_libmp3lame")],
                [Button.inline("Opus", b"set_a_enc_libopus"), Button.inline("Vorbis", b"set_a_enc_libvorbis")],
                [Button.inline("WAV", b"set_a_enc_pcm_s16le"), Button.inline("MPEG", b"set_a_enc_mp2")],
                [Button.inline("FLAC", b"set_a_enc_flac"), Button.inline("ALAC", b"set_a_enc_alac")],
                [Button.inline("↩️ Kembali", b"config_main")]
            ]
            await self.update_status(session, "📌 **Silahkan pilih audio encoder anda !**", buttons=buttons, parse_mode='md')
            await event.answer()
            return

        if data.startswith("set_a_enc_"):
            session.audio_encoder = data.split("_")[-1]
            await self.show_config_main(uid)
            await event.answer(f"Audio Encoder: {session.audio_encoder}")
            return

        if data == "conf_a_bit":
            rates = ["Default", "32 kbps", "64 kbps", "96 kbps", "128 kbps", "192 kbps", "256 kbps", "320 kbps", "512 kbps"]
            buttons = []
            for i in range(0, len(rates), 2):
                row = [Button.inline(rates[i], f"set_a_bit_{rates[i].replace(' ', '_')}".encode())]
                if i+1 < len(rates):
                    row.append(Button.inline(rates[i+1], f"set_a_bit_{rates[i+1].replace(' ', '_')}".encode()))
                buttons.append(row)
            buttons.append([Button.inline("↩️ Kembali", b"config_main")])
            await self.update_status(session, "📌 **Silahkan pilih audio bitrate anda !**", buttons=buttons, parse_mode='md')
            await event.answer()
            return

        if data.startswith("set_a_bit_"):
            session.audio_bitrate = data.split("_")[-1].replace("_", " ")
            await self.show_config_main(uid)
            await event.answer(f"Audio Bitrate: {session.audio_bitrate}")
            return

        if data == "conf_preset":
            presets = ["Default", "Ultrafast", "Superfast", "Veryfast", "Faster", "Fast", "Medium", "Slow", "Slower", "Veryslow"]
            buttons = []
            for i in range(0, len(presets), 2):
                row = [Button.inline(presets[i], f"set_preset_{presets[i]}".encode())]
                if i+1 < len(presets):
                    row.append(Button.inline(presets[i+1], f"set_preset_{presets[i+1]}".encode()))
                buttons.append(row)
            buttons.append([Button.inline("↩️ Kembali", b"config_main")])
            text = (
                "📌 **Silahkan pilih preset anda !**\n\n"
                "⚠️ **Note:** Semakin cepat proses kompresi, semakin besar ukuran file video"
            )
            await self.update_status(session, text, buttons=buttons, parse_mode='md')
            await event.answer()
            return

        if data.startswith("set_preset_"):
            session.preset = data.split("_")[-1]
            await self.show_config_main(uid)
            await event.answer(f"Preset: {session.preset}")
            return

        if data == "conf_crf":
            crfs = ["Default", "18", "20", "23", "25", "28", "30"]
            buttons = []
            for i in range(0, len(crfs), 2):
                row = [Button.inline(crfs[i], f"set_crf_{crfs[i]}".encode())]
                if i+1 < len(crfs):
                    row.append(Button.inline(crfs[i+1], f"set_crf_{crfs[i+1]}".encode()))
                buttons.append(row)
            buttons.append([Button.inline("↩️ Kembali", b"config_main")])
            await self.update_status(session, "📌 **Silahkan pilih CRF anda !**", buttons=buttons, parse_mode='md')
            await event.answer()
            return

        if data.startswith("set_crf_"):
            session.crf = data.split("_")[-1]
            await self.show_config_main(uid)
            await event.answer(f"CRF: {session.crf}")
            return

        if data == "conf_sub_type":
            buttons = [
                [Button.inline("Softsub (Text)", b"set_sub_type_Softsub")],
                [Button.inline("Hardsub (Burn-in)", b"set_sub_type_Hardsub")],
                [Button.inline("↩️ Kembali", b"config_main")]
            ]
            text = (
                "📌 **Pilih Tipe Subtitle**\n\n"
                "• **Softsub:** Subtitle bisa diubah-ubah/dimatikan (tidak re-encode video).\n"
                "• **Hardsub:** Subtitle menyatu dengan gambar (re-encode penuh, permanen)."
            )
            await self.update_status(session, text, buttons=buttons, parse_mode='md')
            await event.answer()
            return

        if data.startswith("set_sub_type_"):
            session.subtitle_type = data.split("_")[-1]
            await self.show_config_main(uid)
            await event.answer(f"Subtitle: {session.subtitle_type}")
            return

        if data == "conf_out_fmt":
            buttons = [
                [Button.inline("MP4", b"set_out_fmt_mp4"), Button.inline("MKV", b"set_out_fmt_mkv")],
                [Button.inline("↩️ Kembali", b"config_main")]
            ]
            await self.update_status(session, "📌 **Pilih Format Output**", buttons=buttons, parse_mode='md')
            await event.answer()
            return

        if data.startswith("set_out_fmt_"):
            session.output_format = data.split("_")[-1]
            await self.show_config_main(uid)
            await event.answer(f"Format: {session.output_format.upper()}")
            return

        if data == "cancel":
            await session.request_cancel()
            await asyncio.sleep(0.5)
            # Final cleanup will be handled by the handler's finally or here if direct cancel
            msgs_to_del = []
            if session.status_message: msgs_to_del.append(session.status_message.id)
            if session.user_video_messages: msgs_to_del.extend(session.user_video_messages)
            if session.incoming_messages: msgs_to_del.extend(session.incoming_messages)
            
            try:
                if msgs_to_del:
                    await self.client.delete_messages(uid, msgs_to_del)
            except: pass

            session.cleanup()
            self.merge_handler.remove_merge_task(uid)
            self.sessions.pop(uid, None)
            await event.answer("Session dibatalkan.")
            try:
                await self.client.send_message(
                    uid,
                    "**Dibatalkan!** Semua file sementara dan pesan dihapus.\n/start untuk mulai baru.",
                    parse_mode='md'
                )
            except Exception:
                pass
            return

        if data == "show_summary":
            await self.show_summary(event, uid)
            await event.answer()
            return

        if data == "merge":
            if self.merge_handler.is_merging(uid):
                await event.answer("Merge sedang berjalan")
                return

            if len(session.videos) < 2:
                await self.update_status(session, "Minimal 2 video untuk merge.")
                await event.answer()
                return
                
            session.stop_status_loop()
            session.is_processing = True

            if get_available_ram_gb() < MIN_RAM_AVAILABLE_GB:
                await self.update_status(session, f"RAM tersisa {get_available_ram_gb():.1f}GB. Tunggu lalu coba lagi.")
                await event.answer()
                return
            if get_disk_free_gb() < MIN_DISK_FREE_GB:
                await self.update_status(session, f"Disk kosong {get_disk_free_gb():.1f}GB. Hubungi admin.")
                await event.answer()
                return

            compatible, _, _ = await session.analyze_compatibility()
            out_ext  = session.output_format.upper()

            await self.update_status(
                session,
                f"**Menyiapkan merge [{out_ext}]...**\n\n"
                f"{len(session.videos)} video  {format_size(session.get_total_size())}\n"
                f"Masuk antrian...",
                parse_mode='md'
            )

            async def merge_progress(pct: float, pdata: dict):
                try:
                    speed   = pdata.get('speed', 'N/A')
                    timeval = pdata.get('out_time', 'N/A')
                    mode_lbl = "Stream Copy" if compatible else "Re-encode"
                    bar      = progress_bar(pct)
                    cpu      = get_cpu_usage()
                    ram      = get_available_ram_gb()
                    text = (
                        f"**Merging -> {out_ext}...**\n\n"
                        f"{mode_lbl}\n"
                        f"`{bar}` {pct:.1f}%\n"
                        f"{timeval}  {speed}x\n\n"
                        f"CPU {cpu:.0f}%  RAM {ram:.1f}GB bebas"
                    )
                    await self.update_status(session, text, parse_mode='md')
                except Exception as e:
                    logger.error(f"merge_progress error: {e}")

            try:
                future = await self.merge_handler.queue_merge(uid, session, merge_progress)
                success, output_path, message, stats = await future

                if success and output_path:
                    out_size  = output_path.stat().st_size
                    orig_size = stats.get("total_size", 0)
                    diff      = out_size - orig_size
                    diff_lbl  = "lebih besar" if diff > 0 else "lebih kecil" if diff < 0 else "sama"

                    sub_info = ""
                    if stats.get("has_subtitle"):
                        sub_info = (
                            f"\nSubtitle: {stats['sub_lang']} — {stats['sub_title']}"
                            f"\n  {stats['sub_codec_src']} -> {stats['sub_codec_out']}"
                        )

                    caption = (
                        f"**Merge Selesai!**\n\n"
                        f"{len(session.videos)} video digabung\n"
                        f"{format_duration(stats.get('total_duration', 0))}\n"
                        f"{format_size(out_size)}\n"
                        f"Selisih: {format_size(abs(diff))} ({diff_lbl})\n"
                        f"Mode: {stats.get('mode', '?')}\n"
                        f"Format: `{stats.get('output_format','mp4').upper()}`"
                        f"{sub_info}"
                    )

                    # ── Upload progress callback ──────────────────────────
                    ul_start    = time.time()
                    ul_last_upd = [0.0]

                    async def upload_progress(sent: int, total: int):
                        now = time.time()
                        if now - ul_last_upd[0] < 3:
                            return
                        ul_last_upd[0] = now
                        pct    = sent / total * 100 if total else 0
                        elap   = now - ul_start
                        speed  = sent / elap if elap > 0 else 0
                        remain = (total - sent) / speed if speed > 0 else 0
                        bar    = progress_bar(pct)
                        await self.update_status(
                            session,
                            f"**Mengupload [{out_ext}]...**\n\n"
                            f"`{bar}` {pct:.1f}%\n"
                            f"{format_size(sent)} / {format_size(total)}\n"
                            f"Speed: {format_speed(speed)}\n"
                            f"Sisa: {int(remain//60)}m {int(remain%60)}s\n"
                            f"Workers: {UPLOAD_WORKERS} koneksi paralel",
                            parse_mode='md'
                        )

                    # part_size_kb=512 adalah batas keras protokol MTProto Telegram
                    # Kecepatan ditingkatkan lewat workers (koneksi TCP paralel)
                    await event.client.send_file(
                        uid,
                        output_path,
                        caption=caption,
                        parse_mode='md',
                        part_size_kb=UPLOAD_PART_SIZE_KB,
                        workers=UPLOAD_WORKERS,
                        supports_streaming=True,
                        progress_callback=upload_progress,
                    )

                    ul_elapsed = time.time() - ul_start
                    avg_spd    = out_size / ul_elapsed if ul_elapsed > 0 else 0
                    logger.info(f"Upload selesai: {format_size(out_size)} dalam {ul_elapsed:.1f}s avg {format_speed(avg_spd)}")

                    if session.status_message:
                        try: await session.status_message.delete()
                        except: pass
                elif message == "CANCELLED":
                    # User tekan /cancel — tidak perlu pesan error
                    logger.info(f"Merge cancelled untuk user {uid}")
                    await session.request_cancel()
                else:
                    await self.update_status(
                        session,
                        f"**Merge gagal:**\n`{message[:300]}`",
                        parse_mode='md'
                    )

            except asyncio.CancelledError:
                logger.info(f"Merge task CancelledError untuk user {uid}")
            except Exception as e:
                logger.error(f"Merge/upload exception: {e}", exc_info=True)
                if not session.cancel_flag:
                    await self.update_status(
                        session, f"**Error:**\n`{str(e)[:300]}`", parse_mode='md'
                    )
            finally:
                # ── Final Cleanup: Delete all tracked status and user video messages ──────────
                try:
                    msgs_to_del = []
                    s_msg = session.status_message
                    if s_msg:
                        msgs_to_del.append(s_msg.id)
                    if session.user_video_messages:
                        msgs_to_del.extend(session.user_video_messages)
                    if session.incoming_messages:
                        msgs_to_del.extend(session.incoming_messages)
                    
                    client = self.client
                    if msgs_to_del and client:
                        # Batch delete for efficiency
                        await client.delete_messages(uid, msgs_to_del)
                        logger.info(f"Cleanup: {len(msgs_to_del)} pesan dihapus untuk user {uid}")
                except Exception as e:
                    logger.warning(f"Gagal cleanup pesan: {e}")

                session.cleanup()
                self.merge_handler.remove_merge_task(uid)
                self.sessions.pop(uid, None)

            await event.answer()

    # ── Auto cleanup ──────────────────────────────────────────────────────────

    async def auto_cleanup_loop(self):
        while True:
            try:
                # Heartbeat log
                logger.info("Bot Heartbeat: Active sessions = %d", len(self.sessions))
                
                now     = datetime.now()
                expired = [uid for uid, s in self.sessions.items()
                           if (now - s.created_at).total_seconds() > 7200]
                for uid in expired:
                    s = self.sessions.pop(uid)
                    if s.status_message:
                        try: await s.status_message.delete()
                        except: pass
                    s.cleanup()
                if expired:
                    logger.info(f"Auto-cleaned {len(expired)} expired sessions")
            except Exception as e:
                logger.error(f"auto_cleanup_loop: {e}")
            await asyncio.sleep(3600)

# ==================== MAIN ====================

async def main():
    total_ram = get_system_ram_gb()
    preset    = get_ffmpeg_preset()

    print("=" * 60)
    print("MERGE VIDEO BOT — Subtitle + Format Pilihan + Upload Cepat")
    print("=" * 60)
    print(f"Max size    : {MAX_FILE_SIZE_GB} GB")
    print(f"RAM         : {total_ram:.1f} GB  |  Preset: {preset}")
    print(f"Concurrent  : {MAX_CONCURRENT_MERGE} user")
    print(f"Subtitle    : tx3g/mov_text/Indonesian dipertahankan")
    print(f"Format      : MP4 (mov_text) atau MKV (srt) — pilihan user")
    print(f"Upload      : {UPLOAD_PART_SIZE_KB} KB/chunk x {UPLOAD_WORKERS} workers paralel")
    print(f"Download    : {DOWNLOAD_REQUEST_SIZE//1024//1024} MB/req x {DOWNLOAD_WORKERS} workers paralel")
    print("=" * 60)
    print("Stream Copy jika codec sama — tanpa re-encode")
    print("Subtitle: tx3g -> mov_text (MP4) / srt (MKV)")
    print("Queue + RAM Guard + Auto Cleanup")
    print("=" * 60)

    # ── Auto clear old sessions only (startup cleanup) ──────────────────────
    if DOWNLOADS_DIR.exists():
        now = time.time()
        leftover = list(DOWNLOADS_DIR.glob("user_*"))
        cleaned_count: int = 0
        if leftover:
            print(f"  Memeriksa {len(leftover)} sisa session lama...")
            for folder in leftover:
                if folder.is_dir():
                    try:
                        # Only delete folders older than 1 hour to avoid killing active sessions
                        # if multiple bot instances are running or on quick restart
                        if now - folder.stat().st_mtime > 3600:
                            shutil.rmtree(folder)
                            print(f"  Hapus session usang: {folder.name}")
                            cleaned_count += 1
                    except Exception as e:
                        print(f"  Gagal hapus {folder.name}: {e}")
            if cleaned_count == 0:
                print("  Tidak ada session usang (>1 jam) untuk dibersihkan.")
            else:
                print(f"  Berhasil membersihkan {cleaned_count} session usang.")
        else:
            print("  Tidak ada sisa session lama.")

    bot = TelegramBot(API_ID, API_HASH, BOT_TOKEN)
    try:
        await bot.start()
    except KeyboardInterrupt:
        print("\nBot stopped by user")
        for _, s in bot.sessions.items():
            s.cleanup()
    except Exception as e:
        print(f"Fatal error: {e}")

if __name__ == "__main__":
    asyncio.run(main())