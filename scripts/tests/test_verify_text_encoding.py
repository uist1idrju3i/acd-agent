"""Tests for the production text-encoding guard."""

from __future__ import annotations

from pathlib import Path

from scripts.verify_text_encoding import check_file


def _violations(tmp_path: Path, source: str) -> list[str]:
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    return [item.rule for item in check_file(path)]


def test_rejects_text_io_without_explicit_utf8(tmp_path: Path) -> None:
    rules = _violations(
        tmp_path,
        """
import io
import subprocess
from pathlib import Path

open("a.txt", "w")
Path("a2.txt").open("w")
Path("b.txt").read_text()
Path("c.txt").write_text("x", encoding=codec)
subprocess.run(["tool"], text=True)
subprocess.Popen(["tool"], universal_newlines=True)
subprocess.check_output(["tool"], text=True, encoding=codec)
io.TextIOWrapper(stream)
""",
    )
    assert rules == [
        "open-encoding",
        "open-encoding",
        "text-method-encoding",
        "text-method-encoding",
        "subprocess-encoding",
        "subprocess-encoding",
        "subprocess-encoding",
        "textiowrapper-encoding",
    ]


def test_accepts_utf8_text_and_binary_io(tmp_path: Path) -> None:
    assert _violations(
        tmp_path,
        """
import io
import subprocess
from pathlib import Path

open("a.txt", "w", encoding="utf-8")
open("b.txt", "rb")
Path("binary.txt").open("rb")
Path("c.txt").read_text(encoding="utf-8-sig")
Path("d.txt").write_bytes(b"x")
Path("strict.txt").read_text(encoding="ascii")
subprocess.run(["tool"], text=True, encoding="utf-8")
subprocess.Popen(["tool"], universal_newlines=True, encoding="utf-8-sig")
io.TextIOWrapper(stream, encoding="utf-8")
""",
    ) == []


def test_unknown_mode_and_non_utf8_literal_fail_closed(tmp_path: Path) -> None:
    rules = _violations(
        tmp_path,
        """
from pathlib import Path

mode = "w"
open("a.txt", mode)
Path("b.txt").write_text("x", encoding="ascii")
Path("c.txt").write_text("x", encoding="latin-1")
""",
    )
    assert rules == [
        "open-encoding",
        "text-method-encoding",
    ]


def test_exemption_requires_reason_and_is_local_to_call(tmp_path: Path) -> None:
    rules = _violations(
        tmp_path,
        """
import subprocess

subprocess.run(["one"], text=True)  # encoding-exempt: external tool emits locale bytes
subprocess.run(["two"], text=True)  # encoding-exempt:
""",
    )
    assert rules == ["subprocess-encoding"]
