"""Run the product-document Skill and record its generated projections."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from acd.pipeline.visual_review import collect_visual_projection_sets

PRODUCT_DOCS_SKILL = "acd-product-docs"
PROJECTION_DOCS_TIMEOUT_SECONDS = 600


class ProjectionDocsError(Exception):
    """Raised when product-document projections cannot be generated."""

    def __init__(self, reason: str, *, output_path: Path | None = None) -> None:
        super().__init__(reason)
        self.output_path = output_path


@dataclass(frozen=True)
class GeneratedDocument:
    """One generated document and its provenance record."""

    kind: str
    path: Path
    provenance_path: Path
    sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "provenance_path": str(self.provenance_path),
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class ProjectionDocsResult:
    """Outcome of one successful product-document projection stage."""

    output_path: Path
    documents: tuple[GeneratedDocument, ...]
    hashes_path: Path
    provenance: dict[str, object]


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _script_path(repository: Path, name: str) -> Path:
    return (
        repository
        / "plugins"
        / "acd"
        / "skills"
        / PRODUCT_DOCS_SKILL
        / "scripts"
        / name
    )


def _document_name(script: Path, *, output_path: Path) -> str:
    match = re.search(
        r"(?m)^\s*DOCUMENT_NAME\s*=\s*[\"']([^\"']+)[\"']\s*$",
        script.read_text(encoding="utf-8"),
    )
    if match is None:
        raise ProjectionDocsError(
            f"DOCUMENT_NAME is missing from product-docs script: {script}",
            output_path=output_path,
        )
    return match.group(1)


def _execute(
    command: list[str],
    *,
    repository: Path,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None,
) -> subprocess.CompletedProcess[str]:
    if runner is not None:
        return runner(command)
    return subprocess.run(
        command,
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=PROJECTION_DOCS_TIMEOUT_SECONDS,
    )


def _require_document(
    output: Path, *, kind: str, document_name: str
) -> GeneratedDocument:
    document = output / document_name
    provenance = output / f"{document_name}.provenance.json"
    if not document.is_file():
        raise ProjectionDocsError(
            f"{kind} document is missing: {document}", output_path=output
        )
    if not provenance.is_file():
        raise ProjectionDocsError(
            f"{kind} provenance is missing: {provenance}", output_path=output
        )
    return GeneratedDocument(
        kind=kind,
        path=document,
        provenance_path=provenance,
        sha256=_sha256(document),
    )


def _write_hashes(output: Path) -> Path:
    hashes_path = output / "hashes.json"
    hashes = {
        path.relative_to(output).as_posix(): _sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path != hashes_path
    }
    hashes_path.write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return hashes_path


def run_projection_docs(
    repository: Path,
    *,
    graph_path: Path,
    out_root: Path,
    board_out: Path,
    firmware_out: Path,
    output: Path,
    enclosure_out: Path,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> ProjectionDocsResult:
    """Run all product-document generators and hash their outputs."""
    readme_script = _script_path(repository, "generate_product_readme.py")
    manual_script = _script_path(repository, "generate_instruction_manual.py")
    interface_script = _script_path(repository, "generate_interface_spec.py")
    quality_script = _script_path(repository, "generate_quality_report.py")
    idea_script = _script_path(repository, "generate_idea_allocation_docs.py")
    for script in (
        readme_script,
        manual_script,
        interface_script,
        quality_script,
        idea_script,
    ):
        if not script.is_file():
            raise ProjectionDocsError(
                f"product-docs Skill script is missing: {script}",
                output_path=output,
            )
    readme_name = _document_name(readme_script, output_path=output)
    manual_name = _document_name(manual_script, output_path=output)
    interface_name = _document_name(interface_script, output_path=output)
    interface_json_name = "interface-spec.json"
    try:
        projections = collect_visual_projection_sets(out_root)
    except Exception as exc:
        raise ProjectionDocsError(
            f"visual projection sets could not be collected: {exc}",
            output_path=output,
        ) from exc
    pins_headers = sorted(firmware_out.rglob("main/acd_pins.h"))
    if len(pins_headers) != 1:
        raise ProjectionDocsError(
            f"expected exactly one acd_pins.h projection, found {len(pins_headers)}",
            output_path=output,
        )
    config_reports = sorted(firmware_out.rglob("firmware-config-report.json"))
    if len(config_reports) != 1:
        raise ProjectionDocsError(
            "expected exactly one firmware-config-report.json projection, "
            f"found {len(config_reports)}",
            output_path=output,
        )
    fw_evidence = sorted(
        path
        for path in firmware_out.rglob("evidence-firmware.json")
        if ".stage-cache" not in path.parts
    )
    if len(fw_evidence) != 1:
        raise ProjectionDocsError(
            "expected exactly one evidence-firmware.json projection, "
            f"found {len(fw_evidence)}",
            output_path=output,
        )
    quality_inputs = {
        "electrical evidence": board_out / "evidence-electrical.json",
        "mechanical evidence": enclosure_out / "evidence-mechanical.json",
        "board rationale coverage": board_out / "rationale-coverage.json",
        "enclosure rationale coverage": enclosure_out / "rationale-coverage.json",
        "design predicates": board_out / "gate-evidence" / "design-predicates.json",
        "DFM report": board_out / "fab" / "dfm-report.json",
        "rationale": graph_path.parent / "rationale.json",
    }
    for label, path in quality_inputs.items():
        if not path.is_file():
            raise ProjectionDocsError(
                f"{label} input is missing: {path}", output_path=output
            )
    theme_song = board_out / "theme-song-projection.json"
    output.mkdir(parents=True, exist_ok=True)
    readme_command = [
        "uv",
        "run",
        "--script",
        str(readme_script),
        "--graph",
        str(graph_path),
        "--projections",
        *[str(path) for path in projections],
    ]
    if theme_song.is_file():
        readme_command.extend(["--theme-song-projection", str(theme_song)])
    readme_command.extend(
        ["--out-dir", str(output), "--base-dir", str(out_root)]
    )
    completed = _execute(
        readme_command,
        repository=repository,
        runner=runner,
    )
    if completed.returncode != 0:
        raise ProjectionDocsError(
            completed.stderr.strip()
            or f"product README generator exited with code {completed.returncode}",
            output_path=output,
        )
    manual_command = [
        "uv",
        "run",
        "--script",
        str(manual_script),
        "--graph",
        str(graph_path),
        "--pins-header",
        str(pins_headers[0]),
        "--out-dir",
        str(output),
        "--base-dir",
        str(out_root),
    ]
    completed = _execute(
        manual_command,
        repository=repository,
        runner=runner,
    )
    if completed.returncode != 0:
        raise ProjectionDocsError(
            completed.stderr.strip()
            or f"instruction manual generator exited with code {completed.returncode}",
            output_path=output,
        )
    interface_command = [
        "uv",
        "run",
        "--script",
        str(interface_script),
        "--graph",
        str(graph_path),
        "--pins-header",
        str(pins_headers[0]),
        "--firmware-config-report",
        str(config_reports[0]),
        "--out-dir",
        str(output),
        "--base-dir",
        str(out_root),
    ]
    completed = _execute(
        interface_command,
        repository=repository,
        runner=runner,
    )
    if completed.returncode != 0:
        raise ProjectionDocsError(
            completed.stderr.strip()
            or f"interface spec generator exited with code {completed.returncode}",
            output_path=output,
        )
    quality_command = [
        "uv",
        "run",
        "--script",
        str(quality_script),
        "--graph",
        str(graph_path),
        "--evidence",
        str(quality_inputs["electrical evidence"]),
        "--evidence",
        str(quality_inputs["mechanical evidence"]),
        "--evidence",
        str(fw_evidence[0]),
        "--rationale-coverage",
        str(quality_inputs["board rationale coverage"]),
        "--rationale-coverage",
        str(quality_inputs["enclosure rationale coverage"]),
        "--rationale",
        str(quality_inputs["rationale"]),
        "--design-predicates",
        str(quality_inputs["design predicates"]),
        "--dfm-report",
        str(quality_inputs["DFM report"]),
        "--out-dir",
        str(output),
        "--base-dir",
        str(out_root),
    ]
    completed = _execute(
        quality_command,
        repository=repository,
        runner=runner,
    )
    if completed.returncode != 0:
        raise ProjectionDocsError(
            completed.stderr.strip()
            or f"quality report generator exited with code {completed.returncode}",
            output_path=output,
        )
    fixture_dir = graph_path.parent
    idea_inputs = {
        "idea record": fixture_dir / "idea" / "idea.json",
        "estimate catalog": fixture_dir / "idea" / "estimate-catalog.json",
        "responsibility declaration": fixture_dir / "responsibility.json",
    }
    idea_present = {label: path for label, path in idea_inputs.items() if path.is_file()}
    documents: list[GeneratedDocument] = [
        _require_document(
            output,
            kind="product_readme",
            document_name=readme_name,
        ),
        _require_document(
            output,
            kind="instruction_manual",
            document_name=manual_name,
        ),
        _require_document(
            output,
            kind="interface_spec",
            document_name=interface_name,
        ),
        _require_document(
            output,
            kind="interface_spec_json",
            document_name=interface_json_name,
        ),
        _require_document(
            output,
            kind="inspection_report",
            document_name="inspection-report.md",
        ),
        _require_document(
            output,
            kind="traceability_report",
            document_name="traceability-report.md",
        ),
        _require_document(
            output,
            kind="quality_report_json",
            document_name="quality-report.json",
        ),
    ]
    idea_allocation_docs = "not_declared"
    if idea_present and len(idea_present) != len(idea_inputs):
        missing = sorted(
            str(path) for label, path in idea_inputs.items() if label not in idea_present
        )
        raise ProjectionDocsError(
            "idea allocation inputs are partially declared; missing: "
            + ", ".join(missing),
            output_path=output,
        )
    if len(idea_present) == len(idea_inputs):
        idea_command = [
            "uv",
            "run",
            "--script",
            str(idea_script),
            "--graph",
            str(graph_path),
            "--idea",
            str(idea_inputs["idea record"]),
            "--estimate-catalog",
            str(idea_inputs["estimate catalog"]),
            "--responsibility",
            str(idea_inputs["responsibility declaration"]),
            "--out-dir",
            str(output),
            "--base-dir",
            str(out_root),
        ]
        completed = _execute(
            idea_command,
            repository=repository,
            runner=runner,
        )
        if completed.returncode != 0:
            raise ProjectionDocsError(
                completed.stderr.strip()
                or "idea allocation generator exited with code "
                f"{completed.returncode}",
                output_path=output,
            )
        idea_allocation_docs = "generated"
        documents += [
            _require_document(
                output, kind="idea_record", document_name="idea-record.md"
            ),
            _require_document(
                output, kind="rough_estimate", document_name="rough-estimate.md"
            ),
            _require_document(
                output,
                kind="rough_estimate_json",
                document_name="rough-estimate.json",
            ),
            _require_document(
                output,
                kind="responsibility_allocation",
                document_name="responsibility-allocation.md",
            ),
            _require_document(
                output,
                kind="responsibility_allocation_json",
                document_name="responsibility-allocation.json",
            ),
            _require_document(
                output,
                kind="cross_domain_block_diagram",
                document_name="cross-domain-block-diagram.svg",
            ),
        ]
    hashes_path = _write_hashes(output)
    provenance: dict[str, object] = {
        "skill_name": PRODUCT_DOCS_SKILL,
        "scripts": {
            script.name: {
                "path": script.relative_to(repository).as_posix(),
                "sha256": _sha256(script),
            }
            for script in (
                readme_script,
                manual_script,
                interface_script,
                quality_script,
                idea_script,
            )
        },
        "pass_evidence": False,
        "idea_allocation_docs": idea_allocation_docs,
    }
    return ProjectionDocsResult(
        output_path=output,
        documents=documents,
        hashes_path=hashes_path,
        provenance=provenance,
    )
