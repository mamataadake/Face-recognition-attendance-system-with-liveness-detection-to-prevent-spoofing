import cv2
import os
import sys

# Configure paths
BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
DATASET_DIR = os.path.join(BACKEND_DIR, "dataset")
CASCADES_DIR = os.path.join(BACKEND_DIR, "cascades")
FACE_CASCADE_PATH = os.path.join(CASCADES_DIR, "haarcascade_frontalface_default.xml")

def realign_dataset():
    face_cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)
    if face_cascade.empty():
        print(f"Error: Failed to load face cascade from {FACE_CASCADE_PATH}")
        return

    if not os.path.exists(DATASET_DIR):
        print(f"Error: Dataset directory {DATASET_DIR} does not exist.")
        return

    folders = os.listdir(DATASET_DIR)
    processed = 0
    fallback = 0

    for folder in folders:
        folder_path = os.path.join(DATASET_DIR, folder)
        if not os.path.isdir(folder_path):
            continue

        print(f"Processing student folder: {folder}...")
        for filename in os.listdir(folder_path):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                img_path = os.path.join(folder_path, filename)
                img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue

                # Detect face in the pre-captured image
                # Use lenient parameters to capture the face in smaller 200x200 crops
                faces = face_cascade.detectMultiScale(
                    img,
                    scaleFactor=1.05,
                    minNeighbors=3,
                    minSize=(40, 40)
                )

                if len(faces) > 0:
                    # Crop to the detected face region
                    largest_face = max(faces, key=lambda f: f[2] * f[3])
                    (x, y, w, h) = largest_face
                    face_crop = img[y:y+h, x:x+w]
                    face_resized = cv2.resize(face_crop, (120, 120))
                    cv2.imwrite(img_path, face_resized)
                    processed += 1
                else:
                    # If face detector misses, fallback to resizing the original crop to 120x120
                    face_resized = cv2.resize(img, (120, 120))
                    cv2.imwrite(img_path, face_resized)
                    fallback += 1

    print(f"Dataset realignment completed! Cropped & Realigned: {processed} images. Resized fallbacks: {fallback} images.")

if __name__ == "__main__":
    realign_dataset()
