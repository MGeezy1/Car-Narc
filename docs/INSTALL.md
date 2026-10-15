# Installation

> **What has been tested:** the install on a regular Linux machine (Python 3.13) and all tests. The Raspberry Pi 5 steps below follow standard Ubuntu practice but **have not been run on a Pi yet**: the Pi CSI camera path (`picamera2`), systemd units and Tailscale steps are untested here. Treat them as a starting point and report what breaks.

## Any Linux machine (development / replaying clips)

Requires Python 3.10+ (Ubuntu 24.04 ships 3.12).

```bash
git clone https://github.com/MGeezy1/Car-Narc.git && cd Car-Narc
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # drop [dev] if you don't need the tests
cp config.example.yaml config.yaml
carnarc check                       # needs internet the first time (model download)
carnarc run -c config.yaml --source clip.mp4 --dry-run
pytest                              # fast tests; `pytest -m slow` also runs the real models
```

Models download on first use into `~/.cache/open-image-models` and `~/.cache/fast-plate-ocr`. After that no internet is needed. For a Pi that will be offline, run `carnarc check` once while it has internet (or copy those two cache folders over).

## Raspberry Pi 5, Ubuntu 24.04

1. **Flash and update.** Ubuntu Server 24.04 for Pi, then `sudo apt update && sudo apt full-upgrade`.
2. **Use an SSD for data.** Plates and snapshots write constantly and wear SD cards. Mount a USB SSD (or NVMe HAT) at e.g. `/mnt/data` and set `storage.data_dir: /mnt/data/carnarc`. If the device could be stolen, encrypt that disk with LUKS (see [HARDWARE.md](HARDWARE.md)).
3. **Install the app** as above, in `/opt/car-narc` or your home directory.
4. **Camera.**
   - USB or RTSP camera: set `camera.source` to the index or URL. Nothing else needed.
   - Pi CSI camera: set `camera.source: picamera2`. `picamera2` comes from apt (`sudo apt install python3-picamera2`), which only installs for the system Python, so create the venv with `python3 -m venv --system-site-packages .venv`. *(Untested on hardware.)*
5. **Measure.** `carnarc check` prints real detection ms/frame and OCR ms/plate on the Pi. Those numbers decide your usable frame rate; the development-machine numbers are not representative. If detection is too slow, try a smaller `detection.plate_model` or a tighter `detection.roi`.

## Run as services (systemd)

Keep the dashboard password out of the unit files and out of git:

```bash
sudo install -m 600 /dev/null /etc/carnarc.env
echo "CARNARC_TOKEN=$(openssl rand -base64 24)" | sudo tee /etc/carnarc.env >/dev/null
```

`/etc/systemd/system/carnarc-run.service`:

```ini
[Unit]
Description=Car Narc capture
After=network.target

[Service]
User=carnarc
WorkingDirectory=/opt/car-narc
ExecStart=/opt/car-narc/.venv/bin/carnarc run -c /opt/car-narc/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/carnarc-web.service`:

```ini
[Unit]
Description=Car Narc dashboard
After=network.target

[Service]
User=carnarc
WorkingDirectory=/opt/car-narc
EnvironmentFile=/etc/carnarc.env
ExecStart=/opt/car-narc/.venv/bin/carnarc web -c /opt/car-narc/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd --system --create-home carnarc    # and give it write access to storage.data_dir
sudo systemctl daemon-reload
sudo systemctl enable --now carnarc-run carnarc-web
journalctl -u carnarc-run -f
```

The capture and dashboard are separate on purpose: a dashboard crash never interrupts capture.

## Remote access

Install [Tailscale](https://tailscale.com/download), `sudo tailscale up`, then `sudo tailscale serve --bg 8080` to publish the loopback dashboard to your tailnet only. Don't use Funnel (that is public internet). More on the privacy trade-offs in [HARDWARE.md](HARDWARE.md).

## Updating

```bash
git pull && pip install -e . && sudo systemctl restart carnarc-run carnarc-web
```

The database schema is created on start; there are no migrations yet, so check [CHANGELOG.md](../CHANGELOG.md) before upgrading a device with data you want to keep.
