"""Compatibility re-export.

The implementation lives in ``acd.core.runtime.fileio``.
"""

from acd.core.runtime.fileio import (
    JSON_INDENT,
    dump_json,
    file_sha256,
    read_json,
    read_json_object,
    sha256_hex,
    write_json,
)

__all__ = [
    "JSON_INDENT",
    "dump_json",
    "file_sha256",
    "read_json",
    "read_json_object",
    "sha256_hex",
    "write_json",
]
