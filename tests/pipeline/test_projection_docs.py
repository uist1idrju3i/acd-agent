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
            names = ("product-readme.md",)
        elif "generate_instruction_manual.py" in " ".join(command):
            names = ("instruction-manual.md",)
        elif "generate_interface_spec.py" in " ".join(command):
            names = ("interface-spec.md", "interface-spec.json")
        elif "generate_shipping_inspection.py" in " ".join(command):
            names = ("shipping-inspection.md", "shipping-inspection.json")
        elif "generate_review_package.py" in " ".join(command):
            names = ("review-package.md", "review-package.json", "graph-diff.json")
        elif "generate_idea_allocation_docs.py" in " ".join(command):
            names = (
                "idea-record.md",
                "rough-estimate.md",
                "rough-estimate.json",
                "responsibility-allocation.md",
                "responsibility-allocation.json",
                "cross-domain-block-diagram.svg",
            )
        else:
            names = (
                "inspection-report.md",
                "traceability-report.md",
                "quality-report.json",
            )
        for name in names:
            (output / name).write_text(f"# {name}\n", encoding="utf-8")
            (output / f"{name}.provenance.json").write_text("{}\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    return runner


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    repository = Path(__file__).resolve().parents[2]
    out_root = tmp_path / "out"
    board_out = out_root / "board"
    enclosure_out = out_root / "enclosure"
    firmware_out = out_root / "firmware"
    output = out_root / "docs"
    projection = out_root / "visual-projections-board.json"
    projection.parent.mkdir(parents=True)
    projection.write_text("{}\n", encoding="utf-8")
    (firmware_out / "main").mkdir(parents=True)
    (firmware_out / "main" / "acd_pins.h").write_text(
        "#define ACD_TARGET_REVISION x\n", encoding="utf-8"
    )
    (firmware_out / "firmware-config-report.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (firmware_out / "evidence-firmware.json").write_text("{}\n", encoding="utf-8")
    board_out.mkdir(parents=True)
    enclosure_out.mkdir(parents=True)
    for lane_dir, name in (
        (board_out, "evidence-electrical.json"),
        (enclosure_out, "evidence-mechanical.json"),
        (board_out, "rationale-coverage.json"),
        (enclosure_out, "rationale-coverage.json"),
    ):
        (lane_dir / name).write_text("{}\n", encoding="utf-8")
    (board_out / "gate-evidence").mkdir()
    (board_out / "gate-evidence" / "design-predicates.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (board_out / "fab").mkdir()
    (board_out / "fab" / "dfm-report.json").write_text("{}\n", encoding="utf-8")
    graph_path = tmp_path / "graph.json"
    graph_path.write_text("{}\n", encoding="utf-8")
    (tmp_path / "rationale.json").write_text("{}\n", encoding="utf-8")
    return (
        repository,
        out_root,
        board_out,
        enclosure_out,
        firmware_out,
        output,
        graph_path,
    )


def _projection_collector(out_root: Path):
    def collect(_root: Path) -> list[Path]:
        return [out_root / "visual-projections-board.json"]

    return collect


def test_run_projection_docs_writes_flat_hashes_and_optional_theme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, out_root, board_out, enclosure_out, firmware_out, output, graph_path = _inputs(
        tmp_path
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        projection_docs,
        "collect_visual_projection_sets",
        _projection_collector(out_root),
    )
    result = run_projection_docs(
        repository,
        graph_path=graph_path,
        out_root=out_root,
        board_out=board_out,
        firmware_out=firmware_out,
        output=output,
        enclosure_out=enclosure_out,
        runner=_runner_factory(calls),
    )
    assert len(result.documents) == 12
    hashes = (output / "hashes.json").read_text(encoding="utf-8")
    assert "product-readme.md" in hashes
    assert "instruction-manual.md" in hashes
    assert "interface-spec.md" in hashes
    assert "interface-spec.json" in hashes
    assert "shipping-inspection.md" in hashes
    assert "shipping-inspection.json" in hashes
    assert "inspection-report.md" in hashes
    assert "traceability-report.md" in hashes
    assert "quality-report.json" in hashes
    assert "review-package.md" in hashes
    assert "review-package.json" in hashes
    assert "graph-diff.json" in hashes
    assert result.provenance["skill_name"] == "acd-product-docs"
    assert result.provenance["pass_evidence"] is False
    assert all("theme-song-projection" not in command for command in calls)
    review_command = next(
        command for command in calls if "generate_review_package.py" in " ".join(command)
    )
    assert "--no-previous-revision" in review_command

    (board_out / "theme-song-projection.json").write_text("{}\n", encoding="utf-8")
    calls.clear()
    run_projection_docs(
        repository,
        graph_path=graph_path,
        out_root=out_root,
        board_out=board_out,
        firmware_out=firmware_out,
        output=output,
        enclosure_out=enclosure_out,
        runner=_runner_factory(calls),
    )
    assert any("--theme-song-projection" in command for command in calls)


def test_run_projection_docs_surfaces_generator_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, out_root, board_out, enclosure_out, firmware_out, output, graph_path = _inputs(
        tmp_path
    )
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
            graph_path=graph_path,
            out_root=out_root,
            board_out=board_out,
            firmware_out=firmware_out,
            output=output,
            enclosure_out=enclosure_out,
            runner=failing_runner,
        )


def test_run_projection_docs_generates_two_language_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, out_root, board_out, enclosure_out, firmware_out, output, graph_path = (
        _inputs(tmp_path)
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        projection_docs,
        "collect_visual_projection_sets",
        _projection_collector(out_root),
    )
    result = run_projection_docs(
        repository,
        graph_path=graph_path,
        out_root=out_root,
        board_out=board_out,
        firmware_out=firmware_out,
        output=output,
        enclosure_out=enclosure_out,
        languages=("ja", "en"),
        runner=_runner_factory(calls),
    )
    assert len(result.documents) == 24
    assert {document.language for document in result.documents} == {"ja", "en"}
    assert result.provenance["languages"] == ["ja", "en"]
    for language in ("ja", "en"):
        root = output if language == "ja" else output / language
        assert (root / "review-package.json").is_file()
        assert (root / "review-package.json.provenance.json").is_file()
    assert any(
        "--lang" in command
        and command[command.index("--lang") + 1] == "en"
        and command[command.index("--out-dir") + 1] == str(output / "en")
        for command in calls
    )
    hashes = (output / "hashes.json").read_text(encoding="utf-8")
    assert "en/review-package.json" in hashes


@pytest.mark.parametrize(
    ("languages", "message"),
    [
        ((), "at least one"),
        (("fr",), "unsupported"),
        (("ja", "ja"), "duplicate"),
    ],
)
def test_run_projection_docs_rejects_invalid_languages(
    tmp_path: Path,
    languages: tuple[str, ...],
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, out_root, board_out, enclosure_out, firmware_out, output, graph_path = (
        _inputs(tmp_path)
    )
    with pytest.raises(ProjectionDocsError, match=message):
        run_projection_docs(
            repository,
            graph_path=graph_path,
            out_root=out_root,
            board_out=board_out,
            firmware_out=firmware_out,
            output=output,
            enclosure_out=enclosure_out,
            languages=languages,
            runner=_runner_factory([]),
        )


@pytest.mark.parametrize("count", [0, 2])
def test_run_projection_docs_requires_one_pins_header(
    tmp_path: Path, count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, out_root, board_out, enclosure_out, firmware_out, output, graph_path = _inputs(
        tmp_path
    )
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
            graph_path=graph_path,
            out_root=out_root,
            board_out=board_out,
            firmware_out=firmware_out,
            output=output,
            enclosure_out=enclosure_out,
            runner=_runner_factory([]),
        )


@pytest.mark.parametrize("count", [0, 2])
def test_run_projection_docs_requires_one_config_report(
    tmp_path: Path, count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, out_root, board_out, enclosure_out, firmware_out, output, graph_path = _inputs(
        tmp_path
    )
    if count == 0:
        (firmware_out / "firmware-config-report.json").unlink()
    else:
        second = firmware_out / "other"
        second.mkdir(parents=True)
        (second / "firmware-config-report.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        projection_docs,
        "collect_visual_projection_sets",
        _projection_collector(out_root),
    )
    with pytest.raises(
        ProjectionDocsError, match=r"exactly one firmware-config-report\.json"
    ):
        run_projection_docs(
            repository,
            graph_path=graph_path,
            out_root=out_root,
            board_out=board_out,
            firmware_out=firmware_out,
            output=output,
            enclosure_out=enclosure_out,
            runner=_runner_factory([]),
        )


def test_run_projection_docs_requires_mechanical_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, out_root, board_out, enclosure_out, firmware_out, output, graph_path = (
        _inputs(tmp_path)
    )
    (enclosure_out / "evidence-mechanical.json").unlink()
    monkeypatch.setattr(
        projection_docs,
        "collect_visual_projection_sets",
        _projection_collector(out_root),
    )
    with pytest.raises(ProjectionDocsError, match="mechanical evidence"):
        run_projection_docs(
            repository,
            graph_path=graph_path,
            out_root=out_root,
            board_out=board_out,
            firmware_out=firmware_out,
            output=output,
            enclosure_out=enclosure_out,
            runner=_runner_factory([]),
        )


def _idea_inputs(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    fixture = repository / "fixtures" / "responsibility" / "sample"
    idea_dir = tmp_path / "idea"
    idea_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "graph.json").write_text(
        (fixture / "graph.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "responsibility.json").write_text(
        (fixture / "responsibility.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (idea_dir / "idea.json").write_text(
        (repository / "fixtures" / "idea" / "sample-usb-thermometer" / "idea.json")
        .read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (idea_dir / "estimate-catalog.json").write_text(
        (
            repository
            / "fixtures"
            / "idea"
            / "sample-usb-thermometer"
            / "estimate-catalog.json"
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _run_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]
):
    repository, out_root, board_out, enclosure_out, firmware_out, output, graph_path = _inputs(
        tmp_path
    )
    monkeypatch.setattr(
        projection_docs,
        "collect_visual_projection_sets",
        _projection_collector(out_root),
    )
    return run_projection_docs(
        repository,
        graph_path=graph_path,
        out_root=out_root,
        board_out=board_out,
        firmware_out=firmware_out,
        output=output,
        enclosure_out=enclosure_out,
        runner=_runner_factory(calls),
    ), output


def test_idea_allocation_docs_not_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    result, _ = _run_docs(tmp_path, monkeypatch, calls)
    assert result.provenance["idea_allocation_docs"] == "not_declared"
    assert not any(
        "generate_idea_allocation_docs.py" in command for command in calls
    )
    assert len(result.documents) == 12


def test_idea_allocation_docs_partial_inputs_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _idea_inputs(tmp_path)
    (tmp_path / "responsibility.json").unlink()
    calls: list[list[str]] = []
    with pytest.raises(ProjectionDocsError, match="partially declared"):
        _run_docs(tmp_path, monkeypatch, calls)


def test_idea_allocation_docs_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _idea_inputs(tmp_path)
    calls: list[list[str]] = []
    result, _output = _run_docs(tmp_path, monkeypatch, calls)
    assert result.provenance["idea_allocation_docs"] == "generated"
    assert len(result.documents) == 18
    assert any(
        "generate_idea_allocation_docs.py" in " ".join(command)
        for command in calls
    )
