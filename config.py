import os
from dotenv import load_dotenv

load_dotenv()

# Bot Token dari @BotFather
BOT_TOKEN = os.getenv('BOT_TOKEN', '8145711855:AAFTWzhL-OYKX7zd2IBZaiEbzPoHvFIqaKU')

# Daftar Admin berdasarkan username (tanpa @)
ADMIN_USERNAMES = ['gasomset', 'bananaboat99']  # Ganti dengan username admin

# Daftar Owner berdasarkan username (tanpa @) - memiliki akses penuh
OWNER_USERNAMES = ['bananaboat99', 'ceo_company']  # Ganti dengan username owner

# Konfigurasi default
DEFAULT_WORK_START = "08:00"
DEFAULT_WORK_END = "17:00"
TOLERANCE_LATE = 15
TOLERANCE_EARLY = 15

ALLOWED_BREAK_TYPES = {
    "toilet": 15,
    "makan": 60,
    "merokok": 10,
    "sholat": 15,
    "lainnya": 30
}

# Notifikasi default
NOTIFICATION_TEXTS = {
    "welcome": "Selamat datang di sistem absensi!",
    "checkin_success": "Absensi masuk berhasil dicatat.",
    "checkin_late": "Anda terlambat {} menit.",
    "break_start": "Istirahat {} dimulai. Durasi: {} menit.",
    "break_end": "Istirahat selesai. Durasi: {} menit {} detik.",
    "break_overdue": "Waktu istirahat sudah habis!",
    "checkout_success": "Absensi pulang berhasil dicatat.",
    "checkout_early": "Anda pulang cepat {} menit.",
    "overtime": "Lembur: {} menit.",
    "action_blocked": "⛔ Anda belum bisa melakukan aktivitas lainnya sebelum menyelesaikan istirahat yang sedang berlangsung.",
    "admin_access_denied": "❌ Akses ditolak. Hanya admin dan owner yang dapat mengakses menu ini.",
    "owner_access_denied": "❌ Akses ditolak. Hanya owner yang dapat mengakses menu ini."
}