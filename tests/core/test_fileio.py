from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from acd.core.runtime.fileio import (
    dump_json,
    file_sha256,
    read_json,
    read_json_object,
    sha256_hex,
    write_json,
)


def test_file_sha256_matches_hashlib_with_prefix(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"\x00\x01acd")
    expected = hashlib.sha256(b"\x00\x01acd").hexdigest()
    assert file_sha256(path) == f"sha256:{expected}"
    assert sha256_hex(b"\x00\x01acd") == expected


def test_file_sha256_missing_file_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        file_sha256(tmp_path / "missing.bin")


def test_write_json_uses_sorted_indented_utf8_layout(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "report.json"
    write_json(path, {"b": 1, "a": "日本語"})
    raw = path.read_bytes()
    assert raw == b'{\n  "a": "\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e",\n  "b": 1\n}\n'
    assert dump_json({"b": 1, "a": "日本語"}) == raw.decode("utf-8")


def test_write_json_without_mkdir_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        write_json(tmp_path / "absent" / "report.json", {}, mkdir=False)


def test_read_json_roundtrip_and_errors(tmp_path: Path) -> None:
    path = tmp_path / "value.json"
    path.write_text(json.dumps([1, {"k": None}]), encoding="utf-8")
    assert read_json(path) == [1, {"k": None}]
    with pytest.raises(ValueError, match="JSON root is not an object"):
        read_json_object(path)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        read_json(path)
    with pytest.raises(FileNotFoundError):
        read_json(tmp_path / "missing.json")


def test_read_json_object_returns_mapping(tmp_path: Path) -> None:
    path = tmp_path / "object.json"
    write_json(path, {"status": "pass"})
    assert read_json_object(path) == {"status": "pass"}
