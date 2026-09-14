"""Tests for the structured lane log contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.core.lane_log import (
    LaneLogError,
    append_lane_log_footer,
    parse_lane_log,
    write_lane_log_header,
)


def _write_sample(path: Path, *, exit_code: int = 0) -> Path:
    write_lane_log_header(
        path,
        image="acd-server@sha256:abc",
        revision="b" * 40,
        command="uv run pytest -n 0",
        started_at="2026-01-01T00:00:00Z",
    )
    path.write_text(
        path.read_text(encoding="utf-8") + "first line\nlast line\n",
        encoding="utf-8",
    )
    append_lane_log_footer(
        path,
        exit_code=exit_code,
        image_digest="sha256:" + "d" * 64,
        execution_context="container",
        failure_kind="none",
        finished_at="2026-01-01T00:10:00Z",
    )
    return path


def test_round_trip_records_fields(tmp_path: Path) -> None:
    record = parse_lane_log(
        _write_sample(tmp_path / "lane.log").read_text(encoding="utf-8")
    )
    assert record.image == "acd-server@sha256:abc"
    assert record.revision == "b" * 40
    assert record.command == "uv run pytest -n 0"
    assert record.exit_code == 0
    assert record.image_digest == "sha256:" + "d" * 64
    assert record.execution_context == "container"
    assert record.failure_kind == "none"
    assert record.output_tail == ("first line", "last line")


def test_output_tail_is_bounded_to_40_lines(tmp_path: Path) -> None:
    path = _write_sample(tmp_path / "lane.log")
    body = "".join(f"line {index}\n" for index in range(50))
    text = path.read_text(encoding="utf-8").replace(
        "first line\nlast line\n", body
    )
    record = parse_lane_log(text)
    assert record.output_tail[0].startswith("...")
    assert record.output_tail[-1] == "line 49"


def test_interrupted_log_is_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "lane.log"
    write_lane_log_header(
        path,
        image="acd-server@sha256:abc",
        revision="b" * 40,
        command="true",
        started_at="2026-01-01T00:00:00Z",
    )
    with pytest.raises(LaneLogError, match="result footer"):
        parse_lane_log(path.read_text(encoding="utf-8"))


def test_unknown_header_version_is_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(LaneLogError, match="header version"):
        parse_lane_log("=== acd-lane-log 9.9 ===\n")


@pytest.mark.parametrize(
    "footer",
    [
        "exit_code: done\nimage_digest: x\nexecution_context: c\nfailure_kind: n\nfinished_at: t\n",
        "exit_code: 0\nimage_digest: x\nexecution_context: c\nfailure_kind: n\n",
    ],
)
def test_bad_footer_is_fail_closed(tmp_path: Path, footer: str) -> None:
    path = tmp_path / "lane.log"
    write_lane_log_header(
        path,
        image="i",
        revision="r",
        command="c",
        started_at="s",
    )
    with path.open("a", encoding="utf-8") as stream:
        stream.write("=== result ===\n" + footer)
    with pytest.raises(LaneLogError):
        parse_lane_log(path.read_text(encoding="utf-8"))


def test_execution_record_omits_raw_image_and_marks_fail_closed(
    tmp_path: Path,
) -> None:
    record = parse_lane_log(
        _write_sample(tmp_path / "lane.log", exit_code=3).read_text(
            encoding="utf-8"
        )
    )
    exported = record.to_execution_record()
    assert exported["log_type"] == "lane_log"
    assert exported["fail_closed"] is True
    assert exported["exit_code"] == 3
    assert exported["target_revision"] == "b" * 40
    assert "image" not in exported
    assert exported["image_digest"] == "sha256:" + "d" * 64
    assert exported["logs"] == ["first line", "last line"]
