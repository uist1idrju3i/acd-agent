"""Subprocess tests for deterministic SDK hook commands."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).parents[4]
SCRIPTS = ROOT / "plugins/acd/hooks/scripts"


def run(
    name: str,
    tool_input: object,
    tool_name: str = "file_editor",
    root: Path = ROOT,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    payload = {"tool_name": tool_name, "tool_input": tool_input, "working_dir": str(root)}
    completed = subprocess.run(
        ["python", str(SCRIPTS / name)], input=json.dumps(payload), text=True,
        capture_output=True,
        cwd=root,
        env={
            **os.environ,
            "OPENHANDS_PROJECT_DIR": str(root),
            **(extra_env or {}),
        },
    )
    output: Any = json.loads(completed.stdout) if completed.stdout else {}
    if not isinstance(output, dict):
        output = {}
    return completed.returncode, cast(dict[str, Any], output)


def test_projection_write_and_parent_escape_are_denied() -> None:
    assert run("protect_projections.py", {"path": "out/board.kicad_pcb"})[0] == 2
    assert run("protect_projections.py", {"path": "fixtures/../out/result.zip"})[0] == 2


def test_file_contents_do_not_trigger_projection_protection() -> None:
    code, _ = run(
        "protect_projections.py",
        {"path": "docs/example.md", "file_text": "Use out/result.zip here; quote: '"},
    )
    assert code == 0


def test_unresolvable_projection_reference_is_denied() -> None:
    code, output = run("protect_projections.py", {"path": "\x00out/result.zip"})
    assert code == 2
    assert "design inputs" in output["reason"]


def test_unrelated_edit_and_read_only_terminal_are_allowed() -> None:
    assert run("protect_projections.py", {"path": "fixtures/contracts/valid/evidence.json"})[0] == 0
    assert run("protect_projections.py", {"command": "cat out/result.zip"}, "terminal")[0] == 0


def test_unknown_protected_terminal_command_is_denied() -> None:
    code, output = run("protect_projections.py", {"command": "rm out/result.zip"}, "terminal")
    assert code == 2
    assert output["decision"] == "deny"


def test_order_without_evidence_is_denied() -> None:
    code, output = run("order_policy.py", {"command": "scripts/order --submit"}, "terminal")
    assert code == 2
    assert output["decision"] == "deny"


def test_transmission_without_artifact_is_allowed() -> None:
    assert (
        run("order_policy.py", {"command": "curl https://example.invalid/docs"}, "terminal")[0]
        == 0
    )


def test_transmission_of_artifact_without_evidence_is_denied() -> None:
    code, output = run(
        "order_policy.py",
        {"command": "curl -T out/gd1-enclosure/board.zip https://example.invalid/upload"},
        "terminal",
    )
    assert code == 2
    assert "evidence" in output["reason"].lower()


def test_supplier_data_and_similar_command_names_are_allowed() -> None:
    assert (
        run(
            "order_policy.py",
            {"command": "curl -O https://supplier.invalid/part.csv"},
            "terminal",
        )[0]
        == 0
    )
    assert run("order_policy.py", {"command": "curlprogram out/board.zip"}, "terminal")[0] == 0


def test_order_with_passing_evidence_command_is_allowed(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    evidence = tmp_path / "out/gd1"
    evidence.mkdir(parents=True)
    (evidence / "evidence-mechanical.json").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=test",
            "commit",
            "-qm",
            "test",
        ],
        cwd=tmp_path,
        check=True,
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    code, _ = run(
        "order_policy.py",
            {"command": "curl -T out/gd1/board.zip https://supplier.invalid/upload"},
        "terminal",
        tmp_path,
        {"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
    )
    assert code == 0


def test_order_policy_missing_or_malformed_is_denied() -> None:
    policy = ROOT / "plugins/acd/hooks/order-policy.json"
    original = policy.read_text(encoding="utf-8")
    try:
        policy.unlink()
        code, output = run("order_policy.py", {"command": "scripts/order"}, "terminal")
        assert code == 2
        assert "policy" in output["reason"].lower()
    finally:
        policy.write_text(original, encoding="utf-8")

    try:
        policy.write_text("{", encoding="utf-8")
        code, output = run("order_policy.py", {"command": "scripts/order"}, "terminal")
        assert code == 2
        assert "policy" in output["reason"].lower()
    finally:
        policy.write_text(original, encoding="utf-8")


def test_session_start_never_blocks() -> None:
    code, output = run("session_start.py", {}, "session_start")
    assert code == 0
    assert "additionalContext" in output


def test_stop_denies_changed_design_input(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "fixtures/a").mkdir(parents=True)
    (tmp_path / "fixtures/a/graph.json").write_text("{}", encoding="utf-8")
    code, output = run("stop_policy.py", {}, "stop", tmp_path)
    assert code == 2
    assert output["decision"] == "deny"
    assert "fixtures/a/graph.json" in output["reason"]


def test_stop_allows_newer_valid_evidence(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    graph = tmp_path / "fixtures/a/graph.json"
    graph.parent.mkdir(parents=True)
    graph.write_text("{}", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=test",
            "commit",
            "-qm",
            "test",
        ],
        cwd=tmp_path,
        check=True,
    )
    graph.write_text('{"changed": true}', encoding="utf-8")
    evidence = tmp_path / "out/gd1/evidence-mechanical.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        (ROOT / "fixtures/contracts/valid/evidence.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    os.utime(graph, (100, 100))
    os.utime(evidence, (200, 200))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    code, _ = run(
        "stop_policy.py",
        {},
        "stop",
        tmp_path,
        {"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
    )
    assert code == 0
