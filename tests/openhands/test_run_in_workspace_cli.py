"""run_in_workspace.py CLI argument and default-download tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/run_in_workspace.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("run_in_workspace_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module() -> Any:  # pyright: ignore[reportUnusedFunction]
    return _load_module()


def _fake_result() -> SimpleNamespace:
    return SimpleNamespace(
        digest="sha256:" + "a" * 64,
        source="image ID",
        exit_code=0,
        stdout="ok\n",
        stderr="",
        downloaded_files=(),
        download_errors=(),
        failure_kind=None,
        host_resource_report=None,
        source_revision="b" * 40,
        source_tree_state="clean",
    )


def _capture_run(module: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(module, "run_command_in_workspace", fake_run)
    return captured


def test_command_without_graph_downloads_only_explicit_paths(
    module: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _capture_run(module, monkeypatch)
    code = module.main(
        ["--image", "acd-server:local", "--repo", str(tmp_path), "true"]
    )
    assert code == 0
    assert captured["command"] == "true"
    assert captured["download_files"] == ()
    assert captured["expected_source_revision"] is None


def test_default_command_uses_gd1_graph_defaults(
    module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_run(module, monkeypatch)
    code = module.main(["--image", "acd-server:local", "--repo", str(ROOT)])
    assert code == 0
    defaults = module.workspace_defaults(
        "golden-design-1", Path("fixtures/golden-design-1")
    )
    assert captured["command"] == defaults.command
    assert captured["download_files"] == defaults.download_files


def test_command_with_explicit_graph_uses_graph_downloads(
    module: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _capture_run(module, monkeypatch)
    code = module.main(
        [
            "--image",
            "acd-server:local",
            "--repo",
            str(ROOT),
            "--graph",
            "fixtures/golden-design-1/graph.json",
            "true",
        ]
    )
    assert code == 0
    defaults = module.workspace_defaults(
        "golden-design-1", Path("fixtures/golden-design-1")
    )
    assert captured["download_files"] == defaults.download_files


def test_bootstrap_record_sets_expected_source_revision(
    module: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = tmp_path / "bootstrap-record.json"
    record.write_text(
        json.dumps({"resolved_revision": "c" * 40}) + "\n", encoding="utf-8"
    )
    captured = _capture_run(module, monkeypatch)
    code = module.main(
        [
            "--image",
            "acd-server:local",
            "--repo",
            str(tmp_path),
            "--bootstrap-record",
            str(record),
            "true",
        ]
    )
    assert code == 0
    assert captured["expected_source_revision"] == "c" * 40


def test_source_revision_is_rejected_with_local_provisional(
    module: Any,
) -> None:
    with pytest.raises(SystemExit) as exc:
        module._parse_args(
            ["--local-provisional", "--source-revision", "b" * 40, "true"]
        )
    assert exc.value.code == 2
