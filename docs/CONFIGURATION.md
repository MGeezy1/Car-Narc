# Configuration reference

Settings live in a YAML file (`cp config.example.yaml config.yaml`, which is git-ignored) passed with `-c config.yaml`. With no `-c`, built-in defaults are used. **Unknown keys are rejected**, so a typo fails at startup instead of silently using a default. `config.example.yaml` is tested to match the built-in defaults exactly.

Everything below is `section.key`, its default, and what it does. Ranges are enforced on load.

## camera

| Key | Default | Meaning |
|---|---|---|
| `camera.source` | `"0"` | USB webcam index (`0`, `1`..), an `rtsp://` URL, a video file path, or `picamera2` for the Pi CSI camera. A video file is processed in order with no frame dropping; live sources always give the newest frame and drop the rest when inference is slower than the camera. |
| `camera.width` | `1920` | Capture width in pixels. |
| `camera.height` | `1080` | Capture height in pixels. |
| `camera.fps` | `30` | Requested frame rate (the camera may give less). |
| `camera.exposure_us` | `500` | picamera2 only. Exposure in microseconds; 500 = 1/2000 s, which freezes a plate at highway speed. Raise it only if the image is too dark and you accept blur. `null` leaves it to auto. |
| `camera.gain` | `null` | picamera2 only. `null` = auto. |

## detection

| Key | Default | Meaning |
|---|---|---|
| `detection.plate_model` | `yolo-v9-t-640-license-plate-end2end` | Plate detector. Larger input finds smaller (more distant) plates but is slower. Options: `yolo-v9-t-256/384/416/512/640-license-plate-end2end`, `yolo-v9-s-608-license-plate-end2end`. |
| `detection.conf_thresh` | `0.4` | Minimum detector confidence, 0..1. Lower finds more plates and more false ones. |
| `detection.roi` | `[0, 0, 1, 1]` | Region searched, as fractions `[x, y, width, height]` of the frame. Cropping to the lane makes distant plates bigger to the detector. Must stay inside the frame. |
| `detection.crop_margin` | `0.08` | Padding around each detected plate before OCR, as a fraction of its size. |

## ocr

| Key | Default | Meaning |
|---|---|---|
| `ocr.model` | `cct-xs-v2-global-model` | fast-plate-ocr model name. |
| `ocr.device` | `cpu` | `cpu`, `cuda` or `auto`. |

## tracking

| Key | Default | Meaning |
|---|---|---|
| `tracking.iou_threshold` | `0.2` | Minimum box overlap with a track's predicted position to match. |
| `tracking.gate_widths` | `3.0` | Fallback match: a box within this many plate-widths of the predicted position still matches (fast movers can have zero overlap between frames). |
| `tracking.max_missed_frames` | `8` | Frames without a detection before a track is closed. Counts *frames*, not seconds, so retune it if you change the frame rate. |
| `tracking.min_reads` | `2` | OCR reads a track needs before it can produce a result. Higher removes wrong one-off reads but misses cars that are only seen briefly; the right value depends on frame rate (see [EVALUATION.md](EVALUATION.md)). |

## plate_rules

| Key | Default | Meaning |
|---|---|---|
| `plate_rules.min_length` | `5` | Shortest plausible plate (characters). |
| `plate_rules.max_length` | `8` | Longest plausible plate. Must be at least `min_length`. |
| `plate_rules.min_confidence` | `0.5` | Results with a consensus confidence below this are dropped. |

## merge

| Key | Default | Meaning |
|---|---|---|
| `merge.window_s` | `3.0` | A finished read is held this many seconds so a later track of the same vehicle can be merged into it. `0` turns merging off and emits reads immediately. |
| `merge.max_edit_distance` | `2` | Plates within this many single-character edits can be the same vehicle. |
| `merge.max_hold_s` | `10.0` | A read also waits while a track that began just after it is still live; never longer than this. |

Cost of merging: a read is emitted up to `window_s` seconds after the plate leaves view. See [ARCHITECTURE.md](ARCHITECTURE.md#merging-fragments-of-one-vehicle).

## storage

| Key | Default | Meaning |
|---|---|---|
| `storage.data_dir` | `data` | Where the database (`carnarc.db`) and `snapshots/` go. Relative paths are relative to where you start the command; use an absolute path for services. Put it on an SSD, not an SD card, for long-term use. |
| `storage.save_snapshots` | `true` | Save the full frame (plate boxed) and the plate crop as JPEGs per read. |
| `storage.jpeg_quality` | `90` | 1..100. |

## web

| Key | Default | Meaning |
|---|---|---|
| `web.host` | `127.0.0.1` | Dashboard bind address. Anything other than loopback requires a password. |
| `web.port` | `8080` | Dashboard port. |
| `web.token_env` | `CARNARC_TOKEN` | Name of the environment variable holding the dashboard password. |

The password is never stored in the config file. Command-line `--host` / `--port` on `carnarc web` override these.
