# Panduan Install Bot di VPS (via PuTTY)

Ikuti langkah-langkah di bawah ini untuk memasang bot hasil update terbaru ke VPS Ubuntu/Debian Anda.

### 1. Persiapan Awal
Login ke VPS menggunakan **PuTTY**, lalu jalankan perintah berikut untuk memastikan sistem siap:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv ffmpeg git -y
```

### 2. Clone Repository
Hapus folder lama (jika ada) dan ambil kode terbaru dari GitHub:
```bash
git clone https://github.com/XIAOYU9977/mrgedl.git
cd mrgedl
```

### 3. Buat Virtual Environment & Install Library
Gunakan venv agar tidak bentrok dengan sistem:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install telethon aiofiles psutil python-dotenv
```

### 4. Konfigurasi Token (.env)
Karena file `.env` tidak diupload ke GitHub (demi keamanan), Anda harus membuatnya manual di VPS:
```bash
nano .env
```
Lalu **Copy-Paste** data berikut (sesuaikan jika ada perubahan):
```text
API_ID=30653860
API_HASH=98e0a87077d4fc642ce183dfd7f46a19
BOT_TOKEN=8561987567:AAFOq5671NYA64qmsM1TbNcKYOpD7wJAJ6Q
```
*Tekan `CTRL+O`, `ENTER`, lalu `CTRL+X` untuk menyimpan.*

### 5. Jalankan Bot
Untuk testing, jalankan langsung:
```bash
python3 marge.py
```

### 6. Menjalankan Bot di Background (Agar tidak mati saat PuTTY ditutup)
Gunakan `screen` atau `tmux`:
```bash
# Install screen
sudo apt install screen -y

# Buka jendela baru
screen -S mergebot

# Jalankan bot
source .venv/bin/activate
python3 marge.py

# Tekan CTRL+A lalu tekan D untuk keluar dari screen (bot tetap jalan)
```

Untuk masuk kembali ke log bot nanti, ketik: `screen -r mergebot`

---
> [!IMPORTANT]
> Pastikan Anda berada di dalam folder `mrgedl` sebelum menjalankan perintah-perintah di atas.
