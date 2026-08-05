import os
import sqlite3
from datetime import datetime
import re

# Base directory paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_VERCEL = os.environ.get('VERCEL') is not None

if IS_VERCEL:
    DB_DIR = "/tmp/attendance"
    DB_PATH = os.path.join(DB_DIR, "attendance.db")
    DATASET_DIR = "/tmp/dataset"
else:
    DB_DIR = os.path.join(BASE_DIR, "attendance")
    DB_PATH = os.path.join(DB_DIR, "attendance.db")
    DATASET_DIR = os.path.join(BASE_DIR, "dataset")

def init_db():
    """Initializes the SQLite database and creates tables if they do not exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(DATASET_DIR, exist_ok=True)
    
    # If running on Vercel, copy pre-bundled datasets to the writable /tmp folder
    if IS_VERCEL:
        src_dataset = os.path.join(BASE_DIR, "dataset")
        if os.path.exists(src_dataset):
            import shutil
            for item in os.listdir(src_dataset):
                s = os.path.join(src_dataset, item)
                d = os.path.join(DATASET_DIR, item)
                if os.path.isdir(s) and not os.path.exists(d):
                    try:
                        shutil.copytree(s, d)
                        print(f"Vercel Init: Copied {item} to {d}")
                    except Exception as e:
                        print(f"Vercel Init: Error copying {item}: {e}")
                        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create Students table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create Attendance table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            student_name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            liveness_status TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE SET NULL
        )
    ''')
    
    conn.commit()
    conn.close()
    
    # Sync folders to DB on startup
    sync_dataset_to_db()

def get_db_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def sync_dataset_to_db():
    """Scans the dataset directory and adds missing student directories to the database."""
    if not os.path.exists(DATASET_DIR):
        return
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    folders = os.listdir(DATASET_DIR)
    for folder in folders:
        folder_path = os.path.join(DATASET_DIR, folder)
        if os.path.isdir(folder_path):
            match = re.match(r"^(\d+)_(.+)$", folder)
            if match:
                student_id = int(match.group(1))
                student_name = match.group(2).replace("_", " ")
                
                cursor.execute("SELECT id FROM students WHERE id = ?", (student_id,))
                row = cursor.fetchone()
                
                if not row:
                    cursor.execute(
                        "INSERT INTO students (id, name) VALUES (?, ?)",
                        (student_id, student_name)
                    )
                    print(f"Database Sync: Added student {student_name} (ID: {student_id}) from dataset folder.")
                    
    conn.commit()
    conn.close()

def get_all_students():
    """Returns a list of all registered students."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, created_at FROM students ORDER BY id ASC")
    rows = cursor.fetchall()
    students = [dict(row) for row in rows]
    conn.close()
    return students

def add_student(student_id, name):
    """Adds a new student to the database. Returns True if successful, False otherwise."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO students (id, name) VALUES (?, ?)", (student_id, name))
        conn.commit()
        # Create folder in dataset
        folder_name = f"{student_id}_{name.replace(' ', '_')}"
        os.makedirs(os.path.join(DATASET_DIR, folder_name), exist_ok=True)
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_student(student_id):
    """Deletes a student from the database and deletes their dataset folder."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM students WHERE id = ?", (student_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
        
    student_name = row['name']
    
    cursor.execute("DELETE FROM students WHERE id = ?", (student_id,))
    conn.commit()
    conn.close()
    
    folder_name = f"{student_id}_{student_name.replace(' ', '_')}"
    folder_path = os.path.join(DATASET_DIR, folder_name)
    if os.path.exists(folder_path):
        import shutil
        try:
            shutil.rmtree(folder_path)
            print(f"Deleted dataset folder: {folder_path}")
        except Exception as e:
            print(f"Error deleting folder {folder_path}: {e}")
            
    return True

def mark_attendance(student_id, student_name, liveness_status="Verified"):
    """Marks attendance for a student for the current day. Prevents duplicate marking on the same day."""
    today = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id FROM attendance WHERE student_id = ? AND date = ?",
        (student_id, today)
    )
    row = cursor.fetchone()
    
    if row:
        conn.close()
        return "Already Marked"
        
    cursor.execute(
        "INSERT INTO attendance (student_id, student_name, date, time, liveness_status, status) VALUES (?, ?, ?, ?, ?, ?)",
        (student_id, student_name, today, current_time, liveness_status, "Present")
    )
    conn.commit()
    conn.close()
    return "Success"

def get_attendance_records(date_filter=None, name_filter=None):
    """Returns attendance records, optionally filtered by date or student name."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT id, student_id, student_name, date, time, liveness_status, status FROM attendance WHERE 1=1"
    params = []
    
    if date_filter:
        query += " AND date = ?"
        params.append(date_filter)
        
    if name_filter:
        query += " AND student_name LIKE ?"
        params.append(f"%{name_filter}%")
        
    query += " ORDER BY date DESC, time DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    records = [dict(row) for row in rows]
    conn.close()
    return records
