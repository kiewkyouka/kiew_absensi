from telegram import ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
import config
import database

db = database.Database()

def has_admin_access(username):
    """Cek apakah user memiliki akses admin"""
    if not username:
        return False
    return username.lower() in [u.lower() for u in config.ADMIN_USERNAMES] or \
           username.lower() in [u.lower() for u in config.OWNER_USERNAMES]

def main_keyboard(user_id, username):
    """Generate keyboard utama berdasarkan status user"""
    # Cek status user saat ini
    active_break = db.get_user_active_break(user_id)
    today_attendance = db.get_today_attendance(user_id)
    
    # Tombol dasar yang selalu tersedia
    base_buttons = [
        ["📊 Lihat Absensi"],
        ["🆘 Bantuan"]
    ]
    
    # Tombol untuk admin
    if has_admin_access(username):
        base_buttons.append(["⚙️ Admin Panel"])
    
    # Jika user sedang istirahat, tombol utama adalah selesai istirahat
    if active_break:
        keyboard = [
            ["✅ Selesai Istirahat"],
            *base_buttons
        ]
    else:
        # Jika belum check in hari ini
        if not today_attendance or not today_attendance[1]:  # No check-in today
            main_buttons = [
                ["🟢 Masuk Kerja"],
                *base_buttons
            ]
        # Jika sudah check in tapi belum check out
        elif today_attendance and today_attendance[1] and not today_attendance[2]:
            main_buttons = [
                ["💼 Pulang Kerja", "☕ Istirahat"],
                *base_buttons
            ]
        # Jika sudah check out (hari selesai)
        else:
            main_buttons = [
                ["📊 Lihat Absensi"],
                ["🆘 Bantuan"]
            ]
            if has_admin_access(username):
                main_buttons.append(["⚙️ Admin Panel"])
        
        keyboard = main_buttons
    
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        input_field_placeholder="Pilih menu..."
    )

def break_types_keyboard():
    """Keyboard untuk memilih jenis istirahat"""
    keyboard = [
        [
            InlineKeyboardButton("🚽 Toilet", callback_data="break_toilet"),
            InlineKeyboardButton("🍽️ Makan", callback_data="break_makan")
        ],
        [
            InlineKeyboardButton("🚬 Merokok", callback_data="break_merokok"),
            InlineKeyboardButton("🕌 Sholat", callback_data="break_sholat")
        ],
        [
            InlineKeyboardButton("📋 Lainnya", callback_data="break_lainnya")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_keyboard(username):
    """Keyboard untuk admin panel"""
    keyboard = [
        [InlineKeyboardButton("⚙️ Pengaturan Sistem", callback_data="admin_settings")],
        [InlineKeyboardButton("📊 Lihat Semua Absensi", callback_data="admin_view_all")],
        [InlineKeyboardButton("👥 Data Karyawan", callback_data="admin_employees")],
        [InlineKeyboardButton("💾 Export Data", callback_data="admin_export")]
    ]
    
    # Tambahkan menu owner jika user adalah owner
    if username.lower() in [u.lower() for u in config.OWNER_USERNAMES]:
        keyboard.append([InlineKeyboardButton("👑 Owner Menu", callback_data="owner_menu")])
    
    keyboard.append([InlineKeyboardButton("↩️ Kembali", callback_data="admin_back")])
    
    return InlineKeyboardMarkup(keyboard)

def settings_keyboard():
    """Keyboard untuk pengaturan sistem"""
    keyboard = [
        [InlineKeyboardButton("🕐 Jam Mulai Kerja", callback_data="set_work_start")],
        [InlineKeyboardButton("🕔 Jam Selesai Kerja", callback_data="set_work_end")],
        [InlineKeyboardButton("⏱️ Durasi Istirahat", callback_data="set_break_times")],
        [InlineKeyboardButton("📝 Teks Notifikasi", callback_data="set_notif_texts")],
        [InlineKeyboardButton("↩️ Kembali", callback_data="settings_back")]
    ]
    return InlineKeyboardMarkup(keyboard)

def owner_keyboard():
    """Keyboard khusus untuk owner"""
    keyboard = [
        [InlineKeyboardButton("📈 Statistik Sistem", callback_data="owner_stats")],
        [InlineKeyboardButton("👥 Kelola Admin", callback_data="owner_manage_admins")],
        [InlineKeyboardButton("💾 Backup Data", callback_data="owner_backup")],
        [InlineKeyboardButton("🔄 Reset Sistem", callback_data="owner_reset")],
        [InlineKeyboardButton("↩️ Kembali", callback_data="owner_back")]
    ]
    return InlineKeyboardMarkup(keyboard)