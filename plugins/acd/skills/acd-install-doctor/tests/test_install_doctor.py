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
    installed = tmp_path / "installed" / "acd"
    shutil.copytree(PLUGIN_ROOT, installed)
    return installed, installed / "skills/acd-install-doctor/scripts/install_doctor.py"


def _run(
    script: Path,
    tmp_path: Path,
    tool_scripts: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = shutil.which("uv")
    assert uv is not None
    (bin_dir / "uv").symlink_to(uv)
    for name, body in (tool_scripts or {}).items():
        tool = bin_dir / name
        tool.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        tool.chmod(0o755)
    environment = {**os.environ, "PATH": str(bin_dir)}
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


def _break_prompt_hash(path: Path) -> None:
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"asset_hash": "sha256:a', '"asset_hash": "sha256:b', 1
        ),
        encoding="utf-8",
    )


def _break_package_ref(path: Path) -> None:
    path.write_text("0" * 40 + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("relative", "mutate"),
    [
        (".plugin/plugin.json", _break_plugin_name),
        ("agents/prompt-manifest.json", _break_prompt_hash),
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
