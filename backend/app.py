import sys
import os

# Wrap everything in a try-except block to capture Vercel startup errors
startup_error = None
try:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    import time
    import threading
    import csv
    import base64
    from datetime import datetime, timedelta
    from flask import Flask, Response, jsonify, request, render_template, send_file
    import cv2
    import numpy as np

    # Import custom modules
    import database as db
    from liveness import LivenessDetector
    from face_recognizer import FaceRecognizerWrapper, train_model_async, get_training_status

    # Configure path variables based on serverless execution environment
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    IS_VERCEL = os.environ.get('VERCEL') is not None

    if IS_VERCEL:
        DATASET_DIR = "/tmp/dataset"
        MODEL_DIR = "/tmp/models"
        MODEL_PATH = os.path.join(MODEL_DIR, "face_trainer.yml")
        ATTENDANCE_DIR = "/tmp/attendance"
    else:
        DATASET_DIR = os.path.join(BASE_DIR, "dataset")
        MODEL_PATH = os.path.join(BASE_DIR, "models", "face_trainer.yml")
        ATTENDANCE_DIR = os.path.join(BASE_DIR, "attendance")

    # Preload files if running on Vercel
    if IS_VERCEL:
        os.makedirs(DATASET_DIR, exist_ok=True)
        os.makedirs(MODEL_DIR, exist_ok=True)
        os.makedirs(ATTENDANCE_DIR, exist_ok=True)
        
        # Copy prebuilt model from bundle to writeable /tmp/models directory
        src_model = os.path.join(BASE_DIR, "models", "face_trainer.yml")
        if os.path.exists(src_model) and not os.path.exists(MODEL_PATH):
            import shutil
            try:
                shutil.copy2(src_model, MODEL_PATH)
            except Exception as e:
                print(f"Vercel App Init: Error copying model: {e}")

    # Initialize SQLite Database
    db.init_db()

    # Initialize Face Recognizer wrapper
    recognizer_wrapper = FaceRecognizerWrapper(MODEL_PATH)
    
except Exception as e:
    import traceback
    startup_error = traceback.format_exc()

# Initialize Flask App (always instantiate app to prevent Vercel boot failures)
BASE_DIR_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR_PATH, "frontend", "templates"),
    static_folder=os.path.join(BASE_DIR_PATH, "frontend", "static")
)

# If a startup error happened, render the traceback on all requests
if startup_error:
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def catch_all_errors(path):
        return f"""
        <html>
            <head><title>SentinelFace - Startup Error</title></head>
            <body style="font-family: sans-serif; padding: 40px; background-color: #0f172a; color: #f8fafc;">
                <h1 style="color: #ef4444; border-bottom: 2px solid #ef4444; padding-bottom: 10px;">Vercel Startup Exception</h1>
                <p>The SentinelFace serverless application failed to initialize on Vercel. See the stack trace details below:</p>
                <pre style="background-color: #1e293b; padding: 20px; border-radius: 8px; overflow-x: auto; border: 1px solid #334155; font-size: 14px; line-height: 1.5; color: #fda4af;">{startup_error}</pre>
            </body>
        </html>
        """, 500
else:
    # Sessions dictionary for tracking liveness state per browser connection
    sessions = {}
    sessions_lock = threading.Lock()

    def decode_base64_image(base64_str):
        """Decodes a base64 image string into an OpenCV BGR image."""
        if ',' in base64_str:
            base64_str = base64_str.split(',')[1]
        img_data = base64.b64decode(base64_str)
        nparr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return img

    # Page Routes
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/dashboard')
    def dashboard_redirect():
        return render_template('index.html')

    # API Endpoints
    @app.route('/api/statistics', methods=['GET'])
    def get_statistics():
        students = db.get_all_students()
        total_students = len(students)
        
        # Calculate total images in dataset
        total_images = 0
        if os.path.exists(DATASET_DIR):
            for folder in os.listdir(DATASET_DIR):
                folder_path = os.path.join(DATASET_DIR, folder)
                if os.path.isdir(folder_path):
                    total_images += len([f for f in os.listdir(folder_path) if f.lower().endswith(('.jpg', '.png', '.jpeg'))])
                    
        # Model status
        model_status = "Not Trained"
        last_modified = "N/A"
        if os.path.exists(MODEL_PATH):
            model_status = "Trained"
            mtime = os.path.getmtime(MODEL_PATH)
            last_modified = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            
        # Attendance today
        today = datetime.now().strftime("%Y-%m-%d")
        today_records = db.get_attendance_records(date_filter=today)
        attendance_today = len(today_records)
        
        # Generate 7-day attendance trend data
        trend_labels = []
        trend_data = []
        for i in range(6, -1, -1):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            day_name = (datetime.now() - timedelta(days=i)).strftime("%a")
            trend_labels.append(day_name)
            recs = db.get_attendance_records(date_filter=date_str)
            trend_data.append(len(recs))
            
        return jsonify({
            "total_students": total_students,
            "total_images": total_images,
            "model_status": model_status,
            "model_last_trained": last_modified,
            "attendance_today": attendance_today,
            "trend_labels": trend_labels,
            "trend_data": trend_data
        })

    @app.route('/api/students', methods=['GET'])
    def get_students():
        students = db.get_all_students()
        # Add image count to each student
        for s in students:
            folder_name = f"{s['id']}_{s['name'].replace(' ', '_')}"
            folder_path = os.path.join(DATASET_DIR, folder_name)
            if os.path.exists(folder_path):
                s['image_count'] = len([f for f in os.listdir(folder_path) if f.lower().endswith(('.jpg', '.png', '.jpeg'))])
            else:
                s['image_count'] = 0
        return jsonify(students)

    @app.route('/api/students', methods=['POST'])
    def register_student():
        data = request.json
        if not data or 'id' not in data or 'name' not in data:
            return jsonify({"success": False, "message": "Missing ID or Name"}), 400
            
        try:
            student_id = int(data['id'])
        except ValueError:
            return jsonify({"success": False, "message": "ID must be a number"}), 400
            
        name = data['name'].strip()
        if not name:
            return jsonify({"success": False, "message": "Name cannot be empty"}), 400
            
        success = db.add_student(student_id, name)
        if success:
            return jsonify({"success": True, "message": "Student registered successfully. Ready to capture faces."})
        else:
            return jsonify({"success": False, "message": "Student ID already exists."}), 400

    @app.route('/api/students/<int:student_id>', methods=['DELETE'])
    def delete_student(student_id):
        success = db.delete_student(student_id)
        if success:
            return jsonify({"success": True, "message": "Student record and face images deleted successfully."})
        else:
            return jsonify({"success": False, "message": "Student not found."}), 404

    @app.route('/api/train', methods=['POST'])
    def train_model():
        success, message = train_model_async(DATASET_DIR, MODEL_PATH)
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400

    @app.route('/api/train/status', methods=['GET'])
    def train_status():
        status_info = get_training_status()
        if status_info["status"] == "success":
            recognizer_wrapper.reload_model()
        return jsonify(status_info)

    @app.route('/api/attendance', methods=['GET'])
    def get_attendance():
        date_filter = request.args.get('date', None)
        name_filter = request.args.get('name', None)
        
        if date_filter == '':
            date_filter = None
        if name_filter == '':
            name_filter = None
            
        records = db.get_attendance_records(date_filter=date_filter, name_filter=name_filter)
        return jsonify(records)

    @app.route('/api/attendance/export', methods=['GET'])
    def export_attendance():
        date_filter = request.args.get('date', None)
        name_filter = request.args.get('name', None)
        
        if date_filter == '':
            date_filter = None
        if name_filter == '':
            name_filter = None
            
        records = db.get_attendance_records(date_filter=date_filter, name_filter=name_filter)
        
        os.makedirs(ATTENDANCE_DIR, exist_ok=True)
        temp_csv = os.path.join(ATTENDANCE_DIR, "export_temp.csv")
        
        try:
            with open(temp_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Student ID", "Student Name", "Date", "Time", "Liveness Verification", "Attendance Status"])
                for r in records:
                    writer.writerow([
                        r.get("student_id", ""),
                        r.get("student_name", ""),
                        r.get("date", ""),
                        r.get("time", ""),
                        r.get("liveness_status", ""),
                        r.get("status", "")
                    ])
        except Exception as e:
            print(f"Error exporting CSV: {e}")
                
        return send_file(temp_csv, as_attachment=True, download_name=f"attendance_report_{datetime.now().strftime('%Y%m%d')}.csv")

    @app.route('/api/camera/process', methods=['POST'])
    def process_camera_frame():
        """Receives, decodes, recognizes, and checks liveness on client-sent video frames."""
        data = request.json
        if not data or 'image' not in data or 'session_id' not in data:
            return jsonify({"success": False, "message": "Missing image or session ID"}), 400
            
        session_id = data['session_id']
        
        try:
            frame = decode_base64_image(data['image'])
            if frame is None:
                return jsonify({"success": False, "message": "Failed to decode image"}), 400
        except Exception as e:
            return jsonify({"success": False, "message": f"Image error: {e}"}), 400
            
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Face detection
        faces = recognizer_wrapper.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.2,
            minNeighbors=5,
            minSize=(120, 120)
        )
        
        if len(faces) == 0:
            with sessions_lock:
                if session_id in sessions:
                    del sessions[session_id]
            return jsonify({
                "face_detected": False,
                "name": "Unknown",
                "confidence": 0.0,
                "liveness_state": "BLINK",
                "liveness_message": "Waiting for face...",
                "blink_count": 0,
                "blink_verified": False,
                "movement_verified": False,
                "time_remaining": 12.0,
                "attendance_status": "Idle"
            })
            
        largest_face = max(faces, key=lambda f: f[2] * f[3])
        (x, y, w, h) = largest_face
        face_gray = gray[y:y+h, x:x+w]
        
        # Run face prediction
        predicted_id = None
        confidence = 999.0
        if recognizer_wrapper.recognizer is not None:
            predicted_id, confidence = recognizer_wrapper.predict(face_gray)
            
        students_list = db.get_all_students()
        names_mapping = {s['id']: s['name'] for s in students_list}
        predicted_name = "Unknown"
        
        if predicted_id is not None and confidence < 60:
            predicted_name = names_mapping.get(predicted_id, "Unknown")
        else:
            predicted_id = None
            
        with sessions_lock:
            if session_id not in sessions:
                sessions[session_id] = {
                    "detector": LivenessDetector(blink_target=1, timeout=12),
                    "student_id": predicted_id,
                    "attendance_status": "Idle"
                }
            session_data = sessions[session_id]
            
            if session_data["student_id"] != predicted_id:
                session_data["detector"] = LivenessDetector(blink_target=1, timeout=12)
                session_data["student_id"] = predicted_id
                session_data["attendance_status"] = "Idle"
                
        liveness_detector = session_data["detector"]
        
        eyes = recognizer_wrapper.eye_cascade.detectMultiScale(
            face_gray,
            scaleFactor=1.1,
            minNeighbors=6,
            minSize=(30, 30)
        )
        
        liveness_state = liveness_detector.update((x, y, w, h), eyes)
        prog = liveness_detector.get_progress()
        
        attendance_status = session_data["attendance_status"]
        if liveness_state == "VERIFIED":
            if predicted_id is not None:
                res = db.mark_attendance(predicted_id, predicted_name, "Verified")
                if res == "Success":
                    attendance_status = "Success (Marked)"
                elif res == "Already Marked":
                    attendance_status = "Success (Already Marked Today)"
            else:
                attendance_status = "Unknown Profile (Logs omitted)"
        elif liveness_state == "SPOOF_SUSPECTED":
            attendance_status = "Access Denied (Spoof Suspected)"
            if predicted_id is not None:
                db.mark_attendance(predicted_id, predicted_name, "SPOOF_SUSPECTED")
                
        session_data["attendance_status"] = attendance_status
        
        return jsonify({
            "face_detected": True,
            "x": int(x), "y": int(y), "w": int(w), "h": int(h),
            "name": predicted_name,
            "confidence": float(confidence),
            "liveness_state": liveness_state,
            "liveness_message": prog["message"],
            "blink_count": prog["blink_count"],
            "blink_verified": prog["blink_verified"],
            "movement_verified": prog["movement_verified"],
            "time_remaining": prog["time_remaining"],
            "attendance_status": attendance_status
        })

    @app.route('/api/camera/register', methods=['POST'])
    def register_camera_frame():
        """Receives registration video frame, crops face and saves it to directory."""
        data = request.json
        if not data or 'image' not in data or 'student_id' not in data or 'count' not in data:
            return jsonify({"success": False, "message": "Missing arguments"}), 400
            
        student_id = int(data['student_id'])
        count = int(data['count'])
        
        conn = db.get_db_connection()
        row = conn.execute("SELECT name FROM students WHERE id = ?", (student_id,)).fetchone()
        conn.close()
        
        if not row:
            return jsonify({"success": False, "message": "Student ID not found in database."}), 404
            
        student_name = row['name']
        folder_name = f"{student_id}_{student_name.replace(' ', '_')}"
        save_path = os.path.join(DATASET_DIR, folder_name)
        os.makedirs(save_path, exist_ok=True)
        
        try:
            frame = decode_base64_image(data['image'])
            if frame is None:
                return jsonify({"success": False, "message": "Failed to decode frame."}), 400
        except Exception as e:
            return jsonify({"success": False, "message": f"Image error: {e}"}), 400
            
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        faces = recognizer_wrapper.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=6,
            minSize=(120, 120)
        )
        
        if len(faces) == 0:
            return jsonify({"success": True, "face_detected": False, "message": "No face detected in capture."})
            
        largest_face = max(faces, key=lambda f: f[2] * f[3])
        (x, y, w, h) = largest_face
        face_crop = gray[y:y+h, x:x+w]
        face_crop = cv2.resize(face_crop, (200, 200))
        
        img_file = os.path.join(save_path, f"{count}.jpg")
        cv2.imwrite(img_file, face_crop)
        
        return jsonify({
            "success": True,
            "face_detected": True,
            "message": f"Captured image {count}/40",
            "x": int(x), "y": int(y), "w": int(w), "h": int(h)
        })

    @app.route('/api/camera/stop', methods=['POST'])
    def stop_camera():
        return jsonify({"success": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
