"""Configuration: dataclasses with defaults, loaded from YAML.

Unknown keys raise, so a typo in config.yaml fails loudly instead of silently
running with a default.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import yaml

T = TypeVar("T")


@dataclass
class CameraConfig:
    source: str = "0"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    exposure_us: int | None = 500
    gain: float | None = None


@dataclass
class DetectionConfig:
    plate_model: str = "yolo-v9-t-640-license-plate-end2end"
    conf_thresh: float = 0.4
    roi: list[float] = field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0])
    crop_margin: float = 0.08


@dataclass
class OcrConfig:
    model: str = "cct-xs-v2-global-model"
    device: str = "cpu"


@dataclass
class TrackingConfig:
    iou_threshold: float = 0.2
    gate_widths: float = 3.0
    max_missed_frames: int = 8
    min_reads: int = 2


@dataclass
class PlateRulesConfig:
    min_length: int = 5
    max_length: int = 8
    min_confidence: float = 0.5


@dataclass
class MergeConfig:
    # A finished read is held this long (seconds after the plate was last seen) in
    # case another track of the same vehicle follows. 0 disables merging, and reads
    # are emitted immediately.
    window_s: float = 3.0
    # Plates this close (single-character edits) can be the same vehicle.
    max_edit_distance: int = 2
    # A read is also held while a track that started right after it is still live (that
    # track is probably the same vehicle, not finished yet). Never longer than this.
    max_hold_s: float = 10.0


@dataclass
class StorageConfig:
    data_dir: str = "data"
    save_snapshots: bool = True
    jpeg_quality: int = 90


@dataclass
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    token_env: str = "CARNARC_TOKEN"


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    plate_rules: PlateRulesConfig = field(default_factory=PlateRulesConfig)
    merge: MergeConfig = field(default_factory=MergeConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    web: WebConfig = field(default_factory=WebConfig)

    @property
    def data_dir(self) -> Path:
        return Path(self.storage.data_dir)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "carnarc.db"

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"


class ConfigError(ValueError):
    pass


def _build(cls: type[T], data: Any, path: str) -> T:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"'{path}' must be a mapping, got {type(data).__name__}")
    fields = {f.name: f for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    unknown = set(data) - set(fields)
    if unknown:
        raise ConfigError(
            f"unknown key(s) under '{path}': {', '.join(sorted(unknown))} "
            f"(valid: {', '.join(sorted(fields))})"
        )
    kwargs: dict[str, Any] = {}
    for name, value in data.items():
        ftype = fields[name].type
        if isinstance(ftype, str):
            ftype = _resolve(ftype)
        if dataclasses.is_dataclass(ftype):
            kwargs[name] = _build(ftype, value, f"{path}.{name}" if path else name)
        else:
            kwargs[name] = value
    return cls(**kwargs)


def _resolve(type_name: str) -> Any:
    return globals().get(type_name, type_name)


def validate(cfg: Config) -> None:
    roi = cfg.detection.roi
    if len(roi) != 4 or not all(isinstance(v, (int, float)) for v in roi):
        raise ConfigError("detection.roi must be four numbers: [x, y, width, height]")
    x, y, w, h = roi
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.0001 and y + h <= 1.0001):
        raise ConfigError("detection.roi must stay inside the frame (fractions 0..1)")
    if not 0 <= cfg.detection.conf_thresh <= 1:
        raise ConfigError("detection.conf_thresh must be between 0 and 1")
    if cfg.plate_rules.min_length > cfg.plate_rules.max_length:
        raise ConfigError("plate_rules.min_length cannot exceed max_length")
    if cfg.tracking.min_reads < 1:
        raise ConfigError("tracking.min_reads must be at least 1")
    if cfg.merge.window_s < 0 or cfg.merge.max_edit_distance < 0 or cfg.merge.max_hold_s < 0:
        raise ConfigError("merge.window_s, merge.max_edit_distance and merge.max_hold_s cannot be negative")
    if not 1 <= cfg.storage.jpeg_quality <= 100:
        raise ConfigError("storage.jpeg_quality must be 1..100")
    cfg.camera.source = str(cfg.camera.source)


def load_config(path: str | Path | None = None) -> Config:
    """Load config from YAML. With no path, returns defaults."""
    if path is None:
        cfg = Config()
    else:
        p = Path(path)
        if not p.is_file():
            raise ConfigError(f"config file not found: {p}")
        raw = yaml.safe_load(p.read_text()) or {}
        cfg = _build(Config, raw, "")
    validate(cfg)
    return cfg
