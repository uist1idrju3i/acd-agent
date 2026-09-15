"""Shared fail-closed document inputs: templates, JSON/graph loading, and provenance."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import cast

from acd.schema.design_graph import DesignGraph, GraphNode

DOCUMENT_SCHEMA_VERSION = "0.1"


SUPPORTED_LANGUAGES = ("ja", "en")


class DocumentGenerationError(ValueError):
    """Raised when a document cannot be generated from its inputs."""


@dataclass(frozen=True)
class DocumentTemplate:
    """One language-specific template catalog."""

    lang: str
    path: Path
    content_hash: str
    strings: Mapping[str, str]

    def t(self, key: str, **values: object) -> str:
        try:
            text = self.strings[key]
        except KeyError as exc:
            raise DocumentGenerationError(
                f"template key {key!r} is missing for language {self.lang!r}"
            ) from exc
        try:
            return text.format(**values)
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise DocumentGenerationError(
                f"template key {key!r} has missing or invalid placeholders"
            ) from exc


def load_template(lang: str) -> DocumentTemplate:
    """Load and validate a language-specific product-document template."""
    if lang not in SUPPORTED_LANGUAGES:
        raise DocumentGenerationError(
            f"unsupported document language {lang!r}; expected one of {SUPPORTED_LANGUAGES!r}"
        )
    path = Path(__file__).resolve().parents[2] / "templates" / f"{lang}.json"
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DocumentGenerationError(f"document template {path} is not valid: {exc}") from exc
    if not isinstance(payload, dict):
        raise DocumentGenerationError(f"document template {path} must be an object of text values")
    strings: dict[str, str] = {}
    entries = cast(dict[object, object], payload)
    for key, value in entries.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise DocumentGenerationError(
                f"document template {path} must be an object of text values"
            )
        strings[key] = value
    return DocumentTemplate(
        lang=lang,
        path=path,
        content_hash=sha256_file(path),
        strings=MappingProxyType(strings),
    )


def require_object(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise DocumentGenerationError(f"field {field!r} is not an object")
    return cast(dict[str, object], value)


def require_str(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DocumentGenerationError(f"field {field!r} is missing or not text")
    return value


def require_list(value: object, *, field: str) -> list[object]:
    if not isinstance(value, list):
        raise DocumentGenerationError(f"field {field!r} is not a list")
    return cast(list[object], value)


def load_json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DocumentGenerationError(f"{label} {path} is not valid: {exc}") from exc
    return require_object(payload, field=label)


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
        return {"path": relative_path(self.path, base_dir), "content_hash": self.content_hash}


def relative_path(path: Path, base_dir: Path) -> str:
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
    template: DocumentTemplate,
    analysis_provenance: Sequence[dict[str, str]] = (),
) -> tuple[Path, Path]:
    """Write a generated document plus its provenance record."""
    out_dir.mkdir(parents=True, exist_ok=True)
    document_path = out_dir / document_name
    document_path.write_text(body, encoding="utf-8")
    all_inputs = [
        *inputs,
        DocumentInput(path=template.path, content_hash=template.content_hash),
    ]
    provenance = {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "artifact_kind": "generated_document",
        "pass_evidence": False,
        "document_kind": document_kind,
        "document_path": relative_path(document_path, base_dir),
        "document_hash": sha256_text(body),
        "graph_id": graph.graph_id,
        "target_revision": graph.revision,
        "template_id": template_id,
        "template_path": relative_path(template.path, base_dir),
        "template_hash": template.content_hash,
        "language": template.lang,
        "generator": {
            "name": generator.name,
            "content_hash": sha256_file(generator),
        },
        "inputs": [item.as_record(base_dir) for item in all_inputs],
        "analysis_results": list(analysis_provenance),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    provenance_path = out_dir / f"{document_name}.provenance.json"
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return document_path, provenance_path
