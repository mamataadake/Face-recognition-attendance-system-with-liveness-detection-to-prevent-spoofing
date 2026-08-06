# Face Recognition Attendance System with Interactive Liveness Detection

SentinelFace is a complete, modern web-based face recognition attendance system designed with anti-spoofing countermeasures. It combines Haar Cascade face and eye detection with the Local Binary Patterns Histograms (LBPH) classifier and an interactive liveness verification state-machine (detecting eye blinks and head movements) to prevent photo or video replay spoofing.

---

## 🌟 Key Features

1. **Vibrant Dark-Theme Dashboard**: Single Page Application (SPA) showcasing attendance analytics, student registration logs, and model statuses.
2. **Interactive Liveness Detection**:
   - **Step 1 (Eye Blink)**: Directs the user to blink. Utilizes a transition-based scanner checking for a state pattern (Eyes Open -> Closed -> Open).
   - **Step 2 (Head Movement)**: Directs the user to move their head. Monitors vertical and horizontal variance of the face bounding box center.
   - **Spoof Prevention**: Flags access attempts as "Spoof Suspected" if the face remains static or fails checking steps before timeout.
3. **Database Integration**: SQLite database storing student profiles and attendance records. Logs date, time, student credentials, and liveness validation logs.
4. **Auto-Synchronization**: Automatically imports and registers existing folder labels (`ID_Name`) from the `dataset` directory on startup.
5. **Background Model Builder**: Rebuilds the LBPH Face Recognizer asynchronously in a background thread with real-time UI progress updates.
6. **Data Export**: Filters logs by student name or date, and exports records to CSV files.

---

## 📁 Project Structure

```
face_recognition_attendance/
├── backend/
│   ├── app.py                  # Flask entrypoint (API routes and webcam streamers)
│   ├── database.py             # SQLite interface & auto-sync script
│   ├── face_recognizer.py      # LBPH Face Recognizer wrapper and training thread
│   └── liveness.py             # Liveness checks (Eye blinks & Head movements)
├── frontend/
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css       # Custom modern dark UI styling
│   │   └── js/
│   │       └── app.js          # SPA navigation, Chart.js trends, webcam polling
│   └── templates/
│       └── index.html          # Web dashboard markup
├── dataset/                    # Face images folders (1_Mamata, 2_Samarth, etc.)
├── models/                     # Holds trained face_trainer.yml model file
├── attendance/                 # Stores SQLite attendance.db database
├── requirements.txt            # Python dependencies
└── README.md                   # Setup and execution guide
```

---

## ⚙️ Installation & Setup (Windows)

### Step 1: Open PowerShell and navigate to the project directory
```powershell
cd "C:\Users\Mamata Adake\.gemini\antigravity\scratch\face_recognition_attendance"
```

### Step 2: Install project dependencies in your environment
Install Flask and other dependencies listed in `requirements.txt` using the project's virtual environment's pip:
```powershell
.\venv\Scripts\pip install -r requirements.txt
```

---

## 🚀 Execution & Demo Steps

### Step 1: Start the Flask Backend Server
Run the web application:
```powershell
.\venv\Scripts\python app.py
```
On startup, the system will read `./dataset`, detect the existing folders (`1_Mamata`, `2_Samarth`, `3_Harsh`), and register them into the database automatically.

### Step 2: Access the Dashboard
Open your web browser and navigate to:
```url
http://localhost:5001
```

### Step 3: Train the Model
1. Go to the **Model Training** tab.
2. Click **Rebuild & Train Model**.
3. Watch the progress bar compile the images and train the LBPH classifier. The summary statistics card will display the results once completed.

### Step 4: Perform Live Attendance with Liveness Check
1. Go to the **Live Recognition** tab.
2. Click **Start Scanner**. This opens your webcam and processes video frames in real time.
3. **Liveness Test**:
   - The scanner will recognize your face and state: **"Step 1/2: Please blink your eyes."**
   - Blink once. Once verified, the scanner moves to **"Step 2/2: Please move your head."**
   - Turn your head slightly to the left/right or up/down.
   - Once verified, the dashboard displays **"Liveness Verified!"** and automatically registers your attendance.
   - If you hold a static printed photograph or phone screen displaying a static image, the checks will timeout and display **"Access Denied (Spoof Flagged)"**.
4. Click **Stop Scanner** to release the webcam.

### Step 5: View Logs
1. Go to the **Attendance Log** tab.
2. Search records by name or filter by date.
3. Click **Export CSV** to download a spreadsheet report.
