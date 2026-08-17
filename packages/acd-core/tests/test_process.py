"""External process envelope tests: hashing, rerun, fail-closed."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from acd_core.process import ExternalToolError, execution_env, run_in_process, run_tool
from acd_schema import Evidence, ToolEnvelope


def _copy_command(src: Path, dst: Path) -> list[str]:
    return [
        sys.executable,
        "-c",
        (
            "import pathlib,sys;"
            "pathlib.Path(sys.argv[2]).write_text(pathlib.Path(sys.argv[1]).read_text())"
        ),
        str(src),
        str(dst),
    ]


def test_run_tool_records_envelope_and_reruns_every_time(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text("payload")
    dst = tmp_path / "out.txt"
    envelope_path = tmp_path / "run.envelope.json"
    kwargs = dict(
        tool_name="copytool",
        tool_version="1.0",
        format_version="txt",
        command=_copy_command(src, dst),
        input_paths=[src],
        output_paths=[dst],
        envelope_path=envelope_path,
        target_revision="r1",
        measurement_conditions="test",
    )
    first = run_tool(**kwargs)  # type: ignore[arg-type]
    assert first.envelope.input_hash.startswith("sha256:")
    assert first.envelope.output_hash.startswith("sha256:")
    assert first.envelope.exit_code == 0

    second = run_tool(**kwargs)  # type: ignore[arg-type]
    assert second.envelope.input_hash == first.envelope.input_hash
    assert second.envelope.started_at >= first.envelope.started_at

    src.write_text("different payload")
    third = run_tool(**kwargs)  # type: ignore[arg-type]
    assert third.envelope.input_hash != first.envelope.input_hash


def test_run_tool_fails_closed_on_missing_input(tmp_path: Path) -> None:
    with pytest.raises(ExternalToolError, match="input file missing"):
        run_tool(
            tool_name="copytool",
            tool_version="1.0",
            format_version="txt",
            command=["true"],
            input_paths=[tmp_path / "absent.txt"],
            output_paths=[],
            envelope_path=tmp_path / "e.json",
            target_revision="r1",
            measurement_conditions="test",
        )


def test_run_tool_fails_closed_on_bad_exit_code(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text("x")
    with pytest.raises(ExternalToolError, match="exited with 3"):
        run_tool(
            tool_name="failtool",
            tool_version="1.0",
            format_version="txt",
            command=[sys.executable, "-c", "import sys; sys.exit(3)"],
            input_paths=[src],
            output_paths=[],
            envelope_path=tmp_path / "e.json",
            target_revision="r1",
            measurement_conditions="test",
        )


def test_run_tool_fails_closed_on_missing_output(tmp_path: Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text("x")
    with pytest.raises(ExternalToolError, match="expected output missing"):
        run_tool(
            tool_name="noout",
            tool_version="1.0",
            format_version="txt",
            command=[sys.executable, "-c", "pass"],
            input_paths=[src],
            output_paths=[tmp_path / "never.txt"],
            envelope_path=tmp_path / "e.json",
            target_revision="r1",
            measurement_conditions="test",
        )


def test_run_in_process_records_normalized_outputs_on_every_run(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("payload")
    output = tmp_path / "output.txt"
    envelope = tmp_path / "envelope.json"
    calls = 0

    def runner() -> None:
        nonlocal calls
        calls += 1
        output.write_bytes(b"timestamp: changing")

    def execute():
        return run_in_process(
            tool_name="in-process",
            tool_version="1.0",
            format_version="txt",
            input_paths=[source],
            output_paths=[output],
            envelope_path=envelope,
            target_revision="r1",
            measurement_conditions="test",
            runner=runner,
            config=b"config",
            output_normalizer=lambda path: path.read_bytes().replace(b"changing", b"fixed"),
        )

    first = execute()
    second = execute()
    assert calls == 2
    assert first.envelope.output_hash == second.envelope.output_hash


@pytest.mark.parametrize(
    ("digest", "in_container", "expected"),
    [
        ("sha256:" + "a" * 64, False, "container=sha256:" + "a" * 64),
        ("", True, "container=unknown"),
        ("", False, "container=none"),
    ],
)
def test_execution_env_records_container_state(
    monkeypatch: pytest.MonkeyPatch,
    digest: str,
    in_container: bool,
    expected: str,
) -> None:
    monkeypatch.setenv("ACD_CONTAINER_IMAGE_DIGEST", digest)
    monkeypatch.setattr("acd_core.process._in_container", lambda: in_container)
    assert expected in execution_env()


def test_unknown_container_envelope_is_not_pass_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACD_CONTAINER_IMAGE_DIGEST", "")
    monkeypatch.setattr("acd_core.process._in_container", lambda: True)
    assert "container=unknown" in execution_env()
    envelope = ToolEnvelope(
        tool_name="test",
        tool_version="1.0",
        format_version="unknown",
        config_hash="sha256:" + "a" * 64,
        input_hash="sha256:" + "b" * 64,
        output_hash="sha256:" + "c" * 64,
        execution_env=execution_env(),
        measurement_conditions="test",
        convergence_state="converged",
        target_revision="r1",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    evidence = Evidence(
        evidence_id="test.unknown-container",
        target_revision="r1",
        status="valid",
        envelope=envelope,
        created_at=datetime.now(UTC),
    )
    assert envelope.has_unknown()
    assert not evidence.supports_pass("r1")
