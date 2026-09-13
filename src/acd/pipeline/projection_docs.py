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
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> ProjectionDocsResult:
    """Run both product-document generators and hash their outputs."""
    readme_script = _script_path(repository, "generate_product_readme.py")
    manual_script = _script_path(repository, "generate_instruction_manual.py")
    for script in (readme_script, manual_script):
        if not script.is_file():
            raise ProjectionDocsError(
                f"product-docs Skill script is missing: {script}",
                output_path=output,
            )
    readme_name = _document_name(readme_script, output_path=output)
    manual_name = _document_name(manual_script, output_path=output)
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
    documents = (
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
    )
    hashes_path = _write_hashes(output)
    provenance: dict[str, object] = {
        "skill_name": PRODUCT_DOCS_SKILL,
        "scripts": {
            script.name: {
                "path": script.relative_to(repository).as_posix(),
                "sha256": _sha256(script),
            }
            for script in (readme_script, manual_script)
        },
        "pass_evidence": False,
    }
    return ProjectionDocsResult(
        output_path=output,
        documents=documents,
        hashes_path=hashes_path,
        provenance=provenance,
    )
