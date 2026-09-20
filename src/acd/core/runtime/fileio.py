"""Shared UTF-8 file helpers for hashing and JSON artifacts.

These helpers centralise the on-disk conventions used across the pipeline:
`sha256:`-prefixed file digests, UTF-8 JSON reads, and sorted, indented,
newline-terminated JSON writes. Callers that need domain-specific error
types wrap the raised ``OSError``/``ValueError`` themselves.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from acd.schema.common import Sha256

JSON_INDENT = 2


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> Sha256:
    """Return the ``sha256:<hex>`` digest of a file's bytes."""
    return f"sha256:{sha256_hex(path.read_bytes())}"


def read_json(path: Path) -> Any:
    """Load a UTF-8 JSON document; raises OSError/UnicodeDecodeError/JSONDecodeError."""
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_object(path: Path) -> dict[str, Any]:
    """Load a JSON document whose root must be an object (fail-closed otherwise)."""
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON root is not an object")
    return cast(dict[str, Any], value)


def dump_json(body: object) -> str:
    """Serialise ``body`` with the canonical artifact layout (sorted, indented, LF)."""
    return json.dumps(body, ensure_ascii=False, indent=JSON_INDENT, sort_keys=True) + "\n"


def write_json(path: Path, body: object, *, mkdir: bool = True) -> None:
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_json(body), encoding="utf-8")
