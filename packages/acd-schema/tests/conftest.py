"""Shared fixtures: JSON Schema registry and repo paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import Schema

type Json = dict[str, "Json"] | list["Json"] | str | int | float | bool | None

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = REPO_ROOT / "schemas"
FIXTURES_DIR = REPO_ROOT / "fixtures" / "contracts"


def _load_json_object(path: Path) -> dict[str, Json]:
    data = cast(Json, json.loads(path.read_text(encoding="utf-8")))
    assert isinstance(data, dict)
    return data


def load_registry() -> Registry[Schema]:
    registry: Registry[Schema] = Registry()
    for path in SCHEMAS_DIR.glob("*.schema.json"):
        contents = _load_json_object(path)
        schema_id = contents["$id"]
        assert isinstance(schema_id, str)
        registry = registry.with_resource(schema_id, Resource.from_contents(contents))
    return registry


@pytest.fixture(scope="session")
def registry() -> Registry[Schema]:
    return load_registry()


def make_validator(schema_name: str, registry: Registry[Schema]) -> Draft202012Validator:
    contents = _load_json_object(SCHEMAS_DIR / schema_name)
    return Draft202012Validator(contents, registry=registry)


def load_fixture(kind: str, name: str) -> dict[str, Json]:
    return _load_json_object(FIXTURES_DIR / kind / name)


def fixture_obj(value: Json) -> dict[str, Json]:
    assert isinstance(value, dict)
    return value


def fixture_list(value: Json) -> list[Json]:
    assert isinstance(value, list)
    return value
