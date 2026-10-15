# Usage

## Commands

```
carnarc check                          load both models and time them on this machine
carnarc run [-c config.yaml] [--source SRC] [--dry-run]
carnarc web [-c config.yaml] [--host H] [--port P]
carnarc bench IMAGES LABELS.csv [--crops] [-c config.yaml]
```

- **`check`** — run this first on any new machine; it reports model load time, detection ms/frame at your configured resolution, and OCR ms/plate.
- **`run`** — capture and recognize. Writes reads to the database and snapshots under `storage.data_dir`. `--source` overrides `camera.source` (a USB index, `rtsp://` URL, video file, or `picamera2`). `--dry-run` uses the real models but only prints reads and writes nothing, which is the safe way to test a mount or replay a clip. Stop with Ctrl-C; pending plates and held merges are flushed on exit.
- **`web`** — the dashboard and JSON API (separate process from `run`; they share the database). Without `CARNARC_TOKEN` it only listens on loopback, and it refuses to start on any other address:

  ```
  refusing to listen on 0.0.0.0: this dashboard shows logged plates and has no
  password. Set one first:  export CARNARC_TOKEN='something-long'
  (or keep host 127.0.0.1 and expose it with `tailscale serve`).
  ```
- **`bench`** — scores single-frame accuracy against your labeled photos (`filename,PLATE` per row). `--crops` if the images are already plate crops. Reports exact-match rate, character error rate and every miss.

## Dashboard

Open the dashboard URL (default `http://127.0.0.1:8080`). When a token is set, the browser asks for a login: **any username, the token as the password**. The page refreshes every 5 seconds and shows the latest reads with snapshots, confidence, read count and alternative readings, plus a watchlist editor.

## Watchlist

Add plates from the dashboard or the API. Plates are normalized to uppercase letters and digits (`my car-1` becomes `MYCAR1`).

Each read gets a `watchlist_hit` value **when it is recorded**:

| Value | Meaning |
|---|---|
| `0` | no match |
| `1` | exact match |
| `2` | near match: same length, exactly one character different (OCR confuses look-alike characters, so a near match is worth a look) |

Adding a plate to the watchlist does **not** re-flag reads already in the database. Hits are also logged by the running capture process.

## JSON API

All routes need the same Basic auth as the dashboard when a token is set (`-u me:$CARNARC_TOKEN`); without credentials they return `401`. The outputs below are real responses from a running server.

```bash
B=http://127.0.0.1:8080; A="-u me:$CARNARC_TOKEN"

curl -s $A $B/api/status
# {"version":"0.1.0","reads":3,"watchlist":1}

curl -s $A "$B/api/reads?limit=2"          # newest first; limit 1..500 (default 50), offset
curl -s $A "$B/api/reads?plate=abc"        # plate prefix filter (case-insensitive)
curl -s $A $B/api/reads/1
# {"id":1,"ts":1000000001.0,"plate":"ABC1234","confidence":0.97,"n_reads":12,
#  "alternatives":[["ABC1Z34",0.08]],"snapshot":"2001-09-08/214641_1_ABC1234.jpg",
#  "crop":"2001-09-08/214641_1_ABC1234_plate.jpg","watchlist_hit":1}

curl -s $A -o plate.jpg $B/snapshots/2001-09-08/214641_1_ABC1234.jpg   # image/jpeg

curl -s $A $B/api/watchlist
# [{"plate":"ABC1234","label":"test car","added_ts":1792024010.34}]

curl -s $A -X POST -H 'Content-Type: application/json' \
     -d '{"plate":"my car-1","label":"neighbour"}' $B/api/watchlist
# {"plate":"MYCAR1","label":"neighbour"}            (201; re-adding updates the label)

curl -s $A -X DELETE $B/api/watchlist/MYCAR1        # 204; 404 if not on the list
```

Fields of a read: `ts` is Unix time the plate was last seen; `confidence` is the consensus confidence (0..1); `n_reads` is how many OCR reads were voted; `alternatives` lists dissenting readings with their weight; `snapshot` / `crop` are paths relative to `/snapshots/` (or `null`).

Errors: `401` bad or missing credentials, `404` unknown read/snapshot/watchlist plate, `422` malformed body (the watchlist routes accept JSON only, so a form post from another website cannot change it).

## Remote access

Keep `web.host` on loopback and use Tailscale to reach it:

```bash
sudo tailscale serve --bg 8080      # https://<device>.<tailnet>.ts.net, tailnet only
```

Set `CARNARC_TOKEN` anyway, so other devices on your tailnet still need the password. See [HARDWARE.md](HARDWARE.md) for what a stolen device exposes and how to stay anonymous.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `unknown key(s) under 'x'` | Typo in config.yaml; the message lists the valid keys. |
| First run is slow or fails offline | The models download once (~few MB) into `~/.cache/open-image-models` and `~/.cache/fast-plate-ocr`. Run `carnarc check` once with internet, then it works offline. |
| No reads at all | Run `--dry-run` on a clip of a clear plate. Check `detection.roi` isn't excluding the lane, and that plates are at least ~24x8 px in the frame (smaller detections are skipped). |
| Reads are wrong or fragmented | See [TUNING.md](TUNING.md). |
| Dashboard shows nothing | `carnarc web` and `carnarc run` must use the same `storage.data_dir`; relative paths depend on the directory you start from. |
