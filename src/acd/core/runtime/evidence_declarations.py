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
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from acd.core.knowledge.naming import artifact_prefix
from acd.core.manufacturing.fab import (
    load_fab_profile,
    load_fab_profile_registry,
    resolve_fab_profile_path,
)
from acd.core.manufacturing.lcsc_record import check_declared_mpn, extract_lcsc_identity
from acd.core.runtime.fileio import read_json
from acd.pipeline.repository import repository_root
from acd.schema.design_fixture import DesignFixtureSpec
from acd.schema.design_graph import DesignGraph
from acd.schema.lane_preflight import LanePreflightProducerGap

EvidenceDeclarationCode = Literal[
    "evidence.cpl_rotation.declared_unverified",
    "evidence.cpl_rotation.mpn_mismatch",
    "evidence.cpl_rotation.structural_copy",
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
    severity: Literal["stop", "warn"] = "stop"


def cpl_rotation_record_path(root: Path, graph_id: str, refdes: str) -> Path:
    """Return the expected measured CPL rotation record for a component."""
    return root / "evidence" / f"{artifact_prefix(graph_id)}-cpl-orientation" / f"{refdes}.json"


def check_cpl_rotation_record(path: Path, *, refdes: str, lcsc: str | None) -> str | None:
    """Return None when the record resolves, else an English reason."""
    if not path.is_file():
        return f"record file is missing: {path}"
    try:
        document = read_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f"record is unreadable or not JSON: {exc}"
    if not isinstance(document, dict):
        return "record is not a JSON object"
    record = cast(dict[str, Any], document)
    record_refdes = record.get("refdes")
    if record_refdes != refdes:
        return f"record refdes {record_refdes!r} does not match declared {refdes!r}"
    record_lcsc = record.get("lcsc")
    if lcsc is not None and isinstance(record_lcsc, str) and record_lcsc != lcsc:
        return f"record lcsc {record_lcsc!r} does not match declared {lcsc!r}"
    response = record.get("response")
    if not isinstance(response, dict):
        return "record has no response object"
    canonical = json.dumps(
        response, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    expected_hash = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    if record.get("response_canonical_sha256") != expected_hash:
        return "response_canonical_sha256 does not match the recomputed hash"
    retrieved_at = record.get("retrieved_at")
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
    available = [(source.get("url"), source.get("fetched_at")) for source in sources]
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
    graph: DesignGraph, root: Path, evidence_root: Path | None = None
) -> list[EvidenceDeclarationFinding]:
    findings: list[EvidenceDeclarationFinding] = []
    record_root = evidence_root if evidence_root is not None else root
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if node.kind != "electrical.component":
            continue
        if node.attrs.get("cpl_rotation_evidence_basis") != "confirmed":
            continue
        refdes_value = node.attrs.get("refdes")
        refdes = refdes_value if isinstance(refdes_value, str) else node.id
        lcsc_value = node.attrs.get("lcsc")
        lcsc = lcsc_value if isinstance(lcsc_value, str) else None
        record_path = cpl_rotation_record_path(record_root, graph.graph_id, refdes)
        reason = check_cpl_rotation_record(record_path, refdes=refdes, lcsc=lcsc)
        if reason is None:
            declared_mpn = node.attrs.get("mpn")
            if isinstance(declared_mpn, str) and declared_mpn:
                try:
                    record = read_json(record_path)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    record = None
                if isinstance(record, Mapping):
                    typed_record = cast(Mapping[str, object], record)
                    response_value = typed_record.get("response")
                    response = (
                        cast(Mapping[str, object], response_value)
                        if isinstance(response_value, Mapping)
                        else None
                    )
                    if isinstance(response, Mapping):
                        identity = extract_lcsc_identity(response)
                        mpn_check = check_declared_mpn(identity, declared_mpn=declared_mpn)
                        if mpn_check.state == "mismatch":
                            observed_part = identity.manufacturer_part or "<unknown>"
                            package = identity.package or "<unknown>"
                            findings.append(
                                EvidenceDeclarationFinding(
                                    code="evidence.cpl_rotation.mpn_mismatch",
                                    node_id=node.id,
                                    kind=node.kind,
                                    attr="mpn",
                                    detail=(
                                        f"declared mpn {declared_mpn!r} but record "
                                        f"{identity.supplier_part or '<unknown>'} "
                                        f"Manufacturer Part is "
                                        f"{observed_part!r} (package {package!r}); "
                                        "next: correct lcsc or mpn in the spec and "
                                        "re-fetch the record"
                                    ),
                                )
                            )
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


def _fab_profile_findings(graph: DesignGraph, root: Path) -> list[EvidenceDeclarationFinding]:
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
            registry = load_fab_profile_registry(root / "profiles" / "fab-profile-registry.json")
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


def _fixture_specs(root: Path, graph: DesignGraph) -> list[tuple[str, DesignFixtureSpec]]:
    """Load comparable fixture specs, excluding the current graph fixture."""
    fixtures_root = root / "fixtures"
    try:
        directories = sorted(path for path in fixtures_root.iterdir() if path.is_dir())
    except OSError:
        return []
    specs: list[tuple[str, DesignFixtureSpec]] = []
    for directory in directories:
        spec_path = directory / "spec.json"
        if not spec_path.is_file():
            continue
        try:
            spec = DesignFixtureSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if spec.graph_id == graph.graph_id:
            continue
        specs.append((directory.name, spec))
    return specs


def _structural_copy_findings(graph: DesignGraph, root: Path) -> list[EvidenceDeclarationFinding]:
    findings: list[EvidenceDeclarationFinding] = []
    other_fixtures = _fixture_specs(root, graph)
    if not other_fixtures:
        return findings
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if (
            node.kind != "electrical.component"
            or node.attrs.get("cpl_rotation_evidence_basis") != "estimated"
        ):
            continue
        refdes_value = node.attrs.get("refdes")
        refdes = refdes_value if isinstance(refdes_value, str) else node.id
        for fixture_name, spec in other_fixtures:
            matched_attr = next(
                (
                    attr
                    for attr in (
                        "cpl_rotation_evidence_note",
                        "cpl_rotation_evidence_revision",
                    )
                    if isinstance(node.attrs.get(attr), str)
                    and fixture_name.casefold() in cast(str, node.attrs[attr]).casefold()
                ),
                None,
            )
            if matched_attr is not None:
                findings.append(
                    EvidenceDeclarationFinding(
                        code="evidence.cpl_rotation.structural_copy",
                        node_id=node.id,
                        kind=node.kind,
                        attr=matched_attr,
                        detail=(
                            f"{refdes}: estimated CPL rotation evidence "
                            f"{matched_attr} mentions fixture "
                            f"'{fixture_name}'; this looks like a structural "
                            "copy — estimated stays unknown for the CPL gate; "
                            "re-derive the evidence from this design or fetch "
                            "a measured record"
                        ),
                        severity="warn",
                    )
                )
                continue
            current_at = node.attrs.get("cpl_rotation_evidence_at")
            current_method = node.attrs.get("cpl_rotation_evidence_method")
            current_note = node.attrs.get("cpl_rotation_evidence_note")
            if isinstance(current_at, str):
                with suppress(ValueError):
                    current_at = datetime.fromisoformat(
                        current_at.replace("Z", "+00:00")
                    ).isoformat()
            current_triple = (current_at, current_method, current_note)
            if not all(isinstance(value, str) and value for value in current_triple):
                continue
            for other_component in spec.components:
                evidence = other_component.cpl_orientation_evidence
                if evidence is None:
                    continue
                other_triple = (
                    evidence.evidence_at.isoformat(),
                    evidence.evidence_method,
                    evidence.evidence_note,
                )
                if current_triple != other_triple:
                    continue
                findings.append(
                    EvidenceDeclarationFinding(
                        code="evidence.cpl_rotation.structural_copy",
                        node_id=node.id,
                        kind=node.kind,
                        attr="cpl_rotation_evidence_note",
                        detail=(
                            f"{refdes}: estimated CPL rotation evidence "
                            "(at/method/note) is identical to fixture "
                            f"'{fixture_name}' component {other_component.refdes}; "
                            "this looks like a value transcription — estimated "
                            "stays unknown for the CPL gate; re-derive the "
                            "evidence from this design or fetch a measured "
                            "record"
                        ),
                        severity="warn",
                    )
                )
                break
    return findings


def collect_evidence_declaration_findings(
    graph: DesignGraph,
    *,
    root: Path | None = None,
    evidence_root: Path | None = None,
) -> list[EvidenceDeclarationFinding]:
    """Report declared evidence attributes without a resolving record."""
    resolved_root = root if root is not None else repository_root()
    return [
        *_cpl_rotation_findings(graph, resolved_root, evidence_root),
        *_fab_profile_findings(graph, resolved_root),
        *_structural_copy_findings(graph, resolved_root),
    ]


def collect_producer_gaps(
    graph: DesignGraph,
    *,
    root: Path | None = None,
    evidence_root: Path | None = None,
) -> list[LanePreflightProducerGap]:
    """Return deterministic acquisition gaps for declared provenance inputs."""
    resolved_root = root if root is not None else repository_root()
    record_root = evidence_root if evidence_root is not None else resolved_root
    gaps: list[LanePreflightProducerGap] = []
    for node in sorted(graph.nodes, key=lambda item: item.id):
        if (
            node.kind == "electrical.component"
            and node.attrs.get("cpl_rotation_evidence_basis") == "confirmed"
        ):
            refdes_value = node.attrs.get("refdes")
            refdes = refdes_value if isinstance(refdes_value, str) else node.id
            lcsc_value = node.attrs.get("lcsc")
            lcsc = lcsc_value if isinstance(lcsc_value, str) else None
            path = cpl_rotation_record_path(record_root, graph.graph_id, refdes)
            reason = check_cpl_rotation_record(path, refdes=refdes, lcsc=lcsc)
            if reason is not None:
                gaps.append(
                    LanePreflightProducerGap(
                        kind="cpl_orientation",
                        refdes=refdes,
                        lcsc=lcsc,
                        producer=(
                            "uv run python scripts/"
                            "fetch_lcsc_footprint_orientation.py"
                            f" --lcsc {lcsc or '<id>'} --refdes {refdes}"
                            " ... --out evidence/<design>-cpl-orientation/"
                        ),
                        detail=reason,
                    )
                )
        elif node.kind == "fab.order_intent":
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
                continue
            try:
                registry = load_fab_profile_registry(
                    resolved_root / "profiles" / "fab-profile-registry.json"
                )
                profile_path = resolve_fab_profile_path(fab_profile, registry)
                profile = load_fab_profile(profile_path)
                sources: list[dict[str, str | None]] = []
                for source in cast(Sequence[Mapping[str, object]], profile.data.get("sources", [])):
                    url = source.get("url")
                    fetched_at = source.get("fetched_at")
                    sources.append(
                        {
                            "url": url if isinstance(url, str) else None,
                            "fetched_at": (fetched_at if isinstance(fetched_at, str) else None),
                        }
                    )
            except (ValueError, OSError):
                continue
            if any(
                source["url"] == profile_source and source["fetched_at"] == profile_fetched_at
                for source in sources
            ):
                continue
            gaps.append(
                LanePreflightProducerGap(
                    kind="fab_profile",
                    profile_source=profile_source,
                    declared_fetched_at=profile_fetched_at,
                    loaded_sources=sources,
                    producer=(
                        "fab profile acquisition/re-recording producer "
                        "(no fetch script is currently present under scripts/)"
                    ),
                    detail=(
                        f"declared ({profile_source!r}, {profile_fetched_at!r}) "
                        f"does not match loaded sources {sources!r}"
                    ),
                )
            )
    return gaps


__all__ = [
    "EvidenceDeclarationCode",
    "EvidenceDeclarationFinding",
    "check_cpl_rotation_record",
    "check_fab_profile_declaration",
    "collect_evidence_declaration_findings",
    "collect_producer_gaps",
    "cpl_rotation_record_path",
]
