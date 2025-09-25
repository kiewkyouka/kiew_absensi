from datetime import datetime, timedelta
from config import DEFAULT_WORK_START, DEFAULT_WORK_END, TOLERANCE_LATE, TOLERANCE_EARLY
import database

def calculate_late_minutes(check_in_time):
    work_start = datetime.strptime(DEFAULT_WORK_START, "%H:%M")
    check_in = datetime.strptime(check_in_time, "%H:%M:%S")
    
    if check_in > work_start:
        late_minutes = (check_in - work_start).total_seconds() / 60
        if late_minutes > TOLERANCE_LATE:
            return int(late_minutes - TOLERANCE_LATE)
    return 0

def calculate_early_leave(check_out_time):
    work_end = datetime.strptime(DEFAULT_WORK_END, "%H:%M")
    check_out = datetime.strptime(check_out_time, "%H:%M:%S")
    
    if check_out < work_end:
        early_minutes = (work_end - check_out).total_seconds() / 60
        if early_minutes > TOLERANCE_EARLY:
            return int(early_minutes - TOLERANCE_EARLY)
    return 0

def calculate_overtime(check_out_time):
    work_end = datetime.strptime(DEFAULT_WORK_END, "%H:%M")
    check_out = datetime.strptime(check_out_time, "%H:%M:%S")
    
    if check_out > work_end:
        overtime_minutes = (check_out - work_end).total_seconds() / 60
        return int(overtime_minutes)
    return 0

def format_attendance_report(records):
    if not records:
        return "Tidak ada data absensi"
    
    report = "📊 **Laporan Absensi**\n\n"
    for record in records:
        date_str, check_in, check_out, status, overtime, late = record
        report += f"📅 {date_str}\n"
        report += f"🟢 Masuk: {check_in}\n"
        report += f"🔴 Pulang: {check_out if check_out else 'Belum'}\n"
        if late > 0:
            report += f"⏰ Terlambat: {late} menit\n"
        if overtime > 0:
            report += f"💪 Lembur: {overtime} menit\n"
        report += "─" * 20 + "\n"
    
    return report

def get_break_time_limit(break_type):
    break_limits = {
        "toilet": 15, "makan": 60, "merokok": 10, 
        "sholat": 15, "lainnya": 30
    }
    return break_limits.get(break_type, 30)