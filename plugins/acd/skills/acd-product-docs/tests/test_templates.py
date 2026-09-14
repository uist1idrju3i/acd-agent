from __future__ import annotations

import json
import re
import string
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
SCRIPTS = ROOT / "scripts"
KEY_PATTERN = re.compile(
    r"""["']((?:interface|manual|quality|readme|review)\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)["']"""
)
CJK_PATTERN = re.compile(r"[\u3400-\u9fff\u3040-\u30ff]")
LITERAL_KEY_PATTERN = re.compile(r"literal_[0-9]+")
SHORT_VALUE_KEYS = {
    "manual.yes",
    "manual.no",
    "manual.firmware_flash_target",
    "quality.finding_count_unit",
    "quality.orphan_record_unit",
    "readme.legacy_voltage_label",
    "manual.led_blink_prefix",
    "manual.usb_flash_transition",
}


def _catalog(language: str) -> dict[str, str]:
    payload = json.loads(
        (TEMPLATES / f"{language}.json").read_text(encoding="utf-8")
    )
    assert isinstance(payload, dict)
    entries = cast(dict[object, object], payload)
    assert all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in entries.items()
    )
    return {
        key: value
        for key, value in entries.items()
        if isinstance(key, str) and isinstance(value, str)
    }


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


def test_template_keys_are_semantic() -> None:
    assert not any(LITERAL_KEY_PATTERN.search(key) for key in _catalog("ja"))


def test_template_values_have_no_outer_whitespace() -> None:
    for catalog in (_catalog("ja"), _catalog("en")):
        assert all(value == value.strip() for value in catalog.values())


def test_template_values_have_meaningful_length() -> None:
    for key, value in _catalog("ja").items():
        assert len(value) >= 2 or key in SHORT_VALUE_KEYS
    for key, value in _catalog("en").items():
        assert len(value) >= 2 or key in SHORT_VALUE_KEYS


def _placeholders(value: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(value)
        if field_name is not None
    }


def test_template_placeholder_sets_match() -> None:
    ja = _catalog("ja")
    en = _catalog("en")
    assert {
        key: _placeholders(value) for key, value in ja.items()
    } == {key: _placeholders(value) for key, value in en.items()}
