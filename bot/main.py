import os
import asyncio
import logging
import time
from pathlib import Path
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import RPCError, FloodWait

from bot.utils import setup_logging, format_size, get_available_ram_gb, get_disk_free_gb, format_duration, get_mediainfo
from bot.progress import get_progress_text, progress_bar
from bot.downloader import Downloader
from bot.merge import (
    get_video_duration, collect_episode_files, sort_episode_order,
    generate_concat_list, merge_video_files
)
from bot.cleaner import cleanup_temp_files

# --- CONFIGURATION ---
API_ID = 30653860
API_HASH = "98e0a87077d4fc642ce183dfd7f46a19"
BOT_TOKEN = "8670555448:AAHz85JOrOjwyY_V10NvbHB_Fipx5qGuy9Y"

BASE_DIR = Path(__file__).parent.parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# System constraints - Scalable to 200 episodes
MIN_RAM_GB = 1.0
MIN_DISK_GB = 5.0
MAX_FILES = 200

# --- BOT INITIALIZATION ---
logger = setup_logging()
app = Client("merge_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
downloader = Downloader(app)

# User sessions
user_sessions = {}

# --- HELPERS ---

def get_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "files": [],
            "status": "waiting_files",
            "msg": None,
            "cancel": False,
            "last_update": 0.0,
            "format": "mkv",
            "sub_mode": "softsub",
            "recv_msg": None
        }
    return user_sessions[user_id]

async def update_status_msg(user_id, text, reply_markup=None, force=False):
    session = get_session(user_id)
    now = time.time()
    
    last_upd = session.get("last_update", 0.0)
    if not force and now - last_upd < 3:
        return
    
    session["last_update"] = float(now)
    pm = enums.ParseMode.MARKDOWN
    
    try:
        if session.get("msg"):
            await session["msg"].edit_text(text, reply_markup=reply_markup, parse_mode=pm)
        else:
            session["msg"] = await app.send_message(user_id, text, reply_markup=reply_markup, parse_mode=pm)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            await session["msg"].edit_text(text, reply_markup=reply_markup, parse_mode=pm)
        except: pass
    except Exception as e:
        logger.error(f"Failed to update status message for {user_id}: {e}")

# --- HANDLERS ---

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message: Message):
    uid = message.from_user.id
    user_sessions.pop(uid, None)
    cleanup_temp_files(uid, TEMP_DIR)
    
    await message.reply(
        "🎬 **Telegram Merge Episode Bot**\n\n"
        "Kirimkan video-video episode yang ingin Anda gabungkan.\n"
        "Setelah semua video terkirim, gunakan perintah /merge.\n\n"
        "**Perintah:**\n"
        "/merge - Mulai proses penggabungan\n"
        "/status - Cek status pengiriman file\n"
        "/cancel - Batalkan dan hapus semua file sementara",
        parse_mode=enums.ParseMode.MARKDOWN
    )

@app.on_message((filters.video | filters.document) & filters.private)
async def video_handler(client, message: Message):
    is_video = False
    if message.video:
        is_video = True
    elif message.document:
        mime = (message.document.mime_type or "").lower()
        name = (message.document.file_name or "").lower()
        if mime.startswith("video/") or "matroska" in mime or name.endswith((".mkv", ".mp4", ".mov", ".avi")):
            is_video = True
            
    if not is_video:
        return

    uid = message.from_user.id
    session = get_session(uid)
    
    if session["status"] != "waiting_files":
        await message.reply("Proses lain sedang berjalan. Harap tunggu atau gunakan /cancel.")
        return

    if len(session["files"]) >= MAX_FILES:
        await message.reply(f"Maksimal {MAX_FILES} file per penggabungan.")
        return

    session["files"].append(message)
    
    count = len(session["files"])
    text = f"✅ Video diterima ({count} file). Kirim lagi atau tekan /merge."
    
    try:
        if session.get("recv_msg"):
            await session["recv_msg"].edit_text(text)
        else:
            session["recv_msg"] = await message.reply(text)
    except:
        # Fallback if message was deleted or can't be edited
        session["recv_msg"] = await message.reply(text)

@app.on_message(filters.command("status") & filters.private)
async def status_cmd(client, message: Message):
    uid = message.from_user.id
    session = get_session(uid)
    
    count = len(session["files"])
    status = session["status"]
    
    text = (
        f"📊 **Status Bot**\n\n"
        f"Jumlah file: {count}\n"
        f"Status: {status}\n"
    )
    await message.reply(text, parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client, message: Message):
    uid = message.from_user.id
    session = get_session(uid)
    
    session["cancel"] = True
    cleanup_temp_files(uid, TEMP_DIR)
    user_sessions.pop(uid, None)
    
    await message.reply("❌ Proses dibatalkan dan file sementara telah dihapus.")

@app.on_callback_query(filters.regex(r"^mi_show"))
async def mediainfo_cb(client, cb: CallbackQuery):
    uid = cb.from_user.id
    session = get_session(uid)
    info = session.get("last_mediainfo")
    
    if not info:
        await cb.answer("❌ Informasi sudah kedaluwarsa atau file telah dihapus.", show_alert=True)
        return

    await cb.answer()
    btn = InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Tutup Info", callback_data="mi_close")]])
    await client.send_message(uid, info, reply_markup=btn, parse_mode=enums.ParseMode.MARKDOWN)

@app.on_callback_query(filters.regex(r"^mi_close"))
async def close_mi_cb(client, cb: CallbackQuery):
    await cb.message.delete()

@app.on_message(filters.command("merge") & filters.private)
async def merge_cmd(client, message: Message):
    uid = message.from_user.id
    session = get_session(uid)
    
    if not session["files"]:
        await message.reply("Kirimkan beberapa video terlebih dahulu!")
        return
    
    # Disk check
    free_gb = get_disk_free_gb(TEMP_DIR)
    if free_gb < MIN_DISK_GB:
        await message.reply(f"⚠️ Ruang disk kritis: Hanya {free_gb:.1f}GB tersisa. Harap bersihkan server.")
        return

    if session["status"] != "waiting_files":
        await message.reply("Proses sedang berjalan.")
        return

    # Choose Format
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("MKV", callback_data="fmt_mkv"), InlineKeyboardButton("MP4", callback_data="fmt_mp4")]
    ])
    await message.reply("Pilih format output:", reply_markup=btn)

@app.on_callback_query(filters.regex(r"^fmt_"))
async def fmt_cb(client, cb: CallbackQuery):
    uid = cb.from_user.id
    session = get_session(uid)
    fmt = cb.data.split("_")[1]
    session["format"] = fmt
    
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("Softsub (Copy)", callback_data="sub_softsub"), InlineKeyboardButton("Hardsub (Burn)", callback_data="sub_hardsub")]
    ])
    await cb.edit_message_text(f"Format: {fmt.upper()}\nPilih mode subtitle:", reply_markup=btn)

@app.on_callback_query(filters.regex(r"^sub_"))
async def sub_cb(client, cb: CallbackQuery):
    uid = cb.from_user.id
    session = get_session(uid)
    mode = cb.data.split("_")[1]
    session["sub_mode"] = mode
    
    await cb.edit_message_text(f"Pilihan:\nFormat: {session['format'].upper()}\nMode: {mode.upper()}\n\n⏳ **Memulai proses...**")
    asyncio.create_task(run_merge_process(uid))

async def run_merge_process(uid):
    session = get_session(uid)
    user_dir = TEMP_DIR / f"user_{uid}"
    user_dir.mkdir(exist_ok=True)
    
    try:
        session["status"] = "processing"
        
        # 1. DOWNLOAD
        downloaded_files = []
        for i, msg in enumerate(session["files"]):
            if session["cancel"]: return
            
            file_name = (msg.video.file_name if msg.video else msg.document.file_name) or f"episode_{i+1}.mp4"
            file_path = user_dir / file_name
            
            async def dl_cb(current, total, pct, text):
                await update_status_msg(uid, f"📥 **Downloading ({i+1}/{len(session['files'])})**\n\n{text}")
            
            await downloader.download_video(msg, file_path, progress_callback=dl_cb)
            
            if not file_path.exists() or file_path.stat().st_size == 0:
                await app.send_message(uid, f"❌ File {file_name} gagal didownload.")
                return
            downloaded_files.append(file_path)

        if session["cancel"]: return

        # 2. SORTING
        await update_status_msg(uid, "🔄 **Mengurutkan episode...**", force=True)
        sorted_files = sort_episode_order(downloaded_files)
        
        # 3. MERGE
        concat_list = user_dir / "list.txt"
        await generate_concat_list(sorted_files, concat_list)
        
        output_file = user_dir / f"merged_{uid}.{session['format']}"
        total_duration = 0.0
        for f in sorted_files:
            total_duration += await get_video_duration(f)
        
        async def merge_cb(pct, time_ms):
            bar = progress_bar(pct)
            await update_status_msg(uid, f"⚙️ **Merging ({session['sub_mode'].upper()})...**\n\n`{bar}` {pct:.1f}%\nDurasi: {format_duration(time_ms)}")

        success = await merge_video_files(
            concat_list, output_file, total_duration, 
            output_format=session['format'], sub_mode=session['sub_mode'], 
            progress_callback=merge_cb
        )
        
        if success and output_file.exists():
            # 4. UPLOAD
            await update_status_msg(uid, "📤 **Uploading hasil merge...**", force=True)
            
            # Extract MediaInfo before cleanup
            session["last_mediainfo"] = await get_mediainfo(output_file)
            
            async def up_cb(current, total):
                pct = (current / total * 100) if total > 0 else 0
                await update_status_msg(uid, f"📤 **Uploading...**\n\nProgress: {pct:.1f}%")

            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("📊 MediaInfo", callback_data="mi_show")]])
            
            await app.send_video(
                uid,
                video=str(output_file),
                caption=f"✅ Berhasil digabung!\nMode: {session['sub_mode'].upper()}\nFormat: {session['format'].upper()}",
                progress=up_cb,
                reply_markup=reply_markup
            )
        else:
            await app.send_message(uid, "❌ Gagal melakukan penggabungan video.")

    except Exception as e:
        logger.error(f"Error in merge process for user {uid}: {e}", exc_info=True)
        await app.send_message(uid, f"❌ Kesalahan: {str(e)}")
    finally:
        cleanup_temp_files(uid, TEMP_DIR)
        user_sessions.pop(uid, None)

if __name__ == "__main__":
    logger.info("Bot starting...")
    app.run()
