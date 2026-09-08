"""Verify that declared evidence attributes resolve to measured records.

A spec may declare ``cpl_rotation_evidence_basis: "confirmed"`` or
``fab.order_intent`` provenance (``profile_source`` / ``profile_fetched_at``)
without a measured record behind it. This module reports such declarations as
``declared_unverified`` findings: an L3 diagnostic, never a gate judgment.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from acd.core.fab import (
    load_fab_profile,
    load_fab_profile_registry,
    resolve_fab_profile_path,
)
from acd.core.naming import artifact_prefix
from acd.pipeline.repository import repository_root
from acd.schema.design_graph import DesignGraph

EvidenceDeclarationCode = Literal[
    "evidence.cpl_rotation.declared_unverified",
    "evidence.fab_profile.declared_unverified",
]


@dataclass(frozen=True)
class EvidenceDeclarationFinding:
    """One declared evidence attribute that does not resolve to a record."""

    code: EvidenceDeclarationCode
    node_id: str
    kind: str
    attr: str
    detail: str


def cpl_rotation_record_path(root: Path, graph_id: str, refdes: str) -> Path:
    """Return the expected measured CPL rotation record for a component."""
    return (
        root
        / "evidence"
        / f"{artifact_prefix(graph_id)}-cpl-orientation"
        / f"{refdes}.json"
    )


def check_cpl_rotation_record(
    path: Path, *, refdes: str, lcsc: str | None
) -> str | None:
    """Return None when the record resolves, else an English reason."""
    if not path.is_file():
        return f"record file is missing: {path}"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f"record is unreadable or not JSON: {exc}"
    if not isinstance(document, dict):
        return "record is not a JSON object"
    record_refdes = document.get("refdes")
    if record_refdes != refdes:
        return f"record refdes {record_refdes!r} does not match declared {refdes!r}"
    record_lcsc = document.get("lcsc")
    if lcsc is not None and isinstance(record_lcsc, str) and record_lcsc != lcsc:
        return (
            f"record lcsc {record_lcsc!r} does not match declared {lcsc!r}"
        )
    response = document.get("response")
    if not isinstance(response, dict):
        return "record has no response object"
    canonical = json.dumps(
        response, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    expected_hash = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    if document.get("response_canonical_sha256") != expected_hash:
        return "response_canonical_sha256 does not match the recomputed hash"
    retrieved_at = document.get("retrieved_at")
    if not isinstance(retrieved_at, str) or not retrieved_at:
        return "retrieved_at is missing"
    try:
        datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    except ValueError:
        return f"retrieved_at {retrieved_at!r} is not an ISO-8601 timestamp"
    return None


def check_fab_profile_declaration(
    *,
    fab_profile: str,
    profile_source: str,
    profile_fetched_at: str,
    sources: Sequence[Mapping[str, object]],
) -> str | None:
    """Return None when some profile source matches the declared pair."""
    available = [
        (source.get("url"), source.get("fetched_at")) for source in sources
    ]
    for url, fetched_at in available:
        if url == profile_source and fetched_at == profile_fetched_at:
            return None
    rendered = ", ".join(f"({url!r}, {fetched_at!r})" for url, fetched_at in available)
    return (
        f"fab profile {fab_profile!r} declares profile_source "
        f"{profile_source!r} fetched at {profile_fetched_at!r}, but the loaded "
        f"profile sources are: {rendered or '<none>'}"
    )


def _cpl_rotation_findings(
    graph: DesignGraph, root: Path
) -> list[EvidenceDeclarationFinding]:
    findings: list[EvidenceDeclarationFinding] = []
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if node.kind != "electrical.component":
            continue
        if node.attrs.get("cpl_rotation_evidence_basis") != "confirmed":
            continue
        refdes_value = node.attrs.get("refdes")
        refdes = refdes_value if isinstance(refdes_value, str) else node.id
        lcsc_value = node.attrs.get("lcsc")
        lcsc = lcsc_value if isinstance(lcsc_value, str) else None
        record_path = cpl_rotation_record_path(root, graph.graph_id, refdes)
        reason = check_cpl_rotation_record(record_path, refdes=refdes, lcsc=lcsc)
        if reason is None:
            continue
        try:
            relative = record_path.relative_to(root)
        except ValueError:
            relative = record_path
        findings.append(
            EvidenceDeclarationFinding(
                code="evidence.cpl_rotation.declared_unverified",
                node_id=node.id,
                kind=node.kind,
                attr="cpl_rotation_evidence_basis",
                detail=(
                    f"{refdes}: cpl_orientation_evidence.evidence_basis "
                    f"'confirmed' does not resolve to a measured record "
                    f"({reason}); expected {relative}; fetch it with "
                    f"`scripts/fetch_lcsc_footprint_orientation.py "
                    f"--refdes {refdes} --lcsc {lcsc or '<lcsc>'} "
                    f"--out {relative}` inside the locked container, or "
                    f"declare evidence_basis 'estimated' (which stays unknown "
                    f"for the CPL gate)"
                ),
            )
        )
    return findings


def _fab_profile_findings(
    graph: DesignGraph, root: Path
) -> list[EvidenceDeclarationFinding]:
    findings: list[EvidenceDeclarationFinding] = []
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if node.kind != "fab.order_intent":
            continue
        fab_profile = node.attrs.get("fab_profile")
        profile_source = node.attrs.get("profile_source")
        profile_fetched_at = node.attrs.get("profile_fetched_at")
        if not (
            isinstance(fab_profile, str)
            and fab_profile
            and isinstance(profile_source, str)
            and profile_source
            and isinstance(profile_fetched_at, str)
            and profile_fetched_at
        ):
            # Absent or non-string declarations are reported by the
            # missing-attribute path of the lane preflight instead.
            continue
        try:
            registry = load_fab_profile_registry(
                root / "profiles" / "fab-profile-registry.json"
            )
            profile_path = resolve_fab_profile_path(fab_profile, registry)
            profile = load_fab_profile(profile_path)
        except (ValueError, OSError) as exc:
            findings.append(
                EvidenceDeclarationFinding(
                    code="evidence.fab_profile.declared_unverified",
                    node_id=node.id,
                    kind=node.kind,
                    attr="fab_profile",
                    detail=(
                        f"fab.order_intent profile {fab_profile!r} cannot be "
                        f"resolved: {exc}; declare a registered profile id or "
                        f"add the profile under `profiles/` with recorded "
                        f"sources"
                    ),
                )
            )
            continue
        sources = cast(Sequence[Mapping[str, object]], profile.data.get("sources", []))
        reason = check_fab_profile_declaration(
            fab_profile=fab_profile,
            profile_source=profile_source,
            profile_fetched_at=profile_fetched_at,
            sources=sources,
        )
        if reason is None:
            continue
        findings.append(
            EvidenceDeclarationFinding(
                code="evidence.fab_profile.declared_unverified",
                node_id=node.id,
                kind=node.kind,
                attr="profile_fetched_at",
                detail=(
                    f"{reason}; update `profile_source`/`profile_fetched_at` "
                    f"to one of the recorded sources, or re-record the fab "
                    f"profile with the fetched source"
                ),
            )
        )
    return findings


def collect_evidence_declaration_findings(
    graph: DesignGraph, *, root: Path | None = None
) -> list[EvidenceDeclarationFinding]:
    """Report declared evidence attributes without a resolving record."""
    resolved_root = root if root is not None else repository_root()
    return [
        *_cpl_rotation_findings(graph, resolved_root),
        *_fab_profile_findings(graph, resolved_root),
    ]


__all__ = [
    "EvidenceDeclarationCode",
    "EvidenceDeclarationFinding",
    "check_cpl_rotation_record",
    "check_fab_profile_declaration",
    "collect_evidence_declaration_findings",
    "cpl_rotation_record_path",
]
