"""Probe tests using stub executables (deterministic, no real tools required)."""

from __future__ import annotations

import io
import os
import stat
import zipfile
from pathlib import Path

import pytest

from acd_core.cad_normalize import CadNormalizationError, normalize_3mf, normalize_step
from acd_tools import probe_all, probe_executable


def make_stub(directory: Path, name: str, script: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def stub_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return tmp_path


def test_missing_executable_is_unknown_not_error(stub_path: Path) -> None:
    result = probe_executable("kicad-cli", "kicad-cli-nonexistent", ["version"], r"([0-9.]+)")
    assert not result.present
    assert result.version == "unknown"
    assert not result.is_known


def test_version_is_parsed_from_stub(stub_path: Path) -> None:
    make_stub(stub_path, "kicad-cli", 'echo "9.0.4"')
    result = probe_executable("kicad-cli", "kicad-cli", ["version"], r"([0-9]+\.[0-9]+\.[0-9]+)")
    assert result.present
    assert result.version == "9.0.4"
    assert result.is_known


def test_unparsable_version_output_is_unknown(stub_path: Path) -> None:
    make_stub(stub_path, "freerouting", 'echo "no version here"')
    result = probe_executable("freerouting", "freerouting", ["--version"], r"([0-9]+\.[0-9]+)")
    assert result.present
    assert result.version == "unknown"
    assert not result.is_known


def test_failing_version_command_is_unknown(stub_path: Path) -> None:
    make_stub(stub_path, "kicad-cli", "exit 3")
    result = probe_executable("kicad-cli", "kicad-cli", ["version"], r"([0-9.]+)")
    assert result.present
    assert result.version == "unknown"


def test_probe_all_reports_every_tool() -> None:
    report = probe_all()
    versions = report.versions()
    assert set(versions) == {"kicad-cli", "freerouting", "cad-kernel"}
    for result in report.results:
        assert result.is_known == (result.present and result.version != "unknown")


def test_step_normalization_removes_only_file_name_timestamp() -> None:
    first = b"FILE_NAME('Open CASCADE Shape Model','2026-08-11T12:00:00',('Author'));"
    second = b"FILE_NAME('Open CASCADE Shape Model','2026-08-11T12:00:01',('Author'));"
    assert first != second
    assert normalize_step(first) == normalize_step(second)


def test_3mf_normalization_removes_uuid_and_zip_timestamp() -> None:
    def make(uuid: str, date_time: tuple[int, int, int, int, int, int]) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            info = zipfile.ZipInfo("3D/3dmodel.model", date_time=date_time)
            archive.writestr(
                info,
                f'<object p:UUID="{uuid}"/>'.encode(),
            )
        return output.getvalue()

    first = make("11111111-1111-1111-1111-111111111111", (2026, 8, 11, 12, 0, 0))
    second = make("22222222-2222-2222-2222-222222222222", (2026, 8, 11, 12, 0, 2))
    assert first != second
    assert normalize_3mf(first) == normalize_3mf(second)


def test_step_normalization_fails_closed_without_measured_pattern() -> None:
    with pytest.raises(CadNormalizationError):
        normalize_step(b"FILE_NAME('Other CAD','2026-08-11T12:00:00');")


def test_3mf_normalization_fails_closed_without_model_entry() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("not-a-model.txt", b"unexpected")
    with pytest.raises(CadNormalizationError):
        normalize_3mf(output.getvalue())
