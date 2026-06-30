# Face + Fingerprint Lock — Laptop Prototype & Raspberry Pi Zero 2 W Build

Two-factor access control demo: OpenCV face-presence detection (Haar Cascade) gates a fingerprint scan before unlocking. Prototyped on a laptop webcam, deployed headless on a Raspberry Pi Zero 2 W with an official Camera Module v2 and a UART fingerprint sensor (AS608/R30x family), auto-starting on boot via systemd.

![demo](docs/demo.gif)
<!-- TODO: replace with actual demo photo/gif -->

## How It Works
1. Camera continuously checks for a face using OpenCV Haar Cascade.
2. Face held in frame for 3s → system requests fingerprint confirmation.
3. **Laptop build:** press `f` to simulate a fingerprint match (for fast dev/demo without sensor hardware).
   **Pi Zero 2 W build:** a real AS608/R30x sensor scans and matches the finger on-device.
4. Match → system unlocks. No match / timeout → resets to locked.
5. No face detected for 5s while unlocked → auto re-locks.
6. Every state change is logged to `access_log.json` with a timestamp.

## Hardware (Pi build)
- Raspberry Pi Zero 2 W
- Raspberry Pi Camera Module v2 (CSI)
- AS608 / R30x UART fingerprint sensor

## Repo Contents
| File | Purpose |
|---|---|
| `laptop_face_lock.py` | Laptop prototype — webcam + simulated fingerprint (`f` key) |
| `pi_zero_face_lock.py` | Pi Zero 2 W build — Camera Module v2 + real fingerprint sensor, headless, includes `--enroll` mode |
| `face-lock-pi-zero.service` | systemd unit for auto-start on boot (headless, no display dependency) |

## Setup
```bash
# Laptop
pip install opencv-python --break-system-packages
python3 laptop_face_lock.py

# Pi Zero 2 W
sudo apt install -y python3-opencv python3-picamera2
pip install pyfingerprint --break-system-packages
python3 pi_zero_face_lock.py --enroll   # enroll a fingerprint once
python3 pi_zero_face_lock.py            # run

# Auto-start on boot
sudo cp face-lock-pi-zero.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now face-lock-pi-zero
```

## Design Notes
- Haar Cascade chosen over `face_recognition`/dlib for fast, dependency-light setup on constrained hardware (Zero 2 W, 512MB RAM).
- Fingerprint matching happens on the sensor module itself, not on the Pi — keeps CPU load minimal.
- Headless Pi build logs to stdout/journald and a local JSON file instead of opening a GUI window.

## Status
Core logic and both builds are complete and tested individually (face detection, state machine, fingerprint enroll/match, systemd auto-start). Full hardware demo writeup/photos to follow.
