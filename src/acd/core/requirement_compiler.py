"""Deterministic requirement-to-graph change compiler."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acd.core.gpio import GpioAssignmentError, apply_gpio_assignment
from acd.core.rationale import subject_hash_for
from acd.core.requirements import (
    RequirementError,
    load_requirements,
    validate_requirements,
)
from acd.schema import (
    DesignGraph,
    GraphNode,
    RationaleDocument,
    RationaleRecord,
    RequirementRecord,
)
from acd.schema.common import canonical_json_sha256


class RequirementCompilationError(ValueError):
    """Raised when a requirement change cannot be compiled safely."""


@dataclass(frozen=True)
class RequirementCompilationResult:
    report: dict[str, Any]
    graph: DesignGraph


def _load_record(path: Path) -> RequirementRecord:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return RequirementRecord.model_validate(value)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RequirementCompilationError(
            f"updated requirement is invalid: {path}: {exc}"
        ) from exc


def _net_id(graph: DesignGraph, value: str) -> str:
    if any(node.id == value and node.kind == "electrical.net" for node in graph.nodes):
        return value
    matches = [
        node.id
        for node in graph.nodes
        if node.kind == "electrical.net" and node.attrs.get("name") == value
    ]
    if len(matches) != 1:
        raise RequirementCompilationError(
            f"requirement expectation net is unknown or ambiguous: {value!r}"
        )
    return matches[0]


def _update_requirement_nodes(
    graph: DesignGraph, requirement_id: str, statement: str
) -> tuple[DesignGraph, tuple[str, ...]]:
    node_id = f"req.{requirement_id}"
    try:
        graph.node_by_id(node_id)
    except KeyError as exc:
        raise RequirementCompilationError(
            f"requirement graph node is missing: {node_id}"
        ) from exc
    updated = [
        node.model_copy(update={"attrs": {**node.attrs, "text": statement}})
        if node.id == node_id
        else node
        for node in graph.nodes
    ]
    return graph.model_copy(update={"nodes": updated}), (node_id,)


def _update_coupled_labels(
    graph: DesignGraph, net_id: str, old_gpio: int, gpio: int
) -> tuple[DesignGraph, tuple[str, ...]]:
    changed: list[str] = []
    testpoint_components = {
        str(node.attrs.get("component"))
        for node in graph.nodes
        if node.kind == "electrical.pin"
        and node.attrs.get("net") == net_id
        and str(node.attrs.get("component", "")).startswith("comp.tp")
    }
    updated: list[GraphNode] = []
    for node in graph.nodes:
        attrs = dict(node.attrs)
        value = attrs.get("value")
        if (
            node.kind == "electrical.component"
            and node.id in testpoint_components
            and isinstance(value, str)
            and f"IO{old_gpio}" in value
        ):
            attrs["value"] = value.replace(f"IO{old_gpio}", f"IO{gpio}")
            updated.append(node.model_copy(update={"attrs": attrs}))
            changed.append(node.id)
        elif node.kind == "mechanical.silk_text":
            text = attrs.get("text")
            if isinstance(text, str) and (
                f"IO{old_gpio}" in text or f"GPIO{old_gpio}" in text
            ):
                attrs["text"] = text.replace(
                    f"IO{old_gpio}", f"IO{gpio}"
                ).replace(f"GPIO{old_gpio}", f"GPIO{gpio}")
                updated.append(node.model_copy(update={"attrs": attrs}))
                changed.append(node.id)
            else:
                updated.append(node)
        else:
            updated.append(node)
    return graph.model_copy(update={"nodes": updated}), tuple(sorted(changed))


def _old_gpio(graph: DesignGraph, net_id: str) -> int:
    assignments = [
        node.attrs.get("gpio")
        for node in graph.nodes
        if node.kind == "firmware.pin_assignment" and node.attrs.get("net") == net_id
    ]
    if len(assignments) != 1 or not isinstance(assignments[0], int):
        raise RequirementCompilationError(
            f"cannot determine existing GPIO assignment for {net_id!r}"
        )
    return assignments[0]


def _refresh_rationale(
    graph: DesignGraph, document: RationaleDocument
) -> RationaleDocument:
    refreshed: list[RationaleRecord] = []
    for record in document.records:
        try:
            expected_hash = subject_hash_for(
                graph, record.subject_nodes, record.subject_attrs
            )
        except KeyError as exc:
            raise RequirementCompilationError(
                f"rationale references missing graph subject: {record.rationale_id}"
            ) from exc
        refreshed.append(
            record.model_copy(
                update={"subject_hash": expected_hash, "target_revision": graph.revision}
            )
        )
    return document.model_copy(update={"records": refreshed})


def _write_transaction(contents: dict[Path, str]) -> None:
    """Replace a set of existing files together, restoring on commit failure."""
    temporary_paths: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    try:
        for path, content in contents.items():
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary_paths[path] = temporary
        try:
            for path, temporary in temporary_paths.items():
                backup = path.with_name(path.name + ".bak")
                os.replace(path, backup)
                backups[path] = backup
                os.replace(temporary, path)
        except OSError:
            for path in backups:
                if path.exists():
                    path.unlink()
                backup = backups.get(path)
                if backup is not None and backup.exists():
                    os.replace(backup, path)
            raise
    finally:
        for path in temporary_paths.values():
            path.unlink(missing_ok=True)
        for path in backups.values():
            path.unlink(missing_ok=True)


def compile_requirement_change(
    fixture_dir: Path,
    requirement_path: Path,
    *,
    dry_run: bool = False,
) -> RequirementCompilationResult:
    """Compile one requirement update and atomically write all coupled inputs."""
    graph_path = fixture_dir / "graph.json"
    requirements_path = fixture_dir / "requirements.json"
    rationale_path = fixture_dir / "rationale.json"
    try:
        graph = DesignGraph.model_validate(
            json.loads(graph_path.read_text(encoding="utf-8"))
        )
        loaded = load_requirements(requirements_path)
        updated = _load_record(requirement_path)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, RequirementError) as exc:
        raise RequirementCompilationError(str(exc)) from exc
    validate_requirements(loaded.document, graph)
    existing = [
        record
        for record in loaded.document.records
        if record.requirement_id == updated.requirement_id
    ]
    if len(existing) != 1:
        raise RequirementCompilationError(
            f"requirement_id is missing or ambiguous: {updated.requirement_id}"
        )
    expectation = updated.expectation or existing[0].expectation
    if expectation is None:
        raise RequirementCompilationError("updated requirement has no supported expectation")
    kind = expectation.get("kind")
    if kind != "gpio_assignment":
        raise RequirementCompilationError(f"unknown expectation kind: {kind!r}")
    net = expectation.get("net")
    gpio = expectation.get("gpio")
    if not isinstance(net, str) or not isinstance(gpio, int) or isinstance(gpio, bool):
        raise RequirementCompilationError("gpio_assignment requires string net and integer gpio")
    net_id = _net_id(graph, net)
    before_graph_hash = canonical_json_sha256(graph.model_dump(mode="json"))
    old_gpio = _old_gpio(graph, net_id)
    try:
        graph, gpio_changed = apply_gpio_assignment(graph, net_id, gpio)
    except GpioAssignmentError as exc:
        raise RequirementCompilationError(str(exc)) from exc
    graph, label_changed = _update_coupled_labels(graph, net_id, old_gpio, gpio)
    graph, requirement_changed = _update_requirement_nodes(
        graph, updated.requirement_id, updated.statement
    )
    records = [
        updated if record.requirement_id == updated.requirement_id else record
        for record in loaded.document.records
    ]
    updated_requirements = loaded.document.model_copy(update={"records": records})
    validate_requirements(updated_requirements, graph)
    try:
        rationale = RationaleDocument.model_validate(
            json.loads(rationale_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RequirementCompilationError(f"rationale document is invalid: {exc}") from exc
    updated_rationale = _refresh_rationale(graph, rationale)
    changed_node_ids = tuple(
        sorted(set(gpio_changed + label_changed + requirement_changed))
    )
    graph_content = json.dumps(
        graph.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    requirements_content = json.dumps(
        updated_requirements.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    rationale_content = json.dumps(
        updated_rationale.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if not dry_run:
        _write_transaction(
            {
                graph_path: graph_content,
                requirements_path: requirements_content,
                rationale_path: rationale_content,
            }
        )
    after_graph_hash = canonical_json_sha256(graph.model_dump(mode="json"))
    report = {
        "status": "dry_run" if dry_run else "written",
        "requirement_id": updated.requirement_id,
        "changed_node_ids": list(changed_node_ids),
        "before_graph_sha256": before_graph_hash,
        "after_graph_sha256": after_graph_hash,
        "before_requirements_sha256": loaded.document_hash,
        "after_requirements_sha256": canonical_json_sha256(
            updated_requirements.model_dump(mode="json")
        ),
        "pass_evidence": False,
        "record_class": "L2",
        "provenance": {
            "requirement_id": updated.requirement_id,
            "source": str(requirement_path),
            "pass_evidence": False,
        },
    }
    return RequirementCompilationResult(report=report, graph=graph)


__all__ = [
    "RequirementCompilationError",
    "RequirementCompilationResult",
    "compile_requirement_change",
]
