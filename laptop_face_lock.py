"""
Laptop Face + Fingerprint Lock Simulator
-----------------------------------------
Runs on any laptop with a webcam. No fingerprint hardware needed -- pressing
the 'F' key simulates a successful fingerprint scan, so the full two-factor
flow (face presence -> fingerprint confirm -> unlock) can be demoed and
tested on a laptop before being run on the Raspberry Pi Zero 2 W with a
real AS608/R30x fingerprint sensor.

Flow:
  1. Camera looks for a face (OpenCV Haar Cascade).
  2. Face must be held in frame for FACE_HOLD_SECONDS -> system asks for
     fingerprint confirmation ("AWAITING_FINGERPRINT").
  3. User presses 'f' within FINGERPRINT_TIMEOUT seconds to simulate a
     successful scan -> UNLOCKED. If they don't press it in time, or the
     face leaves frame first, it resets back to LOCKED.
  4. If unlocked and no face is seen for LOCKOUT_AFTER_SECONDS -> auto
     re-locks.
  5. Every state change is appended to access_log.json.

Run with: python3 laptop_face_lock.py
Press 'f' to simulate fingerprint scan, 'q' to quit.
"""

import cv2
import json
import time
import os
from datetime import datetime

LOG_FILE = "access_log.json"
FACE_HOLD_SECONDS = 3
FINGERPRINT_TIMEOUT = 5
LOCKOUT_AFTER_SECONDS = 5

STATE_LOCKED = "LOCKED"
STATE_AWAITING_FP = "AWAITING_FINGERPRINT"
STATE_UNLOCKED = "UNLOCKED"

state = {
    "status": STATE_LOCKED,
    "face_first_seen": None,
    "last_face_seen": None,
    "awaiting_since": None,
}


def log_event(event_type):
    entry = {"event": event_type, "timestamp": datetime.now().isoformat(timespec="seconds")}
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                logs = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            logs = []
    logs.append(entry)
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)
    print(f"[LOG] {entry}")


def reset_to_locked():
    state["status"] = STATE_LOCKED
    state["face_first_seen"] = None
    state["awaiting_since"] = None


def main():
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face_detector = cv2.CascadeClassifier(cascade_path)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: Could not open webcam. Check camera permissions.")
        return

    print("Laptop Face+Fingerprint Lock started. Press 'f' to simulate fingerprint, 'q' to quit.")
    log_event("system_start")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame from camera.")
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        now = time.time()
        face_detected = len(faces) > 0
        key = cv2.waitKey(1) & 0xFF

        if face_detected:
            state["last_face_seen"] = now
            if state["face_first_seen"] is None:
                state["face_first_seen"] = now

            held = now - state["face_first_seen"]

            if state["status"] == STATE_LOCKED and held >= FACE_HOLD_SECONDS:
                state["status"] = STATE_AWAITING_FP
                state["awaiting_since"] = now
                log_event("face_confirmed_awaiting_fingerprint")

            if state["status"] == STATE_AWAITING_FP:
                if now - state["awaiting_since"] > FINGERPRINT_TIMEOUT:
                    log_event("fingerprint_timeout")
                    reset_to_locked()
                elif key == ord('f'):
                    state["status"] = STATE_UNLOCKED
                    log_event("fingerprint_match_unlocked")
        else:
            state["face_first_seen"] = None
            if state["status"] == STATE_AWAITING_FP:
                log_event("face_lost_during_fingerprint_wait")
                reset_to_locked()
            if state["last_face_seen"] is not None and state["status"] == STATE_UNLOCKED:
                if now - state["last_face_seen"] >= LOCKOUT_AFTER_SECONDS:
                    log_event("auto_relocked")
                    reset_to_locked()

        colors = {STATE_LOCKED: (0, 0, 255), STATE_AWAITING_FP: (0, 200, 255), STATE_UNLOCKED: (0, 200, 0)}
        color = colors[state["status"]]

        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

        cv2.putText(frame, f"STATUS: {state['status']}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

        if state["status"] == STATE_AWAITING_FP:
            remaining = max(0, FINGERPRINT_TIMEOUT - (now - state["awaiting_since"]))
            cv2.putText(frame, f"Press F to scan ({remaining:.1f}s)", (20, 75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        elif state["status"] == STATE_LOCKED and face_detected and state["face_first_seen"]:
            remaining = max(0, FACE_HOLD_SECONDS - (now - state["face_first_seen"]))
            cv2.putText(frame, f"Hold still: {remaining:.1f}s", (20, 75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

        cv2.imshow("Laptop Face+Fingerprint Lock", frame)

        if key == ord('q'):
            break

    log_event("system_stop")
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
