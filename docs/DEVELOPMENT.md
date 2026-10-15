# Development

```bash
pip install -e ".[dev]"
pytest              # fast tests, fake models, no downloads (~seconds)
pytest -m slow      # also runs the real ONNX models (downloads them once)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the module layout and the reasoning behind the tracker and merger. Both the tracker and the merger are accuracy-critical: change them with a test that fails without the change.

## Testing approach

- Unit tests use fake detectors and OCR readers (`tests/conftest.py`: `ocr()`, `make_obs()`), so logic is tested without models.
- `tests/test_models_integration.py` (marker `slow`) runs the real models on rendered plates.
- When fixing a bug, add a regression test and confirm it fails without the fix (the merge regressions were mutation-checked this way).
- `tests/test_config.py` asserts `config.example.yaml` equals the built-in defaults, and `tests/test_docs.py` asserts every config key is documented in `docs/CONFIGURATION.md`.

## Adding a config key

1. Add the field to the dataclass in `src/carnarc/config.py` (and validation if it has a range).
2. Add it, with the default and a comment, to `config.example.yaml`.
3. Add a row to `docs/CONFIGURATION.md`.

The tests above fail if any step is skipped.

## Adding an output (sink)

A sink is any object with `handle(self, read: PlateRead) -> None` (`outputs.Sink`). `Pipeline` calls every sink for each finished read. Write it in `src/carnarc/outputs.py`, add it in `build_pipeline` in `pipeline.py`, and gate it behind a config section. Alerts (ntfy, MQTT) are planned this way. A sink must not raise for routine failures such as a network error; log and carry on so capture continues.

## Conventions

- Python 3.10+, type hints, `from __future__ import annotations`.
- Heavy imports (cv2 models, onnx) are lazy so `--help` and tests stay fast.
- Nothing from `data/`, configs with credentials, or model files is ever committed (`.gitignore` blocks them). Don't commit captured plates or photos of real vehicles.
