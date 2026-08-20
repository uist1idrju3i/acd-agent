# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@4cca489171ac53e6e55639b791c8571482167bd2",
# ]
# ///
"""Shared fail-closed inputs and provenance for generated product documents.

Generated documents are L3 observations: they never carry approval authority
and never flow back into design inputs. Every value written into a document
comes from the design graph or from a recorded projection; missing or
malformed inputs stop generation instead of being reported as "no problem".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.visual_projection import VisualProjectionRecord, VisualProjectionSet

DOCUMENT_SCHEMA_VERSION = "0.1"


class DocumentGenerationError(ValueError):
    """Raised when a document cannot be generated from its inputs."""


def sha256_file(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DocumentGenerationError(f"cannot read input {path}: {exc}") from exc
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DocumentInput:
    path: Path
    content_hash: str

    def as_record(self, base_dir: Path) -> dict[str, str]:
        return {"path": _relative(self.path, base_dir), "content_hash": self.content_hash}


def _relative(path: Path, base_dir: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def load_graph(path: Path) -> tuple[DesignGraph, DocumentInput]:
    """Load the authoritative design graph, failing closed on any defect."""
    content_hash = sha256_file(path)
    try:
        graph = DesignGraph.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError) as exc:
        raise DocumentGenerationError(f"design graph {path} is not valid: {exc}") from exc
    return graph, DocumentInput(path=path, content_hash=content_hash)


@dataclass(frozen=True)
class ProjectionFigure:
    projection_id: str
    projection_type: str
    domain: str
    image_path: Path
    image_hash: str


def load_projection_figures(
    set_paths: Sequence[Path], target_revision: str
) -> tuple[tuple[ProjectionFigure, ...], tuple[DocumentInput, ...]]:
    """Load visual projection sets and resolve every referenced image file."""
    if not set_paths:
        raise DocumentGenerationError("no visual projection set was declared (fail-closed)")
    figures: list[ProjectionFigure] = []
    inputs: list[DocumentInput] = []
    for set_path in set_paths:
        content_hash = sha256_file(set_path)
        try:
            projection_set = VisualProjectionSet.model_validate(
                json.loads(set_path.read_text(encoding="utf-8"))
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise DocumentGenerationError(
                f"visual projection set {set_path} is not valid: {exc}"
            ) from exc
        if projection_set.source_revision != target_revision:
            raise DocumentGenerationError(
                f"visual projection set {set_path} targets revision "
                f"{projection_set.source_revision!r}, not {target_revision!r}"
            )
        inputs.append(DocumentInput(path=set_path, content_hash=content_hash))
        for projection in projection_set.projections:
            figures.append(_figure(projection, set_path.parent))
    if not figures:
        raise DocumentGenerationError("visual projection sets contain no projection")
    return tuple(sorted(figures, key=lambda item: item.projection_id)), tuple(inputs)


def _figure(projection: VisualProjectionRecord, base_dir: Path) -> ProjectionFigure:
    image_path = base_dir / projection.image_path
    if not image_path.is_file():
        raise DocumentGenerationError(
            f"projection {projection.projection_id!r} image {image_path} is missing"
        )
    if projection.regeneration_check.status != "reproduced":
        raise DocumentGenerationError(
            f"projection {projection.projection_id!r} was not reproduced "
            f"(status={projection.regeneration_check.status!r})"
        )
    return ProjectionFigure(
        projection_id=projection.projection_id,
        projection_type=projection.projection_type,
        domain=projection.domain,
        image_path=image_path,
        image_hash=projection.image_hash,
    )


def node_by_id(graph: DesignGraph, node_id: str) -> GraphNode:
    for node in graph.nodes:
        if node.id == node_id:
            return node
    raise DocumentGenerationError(f"graph node {node_id!r} is missing")


def nodes_of_kind(graph: DesignGraph, kind: str) -> tuple[GraphNode, ...]:
    return tuple(sorted((n for n in graph.nodes if n.kind == kind), key=lambda n: n.id))


def single_node_of_kind(graph: DesignGraph, kind: str) -> GraphNode:
    nodes = nodes_of_kind(graph, kind)
    if len(nodes) != 1:
        raise DocumentGenerationError(
            f"graph declares {len(nodes)} {kind} nodes; exactly one is required"
        )
    return nodes[0]


def text_attr(node: GraphNode, name: str) -> str:
    value = node.attrs.get(name)
    if not isinstance(value, str) or not value:
        raise DocumentGenerationError(f"node {node.id!r}: attr {name!r} is missing or not text")
    return value


def number_attr(node: GraphNode, name: str) -> float:
    value = node.attrs.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DocumentGenerationError(f"node {node.id!r}: attr {name!r} is missing or not a number")
    return float(value)


def int_attr(node: GraphNode, name: str) -> int:
    value = node.attrs.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DocumentGenerationError(f"node {node.id!r}: attr {name!r} is missing or not an int")
    return value


def format_number(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def write_document(
    *,
    document_kind: str,
    body: str,
    out_dir: Path,
    document_name: str,
    template_id: str,
    generator: Path,
    graph: DesignGraph,
    inputs: Sequence[DocumentInput],
    base_dir: Path,
) -> tuple[Path, Path]:
    """Write a generated document plus its provenance record."""
    out_dir.mkdir(parents=True, exist_ok=True)
    document_path = out_dir / document_name
    document_path.write_text(body, encoding="utf-8")
    provenance = {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "artifact_kind": "generated_document",
        "pass_evidence": False,
        "document_kind": document_kind,
        "document_path": _relative(document_path, base_dir),
        "document_hash": sha256_text(body),
        "graph_id": graph.graph_id,
        "target_revision": graph.revision,
        "template_id": template_id,
        "generator": {
            "name": generator.name,
            "content_hash": sha256_file(generator),
        },
        "inputs": [item.as_record(base_dir) for item in inputs],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    provenance_path = out_dir / f"{document_name}.provenance.json"
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return document_path, provenance_path
