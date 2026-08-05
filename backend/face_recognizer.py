import cv2
import os
import numpy as np
from PIL import Image
import threading

# Global variables for training state
training_lock = threading.Lock()
training_status = {
    "status": "idle",  # "idle", "training", "success", "error"
    "progress": 0,
    "message": "System is ready for training.",
    "details": {}
}

# Configure paths based on serverless execution environment
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_VERCEL = os.environ.get('VERCEL') is not None

if IS_VERCEL:
    DATASET_DIR = "/tmp/dataset"
    MODEL_PATH = "/tmp/models/face_trainer.yml"
else:
    DATASET_DIR = os.path.join(BASE_DIR, "dataset")
    MODEL_PATH = os.path.join(BASE_DIR, "models", "face_trainer.yml")

# Local cascades path (guaranteed to be bundled on Vercel)
CASCADES_DIR = os.path.join(BASE_DIR, "backend", "cascades")
FACE_CASCADE_PATH = os.path.join(CASCADES_DIR, "haarcascade_frontalface_default.xml")
EYE_CASCADE_PATH = os.path.join(CASCADES_DIR, "haarcascade_eye.xml")

def get_training_status():
    """Returns the current background model training status."""
    with training_lock:
        return training_status.copy()

def set_training_status(status, progress, message, details=None):
    """Safely updates the training status."""
    global training_status
    with training_lock:
        training_status["status"] = status
        training_status["progress"] = progress
        training_status["message"] = message
        if details is not None:
            training_status["details"] = details

class FaceRecognizerWrapper:
    def __init__(self, model_path):
        self.model_path = model_path
        self.recognizer = None
        
        # Load cascades from bundled cascades folder
        self.face_cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)
        self.eye_cascade = cv2.CascadeClassifier(EYE_CASCADE_PATH)
        
        if self.face_cascade.empty():
            print(f"Face Recognizer Error: Failed to load face cascade from {FACE_CASCADE_PATH}")
        if self.eye_cascade.empty():
            print(f"Face Recognizer Error: Failed to load eye cascade from {EYE_CASCADE_PATH}")
            
        self.reload_model()

    def reload_model(self):
        """Loads or reloads the LBPH recognizer model from disk."""
        if os.path.exists(self.model_path):
            try:
                self.recognizer = cv2.face.LBPHFaceRecognizer_create()
                self.recognizer.read(self.model_path)
                print(f"Face Recognizer: Successfully loaded model from {self.model_path}")
                return True
            except Exception as e:
                print(f"Face Recognizer: Error loading model: {e}")
                self.recognizer = None
        else:
            print(f"Face Recognizer: Model file {self.model_path} not found. Needs training.")
            self.recognizer = None
        return False

    def predict(self, face_gray):
        """
        Predicts the student ID for a given grayscale face crop.
        Returns: (student_id, confidence) or (None, None)
        """
        if self.recognizer is None:
            return None, None
            
        try:
            # Preprocess the face crop (Resize and Equalize histogram to improve contrast)
            face_resized = cv2.resize(face_gray, (200, 200))
            face_equalized = cv2.equalizeHist(face_resized)
            
            student_id, confidence = self.recognizer.predict(face_equalized)
            return student_id, confidence
        except Exception as e:
            print(f"Error during prediction: {e}")
            return None, None

def _run_training_async(dataset_path, model_path):
    """Target function for background training thread."""
    try:
        set_training_status("training", 10, "Scanning dataset folder...")
        
        if not os.path.exists(dataset_path):
            set_training_status("error", 0, "Dataset directory does not exist.")
            return

        folders = os.listdir(dataset_path)
        valid_folders = []
        for folder in folders:
            folder_path = os.path.join(dataset_path, folder)
            if os.path.isdir(folder_path):
                # Ensure the folder matches ID_Name format
                parts = folder.split("_")
                if len(parts) >= 2 and parts[0].isdigit():
                    valid_folders.append(folder)

        if not valid_folders:
            set_training_status("error", 0, "No valid student folders (format ID_Name) found in dataset.")
            return

        set_training_status("training", 30, "Reading face images from folders...")
        
        faces = []
        ids = []
        total_images = 0
        
        # Count total images to calculate detailed progress
        for folder in valid_folders:
            folder_path = os.path.join(dataset_path, folder)
            total_images += len([f for f in os.listdir(folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])

        if total_images == 0:
            set_training_status("error", 0, "No image files found in student folders.")
            return

        processed_images = 0
        student_counts = {}

        for folder in valid_folders:
            folder_path = os.path.join(dataset_path, folder)
            student_id = int(folder.split("_")[0])
            student_name = folder.split("_", 1)[1].replace("_", " ")
            student_counts[student_name] = 0
            
            for filename in os.listdir(folder_path):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    img_path = os.path.join(folder_path, filename)
                    try:
                        # Open in grayscale
                        img = Image.open(img_path).convert("L")
                        img_numpy = np.array(img, "uint8")
                        
                        faces.append(img_numpy)
                        ids.append(student_id)
                        
                        student_counts[student_name] += 1
                        processed_images += 1
                        
                        # Calculate progress in the 30% - 80% range
                        prog = int(30 + (processed_images / total_images) * 50)
                        set_training_status("training", prog, f"Loading image {processed_images}/{total_images}...")
                    except Exception as img_err:
                        print(f"Error loading image {img_path}: {img_err}")

        if not faces:
            set_training_status("error", 0, "No training samples could be successfully loaded.")
            return

        set_training_status("training", 85, "Training the LBPH Face Recognizer model...")
        
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        recognizer.train(faces, np.array(ids))
        
        set_training_status("training", 95, "Saving trained model to disk...")
        
        # Ensure models directory exists
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        recognizer.save(model_path)
        
        details = {
            "num_students": len(valid_folders),
            "num_images": len(faces),
            "student_breakdown": student_counts
        }
        
        set_training_status("success", 100, "Model training completed successfully!", details)
        print("Training Thread: Successfully trained and saved model.")
        
    except Exception as e:
        print(f"Training Thread: Error during model training: {e}")
        set_training_status("error", 0, f"Training failed: {str(e)}")

def train_model_async(dataset_path, model_path):
    """Starts model training in a background thread to prevent blocking the Flask server."""
    status = get_training_status()
    if status["status"] == "training":
        return False, "Training is already in progress."
        
    set_training_status("training", 0, "Initializing training background process...")
    thread = threading.Thread(target=_run_training_async, args=(dataset_path, model_path))
    thread.daemon = True
    thread.start()
    return True, "Training started in background."
