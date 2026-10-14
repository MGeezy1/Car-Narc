"""Command line entry point: carnarc {run,web,bench,check}."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from .config import ConfigError, load_config


def _add_config(p: argparse.ArgumentParser) -> None:
    p.add_argument("-c", "--config", default=None, help="path to config.yaml (default: built-in defaults)")


def cmd_run(args: argparse.Namespace) -> int:
    from .camera import open_source
    from .pipeline import Pipeline, build_pipeline

    cfg = load_config(args.config)
    if args.source is not None:
        cfg.camera.source = args.source

    if args.dry_run:
        # Real models, console output only: nothing is written to the database or disk.
        from .detect import PlateDetector
        from .ocr import PlateReader
        from .outputs import LogSink

        pipeline: Pipeline = Pipeline(cfg, PlateDetector(cfg.detection), PlateReader(cfg.ocr), sinks=[LogSink()])
    else:
        pipeline = build_pipeline(cfg)

    source = open_source(cfg.camera)
    logging.getLogger("carnarc").info("capturing from %s (Ctrl-C to stop)", cfg.camera.source)
    try:
        pipeline.run(source.frames())
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    import uvicorn

    from .web.app import create_app, is_loopback

    cfg = load_config(args.config)
    host = args.host or cfg.web.host
    port = args.port or cfg.web.port
    token = os.environ.get(cfg.web.token_env) or None
    if not is_loopback(host) and token is None:
        print(
            f"refusing to listen on {host}: this dashboard shows logged plates and has no\n"
            f"password. Set one first:  export {cfg.web.token_env}='something-long'\n"
            f"(or keep host 127.0.0.1 and expose it with `tailscale serve`).",
            file=sys.stderr,
        )
        return 2
    uvicorn.run(create_app(cfg, token), host=host, port=port)
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    from .bench import load_labels, run_bench
    from .ocr import PlateReader

    cfg = load_config(args.config)
    labels = load_labels(args.labels)
    if not labels:
        print(f"no labels found in {args.labels}", file=sys.stderr)
        return 2
    detector = None
    if not args.crops:
        from .detect import PlateDetector

        detector = PlateDetector(cfg.detection)
    score = run_bench(args.images, labels, PlateReader(cfg.ocr), detector, cfg.detection.crop_margin)
    print(score.report())
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Load both models and time them on a blank frame: a quick 'does this box work' test."""
    import numpy as np

    from .detect import PlateDetector
    from .ocr import PlateReader

    cfg = load_config(args.config)
    t0 = time.perf_counter()
    detector = PlateDetector(cfg.detection)
    reader = PlateReader(cfg.ocr)
    print(f"models loaded in {time.perf_counter() - t0:.1f}s")

    frame = np.zeros((cfg.camera.height, cfg.camera.width, 3), np.uint8)
    detector.detect(frame)  # warm-up
    t0 = time.perf_counter()
    n = 10
    for _ in range(n):
        detector.detect(frame)
    print(f"plate detection @ {cfg.camera.width}x{cfg.camera.height}: {1000 * (time.perf_counter() - t0) / n:.0f} ms/frame")

    crop = np.full((64, 128, 3), 255, np.uint8)
    reader.read([crop])
    t0 = time.perf_counter()
    for _ in range(n):
        reader.read([crop])
    print(f"plate OCR: {1000 * (time.perf_counter() - t0) / n:.0f} ms/plate")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="carnarc", description="Roadside license plate recognition.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="capture and recognize plates")
    _add_config(p)
    p.add_argument("--source", help="override camera.source (index, rtsp:// URL, video file, picamera2)")
    p.add_argument("--dry-run", action="store_true", help="print reads only; write nothing to disk")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("web", help="start the dashboard")
    _add_config(p)
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_web)

    p = sub.add_parser("bench", help="score plate accuracy against labeled images")
    _add_config(p)
    p.add_argument("images", help="folder of images")
    p.add_argument("labels", help="CSV of filename,PLATE")
    p.add_argument("--crops", action="store_true", help="images are already plate crops (skip detection)")
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("check", help="load models and time them on this machine")
    _add_config(p)
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
