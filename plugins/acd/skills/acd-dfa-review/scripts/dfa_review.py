# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@5ef3cbc14db5e30d65fc47a51aca475b8298f890",
# ]
# ///
"""Derive deterministic design-for-assembly review observations."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.dfa_review import (
    DfaAspect,
    DfaFinding,
    DfaReviewReport,
    DfaSeverity,
)

TOOL_VERSION = "acd-dfa-review/0.1.0"
RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "dfa_rules.json"


class DfaReviewInputError(ValueError):
    """Raised when a DFA review input is unreadable or malformed."""


def load_graph(path: Path) -> DesignGraph:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return DesignGraph.model_validate(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise DfaReviewInputError(f"graph {path} is not valid: {exc}") from exc


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _components(graph: DesignGraph) -> list[GraphNode]:
    return sorted(
        (node for node in graph.nodes if node.kind == "electrical.component"),
        key=lambda node: node.id,
    )


def _body_by_component(graph: DesignGraph) -> dict[str, GraphNode]:
    result: dict[str, GraphNode] = {}
    for node in graph.nodes:
        if node.kind != "mechanical.component_body":
            continue
        for dependency in node.depends_on:
            result[dependency] = node
    return result


def _finding(
    number: int,
    aspect: DfaAspect,
    severity: DfaSeverity,
    basis: str,
    subjects: Sequence[str] = (),
    *,
    unknown_reason: str | None = None,
) -> DfaFinding:
    status = "unknown" if unknown_reason is not None else "observed"
    return DfaFinding(
        finding_id=f"DFA-{number:03d}",
        aspect=aspect,
        severity=severity,
        status=status,
        subject_node_ids=sorted(set(subjects)),
        basis=basis,
        unknown_reason=unknown_reason,
    )


def _orientation_finding(graph: DesignGraph, number: int) -> DfaFinding:
    polarized = [
        node
        for node in _components(graph)
        if node.attrs.get("cpl_rotation_polarized") is True
    ]
    if not polarized:
        return _finding(
            number,
            "orientation_uniformity",
            "info",
            "No component declares cpl_rotation_polarized=true.",
        )
    missing = [
        node.id
        for node in polarized
        if _number(node.attrs.get("placement_rotation_deg")) is None
        or _number(node.attrs.get("cpl_rotation_offset_deg")) is None
    ]
    if missing:
        return _finding(
            number,
            "orientation_uniformity",
            "info",
            "Polarized component rotation is not fully declared; "
            f"missing placement_rotation_deg or cpl_rotation_offset_deg for {', '.join(missing)}.",
            missing,
            unknown_reason="polarized component rotation is not fully declared",
        )
    rotations = {
        node.id: (
            float(cast(float | int, node.attrs["placement_rotation_deg"])),
            float(cast(float | int, node.attrs["cpl_rotation_offset_deg"])),
            _text(node.attrs.get("footprint")) or "unknown-footprint",
        )
        for node in polarized
    }
    values = {(placement, offset) for placement, offset, _ in rotations.values()}
    subjects = [node.id for node in polarized]
    families = sorted({family for _, _, family in rotations.values()})
    if len(values) > 1:
        details = ", ".join(
            f"{node_id}={placement:g}+{offset:g}deg"
            for node_id, (placement, offset, _) in sorted(rotations.items())
        )
        return _finding(
            number,
            "orientation_uniformity",
            "advisory",
            "Polarized footprint families "
            f"{', '.join(families)} have non-uniform declared placement_rotation_deg "
            f"and cpl_rotation_offset_deg: {details}.",
            subjects,
        )
    return _finding(
        number,
        "orientation_uniformity",
        "info",
        "Polarized footprint families "
        f"{', '.join(families)} use the same declared placement_rotation_deg and "
        "cpl_rotation_offset_deg.",
        subjects,
    )


def _single_side_finding(
    graph: DesignGraph, body_by_component: Mapping[str, GraphNode], number: int
) -> DfaFinding:
    components = _components(graph)
    sides: dict[str, str] = {}
    for component in components:
        side = _text(component.attrs.get("side")) or _text(component.attrs.get("layer"))
        if side is None:
            body = body_by_component.get(component.id)
            side = _text(body.attrs.get("mounting_side")) if body else None
        if side is None:
            return _finding(
                number,
                "single_side_assembly",
                "info",
                "Component side/layer is not declared for "
                f"{component.id}; mounting_side on its component body was also absent.",
                [component.id],
                unknown_reason="component side/layer not declared",
            )
        sides[component.id] = side
    unique_sides = sorted(set(sides.values()))
    if len(unique_sides) > 1:
        return _finding(
            number,
            "single_side_assembly",
            "advisory",
            "Declared component sides include "
            f"{', '.join(unique_sides)}; double-sided assembly increases reflow passes.",
            sorted(sides),
        )
    return _finding(
        number,
        "single_side_assembly",
        "info",
        f"All declared component mounting_side values are {unique_sides[0]}.",
        sorted(sides),
    )


def _hand_solder_finding(
    graph: DesignGraph, body_by_component: Mapping[str, GraphNode], number: int
) -> DfaFinding:
    components = _components(graph)
    if not any("assembly" in node.attrs for node in components):
        return _finding(
            number,
            "hand_solder_access",
            "info",
            "No electrical component declares the assembly method required to identify "
            "hand-solder or THT work.",
            unknown_reason="component assembly method is not declared",
        )
    assembly_values = {
        (_text(node.attrs.get("assembly")) or "").lower() for node in components
    }
    if not assembly_values or not any(
        value in {"smt", "smd", "tht", "hand", "hand_solder", "press_fit"}
        for value in assembly_values
    ):
        return _finding(
            number,
            "hand_solder_access",
            "info",
            "Electrical component assembly values do not identify SMT or hand-solder "
            "classification.",
            unknown_reason="hand-solder assembly classification is not declared",
        )
    hand_components = [
        node
        for node in components
        if (_text(node.attrs.get("assembly")) or "").lower()
        in {"tht", "hand", "hand_solder", "press_fit"}
    ]
    if not hand_components:
        return _finding(
            number,
            "hand_solder_access",
            "info",
            "No electrical component declares assembly as tht, hand, hand_solder, or press_fit.",
        )
    try:
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        threshold = _number(rules["hand_solder_clearance_mm"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        threshold = None
    if threshold is None:
        return _finding(
            number,
            "hand_solder_access",
            "info",
            "The hand-solder clearance rule is unavailable.",
            [node.id for node in hand_components],
            unknown_reason="hand-solder clearance rule is unavailable",
        )
    component_by_id = {node.id: node for node in components}
    missing_geometry: list[str] = []
    rectangles: dict[str, tuple[float, float, float, float]] = {}
    for node in components:
        body = body_by_component.get(node.id)
        width = _number(body.attrs.get("width_mm")) if body else None
        height = _number(body.attrs.get("height_mm")) if body else None
        x = _number(node.attrs.get("placement_x_mm"))
        y = _number(node.attrs.get("placement_y_mm"))
        rotation = _number(node.attrs.get("placement_rotation_deg"))
        if body is not None:
            x = x if x is not None else _number(body.attrs.get("x_mm"))
            y = y if y is not None else _number(body.attrs.get("y_mm"))
            rotation = (
                rotation
                if rotation is not None
                else _number(body.attrs.get("rotation_deg"))
            )
        if width is None or height is None or x is None or y is None or rotation is None:
            continue
        if round(rotation) % 180 == 90:
            width, height = height, width
        rectangles[node.id] = (x, y, width, height)
    for node in hand_components:
        if node.id not in rectangles:
            missing_geometry.append(node.id)
    if missing_geometry:
        return _finding(
            number,
            "hand_solder_access",
            "info",
            "Hand-solder component body geometry or placement is missing for "
            + ", ".join(missing_geometry)
            + f"; declared clearance threshold is {threshold:g} mm.",
            missing_geometry,
            unknown_reason="hand-solder component geometry is not declared",
        )
    closest: dict[str, tuple[float, str]] = {}
    for node in hand_components:
        x, y, width, height = rectangles[node.id]
        neighbors = [
            neighbor
            for neighbor in component_by_id
            if neighbor != node.id and neighbor in rectangles
        ]
        if not neighbors:
            return _finding(
                number,
                "hand_solder_access",
                "info",
                f"Hand-solder component {node.id} has no neighboring component body "
                "with declared placement and geometry.",
                [node.id],
                unknown_reason="neighbor component geometry is not declared",
            )
        for neighbor in neighbors:
            nx, ny, nwidth, nheight = rectangles[neighbor]
            gap_x = max(abs(x - nx) - (width + nwidth) / 2.0, 0.0)
            gap_y = max(abs(y - ny) - (height + nheight) / 2.0, 0.0)
            clearance = math.hypot(gap_x, gap_y)
            if node.id not in closest or clearance < closest[node.id][0]:
                closest[node.id] = (clearance, neighbor)
    below = [
        (node_id, clearance, neighbor)
        for node_id, (clearance, neighbor) in closest.items()
        if clearance < threshold
    ]
    if below:
        details = ", ".join(
            f"{node_id}={clearance:g}mm to {neighbor}"
            for node_id, clearance, neighbor in sorted(below)
        )
        return _finding(
            number,
            "hand_solder_access",
            "advisory",
            f"Declared nearest-body clearances are below the {threshold:g} mm "
            f"hand-solder keep-out threshold: {details}.",
            [node_id for node_id, _, _ in below],
        )
    details = ", ".join(
        f"{node_id}={clearance:g}mm to {neighbor}"
        for node_id, (clearance, neighbor) in sorted(closest.items())
    )
    return _finding(
        number,
        "hand_solder_access",
        "info",
        f"Declared nearest-body clearances meet the {threshold:g} mm "
        f"hand-solder keep-out threshold: {details}.",
        [node.id for node in hand_components],
    )


def _connector_finding(graph: DesignGraph, number: int) -> DfaFinding:
    nodes = {node.id: node for node in graph.nodes}
    connectors = [
        node
        for node in _components(graph)
        if (_text(node.attrs.get("refdes")) or "").upper().startswith("J")
        or "connector" in (_text(node.attrs.get("footprint")) or "").lower()
    ]
    openings = [node for node in graph.nodes if node.kind == "mechanical.connector_opening"]
    opening_components: dict[str, list[str]] = {}
    for opening in openings:
        references = list(opening.depends_on)
        explicit = _text(opening.attrs.get("component_id")) or _text(
            opening.attrs.get("connector_component_id")
        )
        if explicit is not None:
            references.append(explicit)
        for reference in references:
            if reference not in nodes or nodes[reference].kind != "electrical.component":
                return _finding(
                    number,
                    "connector_cable_order",
                    "stop_recommendation",
                    f"Connector opening {opening.id} references missing component {reference}.",
                    [opening.id],
                )
            opening_components.setdefault(reference, []).append(opening.id)
    if not connectors:
        return _finding(
            number,
            "connector_cable_order",
            "info",
            "No connector component is declared by refdes or connector footprint.",
        )
    without_opening = [node.id for node in connectors if node.id not in opening_components]
    if without_opening:
        return _finding(
            number,
            "connector_cable_order",
            "advisory",
            "Connector(s) "
            + ", ".join(without_opening)
            + " have no declared enclosure opening; cable attachment after "
            "assembly is not defined.",
            without_opening,
        )
    details = "; ".join(
        f"{component_id}: openings {', '.join(sorted(opening_components[component_id]))}"
        for component_id in sorted(opening_components)
    )
    return _finding(
        number,
        "connector_cable_order",
        "info",
        "Install the board before closing the enclosure; declared connector openings: "
        + details
        + ".",
        sorted(opening_components),
    )


def _enclosure_finding(graph: DesignGraph, number: int) -> DfaFinding:
    enclosures = [node for node in graph.nodes if node.kind == "mechanical.enclosure"]
    if not enclosures:
        return _finding(
            number,
            "enclosure_assembly_effort",
            "info",
            "No mechanical.enclosure node is declared.",
            unknown_reason="enclosure assembly declaration is absent",
        )
    declared: list[str] = []
    for enclosure in enclosures:
        for key in (
            "lid",
            "screw_count",
            "screws",
            "snap_count",
            "snap_fits",
            "fastener_count",
        ):
            if key in enclosure.attrs:
                declared.append(f"{enclosure.id}.{key}={enclosure.attrs[key]!r}")
    if not declared:
        return _finding(
            number,
            "enclosure_assembly_effort",
            "info",
            "Enclosure node(s) "
            + ", ".join(node.id for node in enclosures)
            + " do not declare lid, screw, snap, or fastener counts.",
            [node.id for node in enclosures],
            unknown_reason="enclosure assembly effort attributes are not declared",
        )
    return _finding(
        number,
        "enclosure_assembly_effort",
        "info",
        "Declared enclosure assembly inputs: " + ", ".join(sorted(declared)) + ".",
        [node.id for node in enclosures],
    )


def _fixture_finding(graph: DesignGraph, number: int) -> DfaFinding:
    components = _components(graph)
    overhangs = [node for node in graph.nodes if node.kind == "mechanical.board_edge_overhang"]
    polarized = [
        node for node in components if node.attrs.get("cpl_rotation_polarized") is True
    ]
    tht = [
        node
        for node in components
        if (_text(node.attrs.get("assembly")) or "").lower()
        in {"tht", "hand", "hand_solder", "press_fit"}
    ]
    subjects = sorted({node.id for node in polarized + tht + overhangs})
    if polarized and overhangs:
        return _finding(
            number,
            "fixture_required",
            "advisory",
            "Polarity or board-edge constraints are declared: "
            f"cpl_rotation_polarized={[node.id for node in polarized]} and "
            f"board_edge_overhang={[node.id for node in overhangs]}; "
            "a polarity/edge fixture is recommended.",
            subjects,
        )
    if tht or overhangs:
        return _finding(
            number,
            "fixture_required",
            "advisory",
            "THT/hand-solder or board-edge assembly constraints are declared: "
            f"components={[node.id for node in tht]}, overhangs={[node.id for node in overhangs]}; "
            "a fixture is recommended.",
            subjects,
        )
    return _finding(
        number,
        "fixture_required",
        "info",
        "No THT/hand-solder component or board-edge overhang requiring a fixture is declared.",
    )


def review_dfa(
    graph: DesignGraph, placement: Mapping[str, object] | None = None
) -> DfaReviewReport:
    """Review DFA aspects without changing any authoritative gate."""
    del placement
    body_by_component = _body_by_component(graph)
    findings = [
        _orientation_finding(graph, 1),
        _single_side_finding(graph, body_by_component, 2),
        _hand_solder_finding(graph, body_by_component, 3),
        _connector_finding(graph, 4),
        _enclosure_finding(graph, 5),
        _fixture_finding(graph, 6),
    ]
    return DfaReviewReport(
        graph_id=graph.graph_id,
        revision=graph.revision,
        findings=findings,
        input_hash="sha256:" + "0" * 64,
        tool_version=TOOL_VERSION,
    )


def _with_input_hash(
    report: DfaReviewReport, graph_path: Path, placement_path: Path | None
) -> DfaReviewReport:
    import hashlib

    graph_bytes = graph_path.read_bytes()
    placement_bytes = b"" if placement_path is None else placement_path.read_bytes()
    encoded = graph_bytes + b"\0" + placement_bytes
    return report.model_copy(
        update={"input_hash": "sha256:" + hashlib.sha256(encoded).hexdigest()}
    )


def render_markdown(report: DfaReviewReport) -> str:
    lines = [
        "# DFAレビュー",
        "",
        "この資料はL2所見であり、設計ゲートの合否やEvidenceではない。",
        "",
        f"- graph: `{report.graph_id}`",
        f"- revision: `{report.revision}`",
        f"- input hash: `{report.input_hash}`",
        "",
        "| 観点 | 重大度 | 状態 | 対象 | 根拠 | unknown理由 |",
        "|---|---|---|---|---|---|",
    ]
    for finding in report.findings:
        lines.append(
            "| "
            + " | ".join(
                [
                    finding.aspect,
                    finding.severity,
                    finding.status,
                    ", ".join(finding.subject_node_ids) or "—",
                    finding.basis.replace("|", "\\|"),
                    finding.unknown_reason or "—",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--placement-report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        graph = load_graph(args.graph)
        placement = None
        if args.placement_report is not None:
            try:
                placement = json.loads(
                    args.placement_report.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise DfaReviewInputError(
                    f"placement report is not valid: {exc}"
                ) from exc
            if not isinstance(placement, dict):
                raise DfaReviewInputError("placement report must be an object")
            placement = cast(dict[str, object], placement)
        report = _with_input_hash(
            review_dfa(graph, placement),
            args.graph,
            args.placement_report,
        )
        markdown = render_markdown(report)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "dfa-review.json").write_text(
            json.dumps(
                report.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (args.out / "dfa-review.md").write_text(markdown, encoding="utf-8")
        return 0
    except (DfaReviewInputError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"dfa review failed closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
