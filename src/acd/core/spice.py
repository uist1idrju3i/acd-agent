"""Deterministic graph-derived SPICE estimates and ngspice execution."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

from acd.core.electrical import (
    ComponentView,
    ElectricalLane,
    GraphExtractionError,
    extract_electrical_lane,
)
from acd.core.process import ExternalToolError, run_tool
from acd.schema import (
    DesignGraph,
    SpiceAnalysisRequest,
    SpiceCheck,
    SpiceLimit,
    SpiceResult,
    SpiceStatus,
    canonical_sha256,
)

SPICE_TOOL_VERSION = "45.2"
SPICE_FORMAT_VERSION = "1"
_VERSION_RE = re.compile(r"ngspice[-\s]+([0-9]+\.[0-9]+)", re.IGNORECASE)
_VALUE_RE = re.compile(
    r"^\s*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
    r"\s*(meg|g|k|m|u|n|p|f)?(?:[a-zΩ]+)?\s*$",
    re.IGNORECASE,
)
_MEASURE_RE = re.compile(
    r"\b([vi])\(\s*([^)]+?)\s*\)\s*=\s*"
    r"([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)",
    re.IGNORECASE,
)


class SpiceNetlistError(ValueError):
    """Raised when a graph cannot produce a trustworthy SPICE netlist."""


@dataclass(frozen=True)
class SpiceNetlist:
    text: str
    node_map: dict[str, str]
    sha256: str
    version_pin: str
    status: SpiceStatus = "pass"
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpiceRawResult:
    status: SpiceStatus
    ngspice_version: str | None
    output_text: str
    raw_output_sha256: str | None
    measures: dict[str, float]
    traces: dict[str, tuple[tuple[float, float], ...]]
    findings: tuple[str, ...] = ()
    netlist_sha256: str = "unknown"


def _number(value: str, *, kind: str) -> float:
    match = _VALUE_RE.fullmatch(value)
    if match is None:
        raise SpiceNetlistError(f"cannot parse {kind} value {value!r}")
    number = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    scale = {
        "": 1.0,
        "meg": 1e6,
        "g": 1e9,
        "k": 1e3,
        "m": 1e-3,
        "u": 1e-6,
        "n": 1e-9,
        "p": 1e-12,
        "f": 1e-15,
    }[suffix]
    result = number * scale
    if not math.isfinite(result) or result <= 0:
        raise SpiceNetlistError(f"{kind} value must be finite and positive")
    return result


def _node_name(net: str) -> str:
    if net.upper() in {"GND", "0"}:
        return "0"
    return "n" + re.sub(r"[^A-Za-z0-9]", "_", net).strip("_").lower()


def _component_pins(lane: ElectricalLane, component: ComponentView) -> tuple[str, ...]:
    pins = lane.pins_of_component(component.node_id)
    return tuple(pin.net_id or "" for pin in pins)


def _net_names(lane: ElectricalLane) -> dict[str, str]:
    return {
        net.node_id: net.name
        for net in lane.nets
    }


def _component_map(lane: ElectricalLane) -> dict[str, ComponentView]:
    return {
        component.refdes: component
        for component in lane.components
    }


def _resolve_net(net: str, names: dict[str, str]) -> str:
    if net in names:
        return names[net]
    for name in names.values():
        if name == net:
            return name
    raise SpiceNetlistError(f"unknown graph net {net!r}")


def _pins_as_nodes(
    lane: ElectricalLane,
    component: ComponentView,
    names: dict[str, str],
) -> tuple[str, ...]:
    return tuple(
        _node_name(names[net_id])
        for net_id in _component_pins(lane, component)
        if net_id in names
    )


def _check_revision(graph: DesignGraph, request: SpiceAnalysisRequest) -> None:
    if request.graph_id != graph.graph_id or request.revision != graph.revision:
        raise SpiceNetlistError(
            "graph/request graph_id or revision mismatch"
        )


def extract_power_netlist(
    graph: DesignGraph,
    request: SpiceAnalysisRequest,
) -> SpiceNetlist:
    """Extract a deterministic approximate power netlist.

    The LDO is represented by a behavioral source that clamps output to the
    declared nominal voltage and input-minus-dropout voltage. This is an
    estimate model, not a vendor SPICE macro-model.
    """
    _check_revision(graph, request)
    try:
        lane = extract_electrical_lane(graph)
    except GraphExtractionError as exc:
        raise SpiceNetlistError(str(exc)) from exc
    names = _net_names(lane)
    components = _component_map(lane)
    findings: list[str] = []

    def require_component(refdes: str) -> ComponentView:
        component = components.get(refdes)
        if component is None:
            raise SpiceNetlistError(f"requested component {refdes!r} is missing")
        return component

    ldo = require_component(request.models.ldo.refdes)
    if request.models.ldo.model != "behavioral_ldo":
        raise SpiceNetlistError("unsupported LDO model")
    for entry in request.models.decoupling:
        component = require_component(entry.refdes)
        if not component.refdes.upper().startswith("C"):
            raise SpiceNetlistError(
                f"decoupling component {entry.refdes!r} is not a capacitor"
            )
    for entry in request.models.led:
        require_component(entry.refdes)
        require_component(entry.series_resistor_refdes)
    for entry in request.models.i2c_pullups:
        resistor = require_component(entry.resistor_refdes)
        if not resistor.refdes.upper().startswith("R"):
            raise SpiceNetlistError(
                f"I2C pull-up component {entry.resistor_refdes!r} is not a resistor"
            )
        _resolve_net(entry.net, names)
        _resolve_net(entry.vdd_net, names)

    vbus_name = _resolve_net("VBUS_5V", names)
    output_name = next(
        (name for name in names.values() if name in {"+3V3", "3V3"}),
        "+3V3",
    )
    lines = [
        "* ACD deterministic power-network estimate",
        f"* graph_id={graph.graph_id} revision={graph.revision}",
        f".param VBUS_V={request.sources.vbus_v:.12g}",
        f"V_VBUS {_node_name(vbus_name)} 0 {{VBUS_V}}",
    ]
    if request.sources.vbus_ramp_ms > 0:
        lines.append(
            f"* transient ramp requested: {request.sources.vbus_ramp_ms:.12g} ms"
        )

    for component in sorted(components.values(), key=lambda item: item.refdes):
        refdes = component.refdes
        if refdes.upper().startswith("R") or refdes.upper().startswith("C"):
            pins = _pins_as_nodes(lane, component, names)
            if len(pins) != 2:
                findings.append(f"{refdes}: missing two-terminal connectivity")
                continue
            try:
                value = _number(
                    component.value,
                    kind="resistance" if refdes.upper().startswith("R") else "capacitance",
                )
            except SpiceNetlistError:
                findings.append(f"{refdes}: missing or malformed component value")
                continue
            suffix = "R" if refdes.upper().startswith("R") else "C"
            lines.append(
                f"{suffix}_{refdes} {pins[0]} {pins[1]} {value:.12g}"
            )

    ldo_pins = _pins_as_nodes(lane, ldo, names)
    if len(ldo_pins) < 3:
        findings.append(f"{ldo.refdes}: missing LDO pin connectivity")
    else:
        lines.append(
            f"B_{ldo.refdes} {_node_name(output_name)} 0 "
            f"V={{max(0,min({request.models.ldo.vout_v:.12g},"
            f"V({_node_name(vbus_name)})-{request.models.ldo.dropout_v:.12g}))}}"
        )
        if request.models.ldo.iq_a > 0:
            lines.append(
                f"IQ_{ldo.refdes} {_node_name(output_name)} 0 "
                f"{request.models.ldo.iq_a:.12g}"
            )

    for entry in request.models.led:
        component = components[entry.refdes]
        pins = _pins_as_nodes(lane, component, names)
        if len(pins) != 2:
            findings.append(f"{entry.refdes}: missing LED connectivity")
            continue
        model_name = f"LED_{re.sub(r'[^A-Za-z0-9]', '_', entry.refdes)}"
        lines.append(f"D_{entry.refdes} {pins[1]} {pins[0]} {model_name}")
        lines.append(f".model {model_name} D(Is=1e-14 N=1.8)")

    for index, entry in enumerate(
        sorted(request.models.i2c_pullups, key=lambda item: item.net)
    ):
        node = _node_name(_resolve_net(entry.net, names))
        capacitance = entry.bus_capacitance_pf * 1e-12
        lines.append(f"C_BUS_{index + 1} {node} 0 {capacitance:.12g}")

    analysis_kinds = {analysis.kind for analysis in request.analyses}
    if "op" in analysis_kinds:
        lines.append(".op")
    tran = next(
        (analysis for analysis in request.analyses if analysis.kind == "tran"),
        None,
    )
    if tran is not None:
        lines.append(f".tran {tran.tstep:.12g} {tran.tstop:.12g}")
    print_targets = sorted(
        {
            f"V({_node_name(_resolve_net(limit.target, names))})"
            for limit in request.limits
            if limit.quantity == "node_voltage"
            and limit.target in set(names) | set(names.values())
        }
        | {
            f"V({_node_name(_resolve_net(limit.target, names))})"
            for limit in request.limits
            if limit.quantity == "rise_time"
            and limit.target in set(names) | set(names.values())
        }
        | {
            f"@r_{limit.target.lower()}[i]"
            for limit in request.limits
            if limit.quantity == "branch_current"
        }
    )
    if not print_targets:
        print_targets = [f"V({_node_name(output_name)})"]
    if "op" in analysis_kinds:
        op_targets = [target for target in print_targets if target.startswith("@")]
        if op_targets:
            lines.append(".print op " + " ".join(op_targets))
    if tran is not None:
        lines.append(".print tran time " + " ".join(print_targets))
    lines.append(".end")
    text = "\n".join(lines) + "\n"
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    node_map = {key: _node_name(value) for key, value in names.items()}
    node_map.update({value: _node_name(value) for value in names.values()})
    return SpiceNetlist(
        text=text,
        node_map=node_map,
        sha256=digest,
        version_pin=request.ngspice.version_pin,
        status="unknown" if findings else "pass",
        findings=tuple(sorted(set(findings))),
    )


def _parse_version(text: str) -> str | None:
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


def _parse_output(
    text: str,
) -> tuple[dict[str, float], dict[str, tuple[tuple[float, float], ...]], tuple[str, ...]]:
    measures: dict[str, float] = {}
    traces: dict[str, list[tuple[float, float]]] = {}
    for match in _MEASURE_RE.finditer(text):
        measures[f"{match.group(1).lower()}({match.group(2).strip().lower()})"] = float(
            match.group(3)
        )
    headers: list[str] | None = None
    for line in text.splitlines():
        tokens = line.split()
        if not tokens:
            continue
        if any(
            token.lower().startswith(("v(", "i(", "@"))
            for token in tokens
        ):
            headers = []
            for token in tokens:
                lowered_token = token.lower()
                if lowered_token.startswith("@") and lowered_token.endswith("[i]"):
                    device = lowered_token[1:-3]
                    headers.append(f"i({device[2:] if device.startswith('r_') else device})")
                else:
                    headers.append(lowered_token)
            continue
        if headers is None:
            continue
        fields = line.split("\t") if "\t" in line else tokens
        if len(fields) < len(headers):
            continue
        if "time" not in headers and "index" not in headers:
            continue
        time_index = headers.index("time") if "time" in headers else 1
        if time_index >= len(fields) or not fields[time_index].strip():
            continue
        try:
            time_value = float(fields[time_index])
        except ValueError:
            continue
        row_values: dict[int, float] = {}
        numeric_tail: list[float] = []
        for field in fields[time_index + 1 :]:
            if not field.strip():
                continue
            try:
                numeric_tail.append(float(field))
            except ValueError:
                continue
        value_start = len(headers) - len(numeric_tail)
        for offset, value in enumerate(numeric_tail):
            row_values[value_start + offset] = value
        for index, header in enumerate(headers):
            if index not in row_values:
                continue
            value = row_values[index]
            if header.startswith("v("):
                traces.setdefault(header, []).append((time_value, value))
            elif header.startswith("i("):
                measures[header] = value
    findings: list[str] = []
    lowered = text.lower()
    if "timestep too small" in lowered or "doanalyses" in lowered:
        findings.append("ngspice did not converge")
    if not measures and not traces:
        findings.append("ngspice output parse failed")
    return measures, {
        key: tuple(value)
        for key, value in sorted(traces.items())
    }, tuple(sorted(set(findings)))


def run_ngspice(netlist: SpiceNetlist, workdir: Path) -> SpiceRawResult:
    """Run ngspice only through the process adapter and parse its batch output."""
    workdir.mkdir(parents=True, exist_ok=True)
    netlist_path = workdir / "power-network.cir"
    log_path = workdir / "ngspice.out"
    netlist_path.write_text(netlist.text, encoding="utf-8")
    try:
        version_run = run_tool(
            tool_name="ngspice",
            tool_version="unknown",
            format_version=SPICE_FORMAT_VERSION,
            command=["ngspice", "-v"],
            input_paths=[],
            output_paths=[],
            envelope_path=workdir / "ngspice-version-envelope.json",
            target_revision="unknown",
            measurement_conditions="version probe",
        )
    except (ExternalToolError, OSError) as exc:
        return SpiceRawResult(
            status="unknown",
            ngspice_version=None,
            output_text="",
            raw_output_sha256=None,
            measures={},
            traces={},
            findings=("tool_missing", str(exc)),
            netlist_sha256=netlist.sha256,
        )
    version_text = version_run.stdout + "\n" + version_run.stderr
    version = _parse_version(version_text)
    if version != netlist.version_pin:
        return SpiceRawResult(
            status="unknown",
            ngspice_version=version,
            output_text=version_text,
            raw_output_sha256="sha256:"
            + hashlib.sha256(version_text.encode("utf-8")).hexdigest(),
            measures={},
            traces={},
            findings=("tool_version_mismatch",),
            netlist_sha256=netlist.sha256,
        )
    assert version is not None
    try:
        run_tool(
            tool_name="ngspice",
            tool_version=version,
            format_version=SPICE_FORMAT_VERSION,
            command=["ngspice", "-b", "-o", str(log_path), str(netlist_path)],
            input_paths=[netlist_path],
            output_paths=[log_path],
            envelope_path=workdir / "ngspice-envelope.json",
            target_revision="unknown",
            measurement_conditions="graph-derived power-network estimate",
            cwd=workdir,
            convergence_state="converged",
        )
    except (ExternalToolError, OSError) as exc:
        return SpiceRawResult(
            status="unknown",
            ngspice_version=version,
            output_text="",
            raw_output_sha256=None,
            measures={},
            traces={},
            findings=("ngspice execution failed", str(exc)),
            netlist_sha256=netlist.sha256,
        )
    output = log_path.read_text(encoding="utf-8")
    measures, traces, parse_findings = _parse_output(output)
    findings = tuple(sorted(set(parse_findings)))
    return SpiceRawResult(
        status="unknown" if findings else "pass",
        ngspice_version=version,
        output_text=output,
        raw_output_sha256="sha256:" + hashlib.sha256(output.encode("utf-8")).hexdigest(),
        measures=measures,
        traces=traces,
        findings=findings,
        netlist_sha256=netlist.sha256,
    )


def _lookup_measure(
    raw: SpiceRawResult,
    limit: SpiceLimit,
    node_map: dict[str, str],
) -> float | None:
    if limit.quantity == "branch_current":
        candidates = [f"i({limit.target.lower()})"]
    elif limit.quantity == "node_voltage":
        node = node_map.get(limit.target, _node_name(limit.target))
        candidates = [f"v({node.lower()})", f"v({limit.target.lower()})"]
    else:
        trace = raw.traces.get(f"v({node_map.get(limit.target, _node_name(limit.target)).lower()})")
        if not trace:
            return None
        values = [value for _, value in trace]
        low = min(values)
        high = max(values)
        if high <= low:
            return 0.0
        ten = low + (high - low) * 0.1
        ninety = low + (high - low) * 0.9
        t10 = next((time for time, value in trace if value >= ten), None)
        t90 = next((time for time, value in trace if value >= ninety), None)
        return None if t10 is None or t90 is None else t90 - t10
    for candidate in candidates:
        if candidate in raw.measures:
            return raw.measures[candidate]
        trace = raw.traces.get(candidate)
        if trace:
            return trace[-1][1]
    return None


def evaluate_spice(
    graph: DesignGraph,
    request: SpiceAnalysisRequest,
    raw: SpiceRawResult,
) -> SpiceResult:
    """Evaluate declared ranges without promoting the result to Evidence."""
    netlist = extract_power_netlist(graph, request)
    checks: list[SpiceCheck] = []
    findings = list(netlist.findings) + list(raw.findings)
    for limit in request.limits:
        measured = _lookup_measure(raw, limit, netlist.node_map)
        if raw.status != "pass" or measured is None:
            checks.append(
                SpiceCheck(
                    quantity=limit.quantity,
                    target=limit.target,
                    measured=measured,
                    status="unknown",
                    reason="SPICE output unavailable or could not be parsed",
                )
            )
            continue
        tolerance = (limit.tolerance_pct or 0.0) / 100.0
        lower = None if limit.min is None else limit.min * (1 - tolerance)
        upper = None if limit.max is None else limit.max * (1 + tolerance)
        passed = (lower is None or measured >= lower) and (
            upper is None or measured <= upper
        )
        checks.append(
            SpiceCheck(
                quantity=limit.quantity,
                target=limit.target,
                measured=measured,
                status="pass" if passed else "fail",
                reason="within declared range" if passed else "declared range exceeded",
            )
        )
    statuses = [check.status for check in checks]
    if "fail" in statuses:
        status: SpiceStatus = "fail"
    elif "unknown" in statuses or netlist.status == "unknown":
        status = "unknown"
    else:
        status = "pass"
    if not checks:
        checks.append(
            SpiceCheck(
                quantity="node_voltage",
                target="analysis",
                measured=None,
                status="unknown",
                reason="no value limits declared",
            )
        )
        status = "unknown"
    return SpiceResult(
        graph_id=graph.graph_id,
        revision=graph.revision,
        status=status,
        checks=checks,
        findings=sorted(set(findings)),
        netlist_sha256=netlist.sha256,
        raw_output_sha256=raw.raw_output_sha256 or "unknown",
        ngspice_version=raw.ngspice_version or "unknown",
        input_hashes={
            "graph": canonical_sha256(graph),
            "request": canonical_sha256(request),
        },
    )


__all__ = [
    "SpiceNetlist",
    "SpiceNetlistError",
    "SpiceRawResult",
    "evaluate_spice",
    "extract_power_netlist",
    "run_ngspice",
]
