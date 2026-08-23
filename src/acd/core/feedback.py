"""Deterministic proposals for applying physical measurements to design inputs."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile

from acd.core.rationale import (
    RATIONALE_EXEMPT_ATTRS,
    REQUIRED_RATIONALE_ATTRS,
    subject_hash_for,
)
from acd.schema.common import Sha256, canonical_json_sha256
from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.evidence import PhysicalEvidence
from acd.schema.feedback import (
    AppliedFeedbackValidationReport,
    FeedbackApplyPolicy,
    FeedbackPolicy,
    FeedbackProposal,
    FeedbackProposalItem,
)
from acd.schema.rationale import RationaleDocument


class FeedbackError(ValueError):
    """Raised when feedback inputs cannot produce a fail-closed proposal."""


def apply_input_feedback(
    proposal: FeedbackProposal,
    policy: FeedbackApplyPolicy,
    *,
    repository: Path,
    dry_run: bool = False,
    record_path: Path | None = None,
) -> dict[str, object]:
    """Apply a validated proposal atomically, never granting gate authority."""
    if proposal.status != "pass" or not proposal.applicable:
        raise FeedbackError("feedback proposal is not applicable")
    if proposal.graph_id != policy.graph_id or proposal.revision != policy.revision:
        raise FeedbackError("feedback proposal and apply policy do not match")
    policy_rules = {(rule.node_id, rule.attr): rule for rule in policy.rules}
    changed = [item for item in proposal.items if item.status == "proposed"]
    if any((item.node_id, item.attr) not in policy_rules for item in changed):
        raise FeedbackError("feedback proposal target is outside apply whitelist")
    paths = [(repository / path).resolve() for path in policy.input_paths]
    if not paths:
        raise FeedbackError("feedback apply policy has no input paths")
    originals: dict[Path, bytes] = {}
    documents: dict[Path, dict[str, object]] = {}
    graph_path = next((path for path in paths if path.name == "graph.json"), None)
    if graph_path is None:
        raise FeedbackError("feedback apply policy must include graph.json")
    try:
        for path in paths:
            data = path.read_bytes()
            originals[path] = data
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("input JSON root must be an object")
            documents[path] = value
        graph = DesignGraph.model_validate(documents[graph_path])
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FeedbackError("feedback input files are malformed") from exc
    if graph.graph_id != policy.graph_id or graph.revision != policy.revision:
        raise FeedbackError("feedback graph and apply policy do not match")
    nodes = {node.id: node for node in graph.nodes}
    graph_value = graph.model_dump(mode="json")
    graph_nodes = {node["id"]: node for node in graph_value["nodes"]}
    for item in changed:
        rule = policy_rules[(item.node_id, item.attr)]
        if item.difference < -rule.tolerance or item.difference > rule.tolerance:
            raise FeedbackError(f"feedback delta exceeds tolerance: {item.node_id}.{item.attr}")
        if not isinstance(item.proposed_value, (int, float)) or isinstance(
            item.proposed_value, bool
        ):
            raise FeedbackError("feedback proposed value is not numeric")
        value = float(item.proposed_value)
        if rule.minimum is not None and value < rule.minimum:
            raise FeedbackError(f"feedback value is below bound: {item.node_id}.{item.attr}")
        if rule.maximum is not None and value > rule.maximum:
            raise FeedbackError(f"feedback value exceeds bound: {item.node_id}.{item.attr}")
        if item.node_id not in nodes:
            raise FeedbackError("feedback target node is missing")
        attrs = graph_nodes[item.node_id]["attrs"]
        if item.attr not in attrs or attrs[item.attr] != item.current_value:
            raise FeedbackError("feedback current value does not match input")
        attrs[item.attr] = item.proposed_value
    updated_bytes = (
        json.dumps(graph_value, ensure_ascii=False, indent=2, sort_keys=True).encode()
        + b"\n"
    )
    before_hashes = {
        str(path): "sha256:" + hashlib.sha256(data).hexdigest()
        for path, data in originals.items()
    }
    after_hashes = dict(before_hashes)
    after_hashes[str(graph_path)] = "sha256:" + hashlib.sha256(updated_bytes).hexdigest()
    record: dict[str, object] = {
        "schema_version": 1,
        "record_class": "L3",
        "pass_evidence": False,
        "dry_run": dry_run,
        "graph_id": policy.graph_id,
        "revision": policy.revision,
        "before_sha256": before_hashes,
        "after_sha256": after_hashes,
        "changed_targets": [f"{item.node_id}.{item.attr}" for item in changed],
    }
    record["content_sha256"] = canonical_json_sha256(record)
    if not dry_run:
        staged: dict[Path, Path] = {}
        replaced: list[Path] = []
        try:
            for path, original in originals.items():
                content = updated_bytes if path == graph_path else original
                with NamedTemporaryFile("wb", dir=path.parent, delete=False) as temp:
                    temp.write(content)
                    temp.flush()
                    staged[path] = Path(temp.name)
            for path in paths:
                staged[path].replace(path)
                replaced.append(path)
        except (OSError, ValueError) as exc:
            for path in replaced:
                try:
                    with NamedTemporaryFile("wb", dir=path.parent, delete=False) as temp:
                        temp.write(originals[path])
                        temp.flush()
                        Path(temp.name).replace(path)
                except OSError:
                    pass
            raise FeedbackError("feedback update rolled back") from exc
        finally:
            for temporary in staged.values():
                with suppress(OSError):
                    temporary.unlink()
    if record_path is not None:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return record


def _unknown_proposal(reason: str) -> FeedbackProposal:
    return FeedbackProposal(
        status="unknown",
        graph_id="unknown",
        revision="unknown",
        input_hash="unknown",
        output_hash="unknown",
        error=reason,
    )


def _rationale_covers(
    graph: DesignGraph,
    rationale: RationaleDocument,
    node_id: str,
    attr: str,
) -> bool:
    expected_subject_hash: Sha256
    for record in rationale.records:
        if node_id not in record.subject_nodes or attr not in record.subject_attrs:
            continue
        try:
            expected_subject_hash = subject_hash_for(
                graph, record.subject_nodes, record.subject_attrs
            )
        except KeyError:
            continue
        if record.supports_coverage(graph.revision, expected_subject_hash):
            return True
    return False


def _evidence_measurement(
    evidences: Iterable[PhysicalEvidence],
    measurement_name: str,
) -> tuple[PhysicalEvidence, float] | None:
    matches: list[tuple[PhysicalEvidence, float]] = []
    for evidence in evidences:
        for measurement in evidence.measurements:
            if measurement.name == measurement_name:
                matches.append((evidence, measurement.value))
    if len(matches) != 1:
        return None
    return matches[0]


def _classification_is_known(node: GraphNode, attr: str) -> bool:
    return (
        attr in REQUIRED_RATIONALE_ATTRS.get(node.kind, frozenset())
        or attr in RATIONALE_EXEMPT_ATTRS.get(node.kind, {})
    )


def _proposal_output_hash(proposal: FeedbackProposal) -> Sha256:
    value = proposal.model_dump(mode="json")
    value["output_hash"] = "unknown"
    return canonical_json_sha256(value)


def propose_input_feedback(
    graph: DesignGraph,
    rationale: RationaleDocument,
    evidences: list[PhysicalEvidence],
    policy: FeedbackPolicy,
) -> FeedbackProposal:
    """Create a deterministic proposal without mutating the design graph."""
    if policy.graph_id != graph.graph_id:
        return _unknown_proposal("feedback policy graph_id does not match graph")
    if policy.revision != graph.revision:
        return _unknown_proposal("feedback policy revision does not match graph")
    if rationale.graph_id != graph.graph_id or rationale.revision != graph.revision:
        return _unknown_proposal("rationale document does not match graph")
    evidence_ids = [evidence.evidence_id for evidence in evidences]
    if len(set(evidence_ids)) != len(evidence_ids):
        return _unknown_proposal("evidence_id entries must be unique")
    for evidence in evidences:
        if (
            evidence.status != "valid"
            or evidence.target_revision != graph.revision
            or not evidence.supports_measured_claim(graph.revision)
        ):
            return _unknown_proposal(
                f"evidence is not a valid measured claim: {evidence.evidence_id}"
            )

    graph_nodes = {node.id: node for node in graph.nodes}
    items: list[FeedbackProposalItem] = []
    for rule in policy.rules:
        node = graph_nodes.get(rule.node_id)
        if node is None:
            return _unknown_proposal(f"feedback target node is missing: {rule.node_id}")
        if rule.attr not in node.attrs:
            return _unknown_proposal(
                f"feedback target attribute is missing: {rule.node_id}.{rule.attr}"
            )
        if not _classification_is_known(node, rule.attr):
            return _unknown_proposal(
                f"feedback target attribute is unclassified: {rule.node_id}.{rule.attr}"
            )
        match = _evidence_measurement(evidences, rule.measurement_name)
        if match is None:
            return _unknown_proposal(
                f"feedback measurement is missing or ambiguous: {rule.measurement_name}"
            )
        evidence, measured_value = match
        if not math.isfinite(measured_value):
            return _unknown_proposal(
                f"feedback measurement is not finite: {rule.measurement_name}"
            )
        current_value = node.attrs[rule.attr]
        if isinstance(current_value, bool) or not isinstance(
            current_value, (int, float)
        ):
            return _unknown_proposal(
                f"feedback target attribute is not numeric: {rule.node_id}.{rule.attr}"
            )
        difference = measured_value - float(current_value)
        changed = abs(difference) > rule.tolerance
        proposed_value = (
            measured_value if rule.rule_kind == "set_value" else current_value
        )
        rationale_required = (
            changed
            and rule.attr in REQUIRED_RATIONALE_ATTRS.get(node.kind, frozenset())
            and not _rationale_covers(graph, rationale, rule.node_id, rule.attr)
        )
        items.append(
            FeedbackProposalItem(
                rule_id=rule.rule_id,
                status="proposed" if changed else "no_change",
                node_id=rule.node_id,
                attr=rule.attr,
                current_value=current_value,
                measured_value=measured_value,
                proposed_value=proposed_value,
                difference=difference,
                evidence_id=evidence.evidence_id,
                measurement_name=rule.measurement_name,
                decision_kind=rule.decision_kind,
                rationale_required=rationale_required,
            )
        )

    input_hash = canonical_json_sha256(
        {
            "graph": graph.model_dump(mode="json"),
            "rationale": rationale.model_dump(mode="json"),
            "evidences": [
                evidence.model_dump(mode="json")
                for evidence in sorted(evidences, key=lambda item: item.evidence_id)
            ],
            "policy": policy.model_dump(mode="json"),
        }
    )
    proposal = FeedbackProposal(
        status="pass",
        graph_id=graph.graph_id,
        revision=graph.revision,
        input_hash=input_hash,
        output_hash="unknown",
        applicable=not any(item.rationale_required for item in items),
        items=items,
    )
    return proposal.model_copy(update={"output_hash": _proposal_output_hash(proposal)})


def validate_applied_feedback(
    original_graph: DesignGraph,
    updated_graph: DesignGraph,
    proposal: FeedbackProposal,
) -> AppliedFeedbackValidationReport:
    """Verify that an updated graph contains only declared proposal changes."""
    if proposal.status == "unknown":
        return AppliedFeedbackValidationReport(
            status="unknown", reason="feedback proposal is unknown"
        )
    if not proposal.applicable:
        return AppliedFeedbackValidationReport(
            status="fail", reason="feedback proposal requires rationale review"
        )
    if (
        proposal.graph_id != original_graph.graph_id
        or proposal.graph_id != updated_graph.graph_id
        or proposal.revision != original_graph.revision
        or proposal.revision != updated_graph.revision
    ):
        return AppliedFeedbackValidationReport(
            status="fail", reason="feedback proposal and graph revisions do not match"
        )
    original_nodes = {node.id: node for node in original_graph.nodes}
    updated_nodes = {node.id: node for node in updated_graph.nodes}
    if set(original_nodes) != set(updated_nodes):
        return AppliedFeedbackValidationReport(
            status="fail", reason="updated graph changed its node set"
        )
    allowed: dict[tuple[str, str], object] = {}
    for item in proposal.items:
        original_node = original_nodes.get(item.node_id)
        if original_node is None or item.attr not in original_node.attrs:
            return AppliedFeedbackValidationReport(
                status="fail", reason="proposal targets an unknown graph attribute"
            )
        if item.current_value != original_node.attrs[item.attr]:
            return AppliedFeedbackValidationReport(
                status="fail", reason="proposal current value does not match graph"
            )
        if item.status != "proposed":
            continue
        key = (item.node_id, item.attr)
        if key in allowed:
            return AppliedFeedbackValidationReport(
                status="fail", reason="proposal contains duplicate target items"
            )
        allowed[key] = item.proposed_value
    for node_id, original in original_nodes.items():
        updated = updated_nodes[node_id]
        if original.kind != updated.kind or original.depends_on != updated.depends_on:
            return AppliedFeedbackValidationReport(
                status="fail", reason=f"updated graph changed node structure: {node_id}"
            )
        if set(original.attrs) != set(updated.attrs):
            return AppliedFeedbackValidationReport(
                status="fail", reason=f"updated graph changed attributes: {node_id}"
            )
        for attr, original_value in original.attrs.items():
            expected = allowed.get((node_id, attr), original_value)
            if updated.attrs[attr] != expected:
                return AppliedFeedbackValidationReport(
                    status="fail",
                    reason=f"unexpected updated graph difference: {node_id}.{attr}",
                )
    return AppliedFeedbackValidationReport(status="pass")
