"""Shared fixtures and repository paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

type Json = dict[str, "Json"] | list["Json"] | str | int | float | bool | None

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "fixtures" / "contracts"


def _load_json_object(path: Path) -> dict[str, Json]:
    data = cast(Json, json.loads(path.read_text(encoding="utf-8")))
    assert isinstance(data, dict)
    return data


def load_fixture(kind: str, name: str) -> dict[str, Json]:
    return _load_json_object(FIXTURES_DIR / kind / name)


def fixture_obj(value: Json) -> dict[str, Json]:
    assert isinstance(value, dict)
    return value


def fixture_list(value: Json) -> list[Json]:
    assert isinstance(value, list)
    return value
