from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
SCRIPTS = ROOT / "scripts"
KEY_PATTERN = re.compile(r"([a-z]+\.literal_[0-9]+)")
CJK_PATTERN = re.compile(r"[\u3400-\u9fff\u3040-\u30ff]")


def _catalog(language: str) -> dict[str, str]:
    payload = json.loads(
        (TEMPLATES / f"{language}.json").read_text(encoding="utf-8")
    )
    assert isinstance(payload, dict)
    assert all(isinstance(key, str) and isinstance(value, str) for key, value in payload.items())
    return payload


def _referenced_keys() -> set[str]:
    return {
        key
        for path in SCRIPTS.glob("*.py")
        for key in KEY_PATTERN.findall(path.read_text(encoding="utf-8"))
    }


def test_template_catalogs_have_identical_keys() -> None:
    assert set(_catalog("ja")) == set(_catalog("en"))


def test_english_templates_contain_no_cjk() -> None:
    assert not any(CJK_PATTERN.search(value) for value in _catalog("en").values())


def test_scripts_contain_no_cjk() -> None:
    assert not any(
        CJK_PATTERN.search(path.read_text(encoding="utf-8"))
        for path in SCRIPTS.glob("*.py")
    )


def test_template_keys_are_referenced_exactly() -> None:
    keys = set(_catalog("ja"))
    referenced = _referenced_keys()
    assert referenced == keys
