"""Pure deterministic validation for design decision rationale."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Final

from acd_schema import (
    DesignGraph,
    RationaleCoverageReport,
    RationaleDocument,
    RationaleOrphan,
    RationaleRecordSubject,
    RationaleSubject,
    RationaleUnknownProvenance,
)
from acd_schema.common import Sha256

REQUIRED_RATIONALE_ATTRS: Final[dict[str, frozenset[str]]] = {
    "electrical.component": frozenset(
        {"mpn", "lcsc", "placement_x_mm", "placement_y_mm", "placement_rotation_deg"}
    ),
    "electrical.net": frozenset({"width_basis"}),
    "firmware.pin_assignment": frozenset({"gpio"}),
    "mechanical.outline": frozenset({"width_mm", "depth_mm", "thickness_mm"}),
    "mechanical.enclosure": frozenset({"material", "wall_thickness_mm"}),
    "mechanical.silk_text": frozenset({"x_mm", "y_mm", "rotation_deg"}),
}


def subject_hash_for(
    graph: DesignGraph, subject_nodes: list[str], subject_attrs: list[str]
) -> Sha256:
    values: list[list[object]] = []
    for node_id in sorted(subject_nodes):
        node = graph.node_by_id(node_id)
        for attr in sorted(subject_attrs):
            if attr not in node.attrs:
                raise KeyError(f"node {node_id!r} has no attribute {attr!r}")
            values.append([node_id, attr, node.attrs[attr]])
    encoded = json.dumps(
        values, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _subject(node_id: str, attr: str) -> RationaleSubject:
    return RationaleSubject(node_id=node_id, attr=attr)


def check_rationale_coverage(
    graph: DesignGraph, document: RationaleDocument
) -> RationaleCoverageReport:
    graph_id_match = document.graph_id == graph.graph_id
    revision_match = document.revision == graph.revision
    nodes = {node.id: node for node in graph.nodes}
    required = [
        (node.id, attr)
        for node in graph.nodes
        for attr in sorted(REQUIRED_RATIONALE_ATTRS.get(node.kind, frozenset()))
        if attr in node.attrs
    ]
    required_set = set(required)
    covered: dict[tuple[str, str], list[str]] = defaultdict(list)
    stale: list[RationaleRecordSubject] = []
    unknown: list[RationaleUnknownProvenance] = []
    orphan: list[RationaleOrphan] = []

    for record in document.records:
        record_subjects = [
            (node_id, attr)
            for node_id in record.subject_nodes
            for attr in record.subject_attrs
        ]
        record_stale = record.target_revision != graph.revision
        record_orphan = False
        for node_id, attr in record_subjects:
            subject = _subject(node_id, attr)
            node = nodes.get(node_id)
            if node is None:
                orphan.append(RationaleOrphan(
                    rationale_id=record.rationale_id, subject=subject, reason="unknown node"
                ))
                record_orphan = True
                continue
            if attr not in node.attrs:
                orphan.append(RationaleOrphan(
                    rationale_id=record.rationale_id, subject=subject, reason="unknown attribute"
                ))
                record_orphan = True
                continue
            if record_stale:
                stale.append(RationaleRecordSubject(
                    rationale_id=record.rationale_id, subject=subject
                ))
        for requirement_id in record.driving_requirements:
            requirement = nodes.get(requirement_id)
            if requirement is None or requirement.kind not in {"requirement", "safety.boundary"}:
                orphan.append(RationaleOrphan(
                    rationale_id=record.rationale_id,
                    subject=_subject(record.subject_nodes[0], record.subject_attrs[0]),
                    reason=f"invalid driving requirement {requirement_id!r}",
                ))
                record_orphan = True
        hash_matches = False
        if not record_stale and not record_orphan:
            try:
                hash_matches = record.subject_hash == subject_hash_for(
                    graph, record.subject_nodes, record.subject_attrs
                )
            except KeyError:
                hash_matches = False
        if not hash_matches and not record_stale and not record_orphan:
            stale.extend(
                RationaleRecordSubject(
                    rationale_id=record.rationale_id,
                    subject=_subject(node_id, attr),
                )
                for node_id, attr in record_subjects
            )
        if record.provenance.script_hash in (None, "unknown"):
            unknown.append(RationaleUnknownProvenance(rationale_id=record.rationale_id))
        if (
            not record_stale
            and not record_orphan
            and hash_matches
            and record.provenance.script_hash not in (None, "unknown")
        ):
            for subject in record_subjects:
                covered[subject].append(record.rationale_id)

    missing = [
        _subject(node_id, attr)
        for node_id, attr in required
        if not covered[(node_id, attr)]
    ]
    conflicting = [
        RationaleRecordSubject(rationale_id=record_id, subject=_subject(*subject))
        for subject, record_ids in sorted(covered.items())
        if len(record_ids) > 1
        for record_id in record_ids
    ]
    failed = (
        not graph_id_match
        or not revision_match
        or bool(missing or stale or unknown or orphan or conflicting)
    )
    return RationaleCoverageReport(
        status="fail" if failed else "pass",
        graph_id=graph.graph_id,
        revision=graph.revision,
        graph_id_match=graph_id_match,
        revision_match=revision_match,
        missing=missing,
        stale=stale,
        unknown_provenance=unknown,
        orphan=orphan,
        conflicting=conflicting,
        required_count=len(required_set),
        covered_count=sum(1 for subject in required_set if covered[subject]),
        record_count=len(document.records),
    )
