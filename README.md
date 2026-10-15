# Car Narc

Roadside license plate recognition for a Raspberry Pi 5, built around one priority: **getting the plate right**.

A plate detector finds plates in each frame, an OCR model reads them, and a tracker follows each plate across frames and votes character-by-character, so one blurry frame can't produce the final read. Results go to SQLite with snapshots, and a password-protected web dashboard shows them, with a watchlist that also flags near-misses (one character off).

> **Status: v0.1, plate pipeline scaffold.** The logic is unit-tested, but it has **not yet been run on a real road, a real Pi, or real plate photos**. See [What's verified](#whats-verified).

## What works today

| Piece | State |
|---|---|
| Plate detection (open-image-models, YOLOv9) with lane ROI cropping | Loads and runs; **not yet validated on real plate photos** |
| Plate OCR (fast-plate-ocr) | Verified on rendered plate crops, with correct color handling and per-character confidences |
| Multi-frame tracker + voting | Unit-tested, including fast movers with no box overlap between frames |
| Duplicate-read merge (one car read twice) | Unit-tested; verified on one real traffic clip, see [docs/EVALUATION.md](docs/EVALUATION.md) |
| SQLite log, snapshots, watchlist (exact + near match) | Unit-tested |
| Web dashboard + JSON API with auth | Unit-tested |
| `carnarc bench` accuracy scoring | Unit-tested; needs your labeled photos to be useful |
| USB / RTSP / video-file cameras | Implemented, only exercised with a video file |
| Pi CSI camera (picamera2) | Implemented, **untested on hardware** |
| Hailo AI HAT+ acceleration | Not started (CPU/ONNX only for now) |
| Make / model / color classification | Not started (planned after plate accuracy) |
| Push alerts, MQTT | Not started |
| Night mode (IR) | Not started |

## Quick start

Requires Python 3.10+ (Ubuntu 24.04 ships 3.12).

```bash
git clone https://github.com/MGeezy1/Car-Narc.git && cd Car-Narc
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp config.example.yaml config.yaml   # edit camera.source etc.
carnarc check                        # loads the models and times them on this machine
carnarc run --source clip.mp4 --dry-run   # replay a video, print reads, write nothing
carnarc run                          # capture for real (writes to ./data, git-ignored)

export CARNARC_TOKEN='something-long'
carnarc web                          # dashboard on http://127.0.0.1:8080
```

Models (a few MB) download on first use and are cached outside the repo.

## Measuring plate accuracy

Accuracy claims are worthless without your own data, so measure it:

```bash
# labels.csv:  filename,PLATE   (one row per image)
carnarc bench ./photos ./photos/labels.csv            # full frames: detect + OCR
carnarc bench ./crops  ./crops/labels.csv --crops     # images are already plate crops
```

It reports exact-match rate, character error rate, and lists every miss. This scores **single-frame** reads; to see what voting adds, replay a video of a known plate with `carnarc run --dry-run`.

The knobs that matter most for distant plates are in `config.example.yaml`: `detection.roi` (crop to the lane so plates look bigger to the detector), `detection.plate_model` (larger input finds smaller plates, slower), and `camera.exposure_us` (fast shutter to avoid motion blur).

## Security

This device stores plates and photos, so it is locked down by default:

- The dashboard binds to loopback. `carnarc web` **refuses to listen on any other address without a password** (`CARNARC_TOKEN`).
- Every route requires the token (HTTP Basic, any username) when one is set; snapshot paths are confined to the snapshot directory; mutating routes only accept JSON.
- `.gitignore` keeps the database, snapshots, `config.yaml` and secrets out of this public repo. Never commit captures.
- For remote access, keep the default host and use [Tailscale](https://tailscale.com) (`tailscale serve`), or set a token and bind to the Tailscale IP.
- If the device could be physically taken, encrypt the data disk (LUKS) and keep the unlock key off the device. See [docs/HARDWARE.md](docs/HARDWARE.md).

## Responsible use

Personal project. Run it on your own property or with the landowner's permission; don't mount equipment on utility poles or in the road right-of-way. Laws on collecting and retaining plate data vary by state and use. Check yours, and don't use this to harass or track people.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the pipeline works and why, including the speed math
- [docs/HARDWARE.md](docs/HARDWARE.md): parts list, power budget, mounting, night
- [docs/EVALUATION.md](docs/EVALUATION.md): how it did on real footage, and at lower frame rates
- [docs/INSTALL.md](docs/INSTALL.md): install on a PC or a Pi 5, systemd services, Tailscale
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md): every setting
- [docs/USAGE.md](docs/USAGE.md): commands, dashboard, JSON API, watchlist, troubleshooting
- [docs/TUNING.md](docs/TUNING.md): getting the most accurate reads
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): tests, adding config keys and outputs
- [CHANGELOG.md](CHANGELOG.md)

## Roadmap

1. Validate on real plate photos and tune thresholds (needs a labeled set from the actual mount)
2. Hailo AI HAT+ inference path
3. Make / color classifier on the vehicle crop, plus a "label this" screen to build a rear-view training set
4. Alerts (ntfy / MQTT) behind the dashboard's settings
5. Night mode (IR illumination, separate camera profile)

## Credits

Built on [fast-plate-ocr](https://github.com/ankandrew/fast-plate-ocr) and [open-image-models](https://github.com/ankandrew/open-image-models) (both MIT), ONNX Runtime, OpenCV and FastAPI. [OpenALPR](https://github.com/openalpr/openalpr) was evaluated and not used: it is AGPL-licensed and its open-source build is no longer actively developed.

## License

MIT, see [LICENSE](LICENSE).
