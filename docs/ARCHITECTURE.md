# Architecture

```
camera ──► frame ──► plate detector ──► crop (+margin) ──► OCR ──► tracker/voting ──► sinks
 (newest              (ROI only)                          (RGB,     (per-plate          ├─ SQLite + snapshots
  frame wins)                                              per-char  consensus)         ├─ log
                                                           conf.)                       └─ (alerts: planned)
```

Capture (`carnarc run`) and the dashboard (`carnarc web`) are separate processes that share one SQLite database in WAL mode, so a dashboard crash never interrupts capture.

## Why plates are tracked, not just read

A car at 70 mph covers about 103 ft/s. Even a telephoto camera sees a plate clearly for well under a second, which is only a handful of frames. Any single OCR read can be wrong (blur, glare, a partial frame), and one wrong character makes a plate useless for matching.

So each plate gets a track, every OCR read is kept, and the result is a vote:

1. Group reads by length; the group with the most total confidence wins (this rejects a read that picked up an extra or missing character).
2. In that group, choose each character position by confidence-weighted vote.
3. `confidence = (group's share of all weight) × (mean per-position agreement) × (mean read confidence)`, so disagreement in length, in characters, or low model confidence all pull it down.
4. Dissenting reads are kept as `alternatives` and shown in the dashboard instead of being hidden.

A result is only emitted once the plate leaves view (or the stream ends), and only if it has `tracking.min_reads` reads, a plausible length, and `plate_rules.min_confidence`.

## Association

Tracks match new detections by IoU against the *predicted* box (last box plus per-frame velocity). Fast movers can jump more than a plate width between frames, giving zero overlap, so a center-distance gate (`tracking.gate_widths`) provides a fallback match, scored below any real overlap.

Known limitation: two plates very close together (tailgating) can be associated to the wrong track. The vote's agreement term makes such a track's confidence low rather than silently wrong, but it is not solved.

## Details that matter for accuracy

- **Color order.** OpenCV frames are BGR; the OCR model expects RGB (or grayscale, per its config). `PlateReader` converts. Skipping this runs without errors and quietly hurts accuracy.
- **Padded confidences.** fast-plate-ocr returns fixed character slots; confidences are trimmed to the decoded text so text and confidences stay aligned.
- **ROI before detection.** The detector resizes its input (e.g. 640 px). A 1080p frame squeezed to 640 px shrinks a distant plate by 3x; cropping to the lane first keeps it larger.
- **Minimum crop size.** Detections under 24x8 px are skipped; a plate that small is mostly interpolation and would pollute the vote.
- **Newest frame wins.** Live cameras are read on a background thread and inference always gets the latest frame; if inference is slower than the camera, frames are dropped, not queued.

## The speed math

At 70 mph (~31 m/s) a camera aimed down the road at departing rear plates sees them move slowly in-frame, while a side-on camera sees them streak. Shutter matters most: a plate moving 31 m/s blurs by ~1.5 cm per 1/2000 s exposure, which is the reason for `camera.exposure_us: 500` and a global-shutter or fast-sensor camera. Slower shutters rolling-skew and smear the characters, and no OCR model fully recovers that.

## Layout

```
src/carnarc/
  camera.py     frame sources (USB / RTSP / file / picamera2)
  detect.py     plate detector wrapper (ROI handling)
  ocr.py        OCR wrapper (color order, confidence alignment)
  tracker.py    association + voting   <- the accuracy-critical module
  pipeline.py   wires it together, stats, sink fan-out
  storage.py    SQLite, watchlist, snapshot files
  outputs.py    sinks (log, store)
  web/          FastAPI dashboard + API
  bench.py      accuracy scoring
  cli.py        carnarc run | web | bench | check
tests/          unit tests with fake models; `pytest -m slow` runs the real ONNX models
```
