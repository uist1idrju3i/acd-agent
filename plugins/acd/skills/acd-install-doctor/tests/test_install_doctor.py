"""Installation doctor positive and fail-closed checks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[5]
PLUGIN_ROOT = ROOT / "plugins" / "acd"
SCRIPT = PLUGIN_ROOT / "skills" / "acd-install-doctor" / "scripts" / "install_doctor.py"


def _copy_plugin(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    installed = tmp_path / "installed" / "acd"
    shutil.copytree(PLUGIN_ROOT, installed)
    lock_path = tmp_path / "docker" / "image-digests.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "docker" / "image-digests.json", lock_path)
    return installed, installed / "skills/acd-install-doctor/scripts/install_doctor.py"


def _run(
    script: Path,
    tmp_path: Path,
    tool_scripts: dict[str, str] | None = None,
    home: Path | None = None,
    *,
    include_docker: bool = True,
    extra_env: dict[str, str] | None = None,
    doctor_args: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    uv = shutil.which("uv")
    assert uv is not None
    (bin_dir / "uv").symlink_to(uv)
    scripts = dict(tool_scripts or {})
    if include_docker and "docker" not in scripts:
        scripts["docker"] = _docker_stub()
    for name, body in scripts.items():
        tool = bin_dir / name
        tool.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        tool.chmod(0o755)
    environment = {**os.environ, "PATH": str(bin_dir)}
    if home is not None:
        environment["HOME"] = str(home)
    environment.update(extra_env or {})
    completed = subprocess.run(
        [sys.executable, str(script), *(doctor_args or [])],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    return completed, json.loads(completed.stdout)


def _assert_no_required_failures(report: dict[str, Any]) -> None:
    assert report["status"] != "failed"
    assert not [
        check
        for check in report["checks"]
        if check["required"] and check["result"] in {"fail", "unknown"}
    ]


def test_development_tree_is_diagnosable_without_host_tools(tmp_path: Path) -> None:
    copied, script = _copy_plugin(tmp_path)
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 0
    _assert_no_required_failures(report)
    assert report["plugin_root"] == str(copied)
    assert any(
        check["name"] == "docker capability" and check["result"] == "pass"
        for check in report["checks"]
    )
    eda_check = next(
        check for check in report["checks"] if check["name"] == "EDA capabilities"
    )
    assert eda_check["result"] == "pass"
    assert "observed inside" in eda_check["detail"]
    assert eda_check["observed_version"] == "kicad-cli=10.0.6, freerouting=2.3.0"
    install_check = next(
        check for check in report["checks"] if check["name"] == "plugin install location"
    )
    assert install_check["result"] == "pass"


def test_eda_probe_accepts_freerouting_banner_on_nonzero_exit(
    tmp_path: Path,
) -> None:
    _, script = _copy_plugin(tmp_path)
    completed, report = _run(
        script,
        tmp_path,
        {"docker": _docker_probe_stub()},
    )

    assert completed.returncode == 0
    _assert_no_required_failures(report)
    eda_check = next(
        check for check in report["checks"] if check["name"] == "EDA capabilities"
    )
    assert eda_check["result"] == "pass"
    assert eda_check["observed_version"] == "kicad-cli=10.0.6, freerouting=2.3.0"


def test_missing_image_eda_tool_is_degraded(tmp_path: Path) -> None:
    _, script = _copy_plugin(tmp_path)
    _, report = _run(script, tmp_path, {"docker": _docker_missing_kicad_stub()})
    eda_check = next(
        check for check in report["checks"] if check["name"] == "EDA capabilities"
    )
    assert report["status"] == "degraded"
    _assert_no_required_failures(report)
    assert eda_check["result"] == "fail"
    assert "missing: kicad-cli" in eda_check["detail"]


def test_host_without_docker_cli_fails_required_checks(tmp_path: Path) -> None:
    _, script = _copy_plugin(tmp_path)
    completed, report = _run(script, tmp_path, include_docker=False)
    assert completed.returncode == 1
    assert report["status"] == "failed"
    docker_check = next(
        check for check in report["checks"] if check["name"] == "docker capability"
    )
    assert docker_check["required"] is True
    assert docker_check["result"] == "fail"


def test_server_image_pull_failure_fails_closed(tmp_path: Path) -> None:
    _, script = _copy_plugin(tmp_path)
    completed, report = _run(
        script, tmp_path, {"docker": _docker_pull_failure_stub()}
    )
    assert completed.returncode == 1
    assert report["status"] == "failed"
    image_check = next(
        check for check in report["checks"] if check["name"] == "locked ACD server image"
    )
    assert image_check["result"] == "fail"
    assert "pull failed" in image_check["detail"]


def test_no_pull_with_missing_server_image_fails(tmp_path: Path) -> None:
    _, script = _copy_plugin(tmp_path)
    completed, report = _run(
        script,
        tmp_path,
        {"docker": _docker_pull_failure_stub()},
        doctor_args=["--no-pull"],
    )
    assert completed.returncode == 1
    image_check = next(
        check for check in report["checks"] if check["name"] == "locked ACD server image"
    )
    assert image_check["result"] == "fail"
    assert "--no-pull" in image_check["detail"]


def test_image_firmware_tool_absence_fails_required_checks(tmp_path: Path) -> None:
    _, script = _copy_plugin(tmp_path)
    completed, report = _run(
        script,
        tmp_path,
        {"docker": _docker_missing_firmware_stub()},
        doctor_args=["--workspace", str(ROOT)],
    )
    assert completed.returncode == 1
    assert report["status"] == "failed"
    firmware_check = next(
        check
        for check in report["checks"]
        if check["name"] == "workspace firmware prerequisites"
    )
    assert firmware_check["result"] == "fail"
    assert "qemu-system-riscv32" in firmware_check["detail"]


def test_container_mode_does_not_require_docker_cli(tmp_path: Path) -> None:
    _, script = _copy_plugin(tmp_path)
    idf = tmp_path / "esp-idf"
    idf.mkdir()
    (idf / "export.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (idf / "export.sh").chmod(0o755)
    completed, report = _run(
        script,
        tmp_path,
        {
            "kicad-cli": 'printf "10.0.6\\n"',
            "freerouting": 'printf "Freerouting v2.3.0\\n"',
            "qemu-system-riscv32": 'printf "QEMU emulator version 9.2.2\\n"',
            "cmake": 'printf "cmake version 4.2.3\\n"',
        },
        include_docker=False,
        extra_env={"ACD_HOME": "/opt/acd", "IDF_PATH": str(idf)},
    )
    assert completed.returncode == 0
    _assert_no_required_failures(report)
    assert all(
        check["result"] == "pass"
        for check in report["checks"]
        if check["required"]
        and check["name"]
        in {
            "docker capability",
            "locked ACD server image",
            "workspace firmware prerequisites",
        }
    )


def test_tool_registration_check_reports_declared_and_registered_names(
    tmp_path: Path,
) -> None:
    _, script = _copy_plugin(tmp_path)
    _, report = _run(script, tmp_path)
    check = next(
        item for item in report["checks"] if item["name"] == "ACD tool registration"
    )
    assert check["result"] == "pass"
    assert "acd_probe_tools" in check["observed_version"]
    assert "register_acd_tools" in check["detail"]


def test_tool_registration_check_fails_on_undeclared_agent_tool(
    tmp_path: Path,
) -> None:
    copied, script = _copy_plugin(tmp_path)
    agent = copied / "agents" / "acd-electrical.md"
    agent.write_text(
        agent.read_text(encoding="utf-8").replace(
            "  - acd_probe_tools",
            "  - acd_probe_tools\n  - acd_unknown_tool",
        ),
        encoding="utf-8",
    )
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 1
    check = next(
        item for item in report["checks"] if item["name"] == "ACD tool registration"
    )
    assert check["result"] == "fail"
    assert "acd_unknown_tool" in check["detail"]


def test_tool_registration_check_fails_closed_on_missing_manifest(
    tmp_path: Path,
) -> None:
    copied, script = _copy_plugin(tmp_path)
    (copied / ".plugin" / "acd-tool-definitions.json").unlink()
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 1
    check = next(
        item for item in report["checks"] if item["name"] == "ACD tool registration"
    )
    assert check["result"] == "unknown"


def _break_plugin_name(path: Path) -> None:
    path.write_text('{"name":"wrong"}', encoding="utf-8")


def _break_asset_hash(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document["entries"][0]["asset_hash"] = "sha256:" + "0" * 64
    path.write_text(json.dumps(document), encoding="utf-8")


def _break_canonical_hash(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document["canonical_hash"] = "sha256:" + "0" * 64
    path.write_text(json.dumps(document), encoding="utf-8")


def _break_package_ref(path: Path) -> None:
    path.write_text("0" * 40 + "\n", encoding="utf-8")


def _declare_agent_skill(path: Path) -> None:
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "model: inherit",
            "model: inherit\nskills:\n  - acd-placement-search",
            1,
        ),
        encoding="utf-8",
    )


def _drop_installed_store_candidate(path: Path) -> None:
    """Rewrite hook commands so they only resolve the workspace plugin tree."""
    document = json.loads(path.read_text(encoding="utf-8"))

    def visit(value: object) -> None:
        if isinstance(value, dict):
            mapping = cast(dict[str, Any], value)
            command = mapping.get("command")
            if isinstance(command, str) and "/hooks/scripts/" in command:
                script = command.rsplit("/hooks/scripts/", 1)[1].rstrip('"')
                mapping["command"] = (
                    "python3 ${ACD_PLUGIN_ROOT:-$OPENHANDS_PROJECT_DIR/plugins/acd}"
                    f"/hooks/scripts/{script}"
                )
            for child in mapping.values():
                visit(child)
        elif isinstance(value, list):
            for child in cast(list[Any], value):
                visit(child)

    visit(document)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_workspace_only_hook_path_fails_closed(tmp_path: Path) -> None:
    _, script = _copy_plugin(tmp_path)
    _drop_installed_store_candidate(script.parents[3] / "hooks" / "hooks.json")
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 1
    check = next(
        check
        for check in report["checks"]
        if check["name"] == "hook plugin root resolution"
    )
    assert check["result"] == "fail"
    assert ".openhands/plugins/installed/acd" in check["detail"]


@pytest.mark.parametrize(
    ("relative", "mutate"),
    [
        (".plugin/plugin.json", _break_plugin_name),
        ("agents/prompt-manifest.json", _break_asset_hash),
        ("agents/prompt-manifest.json", _break_canonical_hash),
        ("skills/acd-package-ref.txt", _break_package_ref),
        ("agents/acd-search.md", _declare_agent_skill),
    ],
)
def test_required_tree_drift_fails_closed(
    tmp_path: Path, relative: str, mutate: Callable[[Path], None]
) -> None:
    _, script = _copy_plugin(tmp_path)
    target = script.parents[3] / relative
    mutate(target)
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 1
    assert report["status"] == "failed"
    assert any(
        check["required"] and check["result"] in {"fail", "unknown"}
        for check in report["checks"]
    )


def test_declared_agent_skill_is_reported_by_name(tmp_path: Path) -> None:
    _, script = _copy_plugin(tmp_path)
    _declare_agent_skill(script.parents[3] / "agents" / "acd-search.md")
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 1
    check = next(
        check for check in report["checks"] if check["name"] == "agent skill declarations"
    )
    assert check["required"] and check["result"] == "fail"
    assert "acd-placement-search" in check["detail"]


def _package_check(report: dict[str, Any]) -> dict[str, Any]:
    return next(
        check for check in report["checks"] if check["name"] == "Skill package reference"
    )


def test_package_contract_missing_fails_closed(tmp_path: Path) -> None:
    copied, script = _copy_plugin(tmp_path)
    (copied / "skills/acd-package-contract.json").unlink()
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 1
    assert _package_check(report)["result"] == "fail"


def test_package_contract_unparseable_fails_closed(tmp_path: Path) -> None:
    copied, script = _copy_plugin(tmp_path)
    (copied / "skills/acd-package-contract.json").write_text("{", encoding="utf-8")
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 1
    assert _package_check(report)["result"] == "fail"


def test_package_contract_ref_mismatch_fails_closed(tmp_path: Path) -> None:
    copied, script = _copy_plugin(tmp_path)
    contract = copied / "skills/acd-package-contract.json"
    document = json.loads(contract.read_text(encoding="utf-8"))
    document["ref"] = "0" * 40
    contract.write_text(json.dumps(document), encoding="utf-8")
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 1
    assert "contract.ref" in _package_check(report)["detail"]


def test_package_contract_script_hash_fails_closed(tmp_path: Path) -> None:
    copied, script = _copy_plugin(tmp_path)
    contract = copied / "skills/acd-package-contract.json"
    document = json.loads(contract.read_text(encoding="utf-8"))
    entry = next(item for item in document["scripts"] if item["path"].startswith("plugins/acd/"))
    entry["sha256"] = "0" * 64
    contract.write_text(json.dumps(document), encoding="utf-8")
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 1
    assert "sha256" in _package_check(report)["detail"]


def test_package_contract_symbols_and_fixture_kinds_fail_closed(
    tmp_path: Path,
) -> None:
    copied, script = _copy_plugin(tmp_path)
    contract = copied / "skills/acd-package-contract.json"
    document = json.loads(contract.read_text(encoding="utf-8"))
    entry = next(item for item in document["scripts"] if item["path"].startswith("plugins/acd/"))
    entry["acd_symbols"] = []
    document["fixture_kinds"] = ["missing.kind"]
    contract.write_text(json.dumps(document), encoding="utf-8")
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 1
    detail = _package_check(report)["detail"]
    assert "imported acd symbols exceed contract symbols" in detail
    assert "absent from schema" in detail


def test_package_contract_without_edge_kinds_rejects_fixture_edge_kind(
    tmp_path: Path,
) -> None:
    copied, script = _copy_plugin(tmp_path)
    contract = copied / "skills/acd-package-contract.json"
    document = json.loads(contract.read_text(encoding="utf-8"))
    document.pop("edge_kinds", None)
    document["fixture_kinds"] = ["edge.kind"]
    contract.write_text(json.dumps(document), encoding="utf-8")
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 1
    detail = _package_check(report)["detail"]
    assert "absent from schema" in detail


def _docker_stub() -> str:
    return (
        'if [ "$1" = "--version" ]; then '
        'printf "Docker version 27.4.1, build test\\n"; '
        'elif [ "$1" = "run" ]; then '
        '[ "$4" = "" ] || exit 88; '
        'printf "=== kicad-cli ===\\n10.0.6\\n'
        '=== freerouting ===\\nFreerouting v2.3.0\\n"; '
        'printf "=== IDF_PATH/export.sh ===\\npresent\\n'
        '=== qemu-system-riscv32 ===\\nQEMU emulator version 9.2.2\\n'
        '=== cmake ===\\ncmake version 4.2.3\\n"; '
        "else exit 0; fi"
    )


def _docker_probe_stub() -> str:
    return (
        'if [ "$1" = "--version" ]; then '
        'printf "Docker version 27.4.1, build test\\n"; '
        'elif [ "$1" = "run" ]; then '
        '[ "$4" = "" ] || exit 88; '
        'printf "=== kicad-cli ===\\n10.0.6\\n'
        '=== freerouting ===\\nINFO Freerouting v2.3.0\\n"; '
        'printf "=== IDF_PATH/export.sh ===\\npresent\\n'
        '=== qemu-system-riscv32 ===\\nQEMU emulator version 9.2.2\\n'
        '=== cmake ===\\ncmake version 4.2.3\\n"; '
        "else exit 0; fi"
    )


def _docker_missing_kicad_stub() -> str:
    return (
        'if [ "$1" = "--version" ]; then '
        'printf "Docker version 27.4.1, build test\\n"; '
        'elif [ "$1" = "run" ]; then '
        '[ "$4" = "" ] || exit 88; '
        'printf "=== kicad-cli ===\\ncommand not found\\n'
        '=== freerouting ===\\nFreerouting v2.3.0\\n"; '
        'printf "=== IDF_PATH/export.sh ===\\npresent\\n'
        '=== qemu-system-riscv32 ===\\nQEMU emulator version 9.2.2\\n'
        '=== cmake ===\\ncmake version 4.2.3\\n"; '
        "else exit 0; fi"
    )


def _docker_pull_failure_stub() -> str:
    return (
        'if [ "$1" = "--version" ]; then '
        'printf "Docker version 27.4.1, build test\\n"; '
        'elif [ "$1" = "info" ]; then exit 0; '
        'elif [ "$1" = "image" ]; then exit 1; '
        'elif [ "$1" = "pull" ]; then printf "pull failed\\n" >&2; exit 1; '
        "else exit 0; fi"
    )


def _docker_missing_firmware_stub() -> str:
    return (
        'if [ "$1" = "--version" ]; then '
        'printf "Docker version 27.4.1, build test\\n"; '
        'elif [ "$1" = "run" ]; then '
        '[ "$4" = "" ] || exit 88; '
        'printf "=== kicad-cli ===\\n10.0.6\\n'
        '=== freerouting ===\\nFreerouting v2.3.0\\n"; '
        'printf "=== IDF_PATH/export.sh ===\\npresent\\n'
        '=== qemu-system-riscv32 ===\\nmissing\\n'
        '=== cmake ===\\ncmake version 4.2.3\\n"; '
        "else exit 0; fi"
    )


def test_install_location_distinguishes_development_and_store_layouts(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _, development_script = _copy_plugin(tmp_path / "development")
    completed, development_report = _run(
        development_script,
        tmp_path / "development-run",
        {"docker": _docker_stub()},
        home,
    )
    assert completed.returncode == 0
    _assert_no_required_failures(development_report)
    development_check = next(
        check
        for check in development_report["checks"]
        if check["name"] == "plugin install location"
    )
    assert development_check["result"] == "pass"
    assert "development checkout" in development_check["detail"]

    correct_root = home / ".openhands" / "plugins" / "installed" / "acd"
    correct_root.parent.mkdir(parents=True)
    shutil.copytree(PLUGIN_ROOT, correct_root)
    installed_lock = home / ".openhands" / "plugins" / "docker" / "image-digests.json"
    installed_lock.parent.mkdir(parents=True)
    shutil.copy(ROOT / "docker" / "image-digests.json", installed_lock)
    completed, correct_report = _run(
        correct_root / "skills/acd-install-doctor/scripts/install_doctor.py",
        tmp_path / "correct-run",
        {"docker": _docker_stub()},
        home,
    )
    assert completed.returncode == 0
    correct_check = next(
        check
        for check in correct_report["checks"]
        if check["name"] == "plugin install location"
    )
    assert correct_check["result"] == "pass"
    assert "direct installed plugin directory" in correct_check["detail"]

    wrong_root = home / ".openhands" / "plugins" / "installed" / "acd-agent-x" / "plugins" / "acd"
    shutil.copytree(PLUGIN_ROOT, wrong_root)
    completed, wrong_report = _run(
        wrong_root / "skills/acd-install-doctor/scripts/install_doctor.py",
        tmp_path / "wrong-run",
        {"docker": _docker_stub()},
        home,
    )
    assert completed.returncode == 1
    assert wrong_report["status"] == "failed"
    wrong_check = next(
        check
        for check in wrong_report["checks"]
        if check["name"] == "plugin install location"
    )
    assert wrong_check["required"] is True
    assert wrong_check["result"] == "fail"
    assert "repo_path: plugins/acd" in wrong_check["detail"]
    assert "github:uist1idrju3i/acd-agent" in wrong_check["detail"]


def _make_direct_hook_reference(plugin_root: Path) -> None:
    hooks_path = plugin_root / "hooks/hooks.json"
    source = hooks_path.read_text(encoding="utf-8")
    updated = source.replace(
        'exec python3 \\"${p}/hooks/scripts/protect_projections.py\\"',
        'exec \\"${p}/hooks/scripts/protect_projections.py\\"',
        1,
    )
    assert updated != source
    hooks_path.write_text(updated, encoding="utf-8")


def _make_hook_directly_invocable(plugin_root: Path) -> None:
    hook_script = plugin_root / "hooks/scripts/protect_projections.py"
    source = hook_script.read_text(encoding="utf-8")
    if not source.startswith("#!"):
        hook_script.write_text("#!/usr/bin/env python3\n" + source, encoding="utf-8")
    hook_script.chmod(0o755)


def test_hook_invocability_reports_interpreter_dispatch_and_direct_state(
    tmp_path: Path,
) -> None:
    copied, script = _copy_plugin(tmp_path / "initial")
    home = tmp_path / "home"
    home.mkdir()
    completed, report = _run(
        script,
        tmp_path / "initial-run",
        {"docker": _docker_stub()},
        home,
    )
    assert completed.returncode == 0
    _assert_no_required_failures(report)
    hook_check = next(
        check for check in report["checks"] if check["name"] == "hook invocability"
    )
    assert hook_check["required"] is False
    assert hook_check["result"] == "pass"
    assert hook_check["observed_version"] == "0"
    assert "interpreter" in hook_check["detail"]
    assert "do not depend on executable bits" in hook_check["detail"]

    _make_direct_hook_reference(copied)
    completed, fixed_report = _run(
        script,
        tmp_path / "fixed-run",
        {"docker": _docker_stub()},
        home,
    )
    assert completed.returncode == 0
    assert fixed_report["status"] == "degraded"
    _assert_no_required_failures(fixed_report)
    fixed_hook_check = next(
        check for check in fixed_report["checks"] if check["name"] == "hook invocability"
    )
    assert fixed_hook_check["result"] == "fail"
    assert "protect_projections.py" in fixed_hook_check["detail"]
    assert "hook policy would not be enforced" in fixed_hook_check["detail"]

    _make_hook_directly_invocable(copied)
    completed, invocable_report = _run(
        script,
        tmp_path / "invocable-run",
        {"docker": _docker_stub()},
        home,
    )
    assert completed.returncode == 0
    _assert_no_required_failures(invocable_report)
    invocable_hook_check = next(
        check
        for check in invocable_report["checks"]
        if check["name"] == "hook invocability"
    )
    assert invocable_hook_check["result"] == "pass"


def test_workspace_repository_missing_fails_closed(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("install_doctor", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module._workspace_repository_check(tmp_path / "missing")
    assert result["result"] in {"fail", "unknown"}
    assert result["required"] is True


def test_workspace_submodule_missing_fails_closed(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("install_doctor", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module._workspace_submodule_check(tmp_path)
    assert result["result"] == "fail"
    assert result["required"] is True


def test_workspace_lock_out_of_sync_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("install_doctor", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def find_uv(command: str) -> str:
        del command
        return "/bin/uv"

    monkeypatch.setattr(module.shutil, "which", find_uv)

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        assert command == ["/bin/uv", "lock", "--check"]
        return subprocess.CompletedProcess(command, 1, "", "lock needs update")

    monkeypatch.setattr(module.subprocess, "run", run)
    result = module._workspace_lock_check(tmp_path)
    assert result["result"] == "fail"


def test_workspace_missing_server_image_fails_without_pull(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    digest_path = tmp_path / "docker"
    digest_path.mkdir()
    (digest_path / "image-digests.json").write_text(
        json.dumps(
            {
                "acd_server": {
                    "image": "example/acd-server",
                    "digest": "sha256:" + "a" * 64,
                }
            }
        ),
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location("install_doctor", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def find_docker(command: str) -> str:
        del command
        return "/bin/docker"

    monkeypatch.setattr(module.shutil, "which", find_docker)
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(command, 1, "", "not found")

    monkeypatch.setattr(module.subprocess, "run", run)
    result = module._workspace_digest_check(tmp_path)
    assert result["result"] == "fail"
    assert "pull" in result["detail"]
