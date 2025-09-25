import sqlite3
from datetime import datetime, date
import config
import ast

class Database:
    def __init__(self, db_name='absensi.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_tables()
        self.init_settings()
    
    def create_tables(self):
        # Tabel karyawan
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                department TEXT,
                position TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabel absensi
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date DATE,
                check_in TIME,
                check_out TIME,
                status TEXT DEFAULT 'normal',
                overtime_minutes INTEGER DEFAULT 0,
                late_minutes INTEGER DEFAULT 0,
                early_leave_minutes INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES employees (user_id),
                UNIQUE(user_id, date)  -- Tambahkan constraint unik
            )
        ''')
        
        # Tabel istirahat
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS breaks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                attendance_id INTEGER,
                break_type TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                scheduled_duration INTEGER,
                actual_duration INTEGER,
                is_approved INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES employees (user_id),
                FOREIGN KEY (attendance_id) REFERENCES attendance (id)
            )
        ''')
        
        # Tabel pengaturan
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    def init_settings(self):
        """Inisialisasi settings default"""
        default_settings = {
            'work_start': config.DEFAULT_WORK_START,
            'work_end': config.DEFAULT_WORK_END,
            'break_times': str(config.ALLOWED_BREAK_TYPES),
            'notification_texts': str(config.NOTIFICATION_TEXTS)
        }
        
        for key, value in default_settings.items():
            self.conn.execute('''
                INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)
            ''', (key, value))
        self.conn.commit()
    
    def get_setting(self, key):
        """Mengambil nilai setting berdasarkan key"""
        cursor = self.conn.execute('SELECT value FROM settings WHERE key = ?', (key,))
        result = cursor.fetchone()
        return result[0] if result else None
    
    def update_setting(self, key, value, description=""):
        """Memperbarui setting"""
        self.conn.execute('''
            INSERT OR REPLACE INTO settings (key, value, description, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (key, value, description))
        self.conn.commit()
    
    def add_employee(self, user_id, username, full_name, department="", position=""):
        """Menambah atau memperbarui data karyawan"""
        self.conn.execute('''
            INSERT OR REPLACE INTO employees (user_id, username, full_name, department, position)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, full_name, department, position))
        self.conn.commit()
    
    def check_in(self, user_id, check_in_time):
        """Mencatat absensi masuk"""
        today = date.today()
        
        # Cek apakah sudah check in hari ini
        cursor = self.conn.execute('''
            SELECT id, check_in FROM attendance 
            WHERE user_id = ? AND date = ?
        ''', (user_id, today))
        
        existing = cursor.fetchone()
        if existing:
            if existing[1]:  # Jika sudah check in
                return False, "❌ Anda sudah melakukan absensi masuk hari ini."
            else:
                # Update check in yang sudah ada
                self.conn.execute('''
                    UPDATE attendance SET check_in = ? WHERE id = ?
                ''', (check_in_time, existing[0]))
                self.conn.commit()
                return True, f"✅ Absensi masuk berhasil!\n⏰ Waktu: {check_in_time}"
        
        # Insert baru
        self.conn.execute('''
            INSERT INTO attendance (user_id, date, check_in, status)
            VALUES (?, ?, ?, ?)
        ''', (user_id, today, check_in_time, 'normal'))
        self.conn.commit()
        
        return True, f"✅ Absensi masuk berhasil!\n⏰ Waktu: {check_in_time}"
    
    def check_out(self, user_id, check_out_time):
        """Mencatat absensi pulang"""
        today = date.today()
        
        # Cek apakah sudah check out hari ini
        cursor = self.conn.execute('''
            SELECT id, check_in, check_out FROM attendance 
            WHERE user_id = ? AND date = ?
        ''', (user_id, today))
        
        record = cursor.fetchone()
        if not record:
            return False, "❌ Anda harus check in terlebih dahulu sebelum check out."
        
        att_id, check_in, existing_check_out = record
        
        if existing_check_out:
            return False, "❌ Anda sudah melakukan absensi pulang hari ini."
        
        if not check_in:
            return False, "❌ Anda harus check in terlebih dahulu sebelum check out."
        
        # Update check out
        self.conn.execute('''
            UPDATE attendance SET check_out = ? WHERE id = ?
        ''', (check_out_time, att_id))
        self.conn.commit()
        
        return True, f"✅ Absensi pulang berhasil!\n⏰ Waktu: {check_out_time}"
    
    def start_break(self, user_id, break_type, start_time):
        """Memulai istirahat"""
        today = date.today()
        
        # Cek apakah user sudah check in hari ini
        cursor = self.conn.execute('''
            SELECT id FROM attendance 
            WHERE user_id = ? AND date = ? AND check_in IS NOT NULL
        ''', (user_id, today))
        
        record = cursor.fetchone()
        if not record:
            return False, "❌ Anda harus check in terlebih dahulu sebelum istirahat."
        
        att_id = record[0]
        
        # Cek apakah sudah ada istirahat yang aktif
        active_break = self.get_user_active_break(user_id)
        if active_break:
            return False, "❌ Anda masih dalam istirahat yang aktif. Selesaikan terlebih dahulu."
        
        # Dapatkan durasi istirahat dari settings
        break_times_setting = self.get_setting('break_times')
        scheduled_duration = 30  # default
        
        try:
            if break_times_setting:
                break_times = ast.literal_eval(break_times_setting)
                scheduled_duration = break_times.get(break_type, 30)
            else:
                # Fallback ke config
                scheduled_duration = config.ALLOWED_BREAK_TYPES.get(break_type, 30)
        except:
            scheduled_duration = config.ALLOWED_BREAK_TYPES.get(break_type, 30)
        
        # Insert break record
        self.conn.execute('''
            INSERT INTO breaks (user_id, attendance_id, break_type, start_time, scheduled_duration)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, att_id, break_type, start_time, scheduled_duration))
        self.conn.commit()
        
        return True, "Istirahat dimulai"
    
    def end_break(self, user_id, end_time):
        """Mengakhiri istirahat"""
        # Cari break yang masih aktif
        cursor = self.conn.execute('''
            SELECT id, start_time, break_type FROM breaks 
            WHERE user_id = ? AND end_time IS NULL 
            ORDER BY start_time DESC LIMIT 1
        ''', (user_id,))
        
        record = cursor.fetchone()
        if not record:
            return False, "❌ Tidak ada istirahat yang aktif."
        
        break_id, start_time, break_type = record
        
        # Hitung durasi aktual
        start_dt = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
        end_dt = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S')
        actual_duration = (end_dt - start_dt).total_seconds() / 60  # dalam menit
        
        # Update break record
        self.conn.execute('''
            UPDATE breaks SET end_time = ?, actual_duration = ? 
            WHERE id = ?
        ''', (end_time, actual_duration, break_id))
        self.conn.commit()
        
        return True, "Istirahat selesai"
    
    def get_user_active_break(self, user_id):
        """Cek apakah user sedang dalam istirahat"""
        cursor = self.conn.execute('''
            SELECT id, break_type, start_time FROM breaks 
            WHERE user_id = ? AND end_time IS NULL
        ''', (user_id,))
        return cursor.fetchone()
    
    def get_today_breaks(self, user_id):
        """Ambil semua istirahat hari ini untuk user tertentu"""
        today = date.today()
        cursor = self.conn.execute('''
            SELECT break_type, start_time, end_time 
            FROM breaks 
            WHERE user_id = ? AND DATE(start_time) = ?
            ORDER BY start_time
        ''', (user_id, today))
        return cursor.fetchall()
    
    def get_today_attendance(self, user_id):
        """Ambil data absensi hari ini untuk user tertentu"""
        today = date.today()
        cursor = self.conn.execute('''
            SELECT date, check_in, check_out, status 
            FROM attendance 
            WHERE user_id = ? AND date = ?
        ''', (user_id, today))
        return cursor.fetchone()
    
    def get_attendance_records(self, user_id, start_date, end_date):
        """Ambil data absensi dalam rentang tanggal"""
        cursor = self.conn.execute('''
            SELECT date, check_in, check_out, late_minutes, overtime_minutes, early_leave_minutes 
            FROM attendance 
            WHERE user_id = ? AND date BETWEEN ? AND ?
            ORDER BY date DESC
        ''', (user_id, start_date, end_date))
        return cursor.fetchall()
    
    def get_all_employees(self):
        """Ambil semua data karyawan"""
        cursor = self.conn.execute('''
            SELECT user_id, username, full_name, department, position, is_active
            FROM employees
            ORDER BY full_name
        ''')
        return cursor.fetchall()
    
    def get_today_attendance_all(self):
        """Ambil semua absensi hari ini (untuk admin)"""
        today = date.today()
        cursor = self.conn.execute('''
            SELECT e.full_name, a.check_in, a.check_out, a.status, a.late_minutes, a.overtime_minutes
            FROM attendance a
            JOIN employees e ON a.user_id = e.user_id
            WHERE a.date = ?
            ORDER BY e.full_name
        ''', (today,))
        return cursor.fetchall()
    
    def get_employee_by_username(self, username):
        """Cari karyawan berdasarkan username"""
        cursor = self.conn.execute('''
            SELECT user_id, username, full_name, department, position, is_active
            FROM employees
            WHERE username = ?
        ''', (username,))
        return cursor.fetchone()
    
    def update_employee(self, user_id, department=None, position=None, is_active=None):
        """Update data karyawan"""
        query = 'UPDATE employees SET '
        params = []
        
        if department is not None:
            query += 'department = ?, '
            params.append(department)
        if position is not None:
            query += 'position = ?, '
            params.append(position)
        if is_active is not None:
            query += 'is_active = ?, '
            params.append(is_active)
        
        # Hapus koma terakhir dan tambahkan WHERE clause
        query = query.rstrip(', ') + ' WHERE user_id = ?'
        params.append(user_id)
        
        self.conn.execute(query, params)
        self.conn.commit()
    
    def delete_employee(self, user_id):
        """Hapus karyawan (soft delete)"""
        self.conn.execute('''
            UPDATE employees SET is_active = 0 WHERE user_id = ?
        ''', (user_id,))
        self.conn.commit()
    
    def get_system_stats(self):
        """Ambil statistik sistem"""
        stats = {}
        
        # Total karyawan
        cursor = self.conn.execute('SELECT COUNT(*) FROM employees')
        stats['total_employees'] = cursor.fetchone()[0]
        
        # Karyawan aktif
        cursor = self.conn.execute('SELECT COUNT(*) FROM employees WHERE is_active = 1')
        stats['active_employees'] = cursor.fetchone()[0]
        
        # Absensi hari ini
        today = date.today()
        cursor = self.conn.execute('SELECT COUNT(*) FROM attendance WHERE date = ?', (today,))
        stats['today_attendance'] = cursor.fetchone()[0]
        
        # Total absensi
        cursor = self.conn.execute('SELECT COUNT(*) FROM attendance')
        stats['total_attendance'] = cursor.fetchone()[0]
        
        # Istirahat hari ini
        cursor = self.conn.execute('SELECT COUNT(*) FROM breaks WHERE DATE(start_time) = ?', (today,))
        stats['today_breaks'] = cursor.fetchone()[0]
        
        # Total istirahat
        cursor = self.conn.execute('SELECT COUNT(*) FROM breaks')
        stats['total_breaks'] = cursor.fetchone()[0]
        
        return stats
    
    def export_attendance_data(self, start_date, end_date):
        """Export data absensi untuk periode tertentu"""
        cursor = self.conn.execute('''
            SELECT e.full_name, a.date, a.check_in, a.check_out, a.late_minutes, a.overtime_minutes
            FROM attendance a
            JOIN employees e ON a.user_id = e.user_id
            WHERE a.date BETWEEN ? AND ?
            ORDER BY a.date, e.full_name
        ''', (start_date, end_date))
        
        return cursor.fetchall()
    
    def reset_database(self):
        """Reset semua data (hati-hati!)"""
        # Hapus semua data tapi pertahankan struktur tabel
        self.conn.execute('DELETE FROM breaks')
        self.conn.execute('DELETE FROM attendance')
        self.conn.execute('DELETE FROM employees')
        self.conn.execute('DELETE FROM settings')
        
        # Re-initialize settings
        self.init_settings()
        self.conn.commit()

# Inisialisasi database
db = Database()