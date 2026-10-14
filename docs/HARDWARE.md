# Hardware notes

Draft parts list and constraints. Figures are estimates, not measurements; they will be replaced with real numbers once it runs on hardware.

## Parts (draft)

- Raspberry Pi 5, 8 GB, with the official active cooler
- Hailo AI HAT+ (26 TOPS). Treat as required for real-time work at road speed; CPU-only gives a few frames per second. The Hailo software path is **not written yet**.
- USB SSD for the database and snapshots (the HAT uses the Pi's PCIe slot, so no NVMe)
- Camera, one of:
  - Raspberry Pi HQ or Global Shutter camera with a 16-25 mm C/CS lens (cheaper, all on the Pi)
  - A dedicated LPR IP camera over RTSP with varifocal lens, fast shutter and built-in IR (costs more, also covers night)
- Power: 12 V LiFePO4 battery, solar panel and charge controller, 12 V to 5 V 5 A buck converter
- LTE modem or hotspot for backhaul
- Weatherproof enclosure with cable glands

## Camera requirements for roadside at up to 70 mph

- Shutter 1/2000 s or faster. Global shutter preferred; a rolling shutter skews fast-moving characters.
- 30 fps, so a pass yields several usable frames.
- Aim down the road at rear plates, nearly in line with the lane, rather than side-on. Plates stay readable much longer.
- Focal length depends on distance to the lane and the number of lanes. **Open question:** the actual distance and lane count are still unknown, so the lens is not chosen.

## Power (estimate)

A Pi 5 with a Hailo HAT and a camera likely draws 12-18 W, which is roughly 300-400 Wh per day. That is about three days on a 100 Ah LiFePO4 battery, less once the cell modem is counted. A 100-200 W panel with a charge controller makes it self-sustaining in most conditions; idling the pipeline until motion is detected would cut the draw. Measure the real draw before sizing the battery.

## OS

Ubuntu 24.04 is the target. Hailo's driver and runtime are officially supported on Raspberry Pi OS, not Ubuntu, so the Hailo install may need extra work. If it fights us, Raspberry Pi OS is the fallback; the Python code is the same either way. Likewise, picamera2 is packaged for Raspberry Pi OS and needs checking on Ubuntu. Neither has been tried.

## Securing a device that might be taken

What someone could pull from a stolen unit, and mitigations:

| Exposure | Mitigation |
|---|---|
| Stored plates, timestamps, snapshots | Encrypt the data SSD with LUKS. The Pi 5 has no TPM or secure boot, so keep the key off the device and unlock it remotely after each boot. |
| Tailscale node key (lets them join your tailnet as the device) | Use a tagged key and an ACL allowing only your own devices to reach the Pi and nothing outbound from it; revoke the node in the admin console if lost. Tailscale Lock adds protection against rogue nodes. |
| Dashboard token, alert tokens, MQTT credentials | One token per service, nothing personal on the device. |
| The SIM | Its number and account tie back to whoever bought it. |
| Volume of data | Keep less: shorter retention, or plate text plus a thumbnail only. |

Tailscale is tied to a login identity (Google, GitHub, ...), and its coordination server sees device metadata. [Headscale](https://github.com/juanfont/headscale) (self-hosted control server) or plain WireGuard to a small VPS you control removes that dependency. Cellular carriers put devices behind CGNAT, which is why plain WireGuard would need that relay.

## Where it goes

Use your own property or get the landowner's permission. Mounting on a utility pole or in the road right-of-way can be illegal.
