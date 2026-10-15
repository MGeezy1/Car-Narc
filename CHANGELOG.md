# Changelog

## Unreleased (v0.1.x)

- Plate pipeline: detector (open-image-models), OCR (fast-plate-ocr), multi-frame tracker with character-level confidence voting.
- Duplicate-read merge: joins reads of one vehicle that the tracker split (non-overlapping, near-identical plates, live-successor hold).
- SQLite storage with snapshots; watchlist with exact and one-character-off matching (computed when a read is recorded).
- Web dashboard and JSON API with token auth, loopback by default, path-confined snapshots.
- `carnarc run | web | bench | check`.
- Documentation: architecture, hardware, evaluation, installation, configuration, usage, tuning, development.

Not yet built or verified: Pi hardware run, picamera2 camera, Hailo acceleration, make/color classification, alerts/MQTT, night mode.
