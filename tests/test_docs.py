"""Docs must not drift from the code: every config key has to appear in CONFIGURATION.md."""

import dataclasses
from pathlib import Path

from carnarc.config import Config

DOC = (Path(__file__).resolve().parent.parent / "docs" / "CONFIGURATION.md").read_text()


def test_every_config_key_is_documented():
    missing = []
    for section in dataclasses.fields(Config):
        for key in dataclasses.fields(type(getattr(Config(), section.name))):
            full = f"{section.name}.{key.name}"
            if f"`{full}`" not in DOC:
                missing.append(full)
    assert not missing, f"undocumented config keys: {missing}"


def test_documented_keys_exist():
    import re

    valid = {
        f"{s.name}.{k.name}"
        for s in dataclasses.fields(Config)
        for k in dataclasses.fields(type(getattr(Config(), s.name)))
    }
    documented = set(re.findall(r"^\| `([a-z_]+\.[a-z_]+)` \|", DOC, flags=re.M))
    assert documented <= valid, f"docs mention keys that don't exist: {documented - valid}"
