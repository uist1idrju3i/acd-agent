"""Installation doctor positive and fail-closed checks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[5]
PLUGIN_ROOT = ROOT / "plugins" / "acd"
SCRIPT = PLUGIN_ROOT / "skills" / "acd-install-doctor" / "scripts" / "install_doctor.py"


def _copy_plugin(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    installed = tmp_path / "installed" / "acd"
    shutil.copytree(PLUGIN_ROOT, installed)
    return installed, installed / "skills/acd-install-doctor/scripts/install_doctor.py"


def _run(
    script: Path,
    tmp_path: Path,
    tool_scripts: dict[str, str] | None = None,
    home: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    uv = shutil.which("uv")
    assert uv is not None
    (bin_dir / "uv").symlink_to(uv)
    for name, body in (tool_scripts or {}).items():
        tool = bin_dir / name
        tool.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        tool.chmod(0o755)
    environment = {**os.environ, "PATH": str(bin_dir)}
    if home is not None:
        environment["HOME"] = str(home)
    completed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    return completed, json.loads(completed.stdout)


def test_development_tree_is_diagnosable_without_host_tools(tmp_path: Path) -> None:
    copied, script = _copy_plugin(tmp_path)
    completed, report = _run(script, tmp_path)
    assert completed.returncode == 0
    assert report["status"] == "degraded"
    assert report["plugin_root"] == str(copied)
    assert any(
        check["name"] == "docker capability" and check["result"] == "fail"
        for check in report["checks"]
    )
    eda_check = next(
        check for check in report["checks"] if check["name"] == "host EDA capabilities"
    )
    assert eda_check["result"] == "pass"
    assert "missing: kicad-cli, freerouting" in eda_check["detail"]
    assert "build123d / cadquery-ocp are not probed" in eda_check["detail"]
    assert eda_check["observed_version"] == "kicad-cli=unavailable, freerouting=unavailable"
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
        {
            "kicad-cli": 'printf "10.0.5\\n"',
            "freerouting": 'printf "INFO Freerouting v2.3.0\\n"; exit 1',
        },
    )

    assert completed.returncode == 0
    assert report["status"] == "degraded"
    eda_check = next(
        check for check in report["checks"] if check["name"] == "host EDA capabilities"
    )
    assert eda_check["result"] == "pass"
    assert eda_check["observed_version"] == "kicad-cli=10.0.5, freerouting=2.3.0"


def _break_plugin_name(path: Path) -> None:
    path.write_text('{"name":"wrong"}', encoding="utf-8")


def _break_asset_hash(path: Path) -> None:
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"asset_hash": "sha256:a', '"asset_hash": "sha256:b', 1
        ),
        encoding="utf-8",
    )


def _break_canonical_hash(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document["canonical_hash"] = "sha256:" + "0" * 64
    path.write_text(json.dumps(document), encoding="utf-8")


def _break_package_ref(path: Path) -> None:
    path.write_text("0" * 40 + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("relative", "mutate"),
    [
        (".plugin/plugin.json", _break_plugin_name),
        ("agents/prompt-manifest.json", _break_asset_hash),
        ("agents/prompt-manifest.json", _break_canonical_hash),
        ("skills/acd-package-ref.txt", _break_package_ref),
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


def _docker_stub() -> str:
    return (
        'if [ "$1" = "--version" ]; then '
        'printf "Docker version 27.4.1, build test\\n"; '
        "else exit 0; fi"
    )


def _make_hooks_invocable(plugin_root: Path) -> None:
    for hook_script in (plugin_root / "hooks" / "scripts").glob("*.py"):
        source = hook_script.read_text(encoding="utf-8")
        if not source.startswith("#!"):
            hook_script.write_text("#!/usr/bin/env python3\n" + source, encoding="utf-8")
        hook_script.chmod(0o755)


def test_install_location_distinguishes_development_and_store_layouts(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    development_root, development_script = _copy_plugin(tmp_path / "development")
    _make_hooks_invocable(development_root)
    completed, development_report = _run(
        development_script,
        tmp_path / "development-run",
        {"docker": _docker_stub()},
        home,
    )
    assert completed.returncode == 0
    assert development_report["status"] == "ok"
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
    _make_hooks_invocable(correct_root)
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


def test_hook_invocability_is_optional_and_reports_executable_state(
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
    assert report["status"] == "degraded"
    hook_check = next(
        check for check in report["checks"] if check["name"] == "hook invocability"
    )
    assert hook_check["required"] is False
    assert hook_check["result"] == "fail"
    assert "protect_projections.py" in hook_check["detail"]
    assert "hook policy would not be enforced" in hook_check["detail"]

    _make_hooks_invocable(copied)
    completed, fixed_report = _run(
        script,
        tmp_path / "fixed-run",
        {"docker": _docker_stub()},
        home,
    )
    assert completed.returncode == 0
    assert fixed_report["status"] == "ok"
    fixed_hook_check = next(
        check for check in fixed_report["checks"] if check["name"] == "hook invocability"
    )
    assert fixed_hook_check["result"] == "pass"
