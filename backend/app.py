import os
import time
import threading
import csv
from datetime import datetime, timedelta
from flask import Flask, Response, jsonify, request, render_template, send_file
import cv2
import numpy as np

# Import custom modules
import database as db
from liveness import LivenessDetector
from face_recognizer import FaceRecognizerWrapper, train_model_async, get_training_status

# Configure path variables
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
MODEL_PATH = os.path.join(BASE_DIR, "models", "face_trainer.yml")
ATTENDANCE_DIR = os.path.join(BASE_DIR, "attendance")

# Initialize SQLite Database
db.init_db()

# Initialize Flask App
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "frontend", "templates"),
    static_folder=os.path.join(BASE_DIR, "frontend", "static")
)

# Initialize Face Recognizer wrapper
recognizer_wrapper = FaceRecognizerWrapper(MODEL_PATH)

# Thread-safe Camera Manager
class CameraManager:
    def __init__(self):
        self.cap = None
        self.active_stream = None  # "recognition" or "registration"
        self.lock = threading.Lock()

    def get_cap(self, stream_type):
        with self.lock:
            if self.cap is not None and self.active_stream != stream_type:
                self.cap.release()
                self.cap = None
                time.sleep(0.5)  # Allow camera hardware reset
            
            if self.cap is None:
                self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Use DirectShow on Windows for faster startup
                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(0)  # Fallback
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            
            self.active_stream = stream_type
            return self.cap

    def release(self):
        with self.lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            self.active_stream = None

camera_manager = CameraManager()

# Global state for active recognition stream
recognition_state = {
    "face_detected": False,
    "student_id": None,
    "name": "Unknown",
    "confidence": 0.0,
    "liveness_state": "BLINK",
    "liveness_message": "Waiting for face...",
    "blink_count": 0,
    "blink_verified": False,
    "movement_verified": False,
    "time_remaining": 12.0,
    "attendance_status": "Idle"  # "Idle", "Marked", "Already Marked"
}
recognition_state_lock = threading.Lock()

def update_recognition_state(**kwargs):
    with recognition_state_lock:
        for k, v in kwargs.items():
            recognition_state[k] = v

def get_recognition_state():
    with recognition_state_lock:
        return recognition_state.copy()

# Page Route
@app.route('/')
def index():
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
    # Reload model on success
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
    
    # Save to CSV using python's built-in csv module to bypass pandas DLL blocks
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

@app.route('/api/camera/status', methods=['GET'])
def camera_status():
    return jsonify(get_recognition_state())

@app.route('/api/camera/stop', methods=['POST'])
def stop_camera():
    camera_manager.release()
    update_recognition_state(
        face_detected=False,
        name="Unknown",
        liveness_message="Camera Stopped.",
        liveness_state="OFFLINE",
        attendance_status="Idle"
    )
    return jsonify({"success": True})

# --- VIDEO STREAMING GENERATORS ---

def generate_recognition_frames():
    """Generates processed video frames for real-time Face Recognition & Liveness Detection."""
    cap = camera_manager.get_cap("recognition")
    if not cap or not cap.isOpened():
        print("Camera recognition: Failed to open device.")
        return
        
    liveness_detector = None
    tracked_student_id = None
    tracked_student_name = "Unknown"
    consecutive_no_face = 0
    
    # Cache mapping of ID to Name from DB
    students_list = db.get_all_students()
    names_mapping = {s['id']: s['name'] for s in students_list}

    print("Recognition stream: Started generating frames.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        # Flip horizontally for a mirror effect (more natural)
        frame = cv2.flip(frame, 1)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Face Detection
        faces = recognizer_wrapper.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.2,
            minNeighbors=5,
            minSize=(120, 120)
        )
        
        if len(faces) == 0:
            consecutive_no_face += 1
            if consecutive_no_face > 15:
                # Reset liveness checker if no face seen for 15 frames
                liveness_detector = None
                tracked_student_id = None
                tracked_student_name = "Unknown"
                update_recognition_state(
                    face_detected=False,
                    student_id=None,
                    name="Unknown",
                    confidence=0.0,
                    liveness_state="BLINK",
                    liveness_message="Waiting for face...",
                    blink_count=0,
                    blink_verified=False,
                    movement_verified=False,
                    time_remaining=12.0,
                    attendance_status="Idle"
                )
        else:
            consecutive_no_face = 0
            # Process only the largest face in the frame
            largest_face = max(faces, key=lambda f: f[2] * f[3])
            (x, y, w, h) = largest_face
            
            face_gray = gray[y:y+h, x:x+w]
            face_color = frame[y:y+h, x:x+w]
            
            # Predict identity
            predicted_id = None
            confidence = 999.0
            
            if recognizer_wrapper.recognizer is not None:
                predicted_id, confidence = recognizer_wrapper.predict(face_gray)
                
            # Parse student name
            predicted_name = "Unknown"
            if predicted_id is not None and confidence < 60:  # Threshold for LBPH (lower is better match)
                predicted_name = names_mapping.get(predicted_id, "Unknown")
            else:
                predicted_id = None  # Reset if confidence too high (weak match)
                
            # Initialize or update liveness detector for this face
            if liveness_detector is None or tracked_student_id != predicted_id:
                liveness_detector = LivenessDetector(blink_target=1, timeout=12)
                tracked_student_id = predicted_id
                tracked_student_name = predicted_name
                update_recognition_state(attendance_status="Idle")
                
            # Detect eyes inside cropped face region for blink check
            eyes = recognizer_wrapper.eye_cascade.detectMultiScale(
                face_gray,
                scaleFactor=1.1,
                minNeighbors=6,
                minSize=(30, 30)
            )
            
            # Update Liveness state-machine
            liveness_state = liveness_detector.update((x, y, w, h), eyes)
            prog = liveness_detector.get_progress()
            
            # Trigger attendance if verified and not anonymous
            attendance_status = "Pending Verification"
            if liveness_state == "VERIFIED":
                if tracked_student_id is not None:
                    res = db.mark_attendance(tracked_student_id, tracked_student_name, "Verified")
                    if res == "Success":
                        attendance_status = f"Success (Marked)"
                    elif res == "Already Marked":
                        attendance_status = f"Success (Already Marked Today)"
                else:
                    attendance_status = "Unknown Student (Cannot mark)"
            elif liveness_state == "SPOOF_SUSPECTED":
                attendance_status = "Access Denied (Spoof Flagged)"
                if tracked_student_id is not None:
                    # Log spoof attempts in DB
                    db.mark_attendance(tracked_student_id, tracked_student_name, "SPOOF_SUSPECTED")
                    
            # Update global state for REST API
            update_recognition_state(
                face_detected=True,
                student_id=tracked_student_id,
                name=tracked_student_name,
                confidence=confidence,
                liveness_state=liveness_state,
                liveness_message=prog["message"],
                blink_count=prog["blink_count"],
                blink_verified=prog["blink_verified"],
                movement_verified=prog["movement_verified"],
                time_remaining=prog["time_remaining"],
                attendance_status=attendance_status
            )
            
            # --- Draw overlays on frame ---
            # Theme Colors: Green=Verified, Red=Spoof, Blue=Blink, Yellow=Movement
            if liveness_state == "VERIFIED":
                color = (46, 117, 89) # Emerald Green (BGR)
                lbl = f"{tracked_student_name} [LIVE]"
            elif liveness_state == "SPOOF_SUSPECTED":
                color = (59, 59, 225) # Rose Red (BGR)
                lbl = "SPOOF DETECTED!"
            elif liveness_state == "MOVEMENT":
                color = (0, 204, 255) # Bright Yellow (BGR)
                lbl = "Please move head"
            else:
                color = (235, 120, 30) # Soft Blue (BGR)
                lbl = "Blink your eyes"
                
            # Face Bounding Box
            cv2.rectangle(frame, (x, y), (x+w, y+h), color, 3)
            
            # Header Label background
            cv2.rectangle(frame, (x - 2, y - 35), (x + w + 2, y), color, cv2.FILLED)
            cv2.putText(
                frame,
                lbl,
                (x + 5, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA
            )
            
            # Draw eye bounding boxes if in Blink step to show active scanning
            if liveness_state == "BLINK":
                for (ex, ey, ew, eh) in eyes:
                    cv2.rectangle(frame, (x + ex, y + ey), (x + ex + ew, y + ey + eh), (0, 255, 0), 1)

        # Encode frame as JPEG
        ret, jpeg = cv2.imencode('.jpg', frame)
        if not ret:
            continue
            
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n\r\n')
        
        time.sleep(0.03)  # Limit output to ~30 FPS

def generate_registration_frames(student_id):
    """Generates processed video frames for face registration, capturing 40 face images."""
    cap = camera_manager.get_cap("registration")
    if not cap or not cap.isOpened():
        print("Camera registration: Failed to open device.")
        return
        
    # Get student name from DB to form folder name
    conn = db.get_db_connection()
    row = conn.execute("SELECT name FROM students WHERE id = ?", (student_id,)).fetchone()
    conn.close()
    
    if not row:
        print(f"Registration error: Student ID {student_id} not in database.")
        return
        
    student_name = row['name']
    folder_name = f"{student_id}_{student_name.replace(' ', '_')}"
    save_path = os.path.join(DATASET_DIR, folder_name)
    os.makedirs(save_path, exist_ok=True)
    
    count = 0
    last_capture_time = 0
    capture_delay = 0.8  # Wait 800ms between captures to allow angle change

    print(f"Registration stream: Starting capture for student {student_name} (ID: {student_id})")

    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame = cv2.flip(frame, 1)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect faces
        faces = recognizer_wrapper.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=6,
            minSize=(120, 120)
        )
        
        if len(faces) > 0 and count < 40:
            # Take largest face
            largest_face = max(faces, key=lambda f: f[2] * f[3])
            (x, y, w, h) = largest_face
            
            current_time = time.time()
            if current_time - last_capture_time >= capture_delay:
                count += 1
                last_capture_time = current_time
                
                # Crop grayscale face
                face_crop = gray[y:y+h, x:x+w]
                # Resize to standard dimension
                face_crop = cv2.resize(face_crop, (200, 200))
                
                # Save image
                img_file = os.path.join(save_path, f"{count}.jpg")
                cv2.imwrite(img_file, face_crop)
                
            # Draw yellow capture bounding box
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 165, 255), 2)
            cv2.putText(
                frame,
                f"Capturing face... {count}/40",
                (x, y-10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 165, 255),
                2
            )
            
        # Draw total progress HUD
        cv2.rectangle(frame, (20, 20), (220, 60), (0, 0, 0), cv2.FILLED)
        cv2.putText(
            frame,
            f"Dataset: {count}/40",
            (30, 48),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0) if count >= 40 else (255, 255, 255),
            2
        )
        
        if count >= 40:
            cv2.rectangle(frame, (100, 200), (540, 280), (46, 117, 89), cv2.FILLED)
            cv2.putText(
                frame,
                "REGISTRATION COMPLETED!",
                (120, 250),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2
            )
            
        ret_val, jpeg = cv2.imencode('.jpg', frame)
        if not ret_val:
            continue
            
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n\r\n')
               
        if count >= 40:
            # Let the user see the "REGISTRATION COMPLETED" banner for 2 seconds
            time.sleep(2.0)
            break
            
        time.sleep(0.03)
        
    camera_manager.release()

@app.route('/api/camera/stream')
def get_recognition_stream():
    return Response(
        generate_recognition_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/api/camera/register_stream/<int:student_id>')
def get_registration_stream(student_id):
    return Response(
        generate_registration_frames(student_id),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

if __name__ == '__main__':
    # Run server on port 5000
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
