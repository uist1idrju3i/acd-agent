"""Design predicate and DFM report loading for quality documents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from acd.schema.design_graph import DesignGraph
from product_doc_inputs.common import (
    load_json_object,
    require_list,
    require_object,
    require_str,
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
            for entry in require_list(observation.get("predicates"), field="observation.predicates")
        )
    )
    return DesignPredicates(
        target_revision=require_str(data.get("target_revision"), field="target_revision"),
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
            rule_id=require_str(item.get("rule_id"), field="checks_not_implemented[].rule_id"),
            message=require_str(item.get("reason"), field="checks_not_implemented[].reason"),
        )
        for item in (
            require_object(entry, field="checks_not_implemented[]")
            for entry in require_list(
                data.get("checks_not_implemented"), field="checks_not_implemented"
            )
        )
    )
    return DfmReport(
        target_revision=require_str(data.get("target_revision"), field="target_revision"),
        status=require_str(data.get("status"), field="status"),
        profile_id=require_str(data.get("profile_id"), field="profile_id"),
        findings=findings,
        unknowns=unknowns,
        checks_not_implemented=checks_not_implemented,
    )
