"""Tests for ambient ACD tool availability detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from acd.openhands.tools.ambient import (
    NO_CLI_FALLBACK,
    TOOL_CLI_FALLBACKS,
    AmbientToolError,
    check_ambient_registration_drift,
    check_ambient_tool_availability,
    declared_command_tools,
    ensure_ambient_acd_tools,
    registered_tool_names,
    render_tool_availability,
)
from acd.openhands.tools.definitions import ACD_TOOL_DEFINITIONS

REPO_ROOT = Path(__file__).resolve().parents[3]
VIBEBB_COMMAND = REPO_ROOT / "plugins" / "acd" / "commands" / "vibebb-loop.md"


def _command(tmp_path: Path, tools: list[str]) -> Path:
    body = ["---", "description: test", "allowed-tools:"]
    body.extend(f"  - {name}" for name in tools)
    body.extend(["---", "", "# test"])
    path = tmp_path / "command.md"
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def test_every_declared_tool_has_a_declared_fallback() -> None:
    diagnostics = check_ambient_registration_drift()
    assert diagnostics == ()
    for name, _definition in ACD_TOOL_DEFINITIONS:
        assert name in TOOL_CLI_FALLBACKS or name in NO_CLI_FALLBACK
    overlap = set(TOOL_CLI_FALLBACKS) & set(NO_CLI_FALLBACK)
    assert not overlap
    for command in TOOL_CLI_FALLBACKS.values():
        assert (REPO_ROOT / command[0]).is_file()


def test_declared_command_tools_reads_vibebb_command() -> None:
    tools = declared_command_tools(VIBEBB_COMMAND)
    assert "acd_run_design_loop" in tools
    assert tools == tuple(sorted(tools))


def test_registered_conversation_exposes_declared_tools() -> None:
    report = check_ambient_tool_availability(VIBEBB_COMMAND, registered_tool_names())
    assert report.status == "pass"
    assert report.missing_tools == []
    assert report.pass_evidence is False


def test_ambient_conversation_without_acd_tools_fails_closed(tmp_path: Path) -> None:
    command = _command(tmp_path, ["acd_run_design_loop", "acd_validate_design_graph"])
    report = check_ambient_tool_availability(command, ["terminal", "file_editor"])
    assert report.status == "fail"
    assert report.missing_tools == [
        "acd_run_design_loop",
        "acd_validate_design_graph",
    ]
    commands = {item.tool_name: item.command for item in report.fallbacks}
    assert commands["acd_run_design_loop"][-1] == "scripts/run_design_loop.py"
    text = render_tool_availability(report)
    assert "scripts/validate_graph.py" in text
    with pytest.raises(AmbientToolError):
        ensure_ambient_acd_tools(command, ["terminal"])


def test_tool_without_cli_reports_its_reason(tmp_path: Path) -> None:
    command = _command(tmp_path, ["acd_run_firmware_pipeline"])
    report = check_ambient_tool_availability(command, [])
    assert report.status == "fail"
    assert report.fallbacks[0].command == []
    assert report.fallbacks[0].reason is not None


def test_command_declaring_acd_tools_must_check_ambient_availability(
    tmp_path: Path,
) -> None:
    script = tmp_path / "scripts" / "run_design_loop.py"
    script.parent.mkdir()
    script.write_text("", encoding="utf-8")
    command = _command(tmp_path, ["acd_run_design_loop"])
    diagnostics = check_ambient_registration_drift(
        commands_dir=tmp_path,
        repo_root=tmp_path,
        tool_definitions=["acd_run_design_loop"],
        cli_fallbacks={"acd_run_design_loop": ("scripts/run_design_loop.py",)},
        no_cli_fallback={},
    )
    assert "must verify itself" in diagnostics[0]
    command.write_text(
        command.read_text(encoding="utf-8")
        + (
            "\nuv run python scripts/verify_acd_tool_registration.py "
            "--command command.md\n"
        ),
        encoding="utf-8",
    )
    assert check_ambient_registration_drift(
        commands_dir=tmp_path,
        repo_root=tmp_path,
        tool_definitions=["acd_run_design_loop"],
        cli_fallbacks={"acd_run_design_loop": ("scripts/run_design_loop.py",)},
        no_cli_fallback={},
    ) == ()


def test_command_ambient_check_must_point_to_itself(tmp_path: Path) -> None:
    command = _command(tmp_path, ["acd_run_design_loop"])
    command.write_text(
        command.read_text(encoding="utf-8")
        + (
            "\nuv run python scripts/verify_acd_tool_registration.py "
            "--command other.md\n"
        ),
        encoding="utf-8",
    )
    diagnostics = check_ambient_registration_drift(
        commands_dir=tmp_path,
        repo_root=tmp_path,
        tool_definitions=["acd_run_design_loop"],
        cli_fallbacks={"acd_run_design_loop": ("scripts/run_design_loop.py",)},
        no_cli_fallback={},
    )
    assert "must verify itself" in diagnostics[0]


def test_fallback_tables_must_cover_each_tool_once(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "one.py").write_text("", encoding="utf-8")
    (scripts / "two.py").write_text("", encoding="utf-8")
    diagnostics = check_ambient_registration_drift(
        commands_dir=tmp_path,
        repo_root=tmp_path,
        tool_definitions=["acd_one", "acd_two"],
        cli_fallbacks={"acd_one": ("scripts/one.py",), "acd_two": ("scripts/two.py",)},
        no_cli_fallback={"acd_two": "no CLI"},
    )
    assert diagnostics == ("acd_two: must appear in exactly one ambient fallback table",)
    missing = check_ambient_registration_drift(
        commands_dir=tmp_path,
        repo_root=tmp_path,
        tool_definitions=["acd_one", "acd_two"],
        cli_fallbacks={"acd_one": ("scripts/one.py",)},
        no_cli_fallback={},
    )
    assert missing == ("acd_two: must appear in exactly one ambient fallback table",)


def test_fallback_scripts_must_exist(tmp_path: Path) -> None:
    diagnostics = check_ambient_registration_drift(
        commands_dir=tmp_path,
        repo_root=tmp_path,
        tool_definitions=["acd_one"],
        cli_fallbacks={"acd_one": ("scripts/missing.py",)},
        no_cli_fallback={},
    )
    assert diagnostics == (
        "acd_one: CLI fallback script does not exist: scripts/missing.py",
    )


def test_undeclared_tool_is_unknown(tmp_path: Path) -> None:
    command = _command(tmp_path, ["acd_not_a_tool"])
    report = check_ambient_tool_availability(command, [])
    assert report.status == "unknown"


def test_malformed_command_front_matter_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "broken.md"
    path.write_text("# no front matter\n", encoding="utf-8")
    with pytest.raises(AmbientToolError):
        declared_command_tools(path)
    unterminated = tmp_path / "unterminated.md"
    unterminated.write_text("---\nallowed-tools:\n  - acd_probe_tools\n", encoding="utf-8")
    with pytest.raises(AmbientToolError):
        declared_command_tools(unterminated)
    empty = tmp_path / "empty.md"
    empty.write_text("---\ndescription: x\n---\n", encoding="utf-8")
    with pytest.raises(AmbientToolError):
        declared_command_tools(empty)
