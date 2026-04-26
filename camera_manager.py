"""
camera_manager.py — AI Classroom Monitor v3
=============================================
Upgraded:
- Camera ON/OFF toggle
- Manual reconnect
- Video recording (to captures/)
- Behavior note (crowd density label)
- Optimised JPEG encoding
- Frame-skip for higher FPS
Python 3.11 compatible.
"""

import cv2
import time
import os
import threading
import numpy as np
from ultralytics import YOLO


# ── Config ────────────────────────────────────────────────────────────────────
FRAME_W          = 640
FRAME_H          = 480
JPEG_QUALITY     = 75
AUTO_CAPTURE_SEC = 1800
YOLO_CONF        = 0.45
YOLO_SKIP        = 2       # Run YOLO every N frames (skip for speed)


class CameraManager:
    """
    Single webcam (index 0), shared across all 4 dashboard panels.
    """

    def __init__(self, db):
        self.db             = db
        self.student_count  = 0
        self.online         = False
        self.enabled        = True      # ON/OFF toggle
        self.recording      = False
        self.behavior_label = "Normal"  # crowd density label
        self._jpeg_bytes    = None
        self._lock          = threading.Lock()
        self._last_capture  = 0.0
        self._frame_n       = 0        # frame counter for YOLO skip
        self._video_writer  = None

        os.makedirs("captures",  exist_ok=True)
        os.makedirs("snapshots", exist_ok=True)

        # Load YOLO
        print("⏳  Loading YOLOv8n …")
        try:
            self.model = YOLO("yolov8n.pt")
            print("✅  YOLOv8n ready.")
        except Exception as e:
            print(f"⚠️  YOLO failed: {e}")
            self.model = None

        self._cap = self._open_camera()

        t = threading.Thread(target=self._loop, daemon=True, name="CamThread")
        t.start()
        print("📷  Camera thread started.")

    # ── Open camera ───────────────────────────────────────────────────────────
    def _open_camera(self):
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        cap     = cv2.VideoCapture(0, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # reduce latency
            print("✅  Camera 0 opened.")
        else:
            print("⚠️  Camera offline.")
        return cap

    # ── Background loop ───────────────────────────────────────────────────────
    def _loop(self):
        while True:
            try:
                if not self.enabled:
                    self.online     = False
                    self._jpeg_bytes = self._disabled_frame()
                    time.sleep(0.5)
                    continue

                if not self._cap.isOpened():
                    self.online = False
                    time.sleep(3)
                    self._cap = self._open_camera()
                    continue

                ok, frame = self._cap.read()
                if not ok:
                    self.online = False
                    time.sleep(0.1)
                    continue

                self.online   = True
                self._frame_n += 1
                frame         = cv2.resize(frame, (FRAME_W, FRAME_H))

                # YOLO every N frames
                if self._frame_n % YOLO_SKIP == 0 and self.model is not None:
                    count = self._run_yolo(frame)
                    self.student_count  = count
                    self.behavior_label = self._density_label(count)

                self._draw_hud(frame, self.student_count)
                self._encode(frame)

                # Recording
                if self.recording and self._video_writer:
                    self._video_writer.write(frame)

                # Auto capture
                now = time.time()
                if now - self._last_capture >= AUTO_CAPTURE_SEC:
                    auto_cap = self.db.get_setting("auto_capture", "1") == "1"
                    if auto_cap:
                        self._save_frame(frame, prefix="auto")
                    self._last_capture = now

            except Exception as e:
                print(f"[CamThread] {e}")
                time.sleep(1)

    # ── YOLO inference ────────────────────────────────────────────────────────
    def _run_yolo(self, frame: np.ndarray) -> int:
        results = self.model(frame, verbose=False, conf=YOLO_CONF)
        count   = 0
        for r in results:
            for box in r.boxes:
                if int(box.cls) == 0:
                    count += 1
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf            = float(box.conf[0])
                    cv2.rectangle(frame, (x1,y1), (x2,y2), (0,255,120), 2)
                    cv2.putText(frame, f"{conf:.0%}",
                                (x1, max(y1-6,12)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                                (0,255,120), 1, cv2.LINE_AA)
        return count

    # ── Density label ─────────────────────────────────────────────────────────
    def _density_label(self, count: int) -> str:
        if count == 0:   return "Empty"
        if count <= 5:   return "Low"
        if count <= 15:  return "Moderate"
        if count <= 25:  return "High"
        return "Overcrowded"

    # ── HUD ───────────────────────────────────────────────────────────────────
    def _draw_hud(self, frame: np.ndarray, count: int):
        h, w = frame.shape[:2]
        ov   = frame.copy()
        cv2.rectangle(ov, (0,0), (260,65), (0,0,0), -1)
        cv2.addWeighted(ov, 0.45, frame, 0.55, 0, frame)

        cv2.putText(frame, "CAM 1  [LIVE]",
                    (10,20), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (80,190,255), 1, cv2.LINE_AA)
        cv2.putText(frame, f"Students: {count}",
                    (10,48), cv2.FONT_HERSHEY_SIMPLEX,
                    0.82, (0,255,120), 2, cv2.LINE_AA)

        # Density label
        col = (0,200,255) if self.behavior_label in ("Low","Empty") \
              else (0,100,255) if self.behavior_label == "Moderate" \
              else (0,50,255) if self.behavior_label == "High" \
              else (0,0,255)
        cv2.putText(frame, self.behavior_label,
                    (10,63), cv2.FONT_HERSHEY_SIMPLEX,
                    0.42, col, 1, cv2.LINE_AA)

        ts = time.strftime("%H:%M:%S")
        cv2.putText(frame, ts,
                    (w-85,h-10), cv2.FONT_HERSHEY_SIMPLEX,
                    0.42, (150,150,150), 1, cv2.LINE_AA)

        # Recording indicator
        if self.recording:
            cv2.circle(frame, (w-15, 15), 6, (0,0,255), -1)
            cv2.putText(frame, "REC",
                        (w-55,20), cv2.FONT_HERSHEY_SIMPLEX,
                        0.42, (0,0,255), 1, cv2.LINE_AA)

    # ── Encode JPEG ───────────────────────────────────────────────────────────
    def _encode(self, frame: np.ndarray):
        ok, buf = cv2.imencode(".jpg", frame,
                               [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if ok:
            with self._lock:
                self._jpeg_bytes = buf.tobytes()

    # ── Offline/Disabled placeholders ─────────────────────────────────────────
    def _make_placeholder(self, line1: str, line2: str) -> bytes:
        img = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
        img[:] = (12,16,26)
        cx = FRAME_W//2
        cy = FRAME_H//2
        cv2.putText(img, line1, (cx-130, cy-16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (50,50,80), 2, cv2.LINE_AA)
        cv2.putText(img, line2, (cx-150, cy+22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (40,40,60), 1, cv2.LINE_AA)
        _, buf = cv2.imencode(".jpg", img)
        return buf.tobytes()

    def _offline_frame(self) -> bytes:
        return self._make_placeholder("NO CAMERA SIGNAL", "Connect webcam and restart")

    def _disabled_frame(self) -> bytes:
        return self._make_placeholder("CAMERA DISABLED", "Turn ON from dashboard")

    # ── Save frame ────────────────────────────────────────────────────────────
    def _save_frame(self, frame: np.ndarray, prefix: str = "manual",
                    camera_id: int = 0, log_db: bool = True) -> str:
        ts    = int(time.time())
        fname = f"captures/{prefix}_cam{camera_id}_{ts}.jpg"
        cv2.imwrite(fname, frame)
        if log_db:
            self.db.log_capture(camera_id, fname, self.student_count, prefix)
            self.db.log_count(camera_id, self.student_count)
        print(f"📸  Saved: {fname}")
        return fname

    # ── Public: MJPEG stream ──────────────────────────────────────────────────
    def generate_frames(self):
        offline  = self._offline_frame()
        disabled = self._disabled_frame()

        while True:
            with self._lock:
                frame = self._jpeg_bytes

            if not self.enabled:
                data = disabled
            elif frame and self.online:
                data = frame
            else:
                data = offline

            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + data + b"\r\n")
            time.sleep(0.04)

    # ── Public: manual capture ────────────────────────────────────────────────
    def capture_now(self, camera_id: int = 0) -> str | None:
        ok, frame = self._cap.read()
        if ok:
            frame = cv2.resize(frame, (FRAME_W, FRAME_H))
            return self._save_frame(frame, prefix="manual",
                                    camera_id=camera_id, log_db=True)
        return None

    # ── Public: toggle camera ─────────────────────────────────────────────────
    def toggle_camera(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled

    # ── Public: reconnect ─────────────────────────────────────────────────────
    def reconnect(self):
        try: self._cap.release()
        except: pass
        self._cap = self._open_camera()

    # ── Public: start/stop recording ─────────────────────────────────────────
    def start_recording(self) -> str:
        ts    = int(time.time())
        fname = f"captures/video_{ts}.avi"
        fourcc= cv2.VideoWriter_fourcc(*"XVID")
        self._video_writer = cv2.VideoWriter(fname, fourcc, 20.0, (FRAME_W, FRAME_H))
        self.recording     = True
        return fname

    def stop_recording(self) -> bool:
        self.recording = False
        if self._video_writer:
            self._video_writer.release()
            self._video_writer = None
        return True

    # ── Public: status ────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {
            "online":    self.online,
            "count":     self.student_count,
            "enabled":   self.enabled,
            "recording": self.recording,
            "behavior":  self.behavior_label,
        }
