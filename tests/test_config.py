import dataclasses
from pathlib import Path

import pytest

from carnarc.config import Config, ConfigError, load_config

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.yaml"


def write(tmp_path, text: str) -> Path:
    p = tmp_path / "c.yaml"
    p.write_text(text)
    return p


def test_example_config_matches_built_in_defaults():
    """If someone edits one without the other, this fails, so docs can't drift."""
    assert dataclasses.asdict(load_config(EXAMPLE)) == dataclasses.asdict(Config())


def test_no_path_gives_defaults():
    assert load_config(None) == Config()


def test_partial_override_keeps_other_defaults(tmp_path):
    cfg = load_config(write(tmp_path, "camera:\n  source: rtsp://cam/stream\ndetection:\n  conf_thresh: 0.6\n"))
    assert cfg.camera.source == "rtsp://cam/stream"
    assert cfg.detection.conf_thresh == 0.6
    assert cfg.camera.fps == 30


def test_unknown_key_is_rejected_with_a_helpful_message(tmp_path):
    with pytest.raises(ConfigError, match="unknown key.*conf_tresh"):
        load_config(write(tmp_path, "detection:\n  conf_tresh: 0.5\n"))
    with pytest.raises(ConfigError, match="unknown key.*cammera"):
        load_config(write(tmp_path, "cammera:\n  source: 0\n"))


def test_numeric_camera_source_becomes_a_string(tmp_path):
    assert load_config(write(tmp_path, "camera:\n  source: 0\n")).camera.source == "0"


@pytest.mark.parametrize(
    "yaml_text",
    [
        "detection:\n  roi: [0, 0, 1]\n",
        "detection:\n  roi: [0.5, 0, 0.8, 1]\n",  # runs off the right edge
        "detection:\n  conf_thresh: 1.5\n",
        "plate_rules:\n  min_length: 9\n  max_length: 8\n",
        "tracking:\n  min_reads: 0\n",
        "storage:\n  jpeg_quality: 0\n",
    ],
)
def test_invalid_values_are_rejected(tmp_path, yaml_text):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, yaml_text))


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_section_must_be_a_mapping(tmp_path):
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(write(tmp_path, "camera: 5\n"))
