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
    DB_DIR = os.path.join(BASE_DIR, "attendance")
    DB_PATH = os.path.join(DB_DIR, "attendance.db")
    DATASET_DIR = os.path.join(BASE_DIR, "dataset")

# Anonymous Cloud KV Database Endpoint for serverless synchronization
KV_BUCKET = "https://kvdb.io/e05b5fa1-1b07-4e9f-863a-23d9b4b0e8c1/"

def init_db():
    """Initializes the SQLite database and creates tables if they do not exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    
    # If running on Vercel, copy pre-bundled datasets to the writable /tmp folder
    if IS_VERCEL:
        os.makedirs(DATASET_DIR, exist_ok=True)
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
    else:
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
    """Resolves student list from SQLite (when local) or Cloud KV (when serverless)."""
    students = []
    
    if not IS_VERCEL:
        try:
            conn = get_db_connection()
            rows = conn.execute("SELECT id, name, created_at FROM students").fetchall()
            students = [dict(r) for r in rows]
            conn.close()
        except Exception as e:
            print(f"SQLite get_all_students exception: {e}")
            
        if not students:
            # First-boot Fallback to folders if SQLite is empty
            src_dataset = os.path.join(BASE_DIR, "dataset")
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
                # Populate local SQLite
                if students:
                    try:
                        conn = get_db_connection()
                        for s in students:
                            conn.execute("INSERT OR REPLACE INTO students (id, name, created_at) VALUES (?, ?, ?)", (s["id"], s["name"], s["created_at"]))
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass
        return sorted(students, key=lambda x: int(x["id"]))

    # Serverless (Vercel) Flow using Cloud KV
    initialized = False
    try:
        res_init = requests.get(KV_BUCKET + "students_initialized", timeout=1.5)
        if res_init.status_code == 200 and res_init.text.strip() == "true":
            initialized = True
            
        res = requests.get(KV_BUCKET + "students", timeout=1.5)
        if res.status_code == 200:
            students = res.json()
    except Exception as e:
        print(f"Cloud KV Students Fetch Exception: {e}")
        
    if not initialized and not students:
        src_dataset = os.path.join(BASE_DIR, "dataset")
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
            try:
                requests.put(KV_BUCKET + "students_initialized", data="true", timeout=1.5)
                requests.put(KV_BUCKET + "students", data=json.dumps(students), headers={"Content-Type": "application/json"}, timeout=1.5)
            except Exception:
                pass
                    
    return sorted(students, key=lambda x: int(x["id"]))

def get_student_name(student_id):
    """Looks up a student's name by ID."""
    students = get_all_students()
    for s in students:
        if int(s["id"]) == int(student_id):
            return s["name"]
    return None

def add_student(student_id, name):
    """Registers a new student in SQLite, Cloud KV, and directories."""
    # 1. Update SQLite
    try:
        conn = get_db_connection()
        conn.execute("INSERT OR REPLACE INTO students (id, name) VALUES (?, ?)", (student_id, name))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"SQLite add_student error: {e}")
        if not IS_VERCEL:
            return False

    # 2. Update Cloud KV (only if Vercel)
    if IS_VERCEL:
        students = get_all_students()
        students = [s for s in students if int(s["id"]) != int(student_id)]
        students.append({
            "id": int(student_id),
            "name": name,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        try:
            requests.put(KV_BUCKET + "students_initialized", data="true", timeout=1.5)
            requests.put(KV_BUCKET + "students", data=json.dumps(students), headers={"Content-Type": "application/json"}, timeout=2.0)
        except Exception as e:
            print(f"Cloud KV add_student error: {e}")
        
    # 3. Create the directory
    folder_name = f"{student_id}_{name.replace(' ', '_')}"
    new_dir = os.path.join(DATASET_DIR, folder_name)
    os.makedirs(new_dir, exist_ok=True)
    return True

def delete_student(student_id):
    """Deletes a student record from SQLite, Cloud KV, and deletes their face images."""
    # 1. Delete from local SQLite
    try:
        conn = get_db_connection()
        conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"SQLite delete_student error: {e}")

    # 2. Remove from Cloud KV list (only if Vercel)
    if IS_VERCEL:
        students = get_all_students()
        students = [s for s in students if int(s["id"]) != int(student_id)]
        try:
            requests.put(KV_BUCKET + "students", data=json.dumps(students), headers={"Content-Type": "application/json"}, timeout=2.0)
        except Exception as e:
            print(f"Cloud KV delete_student error: {e}")

    # 3. Clean directories
    src_dataset = os.path.join(BASE_DIR, "dataset")
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
    """Fetches attendance records from SQLite (when local) or Cloud KV (when serverless)."""
    records = []
    
    if not IS_VERCEL:
        try:
            conn = get_db_connection()
            rows = conn.execute("SELECT student_id, student_name, date, time, liveness_status, status FROM attendance ORDER BY id DESC").fetchall()
            records = [dict(r) for r in rows]
            conn.close()
        except Exception as e:
            print(f"SQLite Fetch Exception: {e}")
    else:
        try:
            res = requests.get(KV_BUCKET + "logs", timeout=2.5)
            if res.status_code == 200:
                records = res.json()
        except Exception as e:
            print(f"Cloud KV Fetch Exception: {e}")
            
    # Apply filtering logic
    if date_filter:
        records = [r for r in records if r.get("date") == date_filter]
    if name_filter:
        records = [r for r in records if name_filter.lower() in r.get("student_name", "").lower()]
        
    return records

def mark_attendance(student_id, student_name, liveness_status):
    """Logs attendance to local SQLite, and Cloud KV (if Vercel)."""
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
    
    if not IS_VERCEL:
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
            return "Success"
        except Exception as e:
            print(f"SQLite Write Error: {e}")
            return "Error"
            
    # Serverless (Vercel) Flow using Cloud KV
    records = []
    try:
        res = requests.get(KV_BUCKET + "logs", timeout=2.0)
        if res.status_code == 200:
            records = res.json()
    except Exception:
        pass
        
    already_marked = False
    for r in records:
        if r.get("student_id") == student_id and r.get("date") == date_str and r.get("status") == "Present":
            already_marked = True
            break
            
    if already_marked and status == "Present":
        return "Already Marked"
        
    records.insert(0, new_record)
    try:
        requests.put(KV_BUCKET + "logs", data=json.dumps(records), headers={"Content-Type": "application/json"}, timeout=2.0)
    except Exception as e:
        print(f"Cloud KV Upload Error: {e}")
        
    # SQLite fallback
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO attendance (student_id, student_name, date, time, liveness_status, status) VALUES (?, ?, ?, ?, ?, ?)",
            (student_id, student_name, date_str, time_str, liveness_status, status)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
        
    return "Success"

def check_already_marked(student_id):
    """Checks if the student is already marked present today."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    
    if not IS_VERCEL:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT id FROM attendance WHERE student_id = ? AND date = ? AND status = 'Present'",
                (student_id, date_str)
            ).fetchone()
            conn.close()
            return row is not None
        except Exception:
            return False
            
    # Serverless (Vercel) flow
    try:
        res = requests.get(KV_BUCKET + "logs", timeout=2.0)
        if res.status_code == 200:
            records = res.json()
            for r in records:
                if int(r.get("student_id", 0)) == int(student_id) and r.get("date") == date_str and r.get("status") == "Present":
                    return True
    except Exception:
        pass
    return False
