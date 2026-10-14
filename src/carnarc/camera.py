"""Frame sources: USB / RTSP / video file via OpenCV, and Pi CSI via picamera2.

Live sources (USB, RTSP, CSI) always deliver the *newest* frame: if inference is
slower than the camera, stale frames are dropped rather than queued, so latency
never builds up. Video files are read in order with no dropping (for repeatable
testing).

Each frame is a fresh numpy array; downstream code keeps references to the best
frames and relies on that.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Iterator, Protocol

import cv2
import numpy as np

from .config import CameraConfig

log = logging.getLogger(__name__)


@dataclass
class Frame:
    idx: int
    ts: float  # wall-clock seconds
    image: np.ndarray  # BGR


class FrameSource(Protocol):
    def frames(self) -> Iterator[Frame]: ...

    def close(self) -> None: ...


def _is_live(source: str) -> bool:
    s = source.strip().lower()
    return s.isdigit() or s.startswith(("rtsp://", "rtsps://", "http://", "https://"))


class OpenCVSource:
    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self.live = _is_live(cfg.source)
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._latest: Frame | None = None
        self._thread: threading.Thread | None = None

    def _open(self) -> cv2.VideoCapture:
        src = self.cfg.source.strip()
        is_usb = src.isdigit()
        cap = cv2.VideoCapture(int(src) if is_usb else src)
        if not cap.isOpened():
            raise RuntimeError(f"could not open camera source: {self.cfg.source}")
        if is_usb:
            # MJPG is what makes 1080p30 possible on most USB webcams.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
            cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    # -- live: background reader keeps only the newest frame -----------------

    def _reader(self) -> None:
        idx = 0
        cap: cv2.VideoCapture | None = None
        while not self._stop.is_set():
            try:
                if cap is None:
                    cap = self._open()
                ok, img = cap.read()
                if not ok:
                    raise RuntimeError("read failed")
            except Exception as exc:  # reconnect: IP cameras drop out
                log.warning("camera error (%s); reconnecting in 2s", exc)
                if cap is not None:
                    cap.release()
                    cap = None
                self._stop.wait(2.0)
                continue
            idx += 1
            with self._cond:
                self._latest = Frame(idx, time.time(), img)
                self._cond.notify_all()
        if cap is not None:
            cap.release()

    def _live_frames(self) -> Iterator[Frame]:
        self._thread = threading.Thread(target=self._reader, name="camera-reader", daemon=True)
        self._thread.start()
        last_idx = 0
        while not self._stop.is_set():
            with self._cond:
                self._cond.wait_for(
                    lambda: self._stop.is_set() or (self._latest is not None and self._latest.idx > last_idx),
                    timeout=1.0,
                )
                frame = self._latest
            if frame is not None and frame.idx > last_idx:
                last_idx = frame.idx
                yield frame

    # -- file: sequential, nothing dropped -----------------------------------

    def _file_frames(self) -> Iterator[Frame]:
        cap = self._open()
        fps = cap.get(cv2.CAP_PROP_FPS) or float(self.cfg.fps)
        idx = 0
        t0 = time.time()
        try:
            while not self._stop.is_set():
                ok, img = cap.read()
                if not ok:
                    return
                idx += 1
                # Synthetic timestamps from the video clock so results are reproducible.
                yield Frame(idx, t0 + idx / fps, img)
        finally:
            cap.release()

    def frames(self) -> Iterator[Frame]:
        return self._live_frames() if self.live else self._file_frames()

    def close(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=3.0)


class PiCamera2Source:
    """Raspberry Pi CSI camera. Not yet tested on real hardware.

    picamera2's "RGB888" format is stored B,G,R in memory, i.e. already the
    channel order OpenCV expects, so no conversion is applied.
    """

    def __init__(self, cfg: CameraConfig):
        from picamera2 import Picamera2  # type: ignore[import-not-found]

        self.cfg = cfg
        self._stop = threading.Event()
        self._cam = Picamera2()
        controls: dict[str, object] = {"FrameDurationLimits": (int(1e6 / cfg.fps),) * 2}
        if cfg.exposure_us is not None:
            controls["ExposureTime"] = int(cfg.exposure_us)
        if cfg.gain is not None:
            controls["AnalogueGain"] = float(cfg.gain)
        self._cam.configure(
            self._cam.create_video_configuration(
                main={"size": (cfg.width, cfg.height), "format": "RGB888"},
                controls=controls,
            )
        )
        self._cam.start()

    def frames(self) -> Iterator[Frame]:
        idx = 0
        while not self._stop.is_set():
            img = self._cam.capture_array("main")
            idx += 1
            yield Frame(idx, time.time(), img)

    def close(self) -> None:
        self._stop.set()
        self._cam.stop()
        self._cam.close()


def open_source(cfg: CameraConfig) -> FrameSource:
    if cfg.source.strip().lower() == "picamera2":
        return PiCamera2Source(cfg)
    return OpenCVSource(cfg)
