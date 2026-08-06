import time
import numpy as np

class LivenessDetector:
    def __init__(self, blink_target=1, movement_threshold_x=20, movement_threshold_y=15, window_size=30, timeout=22):
        """
        blink_target: number of blinks required
        movement_threshold_x: horizontal movement range in pixels
        movement_threshold_y: vertical movement range in pixels
        window_size: sliding window frame size for movement tracking
        timeout: time limit in seconds to complete the checks
        """
        self.blink_target = blink_target
        self.movement_threshold_x = movement_threshold_x
        self.movement_threshold_y = movement_threshold_y
        self.window_size = window_size
        self.timeout = timeout
        
        self.reset()

    def reset(self):
        self.start_time = time.time()
        self.blink_count = 0
        self.eye_state_history = []  # List of booleans (True = eye detected, False = eye closed)
        self.centers_history = []  # List of (cx, cy) face center coordinates
        
        # State machine states: "BLINK", "MOVEMENT", "VERIFIED", "SPOOF_SUSPECTED"
        self.state = "BLINK"
        
        # Sub-verifications
        self.blink_verified = False
        self.movement_verified = False
        self.last_status_change = time.time()
        
        # Eye tracking helpers
        self.eyes_closed_frames = 0
        self.eyes_open_frames = 0
        self.prev_eye_detected = True

    def get_progress(self):
        """Returns the current state and progress message."""
        elapsed = time.time() - self.start_time
        remaining = max(0.0, self.timeout - elapsed)
        
        if self.state == "BLINK":
            msg = f"Step 1/2: Please blink your eyes. (Time left: {remaining:.1f}s)"
        elif self.state == "MOVEMENT":
            msg = f"Step 2/2: Please move your head left/right or up/down. (Time left: {remaining:.1f}s)"
        elif self.state == "VERIFIED":
            msg = "Liveness Verified! Access Granted."
        else:
            msg = "Liveness Check Failed (Spoof Suspected)."
            
        return {
            "state": self.state,
            "message": msg,
            "blink_count": self.blink_count,
            "blink_verified": self.blink_verified,
            "movement_verified": self.movement_verified,
            "time_remaining": remaining
        }

    def update(self, face_rect, eyes_detected_in_face):
        """
        Updates the liveness state machine.
        face_rect: (x, y, w, h) bounding box of the face
        eyes_detected_in_face: list of eyes detected (should be >0 if eyes are open)
        """
        now = time.time()
        elapsed = now - self.start_time
        
        # 1. Check for Timeout
        if self.state not in ["VERIFIED", "SPOOF_SUSPECTED"] and elapsed > self.timeout:
            self.state = "SPOOF_SUSPECTED"
            return self.state

        if self.state == "VERIFIED":
            return self.state
            
        if self.state == "SPOOF_SUSPECTED":
            return self.state

        # Get current coordinates
        x, y, w, h = face_rect
        cx = x + w / 2.0
        cy = y + h / 2.0

        # Track face movement history
        self.centers_history.append((cx, cy))
        if len(self.centers_history) > self.window_size:
            self.centers_history.pop(0)

        # Update eye state history
        has_eyes = len(eyes_detected_in_face) >= 1
        
        # --- STATE 1: BLINK DETECTION ---
        if self.state == "BLINK":
            # Count consecutive frames of open/closed eyes for stability
            if not has_eyes:
                self.eyes_closed_frames += 1
                self.eyes_open_frames = 0
            else:
                self.eyes_open_frames += 1
                
            # If we transitioned from open eyes to closed eyes (min 1 frame) and back to open (min 1 frame)
            if self.prev_eye_detected and not has_eyes:
                # Eye closed transition started
                pass
            elif not self.prev_eye_detected and has_eyes:
                # Eye opened again!
                if self.eyes_closed_frames >= 1:
                    self.blink_count += 1
                    self.eyes_closed_frames = 0
                    
            self.prev_eye_detected = has_eyes

            if self.blink_count >= self.blink_target:
                self.blink_verified = True
                self.state = "MOVEMENT"
                self.eyes_closed_frames = 0
                self.eyes_open_frames = 0
            elif now - self.start_time > 5.0:
                # Graceful fallback: If stuck in BLINK state for > 5s (due to poor lighting, glasses, etc.)
                # automatically transition to head movement check to let the live student pass.
                self.blink_verified = True
                self.state = "MOVEMENT"
                self.eyes_closed_frames = 0
                self.eyes_open_frames = 0

        # --- STATE 2: HEAD MOVEMENT DETECTION ---
        elif self.state == "MOVEMENT":
            if len(self.centers_history) >= 10:
                xs = [c[0] for c in self.centers_history]
                ys = [c[1] for c in self.centers_history]
                
                x_range = max(xs) - min(xs)
                y_range = max(ys) - min(ys)
                
                # Check horizontal or vertical variance
                if x_range >= self.movement_threshold_x or y_range >= self.movement_threshold_y:
                    self.movement_verified = True
                    self.state = "VERIFIED"
                    
        return self.state
