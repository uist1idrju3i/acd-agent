from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from acd.pipeline import projection_docs
from acd.pipeline.projection_docs import (
    ProjectionDocsError,
    run_projection_docs,
)


def _runner_factory(calls: list[list[str]]):
    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        output = Path(command[command.index("--out-dir") + 1])
        output.mkdir(parents=True, exist_ok=True)
        if "generate_product_readme.py" in " ".join(command):
            name = "product-readme.md"
        else:
            name = "instruction-manual.md"
        (output / name).write_text(f"# {name}\n", encoding="utf-8")
        (output / f"{name}.provenance.json").write_text("{}\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    return runner


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    repository = Path(__file__).resolve().parents[2]
    out_root = tmp_path / "out"
    board_out = out_root / "board"
    firmware_out = out_root / "firmware"
    output = out_root / "docs"
    projection = out_root / "visual-projections-board.json"
    projection.parent.mkdir(parents=True)
    projection.write_text("{}\n", encoding="utf-8")
    (firmware_out / "main").mkdir(parents=True)
    (firmware_out / "main" / "acd_pins.h").write_text(
        "#define ACD_TARGET_REVISION x\n", encoding="utf-8"
    )
    return repository, out_root, board_out, firmware_out, output


def _projection_collector(out_root: Path):
    def collect(_root: Path) -> list[Path]:
        return [out_root / "visual-projections-board.json"]

    return collect


def test_run_projection_docs_writes_flat_hashes_and_optional_theme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, out_root, board_out, firmware_out, output = _inputs(tmp_path)
    (board_out).mkdir()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        projection_docs,
        "collect_visual_projection_sets",
        _projection_collector(out_root),
    )
    result = run_projection_docs(
        repository,
        graph_path=tmp_path / "graph.json",
        out_root=out_root,
        board_out=board_out,
        firmware_out=firmware_out,
        output=output,
        runner=_runner_factory(calls),
    )
    assert len(result.documents) == 2
    hashes = (output / "hashes.json").read_text(encoding="utf-8")
    assert "product-readme.md" in hashes
    assert "instruction-manual.md" in hashes
    assert result.provenance["skill_name"] == "acd-product-docs"
    assert result.provenance["pass_evidence"] is False
    assert all("theme-song-projection" not in command for command in calls)

    (board_out / "theme-song-projection.json").write_text("{}\n", encoding="utf-8")
    calls.clear()
    run_projection_docs(
        repository,
        graph_path=tmp_path / "graph.json",
        out_root=out_root,
        board_out=board_out,
        firmware_out=firmware_out,
        output=output,
        runner=_runner_factory(calls),
    )
    assert any("--theme-song-projection" in command for command in calls)


def test_run_projection_docs_surfaces_generator_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, out_root, board_out, firmware_out, output = _inputs(tmp_path)
    monkeypatch.setattr(
        projection_docs,
        "collect_visual_projection_sets",
        _projection_collector(out_root),
    )

    def failing_runner(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "generator broke")

    with pytest.raises(ProjectionDocsError, match="generator broke"):
        run_projection_docs(
            repository,
            graph_path=tmp_path / "graph.json",
            out_root=out_root,
            board_out=board_out,
            firmware_out=firmware_out,
            output=output,
            runner=failing_runner,
        )


@pytest.mark.parametrize("count", [0, 2])
def test_run_projection_docs_requires_one_pins_header(
    tmp_path: Path, count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, out_root, board_out, firmware_out, output = _inputs(tmp_path)
    if count == 0:
        (firmware_out / "main" / "acd_pins.h").unlink()
    else:
        second = firmware_out / "other" / "main"
        second.mkdir(parents=True)
        (second / "acd_pins.h").write_text("header\n", encoding="utf-8")
    monkeypatch.setattr(
        projection_docs,
        "collect_visual_projection_sets",
        _projection_collector(out_root),
    )
    with pytest.raises(ProjectionDocsError, match=r"exactly one acd_pins\.h"):
        run_projection_docs(
            repository,
            graph_path=tmp_path / "graph.json",
            out_root=out_root,
            board_out=board_out,
            firmware_out=firmware_out,
            output=output,
            runner=_runner_factory([]),
        )
