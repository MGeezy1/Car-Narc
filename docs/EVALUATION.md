# Evaluation log

What has actually been measured, and how much to trust it. Update this as better data arrives.

## Clip 1: slow UK dual-carriageway traffic (60 s, 1080p, 30 fps)

Elevated camera looking at approaching cars (mostly front plates), congested slow traffic, UK plates, hazy light. A hard clip for plate size and compression, an **easy** one for frames per car (about 76 per car, where a car at 70 mph gives far fewer). It is not the intended rear-plate roadside setup.

**Real models, no tuning, default config:** 3,422 plate detections formed 79 tracks, of which 34 became voted reads (the rest had too few reads or low confidence). The median voted read came from 76 frames and had confidence 0.93.

**Accuracy by eye.** There is no ground truth for this clip. Each voted read's best crop was compared with its text by hand: 27 matched, 5 were wrong, 2 were unclear because of blur. All 5 wrong reads were short fragments of a car that also had a longer, better-supported track. That judgement is mine and blurry crops can fool a human too, so treat these as approximate.

**Frame-rate replay.** The detector and OCR were run once over every frame and cached, then replayed through the real tracker and merger at lower frame rates by processing every Nth frame. Scored against the 28 reads judged correct by eye (the "reference"; this measures agreement with the full-rate result, not absolute truth):

| Effective fps | Frames per car (approx.) | Reference cars read exactly (of 28) | Missed entirely |
|---|---|---|---|
| 30 | 76 | 28 | 0 |
| 15 | 38 | 26 | 0 |
| 10 | 25 | 27 | 0 |
| 5 | 13 | 24 | 4 |
| 3 | 7 | 26 | 2 |

(`min_reads: 2`, merge on. The non-monotonic numbers are sampling noise: with only 28 cars, one or two cars change a row.)

**Duplicate merge.** At 30 fps it removed all 4 wrong duplicate reads (34 to 30 emitted) with no recall loss. At lower frame rates it changed nothing: the wrong reads that remained there were each a car's only read (as many wrong reads as cars with no exact read), not duplicates. It was never worse than merge-off in any row.

**`min_reads`.** At 30 fps, raising it from 2 to 5 removed some wrong reads at no recall cost. At 3 fps it cost 2 more missed cars. So the right value depends on frame rate; it is not set from this one clip.

## Caveats

- One clip, one camera angle, UK plates, no ground truth.
- Slow traffic gives many more frames per car than a 70 mph pass will.
- Timings from the development sandbox CPU are not Pi 5 numbers (still unmeasured on the Pi).
- Plate-size and blur at highway speed, and rear plates at night, are untested.

## Bugs this found

- One vehicle was emitted as several reads (fixed: `merge.py`).
- The merge first missed the real case, where the car's long track is still live when the fragment's window runs out (fixed: live-successor hold).
- The merge first matched on the tracker's own alternatives and merged two different cars at 3 fps (fixed, regression test added).
