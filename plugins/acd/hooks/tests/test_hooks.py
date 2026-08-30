"""Subprocess tests for deterministic SDK hook commands."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

from openhands.sdk.hooks.config import HookConfig
from openhands.sdk.hooks.types import HookEventType

ROOT = Path(__file__).parents[4]
SCRIPTS = ROOT / "plugins/acd/hooks/scripts"
HOOKS_PATH = Path(__file__).parents[1] / "hooks.json"


def run(
    name: str,
    tool_input: object,
    tool_name: str = "file_editor",
    root: Path = ROOT,
    extra_env: dict[str, str] | None = None,
    script_root: Path = SCRIPTS,
) -> tuple[int, dict[str, Any]]:
    payload = {"tool_name": tool_name, "tool_input": tool_input, "working_dir": str(root)}
    completed = subprocess.run(
        ["python", str(script_root / name)], input=json.dumps(payload), text=True,
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


def test_projection_guard_allows_pipeline_output_and_stop_report_writes() -> None:
    lane = (
        "uv run --script "
        "plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py "
        "--fixture fixtures/golden-design-1 --out out/gd1-fw"
    )
    assert run("protect_projections.py", {"command": lane}, "terminal")[0] == 0
    assert (
        run(
            "protect_projections.py",
            {"command": lane.replace("--out out/gd1-fw", "--out=out/gd1-fw")},
            "terminal",
        )[0]
        == 0
    )
    assert (
        run(
            "protect_projections.py",
            {"command": f'bash -c "{lane}"'},
            "terminal",
        )[0]
        == 0
    )
    assert (
        run(
            "protect_projections.py",
            {"command": "printf '{}' > out/stop-report.json"},
            "terminal",
        )[0]
        == 0
    )
    assert (
        run(
            "protect_projections.py",
            {
                "command": (
                    "python3 -c "
                    '"open(\'out/stop-report.json\',\'w\').write(\'{}\')"'
                )
            },
            "terminal",
        )[0]
        == 0
    )
    assert (
        run(
            "protect_projections.py",
            {"command": f'bash -c "{lane} && echo done"'},
            "terminal",
        )[0]
        == 0
    )
    assert (
        run(
            "protect_projections.py",
            {"command": "find out -name '*.kicad_pcb'"},
            "terminal",
        )[0]
        == 0
    )


def test_projection_guard_denies_write_targets_and_nested_bypasses() -> None:
    commands = (
        "bash -c \"rm -rf out/gd1-board\"",
        "echo x > out/board.kicad_pcb",
        "sed -i s/a/b/ out/board.kicad_pcb",
        "cp fixtures/x out/board.kicad_pcb",
        "tee out/board.kicad_pcb",
        "python3 -c \"open('out/board.kicad_pcb','w')\"",
        "echo x & rm out/board.kicad_pcb",
        "echo x\nrm out/board.kicad_pcb",
        "echo $(rm out/board.kicad_pcb)",
        "echo `rm out/board.kicad_pcb`",
        "echo out/board.kicad_pcb | xargs rm",
        "find out -delete",
        "find out -exec rm {} +",
        "sed -ni s/a/b/ out/board.kicad_pcb",
    )
    for command in commands:
        assert run("protect_projections.py", {"command": command}, "terminal")[0] == 2


def test_projection_guard_editor_and_patch_contracts() -> None:
    assert (
        run(
            "protect_projections.py",
            {"command": "view", "path": "out/result.zip"},
        )[0]
        == 0
    )
    assert (
        run(
            "protect_projections.py",
            {"command": "str_replace", "path": "out/board.kicad_pcb"},
        )[0]
        == 2
    )
    assert (
        run(
            "protect_projections.py",
            {
                "patch": (
                    "*** Begin Patch\n"
                    "*** Update File: out/board.kicad_pcb\n"
                    "@@\n"
                    "-old\n"
                    "+new\n"
                    "*** End Patch\n"
                ),
            },
            "apply_patch",
        )[0]
        == 2
    )
    assert (
        run(
            "protect_projections.py",
            {
                "patch": (
                    "*** Begin Patch\n"
                    "*** Update File: out/stop-report.json\n"
                    "@@\n"
                    "-old\n"
                    "+new\n"
                    "*** End Patch\n"
                ),
            },
            "apply_patch",
        )[0]
        == 0
    )
    assert (
        run(
            "protect_projections.py",
            {"patch": "*** Begin Patch\n@@\n+no header\n*** End Patch\n"},
            "apply_patch",
        )[0]
        == 2
    )


def test_projection_guard_parse_failures_are_denied() -> None:
    assert (
        run(
            "protect_projections.py",
            {"command": "bash -c \"rm out/result.zip"},
            "terminal",
        )[0]
        == 2
    )
    assert (
        run(
            "protect_projections.py",
            {"command": "cat \x00out/result.zip"},
            "terminal",
        )[0]
        == 2
    )


def _clean_hook_repo(tmp_path: Path) -> Path:
    graph = tmp_path / "fixtures/golden-design-1/graph.json"
    graph.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "fixtures/golden-design-1/graph.json", graph)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
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
    return tmp_path


def test_order_without_evidence_is_denied(tmp_path: Path) -> None:
    root = _clean_hook_repo(tmp_path)
    code, output = run(
        "order_policy.py", {"command": "scripts/order --submit"}, "terminal", root
    )
    assert code == 2
    assert output["decision"] == "deny"


def test_transmission_without_artifact_is_allowed() -> None:
    assert (
        run("order_policy.py", {"command": "curl https://example.invalid/docs"}, "terminal")[0]
        == 0
    )


def test_transmission_of_artifact_without_evidence_is_denied(tmp_path: Path) -> None:
    root = _clean_hook_repo(tmp_path)
    code, output = run(
        "order_policy.py",
        {"command": "curl -T out/gd1-enclosure/board.zip https://example.invalid/upload"},
        "terminal",
        root,
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


def test_unparseable_order_commands_fail_closed_only_when_relevant() -> None:
    code, output = run(
        "order_policy.py",
        {"command": "curl -T out/gd1/board.zip 'https://supplier.invalid/upload"},
        "terminal",
    )
    assert code == 2
    assert output["decision"] == "deny"
    assert run("order_policy.py", {"command": "echo 'unrelated"}, "terminal")[0] == 0


def test_order_with_passing_evidence_command_is_allowed(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    graph = tmp_path / "fixtures/golden-design-1/graph.json"
    graph.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "fixtures/golden-design-1/graph.json", graph)
    evidence = tmp_path / "out/gd1"
    evidence.mkdir(parents=True)
    (evidence / "evidence-mechanical.json").write_text("{}", encoding="utf-8")
    (evidence / "evidence-electrical.json").write_text("{}", encoding="utf-8")
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
    uv.write_text("#!/bin/sh\nprintf 'r1\\n'\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    code, _ = run(
        "order_policy.py",
        {"command": "curl -T out/gd1/board.zip https://supplier.invalid/upload"},
        "terminal",
        tmp_path,
        {"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
    )
    assert code == 0


def test_order_with_dirty_design_input_remains_denied(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    graph = tmp_path / "fixtures/golden-design-1/graph.json"
    graph.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "fixtures/golden-design-1/graph.json", graph)
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
    graph.write_text(graph.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    code, output = run(
        "order_policy.py",
        {"command": "curl -T out/gd1/board.zip https://supplier.invalid/upload"},
        "terminal",
        tmp_path,
    )
    assert code == 2
    assert output["decision"] == "deny"


def test_order_policy_missing_or_malformed_is_denied(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugin"
    shutil.copytree(ROOT / "plugins/acd/hooks", plugin_root / "hooks")
    policy = plugin_root / "hooks/order-policy.json"
    script_root = plugin_root / "hooks/scripts"
    policy.unlink()

    code, output = run(
        "order_policy.py",
        {"command": "scripts/order"},
        "terminal",
        tmp_path,
        script_root=script_root,
    )
    assert code == 2
    assert "policy" in output["reason"].lower()

    policy.write_text("{", encoding="utf-8")
    code, output = run(
        "order_policy.py",
        {"command": "scripts/order"},
        "terminal",
        tmp_path,
        script_root=script_root,
    )
    assert code == 2
    assert "policy" in output["reason"].lower()


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


def test_rationale_hooks_match_sdk_tool_name_and_commands() -> None:
    config = HookConfig.load(HOOKS_PATH)

    post_commands = [
        hook.command
        for hook in config.get_hooks_for_event(HookEventType.POST_TOOL_USE, "file_editor")
        if "hooks/scripts/check_rationale.py" in hook.command
    ]
    assert post_commands
    assert all(command.endswith("--warn-only") for command in post_commands)
    assert not config.get_hooks_for_event(HookEventType.POST_TOOL_USE, "FileEditorTool")

    stop_commands = [
        hook.command
        for hook in config.get_hooks_for_event(HookEventType.STOP, "file_editor")
        if "hooks/scripts/check_rationale.py" in hook.command
    ]
    assert stop_commands
    assert not any(command.endswith("--warn-only") for command in stop_commands)


def _rationale_inputs(root: Path) -> None:
    fixtures = root / "fixtures/golden-design-1"
    fixtures.mkdir(parents=True)
    (fixtures / "graph.json").write_text("{}", encoding="utf-8")
    (fixtures / "rationale.json").write_text("{}", encoding="utf-8")


def _run_rationale_hook(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", str(SCRIPTS / "check_rationale.py"), *arguments],
        input=json.dumps({"working_dir": str(root)}),
        text=True,
        capture_output=True,
        cwd=root,
        env={**os.environ, "OPENHANDS_PROJECT_DIR": str(root)},
        check=False,
    )


def test_rationale_hook_is_not_applicable_without_workspace_inputs(tmp_path: Path) -> None:
    completed = _run_rationale_hook(tmp_path)
    assert completed.returncode == 0
    assert "not applicable" in completed.stdout


def test_rationale_hook_denies_present_inputs_without_the_validator(tmp_path: Path) -> None:
    _rationale_inputs(tmp_path)
    code, output = run("check_rationale.py", {}, "stop", tmp_path)
    assert code == 2
    assert output["decision"] == "deny"
    assert "scripts/check_rationale.py" in output["reason"]


def test_rationale_hook_warn_only_never_blocks(tmp_path: Path) -> None:
    _rationale_inputs(tmp_path)
    assert _run_rationale_hook(tmp_path, "--warn-only").returncode == 0


def test_fail_closed_hooks_are_registered_for_sdk_events() -> None:
    config = HookConfig.load(HOOKS_PATH)

    names = {
        event: {
            hook.name
            for tool in ("file_editor", "terminal")
            for hook in config.get_hooks_for_event(event, tool)
        }
        for event in (
            HookEventType.PRE_TOOL_USE,
            HookEventType.POST_TOOL_USE,
            HookEventType.SESSION_START,
            HookEventType.STOP,
        )
    }
    assert {"protect-derived-projections", "require-order-evidence"} <= names[
        HookEventType.PRE_TOOL_USE
    ]
    assert "verify-markdown" in names[HookEventType.POST_TOOL_USE]
    assert "probe-tools" in names[HookEventType.SESSION_START]
    assert "require-gate-after-input-change" in names[HookEventType.STOP]


def _configured_plugin_hook_commands() -> dict[str, str]:
    document: Any = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))
    commands: dict[str, str] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            mapping = cast(dict[str, Any], value)
            name = mapping.get("name")
            command = mapping.get("command")
            if (
                isinstance(name, str)
                and isinstance(command, str)
                and "/hooks/scripts/" in command
            ):
                commands[name] = command
            for child in mapping.values():
                visit(child)
        elif isinstance(value, list):
            children = cast(list[Any], value)
            for child in children:
                visit(child)

    visit(document)
    return commands


def test_plugin_hook_commands_are_shell_invocable(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugin"
    shutil.copytree(ROOT / "plugins/acd/hooks", plugin_root / "hooks")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    payloads = {
        "protect-derived-projections": {
            "tool_name": "file_editor",
            "tool_input": {"path": "docs/example.md"},
            "working_dir": str(tmp_path),
        },
        "require-order-evidence": {
            "tool_name": "terminal",
            "tool_input": {"command": "printf ok"},
            "working_dir": str(tmp_path),
        },
        "probe-tools": {"working_dir": str(tmp_path)},
        "require-gate-after-input-change": {"working_dir": str(tmp_path)},
        "verify-markdown": {
            "tool_input": {"path": "docs/example.md"},
            "working_dir": str(tmp_path),
        },
        "check-design-rationale": {"working_dir": str(tmp_path)},
        "check-design-rationale-warn": {"working_dir": str(tmp_path)},
    }
    commands = _configured_plugin_hook_commands()
    assert set(commands) == set(payloads)

    environment = {
        **os.environ,
        "ACD_PLUGIN_ROOT": str(plugin_root),
        "OPENHANDS_PROJECT_DIR": str(tmp_path),
    }
    for name, command in commands.items():
        completed = subprocess.run(
            ["sh", "-c", command],
            input=json.dumps(payloads[name]),
            text=True,
            capture_output=True,
            cwd=tmp_path,
            env=environment,
            check=False,
        )
        assert completed.returncode == 0, (
            f"{name} failed to start through its configured shell command: "
            f"{completed.stderr}"
        )


def _hook_environment(tmp_path: Path, **overrides: str) -> dict[str, str]:
    """Build a hook environment without the ACD plugin root variables."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"ACD_PLUGIN_ROOT", "OPENHANDS_PROJECT_DIR", "HOME"}
    }
    environment["OPENHANDS_PROJECT_DIR"] = str(tmp_path)
    environment.update(overrides)
    return environment


def test_plugin_hook_commands_resolve_the_installed_plugin_root(tmp_path: Path) -> None:
    """Hooks run from the installed plugin store when the workspace has no plugin."""
    home = tmp_path / "home"
    installed_root = home / ".openhands" / "plugins" / "installed" / "acd"
    installed_root.parent.mkdir(parents=True)
    shutil.copytree(ROOT / "plugins/acd/hooks", installed_root / "hooks")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)

    for name, command in _configured_plugin_hook_commands().items():
        completed = subprocess.run(
            ["sh", "-c", command],
            input=json.dumps({"working_dir": str(workspace)}),
            text=True,
            capture_output=True,
            cwd=workspace,
            env=_hook_environment(workspace, HOME=str(home)),
            check=False,
        )
        assert completed.returncode == 0, (
            f"{name} did not resolve the installed plugin root: {completed.stderr}"
        )


def test_plugin_hook_commands_fail_closed_without_a_plugin_root(tmp_path: Path) -> None:
    """An unresolvable plugin root blocks the tool call instead of passing silently."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    for name, command in _configured_plugin_hook_commands().items():
        completed = subprocess.run(
            ["sh", "-c", command],
            input=json.dumps({"working_dir": str(workspace)}),
            text=True,
            capture_output=True,
            cwd=workspace,
            env=_hook_environment(workspace, HOME=str(home)),
            check=False,
        )
        assert completed.returncode == 2, (
            f"{name} did not fail closed without a plugin root: {completed.stdout}"
        )
        assert "acd plugin root unresolved" in completed.stderr
