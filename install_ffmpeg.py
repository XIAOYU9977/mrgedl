import os
import urllib.request
import zipfile
import subprocess
import sys

def install_ffmpeg():
    print("Mendownload FFmpeg...")
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z"
    zip_path = "ffmpeg.7z"
    
    # Download file
    urllib.request.urlretrieve(url, zip_path)
    
    # Ekstrak (perlu 7-Zip)
    print("Mengekstrak...")
    os.system(f'7z x {zip_path} -o"C:\\"')
    
    # Rename folder
    import glob
    folders = glob.glob("C:\\ffmpeg-*")
    if folders:
        os.rename(folders[0], "C:\\ffmpeg")
    
    # Tambah ke PATH
    print("Menambahkan ke PATH...")
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE)
    current_path = winreg.QueryValueEx(key, "PATH")[0]
    new_path = current_path + ";C:\\ffmpeg\\bin"
    winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, new_path)
    
    print("FFmpeg berhasil diinstall! Restart CMD dan jalankan bot lagi.")

if __name__ == "__main__":
    install_ffmpeg()