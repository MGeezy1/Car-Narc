# Tuning for accuracy

Defaults are reasonable guesses, **not** tuned on your mount. The only way to tune honestly is to record clips from your camera position and measure. Everything here is a lever to try, in rough order of payoff.

## 1. Get the picture right (biggest effect, no software)

- **Aim down the road at departing rear plates.** A side-on camera sees plates streak; a down-lane camera sees them move slowly in-frame.
- **Shutter.** 1/2000 s (`camera.exposure_us: 500`) or faster. Motion blur cannot be fixed by OCR.
- **Plate size in pixels.** Aim for a plate at least ~100-150 px wide when it is read, and never under 24x8 (those detections are skipped). Narrow the lens field of view or move closer; a lens choice needs your distance to the lane and the lane count.
- **Light.** Glare and backlight hurt more than resolution. Night needs IR illumination and is not built yet.

## 2. Help the detector

- `detection.roi`: crop to the lane. The detector shrinks its input (e.g. to 640 px), so a full 1080p frame makes a distant plate ~3x smaller than a lane-only crop.
- `detection.plate_model`: a larger input finds smaller plates and costs CPU. Check `carnarc check` for the cost on your hardware.
- `detection.conf_thresh`: lower to catch more plates, at the price of false detections (which the plate rules and voting mostly filter).

## 3. Trade recall against wrong reads

- `tracking.min_reads`: raising it removes wrong one-off reads but misses briefly-seen cars. On the one clip tested, 2 to 5 removed some wrong reads at 30 fps at no cost, but cost two more missed cars at 3 fps. At 70 mph you get far fewer frames per car, so don't copy a high value blindly.
- `plate_rules.min_confidence`: raise to be pickier. Non-plate text (signs, placards) can read around 0.6, so 0.5 may let some through.
- `plate_rules.min_length` / `max_length`: set to what your state's plates actually are.

## 4. Frame rate and tracking

- `tracking.max_missed_frames` counts frames. If inference runs at 5 fps instead of 30, 8 missed frames is 1.6 s, not 0.27 s. Reduce it as the processed frame rate drops, or neighbouring cars can be absorbed into one track.
- `tracking.gate_widths` / `iou_threshold`: raise the gate if fast cars lose their tracks between frames; lower it if different cars get joined.

## 5. Duplicates

If one car shows up as several reads: raise `merge.window_s` (costs emit delay) or `merge.max_edit_distance`. If two different cars with similar plates get merged: lower `max_edit_distance`. Merge never joins reads that overlap in time.

## Measure, don't guess

```bash
carnarc run -c config.yaml --source my_clip.mp4 --dry-run   # watch reads, confidence, alternatives
carnarc bench ./photos ./photos/labels.csv                   # score single frames on your own labels
```

Keep a folder of clips from your real mount with the true plates written down; change one setting at a time and re-run. `alternatives` in the dashboard show where the vote disagreed, which tells you which characters the OCR confuses (possible systematic V/Y confusion was seen on the one UK clip).
