import os
import sqlite3
from datetime import datetime
import re
import requests
import json

# Base directory paths
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(BACKEND_DIR)
IS_VERCEL = os.environ.get('VERCEL') is not None

if IS_VERCEL:
    DB_DIR = "/tmp/attendance"
    DB_PATH = os.path.join(DB_DIR, "attendance.db")
    DATASET_DIR = "/tmp/dataset"
else:
    DB_DIR = os.path.join(BACKEND_DIR, "attendance")
    DB_PATH = os.path.join(DB_DIR, "attendance.db")
    DATASET_DIR = os.path.join(BACKEND_DIR, "dataset")

# Anonymous Cloud KV Database Endpoint for serverless synchronization
KV_BUCKET = "https://kvdb.io/MamataAttendanceSystemV2/"

def init_db():
    """Initializes the SQLite database and creates tables if they do not exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    
    # Pre-create the directory for datasets on local machine
    if not IS_VERCEL:
        os.makedirs(DATASET_DIR, exist_ok=True)
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            student_name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            liveness_status TEXT NOT NULL,
            status TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

def get_db_connection():
    """Returns a connection to the local SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_all_students():
    """Resolves student list from Cloud KV (with folder structure fallback)."""
    students = []
    
    # 1. Try to load from Cloud KV
    try:
        res = requests.get(KV_BUCKET + "students", timeout=2.0)
        if res.status_code == 200:
            students = res.json()
    except Exception as e:
        print(f"Cloud KV Students Fetch Exception: {e}")
        
    # 2. Fallback to folder structure if Cloud KV is empty or fails
    if not students:
        src_dataset = os.path.join(BACKEND_DIR, "dataset")
        if os.path.exists(src_dataset):
            for folder in os.listdir(src_dataset):
                match = re.match(r"^(\d+)_(.+)$", folder)
                if match:
                    s_id = int(match.group(1))
                    s_name = match.group(2).replace("_", " ")
                    students.append({
                        "id": s_id,
                        "name": s_name,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    
    return sorted(students, key=lambda x: int(x["id"]))

def get_student_name(student_id):
    """Looks up a student's name by ID (Cloud KV + folder lookup)."""
    students = get_all_students()
    for s in students:
        if int(s["id"]) == int(student_id):
            return s["name"]
    return None

def add_student(student_id, name):
    """Creates a new student folder and registers them in Cloud KV."""
    # 1. Update Cloud KV students list
    students = get_all_students()
    # Check if ID already exists
    for s in students:
        if int(s["id"]) == int(student_id):
            return False
            
    students.append({
        "id": int(student_id),
        "name": name,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    try:
        requests.put(KV_BUCKET + "students", data=json.dumps(students), headers={"Content-Type": "application/json"}, timeout=2.0)
    except Exception as e:
        print(f"Cloud KV add_student error: {e}")
        
    # 2. Create the directory local to the current instance
    folder_name = f"{student_id}_{name.replace(' ', '_')}"
    new_dir = os.path.join(DATASET_DIR, folder_name)
    os.makedirs(new_dir, exist_ok=True)
    return True

def delete_student(student_id):
    """Deletes a student folder and removes them from Cloud KV."""
    # 1. Update Cloud KV students list
    students = get_all_students()
    students = [s for s in students if int(s["id"]) != int(student_id)]
    try:
        requests.put(KV_BUCKET + "students", data=json.dumps(students), headers={"Content-Type": "application/json"}, timeout=2.0)
    except Exception as e:
        print(f"Cloud KV delete_student error: {e}")

    # 2. Clean directories
    src_dataset = os.path.join(BACKEND_DIR, "dataset")
    if os.path.exists(src_dataset):
        for folder in os.listdir(src_dataset):
            if folder.startswith(f"{student_id}_"):
                import shutil
                shutil.rmtree(os.path.join(src_dataset, folder), ignore_errors=True)
                
    if os.path.exists(DATASET_DIR):
        for folder in os.listdir(DATASET_DIR):
            if folder.startswith(f"{student_id}_"):
                import shutil
                shutil.rmtree(os.path.join(DATASET_DIR, folder), ignore_errors=True)
    return True

def get_attendance_records(date_filter=None, name_filter=None):
    """Fetches attendance records from the synchronized Cloud KV store (with SQLite fallback)."""
    records = []
    
    # 1. Attempt to fetch from Cloud KV
    try:
        res = requests.get(KV_BUCKET + "logs", timeout=2.5)
        if res.status_code == 200:
            records = res.json()
    except Exception as e:
        print(f"Cloud KV Fetch Exception: {e}")
        
    # 2. Fallback to local SQLite if Cloud KV fails or is empty
    if not records:
        try:
            conn = get_db_connection()
            rows = conn.execute("SELECT * FROM attendance ORDER BY id DESC").fetchall()
            records = [dict(r) for r in rows]
            conn.close()
        except Exception as e:
            print(f"SQLite Fallback Fetch Exception: {e}")
            
    # Apply filtering logic
    if date_filter:
        records = [r for r in records if r.get("date") == date_filter]
    if name_filter:
        records = [r for r in records if name_filter.lower() in r.get("student_name", "").lower()]
        
    return records

def mark_attendance(student_id, student_name, liveness_status):
    """Logs attendance to the cloud KV store (and local SQLite fallback)."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    status = "Present" if liveness_status == "Verified" else "Absent"
    
    new_record = {
        "student_id": student_id,
        "student_name": student_name,
        "date": date_str,
        "time": time_str,
        "liveness_status": liveness_status,
        "status": status
    }
    
    # 1. Fetch current list from Cloud KV
    records = []
    try:
        res = requests.get(KV_BUCKET + "logs", timeout=2.0)
        if res.status_code == 200:
            records = res.json()
    except Exception:
        pass
        
    # Check if already marked in cloud records
    already_marked = False
    for r in records:
        if r.get("student_id") == student_id and r.get("date") == date_str and r.get("status") == "Present":
            already_marked = True
            break
            
    if already_marked and status == "Present":
        return "Already Marked"
        
    # Append and upload to Cloud KV
    records.insert(0, new_record)
    try:
        requests.put(KV_BUCKET + "logs", data=json.dumps(records), headers={"Content-Type": "application/json"}, timeout=2.0)
    except Exception as e:
        print(f"Cloud KV Upload Error: {e}")
        
    # 2. Write to local SQLite fallback
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if already marked locally
        row = cursor.execute(
            "SELECT id FROM attendance WHERE student_id = ? AND date = ? AND status = 'Present'",
            (student_id, date_str)
        ).fetchone()
        
        if row and status == "Present":
            conn.close()
            return "Already Marked"
            
        cursor.execute(
            "INSERT INTO attendance (student_id, student_name, date, time, liveness_status, status) VALUES (?, ?, ?, ?, ?, ?)",
            (student_id, student_name, date_str, time_str, liveness_status, status)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"SQLite Fallback Write Error: {e}")
        
    return "Success"
