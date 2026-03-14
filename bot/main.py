import os
import asyncio
import logging
import shutil
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import Config
from bot.utils import get_user_temp_dir, clean_user_dir, sort_episodes
from bot.downloader import download_tg
from bot.merge import merge_video_files, cleanup_temp_files, cancel_merge
from bot.cleaner import auto_cleaner

# Logging Setup
logger = logging.getLogger(__name__)

from typing import Dict, List, Any, Optional, Union, TypedDict, cast
import asyncio

# User Session Management
# States: IDLE, DROPPING_FILES, MERGING, UPLOADING

class UserSession(TypedDict, total=False):
    files: List[str]
    mode: int
    status: str
    current_task: Optional[asyncio.Task]
    video_encoder: str
    video_bitrate: str
    audio_encoder: str
    audio_bitrate: str
    preset: str
    crf: str

user_sessions: Dict[int, UserSession] = {}

def get_session(user_id: int) -> UserSession:
    if user_id not in user_sessions:
        user_sessions[user_id] = cast(UserSession, {
            "files": [],
            "mode": 1,
            "status": "IDLE",
            "current_task": None,
            "video_encoder": "Default",
            "video_bitrate": "Default",
            "audio_encoder": "Default",
            "audio_bitrate": "Default",
            "preset": "Default",
            "crf": "Default"
        })
    return user_sessions[user_id]

bot = Client(
    "fresh_video_merge_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

@bot.on_message(filters.command("start"))
async def start_handler(client, message):
    logger.info(f"Received /start from {message.from_user.id}")
    user_id = message.from_user.id
    session = get_session(user_id)
    session["status"] = "IDLE"
    
    welcome_text = (
        "👋 **Selamat datang di BOT MERGE EPISODE!**\n\n"
        "Kirim video (MKV/MP4) yang ingin digabung.\n"
        "Bot akan otomatis mengurutkan berdasarkan nama file.\n\n"
        "**Pilih Mode Subtitle:**\n"
        "Mode 1: Softsub (Cepat, Tanpa Encode)\n"
        "Mode 2: Hardsub (Lambat, Encode)\n\n"
        "Status: **Idle**"
    )
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Mode 1 (Soft)", callback_data="set_mode_1"),
            InlineKeyboardButton("Mode 2 (Hard)", callback_data="set_mode_2")
        ]
    ])
    
    await message.reply_text(welcome_text, reply_markup=keyboard)

@bot.on_callback_query(filters.regex(r"^set_mode_(\d)$"))
async def mode_callback(client, callback_query):
    mode = int(callback_query.data.split("_")[-1])
    user_id = callback_query.from_user.id
    session = get_session(user_id)
    session["mode"] = mode
    
    await callback_query.answer(f"Mode diatur ke {mode}")
    
    text = (
        f"✅ Mode subtitle diatur ke: **Mode {mode}**\n\n"
        "📌 **Silahkan pilih menu encoding anda !**\n\n"
        f"• Video Encoder: `{session['video_encoder']}`\n"
        f"• Video Bitrate: `{session['video_bitrate']}`\n"
        f"• Audio Encoder: `{session['audio_encoder']}`\n"
        f"• Audio Bitrate: `{session['audio_bitrate']}`\n"
        f"• CRF: `{session['crf']}`\n"
        f"• Preset: `{session['preset']}`\n\n"
        "Silahkan kirim file video Anda atau buka /settings untuk mengubah konfigurasi."
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Settings Encoding", callback_data="config_main")],
        [InlineKeyboardButton("📁 Mulai Kirim File", callback_data="close_menu")]
    ])
    
    await callback_query.edit_message_text(text, reply_markup=keyboard)

@bot.on_callback_query(filters.regex(r"^config_main$"))
async def config_main_callback(client, callback_query):
    user_id = callback_query.from_user.id
    session = get_session(user_id)
    
    text = (
        "📌 **Menu Konfigurasi Encoding**\n\n"
        f"• Video Encoder: `{session['video_encoder']}`\n"
        f"• Video Bitrate: `{session['video_bitrate']}`\n"
        f"• Audio Encoder: `{session['audio_encoder']}`\n"
        f"• Audio Bitrate: `{session['audio_bitrate']}`\n"
        f"• CRF: `{session['crf']}`\n"
        f"• Preset: `{session['preset']}`"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Video Encoder", callback_data="conf_v_enc"), InlineKeyboardButton("Video Bitrate", callback_data="conf_v_bit")],
        [InlineKeyboardButton("Audio Encoder", callback_data="conf_a_enc"), InlineKeyboardButton("Audio Bitrate", callback_data="conf_a_bit")],
        [InlineKeyboardButton("CRF", callback_data="conf_crf"), InlineKeyboardButton("Preset", callback_data="conf_preset")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="close_menu")]
    ])
    
    await callback_query.edit_message_text(text, reply_markup=keyboard)

@bot.on_callback_query(filters.regex(r"^close_menu$"))
async def close_menu_callback(client, callback_query):
    await callback_query.edit_message_text("✅ Konfigurasi disimpan. Silakan kirim file video Anda.")

# --- Video Encoder Menu ---
@bot.on_callback_query(filters.regex(r"^conf_v_enc$"))
async def conf_v_enc_callback(client, callback_query):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Default", callback_data="set_v_enc_Default")],
        [InlineKeyboardButton("H.264", callback_data="set_v_enc_libx264"), InlineKeyboardButton("H.265", callback_data="set_v_enc_libx265")],
        [InlineKeyboardButton("VP8", callback_data="set_v_enc_libvpx"), InlineKeyboardButton("VP9", callback_data="set_v_enc_libvpx-vp9")],
        [InlineKeyboardButton("AV1", callback_data="set_v_enc_libaom-av1"), InlineKeyboardButton("Theora", callback_data="set_v_enc_libtheora")],
        [InlineKeyboardButton("MPEG4", callback_data="set_v_enc_mpeg4"), InlineKeyboardButton("MPEG2", callback_data="set_v_enc_mpeg2video")],
        [InlineKeyboardButton("↩️ Kembali", callback_data="config_main")]
    ])
    await callback_query.edit_message_text("📌 **Silahkan pilih video encoder anda !**", reply_markup=keyboard)

@bot.on_callback_query(filters.regex(r"^set_v_enc_(.+)$"))
async def set_v_enc_callback(client, callback_query):
    val = callback_query.matches[0].group(1)
    session = get_session(callback_query.from_user.id)
    session["video_encoder"] = val
    await config_main_callback(client, callback_query)

# --- Video Bitrate Menu ---
@bot.on_callback_query(filters.regex(r"^conf_v_bit$"))
async def conf_v_bit_callback(client, callback_query):
    rates = ["Default", "500k", "1200k", "2000k", "3000k", "4000k", "5000k", "6000k", "7000k", "8000k", "9000k", "10000k"]
    buttons = []
    for i in range(0, len(rates), 2):
        row = [InlineKeyboardButton(rates[i], callback_data=f"set_v_bit_{rates[i]}")]
        if i+1 < len(rates):
            row.append(InlineKeyboardButton(rates[i+1], callback_data=f"set_v_bit_{rates[i+1]}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("↩️ Kembali", callback_data="config_main")])
    await callback_query.edit_message_text("📌 **Silahkan pilih video bitrate anda !**", reply_markup=InlineKeyboardMarkup(buttons))

@bot.on_callback_query(filters.regex(r"^set_v_bit_(.+)$"))
async def set_v_bit_callback(client, callback_query):
    val = callback_query.matches[0].group(1)
    session = get_session(callback_query.from_user.id)
    session["video_bitrate"] = val
    await config_main_callback(client, callback_query)

# --- Audio Encoder Menu ---
@bot.on_callback_query(filters.regex(r"^conf_a_enc$"))
async def conf_a_enc_callback(client, callback_query):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Default", callback_data="set_a_enc_Default")],
        [InlineKeyboardButton("AAC", callback_data="set_a_enc_aac"), InlineKeyboardButton("MP3", callback_data="set_a_enc_libmp3lame")],
        [InlineKeyboardButton("Opus", callback_data="set_a_enc_libopus"), InlineKeyboardButton("Vorbis", callback_data="set_a_enc_libvorbis")],
        [InlineKeyboardButton("WAV", callback_data="set_a_enc_pcm_s16le"), InlineKeyboardButton("MPEG", callback_data="set_a_enc_mp2")],
        [InlineKeyboardButton("FLAC", callback_data="set_a_enc_flac"), InlineKeyboardButton("ALAC", callback_data="set_a_enc_alac")],
        [InlineKeyboardButton("↩️ Kembali", callback_data="config_main")]
    ])
    await callback_query.edit_message_text("📌 **Silahkan pilih audio encoder anda !**", reply_markup=keyboard)

@bot.on_callback_query(filters.regex(r"^set_a_enc_(.+)$"))
async def set_a_enc_callback(client, callback_query):
    val = callback_query.matches[0].group(1)
    session = get_session(callback_query.from_user.id)
    session["audio_encoder"] = val
    await config_main_callback(client, callback_query)

# --- Audio Bitrate Menu ---
@bot.on_callback_query(filters.regex(r"^conf_a_bit$"))
async def conf_a_bit_callback(client, callback_query):
    rates = ["Default", "32 kbps", "64 kbps", "96 kbps", "128 kbps", "192 kbps", "256 kbps", "320 kbps", "512 kbps"]
    buttons = []
    for i in range(0, len(rates), 2):
        row = [InlineKeyboardButton(rates[i], callback_data=f"set_a_bit_{rates[i].replace(' ', '_')}")]
        if i+1 < len(rates):
            row.append(InlineKeyboardButton(rates[i+1], callback_data=f"set_a_bit_{rates[i+1].replace(' ', '_')}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("↩️ Kembali", callback_data="config_main")])
    await callback_query.edit_message_text("📌 **Silahkan pilih audio bitrate anda !**", reply_markup=InlineKeyboardMarkup(buttons))

@bot.on_callback_query(filters.regex(r"^set_a_bit_(.+)$"))
async def set_a_bit_callback(client, callback_query):
    val = callback_query.matches[0].group(1).replace("_", " ")
    session = get_session(callback_query.from_user.id)
    session["audio_bitrate"] = val
    await config_main_callback(client, callback_query)

# --- Preset Menu ---
@bot.on_callback_query(filters.regex(r"^conf_preset$"))
async def conf_preset_callback(client, callback_query):
    presets = ["Default", "Ultrafast", "Superfast", "Veryfast", "Faster", "Fast", "Medium", "Slow", "Slower", "Veryslow"]
    buttons = []
    for i in range(0, len(presets), 2):
        row = [InlineKeyboardButton(presets[i], callback_data=f"set_preset_{presets[i]}")]
        if i+1 < len(presets):
            row.append(InlineKeyboardButton(presets[i+1], callback_data=f"set_preset_{presets[i+1]}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("↩️ Kembali", callback_data="config_main")])
    text = (
        "📌 **Silahkan pilih preset anda !**\n\n"
        "⚠️ **Note:** Semakin cepat proses kompresi, semakin besar ukuran file video"
    )
    await callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

@bot.on_callback_query(filters.regex(r"^set_preset_(.+)$"))
async def set_preset_callback(client, callback_query):
    val = callback_query.matches[0].group(1)
    session = get_session(callback_query.from_user.id)
    session["preset"] = val
    await config_main_callback(client, callback_query)

# --- CRF Menu ---
@bot.on_callback_query(filters.regex(r"^conf_crf$"))
async def conf_crf_callback(client, callback_query):
    crfs = ["Default", "18", "20", "23", "25", "28", "30"]
    buttons = []
    for i in range(0, len(crfs), 2):
        row = [InlineKeyboardButton(crfs[i], callback_data=f"set_crf_{crfs[i]}")]
        if i+1 < len(crfs):
            row.append(InlineKeyboardButton(crfs[i+1], callback_data=f"set_crf_{crfs[i+1]}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("↩️ Kembali", callback_data="config_main")])
    await callback_query.edit_message_text("📌 **Silahkan pilih CRF anda !**", reply_markup=InlineKeyboardMarkup(buttons))

@bot.on_callback_query(filters.regex(r"^set_crf_(.+)$"))
async def set_crf_callback(client, callback_query):
    val = callback_query.matches[0].group(1)
    session = get_session(callback_query.from_user.id)
    session["crf"] = val
    await config_main_callback(client, callback_query)

@bot.on_message(filters.video | filters.document)
async def file_handler(client, message):
    logger.info(f"Received file from {message.from_user.id}")
    user_id = message.from_user.id
    session = get_session(user_id)
    
    if session["status"] == "MERGING":
        return await message.reply_text("⚠️ Tunggu proses merge selesai sebelum mengirim file baru.")
    
    file = message.video or message.document
    if not file: return
    
    file_name = file.file_name
    if not (file_name.lower().endswith(".mkv") or file_name.lower().endswith(".mp4")):
        return
    
    session["status"] = "DROPPING_FILES"
    status_msg = await message.reply_text("📥 Mendownload file...")
    
    async def download_worker():
        try:
            user_dir = get_user_temp_dir(user_id)
            file_path = await download_tg(client, message, user_dir)
            
            # Validasi file size
            if os.path.getsize(str(file_path)) == 0:
                os.remove(str(file_path))
                raise Exception("File kosong (0 byte) terdeteksi.")
                
            # Ensure files is a list
            current_files = session.get("files")
            if not isinstance(current_files, list):
                current_files = []
                session["files"] = current_files
                
            current_files.append(str(file_path))
            sorted_files = list(sort_episodes(current_files))
            session["files"] = sorted_files
            
            user_files = sorted_files
            file_list_text = "\n".join([f"{i+1}. {os.path.basename(str(f))}" for i, f in enumerate(user_files)])
            
            response = (
                f"✅ **Episode diterima:**\n\n"
                f"{file_list_text}\n\n"
                f"**Total:** {len(user_files)}\n\n"
                f"Ketik /merge untuk mulai atau /cancel untuk reset."
            )
            await status_msg.edit_text(response)
        except asyncio.CancelledError:
            logger.info(f"Download task for user {user_id} was cancelled.")
            await status_msg.edit_text("❌ Download dibatalkan.")
        except Exception as e:
            logger.error(f"Download error for user {user_id}: {e}")
            await status_msg.edit_text(f"❌ Gagal: {e}")
        finally:
            session["status"] = "IDLE"
            session["current_task"] = None

    task = asyncio.create_task(download_worker())
    session["current_task"] = task

@bot.on_message(filters.command("merge"))
async def merge_handler(client, message):
    logger.info(f"Received /merge from {message.from_user.id}")
    user_id = message.from_user.id
    session = get_session(user_id)
    
    # Validasi Input
    user_files = session.get("files")
    if not isinstance(user_files, list) or not user_files:
        return await message.reply_text("❌ Kirim beberapa file dulu!")
    
    if len(user_files) < 2:
        return await message.reply_text("❌ Minimal kirim 2 file untuk digabung.")

    if session["status"] == "MERGING":
        return await message.reply_text("⚠️ Proses merge sedang berjalan...")
    
    # Cek keberadaan file fisik
    user_files = session.get("files")
    if not isinstance(user_files, list):
        user_files = []
        
    valid_files = [str(f) for f in user_files if os.path.exists(str(f)) and os.path.getsize(str(f)) > 0]
    if len(valid_files) != len(user_files):
        session["files"] = valid_files
        return await message.reply_text("⚠️ Beberapa file hilang atau rusak. Silakan kirim ulang.")

    session["status"] = "MERGING"
    status_msg = await message.reply_text("🚀 Memulai proses penggabungan...")
    
    async def merge_worker():
        try:
            mode = session["mode"]
            user_files = session.get("files", [])
            if not isinstance(user_files, list): user_files = []
            
            # Pass all encoding settings
            settings = {
                "video_encoder": session.get("video_encoder", "Default"),
                "video_bitrate": session.get("video_bitrate", "Default"),
                "audio_encoder": session.get("audio_encoder", "Default"),
                "audio_bitrate": session.get("audio_bitrate", "Default"),
                "crf": session.get("crf", "Default"),
                "preset": session.get("preset", "Default")
            }
            
            output_path = await merge_video_files(user_files, user_id, mode, status_msg, settings)
            
            if not output_path: # Cancelled or failed
                return

            session["status"] = "UPLOADING"
            await status_msg.edit_text("📤 Mengunggah hasil ke Telegram...")
            
            await client.send_video(
                chat_id=message.chat.id,
                video=output_path,
                caption=f"✅ **Merge Berhasil!**\n\nMode: {'Softsub' if mode == 1 else 'Hardsub'}\nTotal Episode: {len(user_files)}",
                supports_streaming=True
            )
            
            await status_msg.delete()
            cleanup_temp_files(user_id)
            session["files"] = []
        except asyncio.CancelledError:
            logger.info(f"Merge task for user {user_id} was cancelled.")
            cancel_merge(user_id)
            await status_msg.edit_text("❌ Proses merge dibatalkan.")
        except Exception as e:
            logger.error(f"Merge error for user {user_id}: {e}")
            await status_msg.edit_text(f"❌ Terjadi kesalahan: {e}")
        finally:
            cleanup_temp_files(user_id)
            session["status"] = "IDLE"
            session["current_task"] = None

    task = asyncio.create_task(merge_worker())
    session["current_task"] = task

@bot.on_message(filters.command("cancel"))
async def cancel_handler(client, message):
    user_id = message.from_user.id
    session = get_session(user_id)
    
    cancelled_anything = False
    
    # 1. Cancel active asyncio task
    task = cast(Optional[asyncio.Task], session.get("current_task"))
    if task and not task.done():
        task.cancel()
        cancelled_anything = True
        
    # 2. Kill FFmpeg process if any
    if cancel_merge(user_id):
        cancelled_anything = True
        
    # 3. Clean up
    cleanup_temp_files(user_id)
    session["files"] = []
    session["status"] = "IDLE"
    session["current_task"] = None
    
    msg = "🛑 **Proses dibatalkan!** Antrian Anda telah dibersihkan." if cancelled_anything else "🗑️ Antrian Anda kosong."
    await message.reply_text(msg)

@bot.on_message(filters.command("status"))
async def status_handler(client, message):
    user_id = message.from_user.id
    session = get_session(user_id)
    user_files = session.get("files", [])
    if not isinstance(user_files, list): user_files = []
    
    await message.reply_text(
        f"📊 **Status Saat Ini**\n\n"
        f"• File Antrian: {len(user_files)}\n"
        f"• Status Bot: `{session['status']}`\n"
        f"• Mode: {'Softsub' if session['mode'] == 1 else 'Hardsub'}\n\n"
        "📌 **Encoding Settings:**\n"
        f"• Video Encoder: `{session.get('video_encoder', 'Default')}`\n"
        f"• Video Bitrate: `{session.get('video_bitrate', 'Default')}`\n"
        f"• Audio Encoder: `{session.get('audio_encoder', 'Default')}`\n"
        f"• Audio Bitrate: `{session.get('audio_bitrate', 'Default')}`\n"
        f"• CRF: `{session.get('crf', 'Default')}`\n"
        f"• Preset: `{session.get('preset', 'Default')}`"
    )

@bot.on_message(filters.command("help"))
async def help_handler(client, message):
    help_text = (
        "📖 **Cara Menggunakan Bot:**\n\n"
        "1. Jalankan /start\n"
        "2. Kirim minimal 2 file video (MKV/MP4)\n"
        "3. Tunggu hingga semua file terdaftar\n"
        "4. Ketik /merge untuk mulai proses\n"
        "5. Gunakan /cancel jika ingin reset antrian\n\n"
        "Bot akan otomatis mengurutkan episode berdasarkan angka di nama file."
    )
    await message.reply_text(help_text)

@bot.on_message(filters.all)
async def debug_handler(client, message):
    logger.info(f"CATCH-ALL: Received message type {message.media} from {message.from_user.id if message.from_user else 'unknown'}")

async def start_bot():
    logger.info("Bot starting...")
    await bot.start()
    me = await bot.get_me()
    logger.info(f"Bot is online! Username: @{me.username} (ID: {me.id})")
    asyncio.create_task(auto_cleaner())
    await idle()
    await bot.stop()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.fatal(f"Bot crashed: {e}")
    finally:
        loop.close()
