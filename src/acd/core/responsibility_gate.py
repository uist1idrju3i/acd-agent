"""Deterministic responsibility-assignment gate (ADR-0049 §7, roadmap 21.7).

The gate checks that every declared function has exactly one domain (unless a
SharedAssignmentContract permits more), that assigned domains are capable of
the declared function needs, and that every cross-domain dependency is matched
by an interface declared by both sides. The rationale coverage of the `domain`
attribute is enforced by the existing rationale coverage gate and is not
duplicated here. This gate emits gate evidence only; it creates no
authoritative Evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast, get_args

from acd.schema.design_graph import DesignGraph
from acd.schema.responsibility import (
    Assignment,
    DomainCapability,
    FunctionNeed,
    ResponsibilityCriterion,
    ResponsibilityDeclaration,
    ResponsibilityDomain,
    ResponsibilityFinding,
    ResponsibilityFindingCode,
    ResponsibilityGateResult,
)


class ResponsibilityGateError(ValueError):
    """Raised when a responsibility gate input cannot be loaded or validated."""


def load_responsibility_declaration(path: Path) -> ResponsibilityDeclaration:
    """Load the responsibility declaration; any failure is an error."""
    try:
        return ResponsibilityDeclaration.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ResponsibilityGateError(
            f"responsibility declaration {path} is not valid: {exc}"
        ) from exc


_DOMAINS = frozenset(get_args(ResponsibilityDomain))
_CRITERIA = frozenset(get_args(ResponsibilityCriterion))


def _finding(
    code: ResponsibilityFindingCode, subject: str, detail: str
) -> ResponsibilityFinding:
    return ResponsibilityFinding(code=code, subject=subject, detail=detail)


def _capability_conflicts(
    need: FunctionNeed, capability: DomainCapability
) -> list[tuple[str, str, str]]:
    """Return (code, field, detail) triples for one need/capability pair."""
    findings: list[tuple[str, str, str]] = []
    subject = need.function_id
    domain = capability.domain

    pairs: list[tuple[str, object, object]] = [
        ("gpio_count", need.gpio_count, capability.gpio_count),
        ("communication", need.communication, capability.communication),
        ("memory_kb", need.memory_kb, capability.memory_kb),
        ("power_source", need.power_source, capability.power_sources),
        ("motion", need.motion, capability.motion),
    ]
    for field, need_value, cap_value in pairs:
        if need_value == "unknown":
            findings.append(
                (
                    "unknown_state",
                    f"{subject}.{field}",
                    f"function {subject} declares {field} as unknown",
                )
            )
            continue
        if cap_value == "unknown":
            findings.append(
                (
                    "unknown_state",
                    f"{subject}.{field}",
                    f"domain {domain} declares {field} capability as unknown",
                )
            )
            continue
        conflict: str | None = None
        if field == "gpio_count" or field == "memory_kb":
            if (
                isinstance(need_value, int)
                and isinstance(cap_value, int)
                and need_value > cap_value
            ):
                conflict = (
                    f"{field} need {need_value} exceeds domain "
                    f"{domain} capability {cap_value}"
                )
        elif field == "communication":
            if isinstance(need_value, list) and isinstance(cap_value, list):
                need_list = cast(list[str], need_value)
                cap_list = cast(list[str], cap_value)
                missing = sorted(set(need_list) - set(cap_list))
                if missing:
                    conflict = (
                        f"communication {missing} not declared by domain "
                        f"{domain}"
                    )
        elif field == "power_source":
            if isinstance(cap_value, list) and need_value not in cap_value:
                conflict = (
                    f"power_source {need_value!r} not declared by domain "
                    f"{domain}"
                )
        elif (
            field == "motion" and need_value is True and cap_value is False
        ):
            conflict = f"domain {domain} declares no motion capability"
        if conflict is not None:
            findings.append(
                ("capability_conflict", f"{subject}.{field}", conflict)
            )
    return findings


def check_responsibility(
    graph: DesignGraph, declaration: ResponsibilityDeclaration
) -> ResponsibilityGateResult:
    """Run the deterministic responsibility-assignment gate."""
    findings: list[ResponsibilityFinding] = []
    assignments: list[Assignment] = []
    if (
        declaration.graph_id != graph.graph_id
        or declaration.revision != graph.revision
    ):
        findings.append(
            _finding(
                "graph_mismatch",
                declaration.graph_id,
                f"declaration targets {declaration.graph_id}@{declaration.revision}"
                f" but the graph is {graph.graph_id}@{graph.revision}",
            )
        )
        return ResponsibilityGateResult(
            graph_id=graph.graph_id,
            revision=graph.revision,
            status="fail",
            assignments=[],
            findings=findings,
        )

    needs = {item.function_id: item for item in declaration.functions}
    capabilities = {item.domain: item for item in declaration.capabilities}

    by_function: dict[
        str, list[tuple[str, ResponsibilityDomain, list[ResponsibilityCriterion]]]
    ] = {}
    for node in graph.nodes:
        if node.kind != "design.responsibility":
            continue
        function_id = node.attrs.get("function_id")
        domain = node.attrs.get("domain")
        criteria = node.attrs.get("criteria")
        if not isinstance(function_id, str) or not function_id:
            findings.append(
                _finding(
                    "invalid_function_id",
                    node.id,
                    f"node {node.id} lacks a function_id attribute",
                )
            )
            continue
        if not isinstance(domain, str) or domain not in _DOMAINS:
            findings.append(
                _finding(
                    "invalid_domain",
                    node.id,
                    f"node {node.id} domain {domain!r} is not a declared domain",
                )
            )
            continue
        if (
            not isinstance(criteria, list)
            or not criteria
            or any(item not in _CRITERIA for item in criteria)
        ):
            findings.append(
                _finding(
                    "invalid_criteria",
                    node.id,
                    f"node {node.id} criteria {criteria!r} are not valid",
                )
            )
            continue
        if function_id not in needs:
            findings.append(
                _finding(
                    "undeclared_function",
                    node.id,
                    f"function {function_id!r} is not a declared function need",
                )
            )
            continue
        typed_criteria = cast(list[ResponsibilityCriterion], list(criteria))
        typed_domain = cast(ResponsibilityDomain, domain)
        by_function.setdefault(function_id, []).append(
            (node.id, typed_domain, typed_criteria)
        )

    shared = {
        item.function_id: set(item.domains)
        for item in declaration.shared_assignments
    }
    for function_id in sorted(needs):
        entries = by_function.get(function_id, [])
        if not entries:
            findings.append(
                _finding(
                    "unassigned",
                    function_id,
                    f"function {function_id} has no design.responsibility node",
                )
            )
            continue
        if len(entries) > 1:
            assigned = {domain for _, domain, _ in entries}
            if shared.get(function_id) != assigned:
                findings.append(
                    _finding(
                        "multiple_assignment",
                        function_id,
                        f"function {function_id} is assigned to "
                        f"{sorted(assigned)} without a shared-assignment "
                        "contract",
                    )
                )
                continue
        for node_id, domain, criteria in entries:
            assignments.append(
                Assignment(
                    function_id=function_id,
                    domain=domain,
                    node_id=node_id,
                    criteria=criteria,
                )
            )
            capability = capabilities.get(domain)
            if capability is None:
                findings.append(
                    _finding(
                        "missing_capability",
                        function_id,
                        f"domain {domain} has no capability declaration",
                    )
                )
                continue
            need = needs[function_id]
            for code, subject, detail in _capability_conflicts(
                need, capability
            ):
                findings.append(
                    _finding(
                        cast("ResponsibilityFindingCode", code),
                        subject,
                        detail,
                    )
                )

    assigned_domains: dict[str, set[str]] = {
        function_id: {domain for _, domain, _ in entries}
        for function_id, entries in by_function.items()
    }
    for dependency in declaration.dependencies:
        left = assigned_domains.get(dependency.function_id)
        right = assigned_domains.get(dependency.depends_on)
        if not left or not right:
            continue
        for source in sorted(left):
            for target in sorted(right):
                if source == target:
                    continue
                pair = tuple(sorted((source, target)))
                if not any(
                    interface.domains == pair
                    for interface in declaration.interfaces
                ):
                    findings.append(
                        _finding(
                            "missing_interface",
                            f"{dependency.function_id}->{dependency.depends_on}",
                            f"dependency crosses domains {pair[0]}/{pair[1]} "
                            "without a declared interface",
                        )
                    )
    for interface in declaration.interfaces:
        if set(interface.declared_by) != set(interface.domains):
            findings.append(
                _finding(
                    "one_sided_interface",
                    interface.interface_id,
                    f"interface {interface.interface_id} is declared by "
                    f"{sorted(set(interface.declared_by))} but connects "
                    f"{list(interface.domains)}",
                )
            )

    findings.sort(key=lambda item: (item.code, item.subject))
    return ResponsibilityGateResult(
        graph_id=graph.graph_id,
        revision=graph.revision,
        status="pass" if not findings else "fail",
        assignments=assignments,
        findings=findings,
    )
