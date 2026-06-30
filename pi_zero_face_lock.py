"""
Raspberry Pi Zero 2 W Face + Fingerprint Lock (headless)
-----------------------------------------------------------
Hardware: Pi Zero 2 W, official Raspberry Pi Camera Module v2 (CSI ribbon,
NOT a USB webcam), and a UART fingerprint sensor from the AS608 / R30x
family (the common cheap optical modules sold for Arduino/Pi projects).

No monitor is attached (headless) -- there is no cv2.imshow() anywhere in
this script. All status is written to stdout (captured by `journalctl` when
run as a systemd service) and to access_log.json.

Two-factor flow:
  1. Camera Module v2 looks for a face (Haar Cascade -- light enough for
     the Zero 2 W's quad-core Cortex-A53).
  2. Face held in frame for FACE_HOLD_SECONDS -> system asks the
     fingerprint sensor to scan ("AWAITING_FINGERPRINT").
  3. Fingerprint sensor does its OWN on-module matching against previously
     enrolled templates (the Pi just asks it "do you see a known finger?"
     and gets back a template ID or "no match" -- the Pi is not running
     any matching math itself).
  4. Match -> UNLOCKED. No match / timeout -> back to LOCKED.
  5. Unlocked + no face for LOCKOUT_AFTER_SECONDS -> auto re-lock.

Enrollment (run this once per person BEFORE normal operation):
    python3 pi_zero_face_lock.py --enroll

Normal run:
    python3 pi_zero_face_lock.py

Requires:
    sudo apt install -y python3-opencv python3-picamera2
    pip install pyfingerprint --break-system-packages
    Sensor wiring: TX/RX to Pi UART (/dev/serial0), VCC to 3.3V or 5V per
    your module's datasheet, GND to GND. Enable UART via raspi-config
    (Interface Options -> Serial Port -> login shell: No, hardware: Yes).
"""

import json
import os
import sys
import time
from datetime import datetime

import cv2
from picamera2 import Picamera2

try:
    from pyfingerprint.pyfingerprint import PyFingerprint
except ImportError:
    PyFingerprint = None  # allows --help / face-only testing without the lib installed

LOG_FILE = "/home/pi/face_lock_pi/access_log.json"
FACE_HOLD_SECONDS = 3
FINGERPRINT_TIMEOUT = 8          # sensor scans are slower than a keypress
LOCKOUT_AFTER_SECONDS = 5
FRAME_CHECK_EVERY_N = 3          # only run face detection every Nth frame to save CPU
CAPTURE_SIZE = (320, 240)        # low-res keeps Haar Cascade fast on the Zero 2 W
FP_PORT = "/dev/serial0"
FP_BAUD = 57600

STATE_LOCKED = "LOCKED"
STATE_AWAITING_FP = "AWAITING_FINGERPRINT"
STATE_UNLOCKED = "UNLOCKED"


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
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)
    print(f"[LOG] {entry}", flush=True)


def connect_fingerprint():
    if PyFingerprint is None:
        print("ERROR: pyfingerprint not installed. Run: pip install pyfingerprint --break-system-packages")
        sys.exit(1)
    try:
        sensor = PyFingerprint(FP_PORT, FP_BAUD, 0xFFFFFFFF, 0x00000000)
        if not sensor.verifyPassword():
            raise ValueError("Sensor password incorrect")
        return sensor
    except Exception as e:
        print(f"ERROR: Could not connect to fingerprint sensor on {FP_PORT}: {e}")
        sys.exit(1)


def enroll_fingerprint():
    """Interactive enrollment: place the same finger twice to register it."""
    sensor = connect_fingerprint()
    print(f"Sensor OK. Templates stored: {sensor.getTemplateCount()}/{sensor.getStorageCapacity()}")

    print("Place finger on sensor...")
    while not sensor.readImage():
        pass
    sensor.convertImage(0x01)

    result = sensor.searchTemplate()
    if result[0] != -1:
        print(f"This finger is already enrolled as template #{result[0]}.")
        return

    print("Remove finger, then place the SAME finger again...")
    time.sleep(1.5)
    while sensor.readImage():
        pass
    while not sensor.readImage():
        pass
    sensor.convertImage(0x02)

    if sensor.compareCharacteristics() == 0:
        print("ERROR: Fingers did not match. Try enrollment again.")
        return

    sensor.createTemplate()
    position = sensor.storeTemplate()
    print(f"Enrollment successful. Stored as template #{position}.")
    log_event(f"fingerprint_enrolled_id_{position}")


def main():
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(main={"size": CAPTURE_SIZE, "format": "RGB888"})
    picam2.configure(config)
    picam2.start()
    time.sleep(1)  # let auto-exposure settle

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face_detector = cv2.CascadeClassifier(cascade_path)
    fp_sensor = connect_fingerprint()

    status = STATE_LOCKED
    face_first_seen = None
    last_face_seen = None
    awaiting_since = None
    frame_count = 0
    face_detected = False

    print("Pi Zero 2 W Face+Fingerprint Lock started (headless). Ctrl+C to stop.", flush=True)
    log_event("system_start")

    try:
        while True:
            frame = picam2.capture_array()
            frame_count += 1

            if frame_count % FRAME_CHECK_EVERY_N == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                faces = face_detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
                face_detected = len(faces) > 0

            now = time.time()

            if face_detected:
                last_face_seen = now
                if face_first_seen is None:
                    face_first_seen = now
                held = now - face_first_seen

                if status == STATE_LOCKED and held >= FACE_HOLD_SECONDS:
                    status = STATE_AWAITING_FP
                    awaiting_since = now
                    print("Face confirmed. Place finger on sensor...", flush=True)
                    log_event("face_confirmed_awaiting_fingerprint")

                if status == STATE_AWAITING_FP:
                    if now - awaiting_since > FINGERPRINT_TIMEOUT:
                        log_event("fingerprint_timeout")
                        status, face_first_seen, awaiting_since = STATE_LOCKED, None, None
                    elif fp_sensor.readImage():
                        fp_sensor.convertImage(0x01)
                        result = fp_sensor.searchTemplate()
                        template_id = result[0]
                        if template_id != -1:
                            status = STATE_UNLOCKED
                            log_event(f"fingerprint_match_unlocked_id_{template_id}")
                        else:
                            log_event("fingerprint_no_match")
                            status, face_first_seen, awaiting_since = STATE_LOCKED, None, None
            else:
                face_first_seen = None
                if status == STATE_AWAITING_FP:
                    log_event("face_lost_during_fingerprint_wait")
                    status, awaiting_since = STATE_LOCKED, None
                if status == STATE_UNLOCKED and last_face_seen is not None:
                    if now - last_face_seen >= LOCKOUT_AFTER_SECONDS:
                        log_event("auto_relocked")
                        status = STATE_LOCKED

            time.sleep(0.05)  # ~20fps loop cap, easy on the Zero 2 W's CPU

    except KeyboardInterrupt:
        pass
    finally:
        log_event("system_stop")
        picam2.stop()


if __name__ == "__main__":
    if "--enroll" in sys.argv:
        enroll_fingerprint()
    else:
        main()
