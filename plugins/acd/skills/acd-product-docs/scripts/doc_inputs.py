# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@07e980060b05d3326dacf2b1a72d3fe9e8a37fc5",
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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import cast

from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.theme_song import ThemeSongProjection
from acd.schema.visual_projection import VisualProjectionRecord, VisualProjectionSet

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
            f"unsupported document language {lang!r}; "
            f"expected one of {SUPPORTED_LANGUAGES!r}"
        )
    path = Path(__file__).resolve().parents[1] / "templates" / f"{lang}.json"
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DocumentGenerationError(
            f"document template {path} is not valid: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise DocumentGenerationError(
            f"document template {path} must be an object of text values"
        )
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


@dataclass(frozen=True)
class PredicateObservation:
    """One design-predicate observation row."""

    name: str
    evaluation_stage: str
    status: str
    detail: str


@dataclass(frozen=True)
class DesignPredicates:
    """Parsed design-predicates gate observation."""

    target_revision: str
    status: str
    predicates: tuple[PredicateObservation, ...]


@dataclass(frozen=True)
class DfmFinding:
    """One DFM finding row."""

    rule_id: str
    message: str


@dataclass(frozen=True)
class DfmReport:
    """Parsed DFM report."""

    target_revision: str
    status: str
    profile_id: str
    findings: tuple[DfmFinding, ...]
    unknowns: dict[str, str]
    checks_not_implemented: tuple[DfmFinding, ...]


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


@dataclass(frozen=True)
class ProjectionFigure:
    projection_id: str
    projection_type: str
    domain: str
    image_path: Path
    image_hash: str
    renderer_type: str
    renderer_tool_version: str
    media_type: str


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
        renderer_type=projection.renderer.renderer_type,
        renderer_tool_version=projection.renderer.tool_version,
        media_type=projection.media_type,
    )


def load_design_predicates(path: Path, graph: DesignGraph) -> DesignPredicates:
    """Parse the design-predicates gate observation file."""
    data = load_json_object(path, label="design predicates")
    observation = require_object(data.get("observation"), field="observation")
    predicates = tuple(
        PredicateObservation(
            name=require_str(item.get("name"), field="predicates[].name"),
            evaluation_stage=require_str(
                item.get("evaluation_stage"), field="predicates[].evaluation_stage"
            ),
            status=require_str(item.get("status"), field="predicates[].status"),
            detail=require_str(item.get("detail"), field="predicates[].detail"),
        )
        for item in (
            require_object(entry, field="predicates[]")
            for entry in require_list(
                observation.get("predicates"), field="observation.predicates"
            )
        )
    )
    return DesignPredicates(
        target_revision=require_str(
            data.get("target_revision"), field="target_revision"
        ),
        status=require_str(data.get("status"), field="status"),
        predicates=predicates,
    )


def load_dfm_report(path: Path, graph: DesignGraph) -> DfmReport:
    """Parse the DFM report file."""
    data = load_json_object(path, label="DFM report")
    findings = tuple(
        DfmFinding(
            rule_id=require_str(item.get("rule_id"), field="findings[].rule_id"),
            message=require_str(item.get("message"), field="findings[].message"),
        )
        for item in (
            require_object(entry, field="findings[]")
            for entry in require_list(data.get("findings"), field="findings")
        )
    )
    unknowns_raw = require_object(data.get("unknowns"), field="unknowns")
    unknowns = {
        key: require_str(
            require_object(value, field=f"unknowns.{key}").get("reason"),
            field=f"unknowns.{key}.reason",
        )
        for key, value in unknowns_raw.items()
    }
    checks_not_implemented = tuple(
        DfmFinding(
            rule_id=require_str(
                item.get("rule_id"), field="checks_not_implemented[].rule_id"
            ),
            message=require_str(
                item.get("reason"), field="checks_not_implemented[].reason"
            ),
        )
        for item in (
            require_object(entry, field="checks_not_implemented[]")
            for entry in require_list(
                data.get("checks_not_implemented"), field="checks_not_implemented"
            )
        )
    )
    return DfmReport(
        target_revision=require_str(
            data.get("target_revision"), field="target_revision"
        ),
        status=require_str(data.get("status"), field="status"),
        profile_id=require_str(data.get("profile_id"), field="profile_id"),
        findings=findings,
        unknowns=unknowns,
        checks_not_implemented=checks_not_implemented,
    )


@dataclass(frozen=True)
class ThemeSongFigure:
    title: str
    key: str
    bpm: int
    bars: int
    composer_id: str
    source: str
    midi_path: Path
    midi_hash: str
    mml_path: Path | None
    mml_hash: str | None
    mml_reason: str | None
    regeneration_status: str
    pass_evidence: bool


def load_theme_song(
    path: Path, graph: DesignGraph
) -> tuple[ThemeSongFigure, DocumentInput]:
    """Load a recorded theme-song projection and its MIDI artifact, fail-closed."""
    content_hash = sha256_file(path)
    try:
        projection = ThemeSongProjection.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise DocumentGenerationError(
            f"theme-song projection {path} is not valid: {exc}"
        ) from exc
    if projection.graph_id != graph.graph_id:
        raise DocumentGenerationError(
            f"theme-song projection {path} targets graph "
            f"{projection.graph_id!r}, not {graph.graph_id!r}"
        )
    if projection.source_revision != graph.revision:
        raise DocumentGenerationError(
            f"theme-song projection {path} targets revision "
            f"{projection.source_revision!r}, not {graph.revision!r}"
        )
    if projection.regeneration_check.status != "reproduced":
        raise DocumentGenerationError(
            f"theme-song projection {path} was not reproduced "
            f"(status={projection.regeneration_check.status!r})"
        )
    midi_artifacts = [
        artifact for artifact in projection.artifacts if artifact.media_type == "audio/midi"
    ]
    mml_artifacts = [
        artifact for artifact in projection.artifacts if artifact.media_type == "text/x-mml"
    ]
    if len(midi_artifacts) != 1 or len(mml_artifacts) > 1:
        raise DocumentGenerationError(
            "theme-song projection must declare one MIDI and at most one MML"
        )
    artifact = midi_artifacts[0]
    midi_path = (path.parent / artifact.path).resolve()
    if not midi_path.is_file():
        raise DocumentGenerationError(
            f"theme-song artifact {midi_path} is missing"
        )
    midi_hash = sha256_file(midi_path)
    if midi_hash != artifact.content_hash:
        raise DocumentGenerationError(
            f"theme-song artifact {midi_path} hash mismatch "
            f"(declared={artifact.content_hash!r}, actual={midi_hash!r})"
        )
    mml_path: Path | None = None
    mml_hash: str | None = None
    if mml_artifacts:
        mml_artifact = mml_artifacts[0]
        mml_path = (path.parent / mml_artifact.path).resolve()
        if not mml_path.is_file():
            raise DocumentGenerationError(f"theme-song artifact {mml_path} is missing")
        mml_hash = sha256_file(mml_path)
        if mml_hash != mml_artifact.content_hash:
            raise DocumentGenerationError(
                f"theme-song artifact {mml_path} hash mismatch "
                f"(declared={mml_artifact.content_hash!r}, actual={mml_hash!r})"
            )
    figure = ThemeSongFigure(
        title=projection.title,
        key=projection.key,
        bpm=projection.bpm,
        bars=projection.bars,
        composer_id=projection.composer_id,
        source=projection.source,
        midi_path=midi_path,
        midi_hash=artifact.content_hash,
        mml_path=mml_path,
        mml_hash=mml_hash,
        mml_reason=projection.mml_check.reason,
        regeneration_status=projection.regeneration_check.status,
        pass_evidence=projection.pass_evidence,
    )
    return figure, DocumentInput(path=path, content_hash=content_hash)


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
        "generated_at": datetime.now(UTC).isoformat(),
    }
    provenance_path = out_dir / f"{document_name}.provenance.json"
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return document_path, provenance_path
