"""
Eye Tracking Engine — Phase 3
Webcam-based gaze estimation. No specialist hardware needed.

Approach:
  1. Face mesh (MediaPipe FaceMesh, 468 landmarks) to locate eye regions.
  2. Iris landmark tracking (MediaPipe Iris, sub-mesh) for pupil centre.
  3. Gaze vector estimated from pupil position relative to eye corner anchors.
  4. Kalman-filter smoothing to suppress jitter.
  5. 9-point calibration maps raw gaze vectors to screen coordinates.
  6. Dwell detection: eyes fixate on a region for DWELL_SEC → trigger click.

Limitations (standard webcam):
  - Accuracy: ±2–4° (~50–100px on a 1080p display at 60cm)
  - Requires calibration each session
  - Sensitive to head movement — recalibrate if head moves significantly

Signals:
  gaze_point(x, y)         — normalised screen coords (0–1, 0–1)
  dwell_click(x, y)         — user dwelled for long enough → click
  calibration_progress(n)   — calibration point n collected
  calibration_complete()
  error(msg)
"""
from __future__ import annotations
import time
from typing import Optional

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal


# ── Constants ─────────────────────────────────────────────────────────────────
DWELL_SEC          = 1.2   # seconds of fixation required to trigger click
DWELL_RADIUS_NORM  = 0.06  # normalised radius — fixation must stay within this
KALMAN_Q           = 1e-4  # process noise
KALMAN_R           = 0.01  # measurement noise
SMOOTHING_ALPHA    = 0.25  # EMA smoothing (0 = max smooth, 1 = raw)


# ── Kalman filter (2D) ────────────────────────────────────────────────────────

class KalmanFilter2D:
    def __init__(self, q: float = KALMAN_Q, r: float = KALMAN_R):
        self._x = np.zeros(4)          # state: [x, y, dx, dy]
        self._P = np.eye(4) * 0.1      # covariance
        self._F = np.array([           # state transition
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ], dtype=float)
        self._H = np.array([[1,0,0,0],[0,1,0,0]], dtype=float)  # measurement
        self._Q = np.eye(4) * q
        self._R = np.eye(2) * r
        self._initialised = False

    def update(self, measurement: np.ndarray) -> np.ndarray:
        if not self._initialised:
            self._x[:2] = measurement
            self._initialised = True
            return measurement

        # Predict
        self._x = self._F @ self._x
        self._P = self._F @ self._P @ self._F.T + self._Q

        # Update
        y = measurement - self._H @ self._x
        S = self._H @ self._P @ self._H.T + self._R
        K = self._P @ self._H.T @ np.linalg.inv(S)
        self._x = self._x + K @ y
        self._P = (np.eye(4) - K @ self._H) @ self._P

        return self._x[:2].copy()

    def reset(self):
        self._x = np.zeros(4)
        self._P = np.eye(4) * 0.1
        self._initialised = False


# ── Gaze calibration ─────────────────────────────────────────────────────────

class GazeCalibration:
    """
    Maps raw gaze vectors (from iris tracking) to normalised screen coords.
    Uses a 9-point grid and 2D polynomial regression (degree 2).
    """
    GRID_POINTS = [
        (0.1, 0.1), (0.5, 0.1), (0.9, 0.1),
        (0.1, 0.5), (0.5, 0.5), (0.9, 0.5),
        (0.1, 0.9), (0.5, 0.9), (0.9, 0.9),
    ]

    def __init__(self):
        self._raw_samples: list[np.ndarray] = []  # raw gaze per calib point
        self._screen_pts:  list[np.ndarray] = []  # corresponding screen coords
        self._coeff_x: Optional[np.ndarray] = None
        self._coeff_y: Optional[np.ndarray] = None
        self._fitted = False

    def add_sample(self, raw_gaze: np.ndarray, screen_point_idx: int):
        if screen_point_idx >= len(self.GRID_POINTS):
            return
        sx, sy = self.GRID_POINTS[screen_point_idx]
        self._raw_samples.append(raw_gaze.copy())
        self._screen_pts.append(np.array([sx, sy]))

    def fit(self) -> bool:
        if len(self._raw_samples) < 4:
            return False
        raw = np.array(self._raw_samples)
        scr = np.array(self._screen_pts)
        # Build polynomial feature matrix [1, x, y, x², xy, y²]
        X = self._poly_features(raw)
        try:
            self._coeff_x = np.linalg.lstsq(X, scr[:, 0], rcond=None)[0]
            self._coeff_y = np.linalg.lstsq(X, scr[:, 1], rcond=None)[0]
            self._fitted = True
            return True
        except Exception:
            return False

    def map(self, raw_gaze: np.ndarray) -> Optional[np.ndarray]:
        if not self._fitted:
            return None
        x = float(np.dot(self._poly_features(raw_gaze.reshape(1, -1)), self._coeff_x))
        y = float(np.dot(self._poly_features(raw_gaze.reshape(1, -1)), self._coeff_y))
        return np.clip([x, y], 0.0, 1.0)

    @staticmethod
    def _poly_features(X: np.ndarray) -> np.ndarray:
        x, y = X[:, 0], X[:, 1]
        return np.column_stack([np.ones(len(X)), x, y, x**2, x*y, y**2])

    @property
    def is_calibrated(self) -> bool:
        return self._fitted

    @property
    def total_points(self) -> int:
        return len(self.GRID_POINTS)


# ── Dwell detector ────────────────────────────────────────────────────────────

class DwellDetector:
    def __init__(self, dwell_sec: float = DWELL_SEC, radius: float = DWELL_RADIUS_NORM):
        self._dwell_sec = dwell_sec
        self._radius    = radius
        self._origin: Optional[np.ndarray] = None
        self._start: Optional[float] = None
        self._fired = False

    def update(self, pos: np.ndarray) -> bool:
        """Returns True the moment a dwell is completed (fires once per fixation)."""
        if self._origin is None:
            self._origin = pos.copy()
            self._start  = time.time()
            self._fired  = False
            return False

        dist = float(np.linalg.norm(pos - self._origin))
        if dist > self._radius:
            # Moved — reset
            self._origin = pos.copy()
            self._start  = time.time()
            self._fired  = False
            return False

        if not self._fired and (time.time() - self._start) >= self._dwell_sec:
            self._fired = True
            return True

        return False

    def reset(self):
        self._origin = None
        self._start  = None
        self._fired  = False


# ── Worker thread ─────────────────────────────────────────────────────────────

class EyeTrackingWorker(QThread):
    gaze_point           = pyqtSignal(float, float)   # normalised x, y
    dwell_click          = pyqtSignal(float, float)
    calibration_progress = pyqtSignal(int)             # point index collected
    calibration_complete = pyqtSignal()
    error                = pyqtSignal(str)

    def __init__(self, settings, camera_index: int = 0, parent=None):
        super().__init__(parent)
        self.settings     = settings
        self.camera_index = camera_index
        self._running     = False
        self._calibrating = False
        self._calib_point = 0
        self._calib_samples: list[np.ndarray] = []  # buffered for current point
        self._calibration  = GazeCalibration()
        self._kalman       = KalmanFilter2D()
        self._dwell        = DwellDetector(
            dwell_sec=float(settings.get("eye_dwell_sec", DWELL_SEC))
        )
        self._alpha        = float(settings.get("eye_smoothing", SMOOTHING_ALPHA))
        self._last_pos: Optional[np.ndarray] = None

    def start_calibration(self):
        self._calibrating  = True
        self._calib_point  = 0
        self._calib_samples = []
        self._calibration   = GazeCalibration()
        self._kalman.reset()

    def advance_calibration_point(self):
        """Call when user has fixed on the current calibration target."""
        if not self._calibrating or not self._calib_samples:
            return
        avg = np.mean(self._calib_samples, axis=0)
        self._calibration.add_sample(avg, self._calib_point)
        self.calibration_progress.emit(self._calib_point)
        self._calib_point += 1
        self._calib_samples = []

        if self._calib_point >= self._calibration.total_points:
            if self._calibration.fit():
                self._calibrating = False
                self.calibration_complete.emit()
            else:
                self.error.emit("Calibration failed — not enough data")

    def run(self):
        try:
            import cv2
            import mediapipe as mp
        except ImportError as e:
            self.error.emit(f"Missing: {e}. Run: pip install opencv-python mediapipe")
            return

        mp_face = mp.solutions.face_mesh
        self._running = True

        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            self.error.emit(f"Cannot open camera {self.camera_index}")
            return

        # Iris landmark indices (MediaPipe FaceMesh with refine_landmarks=True)
        LEFT_IRIS  = [474, 475, 476, 477]
        RIGHT_IRIS = [469, 470, 471, 472]
        # Eye corner anchors
        L_INNER = 362
        L_OUTER = 263
        R_INNER = 133
        R_OUTER = 33

        with mp_face.FaceMesh(
            refine_landmarks=True,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.7,
        ) as face_mesh:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    continue

                h, w = frame.shape[:2]
                rgb  = cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)
                res  = face_mesh.process(rgb)

                if not res.multi_face_landmarks:
                    continue

                lm = res.multi_face_landmarks[0].landmark

                # ── Iris centres ──────────────────────────────
                l_iris = np.mean([[lm[i].x, lm[i].y] for i in LEFT_IRIS], axis=0)
                r_iris = np.mean([[lm[i].x, lm[i].y] for i in RIGHT_IRIS], axis=0)

                # ── Normalise by eye width ────────────────────
                l_width = abs(lm[L_OUTER].x - lm[L_INNER].x) + 1e-8
                r_width = abs(lm[R_OUTER].x - lm[R_INNER].x) + 1e-8

                l_norm = np.array([
                    (l_iris[0] - lm[L_INNER].x) / l_width,
                    l_iris[1] - (lm[362].y + lm[374].y) / 2,
                ])
                r_norm = np.array([
                    (r_iris[0] - lm[R_INNER].x) / r_width,
                    r_iris[1] - (lm[133].y + lm[145].y) / 2,
                ])

                raw_gaze = (l_norm + r_norm) / 2

                if self._calibrating:
                    self._calib_samples.append(raw_gaze)
                    continue

                # ── Map to screen ─────────────────────────────
                if self._calibration.is_calibrated:
                    screen_pos = self._calibration.map(raw_gaze)
                else:
                    # Uncalibrated fallback: simple linear mapping
                    screen_pos = np.clip(raw_gaze * 2.5 + 0.5, 0, 1)

                if screen_pos is None:
                    continue

                # ── Kalman + EMA smooth ───────────────────────
                screen_pos = self._kalman.update(screen_pos)
                if self._last_pos is not None:
                    screen_pos = self._alpha * screen_pos + (1 - self._alpha) * self._last_pos
                self._last_pos = screen_pos.copy()

                x, y = float(screen_pos[0]), float(screen_pos[1])
                self.gaze_point.emit(x, y)

                if self._dwell.update(screen_pos):
                    self.dwell_click.emit(x, y)

        cap.release()

    def stop(self):
        self._running = False


# ── EyeTracker (public API) ───────────────────────────────────────────────────

class EyeTracker(QObject):
    gaze_point           = pyqtSignal(float, float)
    dwell_click          = pyqtSignal(float, float)
    calibration_progress = pyqtSignal(int)
    calibration_complete = pyqtSignal()
    error                = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._worker: Optional[EyeTrackingWorker] = None

    def start(self, camera_index: int = 0):
        if self._worker and self._worker.isRunning():
            return
        self._worker = EyeTrackingWorker(self.settings, camera_index, self)
        self._worker.gaze_point.connect(self.gaze_point)
        self._worker.dwell_click.connect(self.dwell_click)
        self._worker.calibration_progress.connect(self.calibration_progress)
        self._worker.calibration_complete.connect(self.calibration_complete)
        self._worker.error.connect(self.error)
        self._worker.start()

    def stop(self):
        if self._worker:
            self._worker.stop()
            self._worker.quit()
            self._worker.wait(2000)

    def start_calibration(self):
        if self._worker:
            self._worker.start_calibration()

    def advance_calibration(self):
        if self._worker:
            self._worker.advance_calibration_point()

    @property
    def is_running(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    @property
    def is_calibrated(self) -> bool:
        return bool(self._worker and self._worker._calibration.is_calibrated)
