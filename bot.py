import logging
import asyncio
import ast
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import database
import keyboards
import utils

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Inisialisasi scheduler
scheduler = AsyncIOScheduler()
db = database.Database()

# Dictionary untuk state pengaturan
user_settings_state = {}

def format_message_with_mention(user, message):
    """Format pesan dengan mention ke user"""
    user_name = user.full_name
    if user.username:
        mention = f"@{user.username}"
    else:
        mention = f"[{user_name}](tg://user?id={user.id})"
    
    return f"👤 {mention}\n{message}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk perintah /start"""
    user = update.effective_user
    # Daftarkan user ke database
    db.add_employee(user.id, user.username, user.full_name)
    
    welcome_text = db.get_setting('notification_texts')
    welcome_msg = "Selamat datang di sistem absensi!"
    
    try:
        notif_texts = ast.literal_eval(welcome_text)
        welcome_msg = notif_texts.get('welcome', welcome_msg)
    except:
        pass
    
    # Tampilkan pesan welcome khusus untuk admin/owner
    if keyboards.has_admin_access(user.username):
        welcome_msg += "\n\n👑 Anda login sebagai Administrator"
    
    message_with_mention = format_message_with_mention(user, f"👋 {welcome_msg}\n\nHalo {user.full_name}!")
    
    await update.message.reply_text(
        message_with_mention,
        reply_markup=keyboards.main_keyboard(user.id, user.username),
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk pesan teks"""
    user = update.effective_user
    user_id = user.id
    username = user.username
    text = update.message.text
    
    # Cek jika user sedang dalam mode pengaturan
    if user_id in user_settings_state:
        await handle_settings_input(update, context)
        return
    
    # Cek jika user sedang istirahat dan mencoba akses menu lain
    active_break = db.get_user_active_break(user_id)
    if active_break and text not in ["✅ Selesai Istirahat", "🆘 Bantuan", "/selesai_istirahat", "/help", "/start"]:
        notif_text = db.get_setting('notification_texts')
        blocked_msg = "⛔ Anda belum bisa melakukan aktivitas lainnya sebelum menyelesaikan istirahat yang sedang berlangsung."
        
        try:
            notif_texts = ast.literal_eval(notif_text)
            blocked_msg = notif_texts.get('action_blocked', blocked_msg)
        except:
            pass
        
        message_with_mention = format_message_with_mention(user, blocked_msg)
        await update.message.reply_text(message_with_mention)
        return
    
    # Handle menu berdasarkan text
    if text == "🟢 Masuk Kerja":
        await check_in(update, context)
    elif text == "💼 Pulang Kerja":
        await check_out(update, context)
    elif text == "☕ Istirahat":
        await start_break_menu(update, context)
    elif text == "✅ Selesai Istirahat":
        await end_break_command(update, context)
    elif text == "📊 Lihat Absensi":
        await view_attendance(update, context)
    elif text == "⚙️ Admin Panel":
        await admin_panel(update, context)
    elif text == "🆘 Bantuan":
        await help_command(update, context)
    else:
        # Jika pesan tidak dikenali, kirim keyboard utama
        message_with_mention = format_message_with_mention(user, "Silakan pilih menu:")
        await update.message.reply_text(
            message_with_mention,
            reply_markup=keyboards.main_keyboard(user_id, username)
        )

async def check_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk absensi masuk"""
    user = update.effective_user
    user_id = user.id
    username = user.username
    current_time = datetime.now().strftime("%H:%M:%S")
    
    success, message = db.check_in(user_id, current_time)
    
    if success:
        # Hitung keterlambatan
        work_start = db.get_setting('work_start') or config.DEFAULT_WORK_START
        late_minutes = utils.calculate_late_minutes(current_time)
        
        if late_minutes > 0:
            notif_text = db.get_setting('notification_texts')
            late_msg = f"⏰ Anda terlambat {late_minutes} menit."
            
            try:
                notif_texts = ast.literal_eval(notif_text)
                late_msg = notif_texts.get('checkin_late', '').format(late_minutes)
            except:
                pass
            
            message += f"\n{late_msg}"
        
        # Update database
        if late_minutes > 0:
            db.conn.execute('UPDATE attendance SET late_minutes = ? WHERE user_id = ? AND date = DATE("now")', 
                          (late_minutes, user_id))
            db.conn.commit()
    
    message_with_mention = format_message_with_mention(user, message)
    await update.message.reply_text(message_with_mention, reply_markup=keyboards.main_keyboard(user_id, username))

async def check_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk absensi pulang"""
    user = update.effective_user
    user_id = user.id
    username = user.username
    current_time = datetime.now().strftime("%H:%M:%S")
    
    success, message = db.check_out(user_id, current_time)
    
    if success:
        # Hitung lembur dan pulang cepat
        work_end = db.get_setting('work_end') or config.DEFAULT_WORK_END
        overtime = utils.calculate_overtime(current_time)
        early_leave = utils.calculate_early_leave(current_time)
        
        notif_text = db.get_setting('notification_texts')
        
        if overtime > 0:
            overtime_msg = f"💪 Lembur: {overtime} menit."
            try:
                notif_texts = ast.literal_eval(notif_text)
                overtime_msg = notif_texts.get('overtime', '').format(overtime)
            except:
                pass
            message += f"\n{overtime_msg}"
        
        if early_leave > 0:
            early_msg = f"🚪 Pulang cepat: {early_leave} menit."
            try:
                notif_texts = ast.literal_eval(notif_text)
                early_msg = notif_texts.get('checkout_early', '').format(early_leave)
            except:
                pass
            message += f"\n{early_msg}"
        
        # Update database
        db.conn.execute('''
            UPDATE attendance SET overtime_minutes = ?, early_leave_minutes = ? 
            WHERE user_id = ? AND date = DATE("now")
        ''', (overtime, early_leave, user_id))
        db.conn.commit()
    
    message_with_mention = format_message_with_mention(user, message)
    await update.message.reply_text(message_with_mention, reply_markup=keyboards.main_keyboard(user_id, username))

async def start_break_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan menu pilihan istirahat"""
    user = update.effective_user
    user_id = user.id
    username = user.username
    
    # Cek apakah user sudah check in hari ini
    today_attendance = db.get_today_attendance(user_id)
    if not today_attendance or not today_attendance[1]:  # No check-in today
        message_with_mention = format_message_with_mention(user, "❌ Anda harus check-in terlebih dahulu sebelum melakukan istirahat.")
        await update.message.reply_text(
            message_with_mention,
            reply_markup=keyboards.main_keyboard(user_id, username)
        )
        return
    
    message_with_mention = format_message_with_mention(user, "Pilih jenis istirahat:")
    await update.message.reply_text(
        message_with_mention,
        reply_markup=keyboards.break_types_keyboard()
    )

async def break_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk callback jenis istirahat"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_id = user.id
    username = user.username
    break_type = query.data.replace("break_", "")
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success, message = db.start_break(user_id, break_type, current_time)
    
    if success:
        # Dapatkan durasi istirahat dari settings
        break_times = db.get_setting('break_times')
        break_duration = 30  # default
        
        try:
            break_settings = ast.literal_eval(break_times)
            break_duration = break_settings.get(break_type, 30)
        except:
            # Fallback ke config default
            break_duration = config.ALLOWED_BREAK_TYPES.get(break_type, 30)
        
        notif_text = db.get_setting('notification_texts')
        break_msg = f"☕ Istirahat {break_type} dimulai. Durasi: {break_duration} menit."
        
        try:
            notif_texts = ast.literal_eval(notif_text)
            break_msg = notif_texts.get('break_start', '').format(break_type, break_duration)
        except:
            pass
        
        # Schedule reminder
        scheduler.add_job(
            send_break_reminder, 
            'date', 
            run_date=datetime.now() + timedelta(minutes=break_duration),
            args=[user_id, break_type],
            id=f"break_reminder_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        
        message_with_mention = format_message_with_mention(user, break_msg)
        await query.edit_message_text(message_with_mention)
        
        # Kirim ulang keyboard yang diperbarui
        followup_message = format_message_with_mention(user, "Silakan klik '✅ Selesai Istirahat' ketika kembali:")
        await query.message.reply_text(
            followup_message, 
            reply_markup=keyboards.main_keyboard(user_id, username)
        )
    else:
        message_with_mention = format_message_with_mention(user, "❌ Gagal memulai istirahat: " + message)
        await query.edit_message_text(message_with_mention)

async def send_break_reminder(user_id, break_type):
    """Mengirim reminder waktu istirahat habis"""
    from telegram import Bot
    bot = Bot(token=config.BOT_TOKEN)
    try:
        # Dapatkan info user dari database untuk mention
        cursor = db.conn.execute('SELECT username, full_name FROM employees WHERE user_id = ?', (user_id,))
        user_info = cursor.fetchone()
        
        if user_info:
            username, full_name = user_info
            if username:
                mention = f"@{username}"
            else:
                mention = f"[{full_name}](tg://user?id={user_id})"
            
            reminder_msg = f"👤 {mention}\n⏰ Reminder: Waktu istirahat {break_type} Anda sudah habis!\nGunakan tombol '✅ Selesai Istirahat' untuk mengakhiri."
            
            await bot.send_message(
                user_id,
                reminder_msg,
                parse_mode='Markdown'
            )
        else:
            # Fallback jika tidak ada info user
            await bot.send_message(
                user_id,
                f"⏰ Reminder: Waktu istirahat {break_type} Anda sudah habis!\nGunakan tombol '✅ Selesai Istirahat' untuk mengakhiri."
            )
    except Exception as e:
        logger.error(f"Gagal mengirim reminder ke user {user_id}: {e}")

async def end_break_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk menyelesaikan istirahat"""
    user = update.effective_user
    user_id = user.id
    username = user.username
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    success, message = db.end_break(user_id, current_time)
    
    if success:
        # Hapus reminder
        try:
            # Cari dan hapus job reminder untuk user ini
            jobs = scheduler.get_jobs()
            for job in jobs:
                if job.id.startswith(f"break_reminder_{user_id}"):
                    scheduler.remove_job(job.id)
        except Exception as e:
            logger.error(f"Gagal menghapus reminder untuk user {user_id}: {e}")
        
        # Hitung durasi dan tampilkan detail
        breaks_today = db.get_today_breaks(user_id)
        total_breaks = len(breaks_today)
        
        # Hitung durasi istirahat terakhir
        last_break = breaks_today[-1] if breaks_today else None
        if last_break:
            break_type, start_time, end_time = last_break
            start_dt = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
            end_dt = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S')
            duration = end_dt - start_dt
            minutes = duration.total_seconds() // 60
            seconds = duration.total_seconds() % 60
            
            notif_text = db.get_setting('notification_texts')
            end_msg = f"✅ Istirahat selesai. Durasi: {int(minutes)} menit {int(seconds)} detik."
            
            try:
                notif_texts = ast.literal_eval(notif_text)
                end_msg = notif_texts.get('break_end', '').format(int(minutes), int(seconds))
            except:
                pass
            
            # Hitung total istirahat per jenis (breakdown detail)
            break_counts = {}
            for break_record in breaks_today:
                br_type, _, _ = break_record
                break_counts[br_type] = break_counts.get(br_type, 0) + 1
            
            # Format detail per jenis istirahat
            break_details = []
            for br_type, count in break_counts.items():
                # Konversi nama jenis istirahat ke bahasa Indonesia yang lebih baik
                type_names = {
                    'toilet': '🚽 Toilet',
                    'makan': '🍽️ Makan', 
                    'merokok': '🚬 Merokok',
                    'sholat': '🕌 Sholat',
                    'lainnya': '📋 Lainnya'
                }
                display_name = type_names.get(br_type, br_type.capitalize())
                break_details.append(f"• {display_name}: {count} kali")
            
            detail = f"""📊 Detail Istirahat:
• Jenis: {break_type}
• Mulai: {start_time.split(' ')[1]}
• Selesai: {end_time.split(' ')[1]}
• Durasi: {int(minutes)} menit {int(seconds)} detik
• Total istirahat hari ini: {total_breaks} kali

📈 Breakdown per Jenis:
{chr(10).join(break_details)}"""
            
            message_with_mention = format_message_with_mention(user, f"{end_msg}\n{detail}")
            await update.message.reply_text(message_with_mention)
        else:
            message_with_mention = format_message_with_mention(user, "✅ Istirahat selesai.")
            await update.message.reply_text(message_with_mention)
    else:
        message_with_mention = format_message_with_mention(user, message)
        await update.message.reply_text(message_with_mention)
    
    # Kembalikan ke keyboard normal
    message_with_mention = format_message_with_mention(user, "Silakan pilih menu:")
    await update.message.reply_text(
        message_with_mention, 
        reply_markup=keyboards.main_keyboard(user_id, username)
    )

async def view_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk melihat absensi pribadi"""
    user = update.effective_user
    
    # Tampilkan opsi periode
    keyboard = [
        [InlineKeyboardButton("Hari Ini", callback_data="attendance_today")],
        [InlineKeyboardButton("Minggu Ini", callback_data="attendance_week")],
        [InlineKeyboardButton("Bulan Ini", callback_data="attendance_month")],
        [InlineKeyboardButton("Semua Data", callback_data="attendance_all")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_with_mention = format_message_with_mention(user, "📊 Pilih periode laporan absensi:")
    await update.message.reply_text(
        message_with_mention,
        reply_markup=reply_markup
    )

async def attendance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback untuk laporan absensi"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_id = user.id
    username = user.username
    period = query.data.replace("attendance_", "")
    
    today = datetime.now().date()
    
    if period == "today":
        start_date = today
        end_date = today
        title = "Hari Ini"
    elif period == "week":
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
        title = "Minggu Ini"
    elif period == "month":
        start_date = today.replace(day=1)
        if today.month == 12:
            end_date = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end_date = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        title = "Bulan Ini"
    else:  # all
        start_date = today - timedelta(days=30)
        end_date = today
        title = "30 Hari Terakhir"
    
    # Ambil data dari database
    cursor = db.conn.execute('''
        SELECT date, check_in, check_out, late_minutes, overtime_minutes, early_leave_minutes 
        FROM attendance 
        WHERE user_id = ? AND date BETWEEN ? AND ?
        ORDER BY date DESC
    ''', (user_id, start_date, end_date))
    
    records = cursor.fetchall()
    
    if not records:
        message_with_mention = format_message_with_mention(user, f"📊 Tidak ada data absensi untuk periode {title}.")
        await query.edit_message_text(message_with_mention)
        return
    
    # Format laporan dengan mention
    report = f"👤 {format_message_with_mention(user, '').split(chr(10))[0]}\n"
    report += f"📊 LAPORAN ABSENSI - {title.upper()}\n"
    report += f"Periode: {start_date} sampai {end_date}\n"
    report += "─" * 40 + "\n\n"
    
    total_kerja = 0
    total_terlambat = 0
    total_lembur = 0
    hari_kerja = 0
    
    for record in records:
        date_str, check_in, check_out, late, overtime, early_leave = record
        
        report += f"📅 {date_str}\n"
        report += f"🟢 Masuk: {check_in if check_in else 'Tidak absen'}\n"
        
        if check_out:
            report += f"🔴 Pulang: {check_out}\n"
            
            # Hitung jam kerja
            if check_in:
                masuk = datetime.strptime(check_in, '%H:%M:%S')
                pulang = datetime.strptime(check_out, '%H:%M:%S')
                jam_kerja = (pulang - masuk).total_seconds() / 3600
                total_kerja += jam_kerja
                hari_kerja += 1
                report += f"⏱️ Jam kerja: {jam_kerja:.1f} jam\n"
        
        if late and late > 0:
            report += f"⏰ Terlambat: {late} menit\n"
            total_terlambat += late
        
        if overtime and overtime > 0:
            report += f"💪 Lembur: {overtime} menit\n"
            total_lembur += overtime
            
        if early_leave and early_leave > 0:
            report += f"🚪 Pulang cepat: {early_leave} menit\n"
            
        report += "─" * 30 + "\n"
    
    # Total
    report += "\n📈 TOTAL:\n"
    report += f"• Hari kerja: {hari_kerja} hari\n"
    report += f"• Total jam kerja: {total_kerja:.1f} jam\n"
    if total_terlambat > 0:
        report += f"• Total terlambat: {total_terlambat} menit\n"
    if total_lembur > 0:
        report += f"• Total lembur: {total_lembur} menit\n"
    
    # Tambahkan tombol kembali
    back_button = InlineKeyboardButton("↩️ Kembali", callback_data="back_main")
    reply_markup = InlineKeyboardMarkup([[back_button]])
    
    await query.edit_message_text(report, reply_markup=reply_markup)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk panel admin"""
    user = update.effective_user
    
    if not keyboards.has_admin_access(user.username):
        notif_text = db.get_setting('notification_texts')
        denied_msg = "❌ Akses ditolak. Hanya admin dan owner yang dapat mengakses menu ini."
        
        try:
            notif_texts = ast.literal_eval(notif_text)
            denied_msg = notif_texts.get('admin_access_denied', denied_msg)
        except:
            pass
        
        message_with_mention = format_message_with_mention(user, denied_msg)
        await update.message.reply_text(message_with_mention)
        return
    
    message_with_mention = format_message_with_mention(user, "⚙️ Admin Panel\nPilih menu:")
    await update.message.reply_text(
        message_with_mention,
        reply_markup=keyboards.admin_keyboard(user.username)
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback untuk menu admin"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    username = user.username
    
    if not keyboards.has_admin_access(username):
        notif_text = db.get_setting('notification_texts')
        denied_msg = "❌ Akses ditolak. Hanya admin dan owner yang dapat mengakses menu ini."
        
        try:
            notif_texts = ast.literal_eval(notif_text)
            denied_msg = notif_texts.get('admin_access_denied', denied_msg)
        except:
            pass
        
        message_with_mention = format_message_with_mention(user, denied_msg)
        await query.edit_message_text(message_with_mention)
        return
    
    action = query.data
    
    if action == "admin_settings":
        message_with_mention = format_message_with_mention(user, "⚙️ Pengaturan Sistem\nPilih yang ingin diubah:")
        await query.edit_message_text(
            message_with_mention,
            reply_markup=keyboards.settings_keyboard()
        )
    elif action == "admin_view_all":
        await view_all_attendance(query)
    elif action == "admin_employees":
        await view_employees(query)
    elif action == "admin_export":
        await export_data(query)
    elif action == "owner_menu":
        await owner_panel(query)
    elif action == "admin_back" or action == "back_main":
        # SOLUSI: Hapus pesan inline dan kirim pesan baru dengan ReplyKeyboard
        if user.id in user_settings_state:
            del user_settings_state[user.id]
        
        # Hapus pesan inline keyboard
        await query.delete_message()
        
        # Kirim pesan baru dengan ReplyKeyboardMarkup
        message_with_mention = format_message_with_mention(user, "Kembali ke menu utama")
        await query.message.reply_text(
            message_with_mention,
            reply_markup=keyboards.main_keyboard(user.id, username)
        )

async def view_all_attendance(query):
    """Melihat semua absensi (admin only)"""
    user = query.from_user
    username = user.username
    today = datetime.now().date()
    cursor = db.conn.execute('''
        SELECT e.full_name, a.check_in, a.check_out, a.status, a.late_minutes, a.overtime_minutes
        FROM attendance a
        JOIN employees e ON a.user_id = e.user_id
        WHERE a.date = ?
        ORDER BY e.full_name
    ''', (today,))
    
    records = cursor.fetchall()
    
    if not records:
        message_with_mention = format_message_with_mention(user, "📊 Tidak ada data absensi hari ini.")
        await query.edit_message_text(message_with_mention)
        return
    
    report = f"👤 {format_message_with_mention(user, '').split(chr(10))[0]}\n"
    report += "📊 LAPORAN ABSENSI HARIAN (Admin)\n"
    report += f"Tanggal: {today}\n"
    report += "─" * 50 + "\n"
    
    for record in records:
        nama, check_in, check_out, status, late, overtime = record
        report += f"👤 {nama}\n"
        report += f"   🟢 Masuk: {check_in if check_in else 'Belum'}\n"
        report += f"   🔴 Pulang: {check_out if check_out else 'Belum'}\n"
        report += f"   📊 Status: {status}\n"
        
        if late and late > 0:
            report += f"   ⏰ Terlambat: {late} menit\n"
            
        if overtime and overtime > 0:
            report += f"   💪 Lembur: {overtime} menit\n"
            
        report += "─" * 30 + "\n"
    
    await query.edit_message_text(report, reply_markup=keyboards.admin_keyboard(username))

async def view_employees(query):
    """Melihat data karyawan (admin only)"""
    user = query.from_user
    username = user.username
    cursor = db.conn.execute('''
        SELECT user_id, username, full_name, department, position, is_active
        FROM employees
        ORDER BY full_name
    ''')
    
    employees = cursor.fetchall()
    
    if not employees:
        message_with_mention = format_message_with_mention(user, "👥 Tidak ada data karyawan.")
        await query.edit_message_text(message_with_mention)
        return
    
    report = f"👤 {format_message_with_mention(user, '').split(chr(10))[0]}\n"
    report += "👥 DATA KARYAWAN\n"
    report += "─" * 40 + "\n"
    
    for emp in employees:
        user_id, username, full_name, department, position, is_active = emp
        status = "Aktif" if is_active else "Non-Aktif"
        report += f"👤 {full_name}\n"
        report += f"   📧 Username: @{username if username else 'Tidak ada'}\n"
        report += f"   🏢 Dept: {department or '-'}\n"
        report += f"   💼 Posisi: {position or '-'}\n"
        report += f"   📊 Status: {status}\n"
        report += "─" * 30 + "\n"
    
    await query.edit_message_text(report, reply_markup=keyboards.admin_keyboard(username))

async def export_data(query):
    """Handler untuk export data (admin only)"""
    user = query.from_user
    username = user.username
    # Simpan data ke file (contoh sederhana)
    try:
        today = datetime.now().date()
        cursor = db.conn.execute('''
            SELECT e.full_name, a.date, a.check_in, a.check_out, a.late_minutes, a.overtime_minutes
            FROM attendance a
            JOIN employees e ON a.user_id = e.user_id
            WHERE a.date = ?
            ORDER BY e.full_name
        ''', (today,))
        
        records = cursor.fetchall()
        
        if not records:
            message_with_mention = format_message_with_mention(user, "📊 Tidak ada data absensi hari ini untuk di-export.")
            await query.edit_message_text(message_with_mention)
            return
        
        # Format data untuk export
        export_data = []
        for record in records:
            nama, date, check_in, check_out, late, overtime = record
            export_data.append({
                'nama': nama,
                'tanggal': date,
                'check_in': check_in,
                'check_out': check_out,
                'terlambat_menit': late,
                'lembur_menit': overtime
            })
        
        # Simpan ke file JSON
        export_filename = f"export_absensi_{today}.json"
        with open(export_filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        message_with_mention = format_message_with_mention(user, 
            f"✅ Export data berhasil!\n"
            f"📁 File: {export_filename}\n"
            f"📊 Total data: {len(export_data)} records\n\n"
            f"File export telah disimpan di server."
        )
        
        await query.edit_message_text(
            message_with_mention,
            reply_markup=keyboards.admin_keyboard(username)
        )
        
    except Exception as e:
        message_with_mention = format_message_with_mention(user, f"❌ Gagal melakukan export: {str(e)}")
        await query.edit_message_text(
            message_with_mention,
            reply_markup=keyboards.admin_keyboard(username)
        )

async def owner_panel(query):
    """Panel khusus owner"""
    user = query.from_user
    username = user.username
    
    if not keyboards.has_admin_access(username):
        notif_text = db.get_setting('notification_texts')
        denied_msg = "❌ Akses ditolak. Hanya admin dan owner yang dapat mengakses menu ini."
        
        try:
            notif_texts = ast.literal_eval(notif_text)
            denied_msg = notif_texts.get('admin_access_denied', denied_msg)
        except:
            pass
        
        message_with_mention = format_message_with_mention(user, denied_msg)
        await query.edit_message_text(message_with_mention)
        return
    
    message_with_mention = format_message_with_mention(user, "👑 Administrator Panel\nPilih menu:")
    await query.edit_message_text(
        message_with_mention,
        reply_markup=keyboards.owner_keyboard()
    )

async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback untuk menu owner"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    username = user.username
    
    if not keyboards.has_admin_access(username):
        notif_text = db.get_setting('notification_texts')
        denied_msg = "❌ Akses ditolak. Hanya admin dan owner yang dapat mengakses menu ini."
        
        try:
            notif_texts = ast.literal_eval(notif_text)
            denied_msg = notif_texts.get('admin_access_denied', denied_msg)
        except:
            pass
        
        message_with_mention = format_message_with_mention(user, denied_msg)
        await query.edit_message_text(message_with_mention)
        return
    
    action = query.data
    
    if action == "owner_stats":
        await show_system_stats(query)
    elif action == "owner_manage_admins":
        await manage_admins(query)
    elif action == "owner_reset":
        await confirm_system_reset(query)
    elif action == "owner_backup":
        await backup_data(query)
    elif action == "owner_back":
        message_with_mention = format_message_with_mention(user, "⚙️ Admin Panel\nPilih menu:")
        await query.edit_message_text(
            message_with_mention,
            reply_markup=keyboards.admin_keyboard(username)
        )

async def show_system_stats(query):
    """Menampilkan statistik sistem"""
    user = query.from_user
    username = user.username
    
    # Hitung total karyawan
    cursor = db.conn.execute('SELECT COUNT(*) FROM employees')
    total_employees = cursor.fetchone()[0]
    
    # Hitung total absensi hari ini
    today = datetime.now().date()
    cursor = db.conn.execute('SELECT COUNT(*) FROM attendance WHERE date = ?', (today,))
    today_attendance = cursor.fetchone()[0]
    
    # Hitung karyawan aktif
    cursor = db.conn.execute('SELECT COUNT(*) FROM employees WHERE is_active = 1')
    active_employees = cursor.fetchone()[0]
    
    # Hitung total istirahat hari ini
    cursor = db.conn.execute('SELECT COUNT(*) FROM breaks WHERE DATE(start_time) = ?', (today,))
    total_breaks = cursor.fetchone()[0]
    
    # Hitung total data dalam database
    cursor = db.conn.execute('SELECT COUNT(*) FROM attendance')
    total_attendance = cursor.fetchone()[0]
    
    cursor = db.conn.execute('SELECT COUNT(*) FROM breaks')
    total_breaks_all = cursor.fetchone()[0]
    
    stats_text = f"""👤 {format_message_with_mention(user, '').split(chr(10))[0]}
📈 **STATISTIK SISTEM** 📈

👥 **Data Karyawan:**
• Total Karyawan: {total_employees}
• Karyawan Aktif: {active_employees}
• Karyawan Non-Aktif: {total_employees - active_employees}

📊 **Absensi Hari Ini:**
• Total Absensi: {today_attendance}

⏰ **Aktivitas Hari Ini:**
• Total Istirahat: {total_breaks}

💾 **Database:**
• Total Absensi: {total_attendance} records
• Total Istirahat: {total_breaks_all} records
• Total Karyawan: {total_employees} records

🔄 **Status Sistem:**
• Database: ✅ Normal
• Scheduler: ✅ Berjalan
• Bot: ✅ Online"""
    
    await query.edit_message_text(stats_text, parse_mode='Markdown', reply_markup=keyboards.owner_keyboard())

async def manage_admins(query):
    """Kelola admin"""
    user = query.from_user
    username = user.username
    
    admin_list = "\n".join([f"• @{admin}" for admin in config.ADMIN_USERNAMES])
    owner_list = "\n".join([f"• 👑 @{owner}" for owner in config.OWNER_USERNAMES])
    
    admin_text = f"""👤 {format_message_with_mention(user, '').split(chr(10))[0]}
👥 **PENGELOLAAN ADMINISTRATOR**

**Owner saat ini:**
{owner_list}

**Admin saat ini:**
{admin_list}

**Total Akses: {len(config.ADMIN_USERNAMES) + len(config.OWNER_USERNAMES)} user**

**Perintah untuk menambah admin:**
Tambahkan username ke file config.py:

ADMIN_USERNAMES = ['username1', 'username2', 'username_baru']
OWNER_USERNAMES = ['owner1', 'owner2']

**Catatan:**
- Owner dan Admin memiliki akses penuh
- Perubahan memerlukan restart bot"""
    
    await query.edit_message_text(admin_text, parse_mode='Markdown', reply_markup=keyboards.owner_keyboard())

async def confirm_system_reset(query):
    """Konfirmasi reset sistem"""
    user = query.from_user
    username = user.username
    
    keyboard = [
        [InlineKeyboardButton("❌ Batalkan", callback_data="owner_back")],
        [InlineKeyboardButton("🔥 RESET SEMUA DATA", callback_data="owner_confirm_reset")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_with_mention = format_message_with_mention(user, 
        "⚠️ **PERINGATAN: RESET SISTEM** ⚠️\n\n"
        "Anda akan menghapus SEMUA data:\n"
        "• Data absensi\n• Data karyawan\n• Data istirahat\n• Semua pengaturan\n\n"
        "Tindakan ini TIDAK DAPAT DIBATALKAN!\n"
        "Apakah Anda yakin?"
    )
    
    await query.edit_message_text(
        message_with_mention,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def backup_data(query):
    """Backup data"""
    user = query.from_user
    username = user.username
    
    # Simpan data ke file (contoh sederhana)
    try:
        # Backup data employees
        cursor = db.conn.execute('SELECT * FROM employees')
        employees = cursor.fetchall()
        
        # Backup data attendance
        cursor = db.conn.execute('SELECT * FROM attendance')
        attendance = cursor.fetchall()
        
        # Backup data breaks
        cursor = db.conn.execute('SELECT * FROM breaks')
        breaks = cursor.fetchall()
        
        # Buat data backup
        backup_data = {
            'timestamp': datetime.now().isoformat(),
            'employees': employees,
            'attendance': attendance,
            'breaks': breaks,
            'total_records': len(employees) + len(attendance) + len(breaks)
        }
        
        # Simpan ke file
        backup_filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(backup_filename, 'w') as f:
            json.dump(backup_data, f, indent=2)
        
        message_with_mention = format_message_with_mention(user,
            f"✅ Backup berhasil!\n"
            f"📁 File: {backup_filename}\n"
            f"📊 Total data: {backup_data['total_records']} records\n\n"
            f"File backup telah disimpan di server."
        )
        
        await query.edit_message_text(
            message_with_mention,
            reply_markup=keyboards.owner_keyboard()
        )
        
    except Exception as e:
        message_with_mention = format_message_with_mention(user, f"❌ Gagal melakukan backup: {str(e)}")
        await query.edit_message_text(
            message_with_mention,
            reply_markup=keyboards.owner_keyboard()
        )

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback untuk pengaturan"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    username = user.username
    
    if not keyboards.has_admin_access(username):
        message_with_mention = format_message_with_mention(user, "❌ Akses ditolak. Hanya admin dan owner yang dapat mengakses pengaturan.")
        await query.edit_message_text(message_with_mention)
        return
    
    action = query.data
    
    if action == "set_work_start":
        user_settings_state[user.id] = {'action': 'set_work_start'}
        message_with_mention = format_message_with_mention(user, "🕐 Masukkan jam mulai kerja (format: HH:MM):\nContoh: 08:00")
        await query.edit_message_text(message_with_mention)
    elif action == "set_work_end":
        user_settings_state[user.id] = {'action': 'set_work_end'}
        message_with_mention = format_message_with_mention(user, "🕔 Masukkan jam selesai kerja (format: HH:MM):\nContoh: 17:00")
        await query.edit_message_text(message_with_mention)
    elif action == "set_break_times":
        user_settings_state[user.id] = {'action': 'set_break_times'}
        message_with_mention = format_message_with_mention(user, 
            "⏱️ Masukkan durasi istirahat (format JSON):\n"
            'Contoh: {"toilet": 15, "makan": 30, "merokok": 10, "sholat": 15, "lainnya": 20}'
        )
        await query.edit_message_text(message_with_mention)
    elif action == "set_notif_texts":
        user_settings_state[user.id] = {'action': 'set_notif_texts'}
        message_with_mention = format_message_with_mention(user,
            "📝 Masukkan teks notifikasi (format JSON):\n"
            'Contoh: {"welcome": "Selamat datang!", "checkin_late": "Anda terlambat {0} menit"}'
        )
        await query.edit_message_text(message_with_mention)
    elif action == "settings_back":
        message_with_mention = format_message_with_mention(user, "⚙️ Admin Panel\nPilih menu:")
        await query.edit_message_text(
            message_with_mention,
            reply_markup=keyboards.admin_keyboard(username)
        )

async def handle_settings_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk input pengaturan"""
    user = update.effective_user
    user_id = user.id
    username = user.username
    text = update.message.text
    
    if user_id not in user_settings_state:
        message_with_mention = format_message_with_mention(user, "Silakan pilih menu:")
        await update.message.reply_text(
            message_with_mention,
            reply_markup=keyboards.main_keyboard(user_id, username)
        )
        return
    
    action = user_settings_state[user_id]['action']
    success = False
    
    try:
        if action == "set_work_start":
            # Validasi format waktu
            if len(text) == 5 and text[2] == ':':
                hours, minutes = text.split(':')
                if hours.isdigit() and minutes.isdigit() and 0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59:
                    db.update_setting('work_start', text)
                    success = True
                    message = f"✅ Jam mulai kerja diubah menjadi: {text}"
                else:
                    message = "❌ Format waktu tidak valid. Gunakan HH:MM (contoh: 08:00)"
            else:
                message = "❌ Format tidak valid. Gunakan HH:MM (contoh: 08:00)"
                
        elif action == "set_work_end":
            if len(text) == 5 and text[2] == ':':
                hours, minutes = text.split(':')
                if hours.isdigit() and minutes.isdigit() and 0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59:
                    db.update_setting('work_end', text)
                    success = True
                    message = f"✅ Jam selesai kerja diubah menjadi: {text}"
                else:
                    message = "❌ Format waktu tidak valid. Gunakan HH:MM (contoh: 17:00)"
            else:
                message = "❌ Format tidak valid. Gunakan HH:MM (contoh: 17:00)"
                
        elif action == "set_break_times":
            try:
                # Validasi JSON
                break_times = json.loads(text)
                if isinstance(break_times, dict):
                    db.update_setting('break_times', text)
                    success = True
                    message = "✅ Durasi istirahat berhasil diubah"
                else:
                    message = "❌ Format JSON tidak valid. Harus berupa object/dictionary"
            except json.JSONDecodeError:
                message = "❌ Format JSON tidak valid. Gunakan format yang benar"
                
        elif action == "set_notif_texts":
            try:
                notif_texts = json.loads(text)
                if isinstance(notif_texts, dict):
                    db.update_setting('notification_texts', text)
                    success = True
                    message = "✅ Teks notifikasi berhasil diubah"
                else:
                    message = "❌ Format JSON tidak valid. Harus berupa object/dictionary"
            except json.JSONDecodeError:
                message = "❌ Format JSON tidak valid. Gunakan format yang benar"
                
        else:
            message = "❌ Aksi tidak dikenali"
            
    except Exception as e:
        message = f"❌ Error: {str(e)}"
    
    # Hapus state pengaturan
    if user_id in user_settings_state:
        del user_settings_state[user_id]
    
    message_with_mention = format_message_with_mention(user, message)
    await update.message.reply_text(message_with_mention)
    
    if success:
        # Kembali ke menu pengaturan
        message_with_mention = format_message_with_mention(user, "⚙️ Pengaturan Sistem\nPilih yang ingin diubah:")
        await update.message.reply_text(
            message_with_mention,
            reply_markup=keyboards.settings_keyboard()
        )
    else:
        # Kembali ke menu utama
        message_with_mention = format_message_with_mention(user, "Silakan pilih menu:")
        await update.message.reply_text(
            message_with_mention,
            reply_markup=keyboards.main_keyboard(user_id, username)
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk perintah /help"""
    user = update.effective_user
    user_id = user.id
    username = user.username
    
    help_text = """🆘 **BANTUAN SISTEM ABSENSI** 🆘

**Fitur Utama:**
🟢 **Masuk Kerja** - Absensi saat datang kerja
💼 **Pulang Kerja** - Absensi saat pulang kerja  
☕ **Istirahat** - Mulai istirahat (toilet, makan, dll)
✅ **Selesai Istirahat** - Akhiri istirahat
📊 **Lihat Absensi** - Lihat riwayat absensi pribadi

**Jenis Istirahat:**
🚽 **Toilet** - Keperluan toilet (15 menit)
🍽️ **Makan** - Istirahat makan (30 menit)  
🚬 **Merokok** - Istirahat merokok (10 menit)
🕌 **Sholat** - Istirahat sholat (15 menit)
📋 **Lainnya** - Keperluan lainnya (20 menit)

**Perintah:**
/start - Memulai bot
/help - Menampilkan bantuan ini
/selesai_istirahat - Menyelesaikan istirahat

**Admin/Owner:**
⚙️ **Admin Panel** - Menu khusus administrator

**Tips:**
- Pastikan terkoneksi internet saat absensi
- Gunakan tombol sesuai urutan aktivitas
- Hubungi admin jika ada kendala"""
    
    message_with_mention = format_message_with_mention(user, help_text)
    await update.message.reply_text(message_with_mention, parse_mode='Markdown')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk error"""
    logger.error(f"Error: {context.error}", exc_info=context.error)
    
    if update and update.effective_user:
        user = update.effective_user
        user_id = user.id
        try:
            message_with_mention = format_message_with_mention(user, "❌ Terjadi kesalahan sistem. Silakan coba lagi atau hubungi admin.")
            await context.bot.send_message(
                user_id,
                message_with_mention,
                parse_mode='Markdown'
            )
        except:
            # Fallback tanpa mention jika error
            await context.bot.send_message(
                user_id,
                "❌ Terjadi kesalahan sistem. Silakan coba lagi atau hubungi admin."
            )

def main():
    """Fungsi utama untuk menjalankan bot"""
    
    # Setup bot
    application = Application.builder().token(config.BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("selesai_istirahat", end_break_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(break_callback, pattern="^break_"))
    application.add_handler(CallbackQueryHandler(attendance_callback, pattern="^attendance_"))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(owner_callback, pattern="^owner_"))
    application.add_handler(CallbackQueryHandler(settings_callback, pattern="^set_"))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^back_"))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start scheduler
    scheduler.start()
    
    # Jalankan bot
    print("🤖 Bot absensi sedang berjalan...")
    print("Tekan Ctrl+C untuk menghentikan")
    
    application.run_polling()

if __name__ == "__main__":
    main()
