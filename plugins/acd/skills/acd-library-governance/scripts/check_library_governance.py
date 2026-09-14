# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@547deea8468f06aa14b9187ee7992db502a74a1d",
# ]
# ///
"""Check KiCad library assets and project library-table declarations."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from acd.schema.design_graph import DesignGraph

TOOL_VERSION = "acd-library-governance/0.1.0"


class PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PadSizeRange(PolicyModel):
    min_x: float
    max_x: float
    min_y: float
    max_y: float


class CourtyardMarginRange(PolicyModel):
    min: float
    max: float


class FootprintRule(PolicyModel):
    package_pattern: str = Field(min_length=1)
    pad_size_mm: PadSizeRange | None = None
    courtyard_required: bool
    courtyard_margin_mm: CourtyardMarginRange | None = None
    origin: Literal["centroid", "pin1"] | None = None
    origin_tolerance_mm: float = Field(ge=0)
    allowed_layers: list[str] = Field(default_factory=list)


class LibTableRules(PolicyModel):
    require_all_referenced_libraries: bool
    allowed_sources: list[str] = Field(default_factory=list)


class HashPinning(PolicyModel):
    require_footprint_sha256: bool
    require_symbol_sha256: bool


class LibraryPolicy(PolicyModel):
    schema_version: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    graph_id: str | None = None
    revision: str | None = None
    footprint_rules: list[FootprintRule]
    lib_table_rules: LibTableRules
    hash_pinning: HashPinning


SExpr = str | list["SExpr"]


class InputError(ValueError):
    """Raised for malformed or unavailable review inputs."""


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char in "()":
            tokens.append(char)
            index += 1
            continue
        if char == '"':
            index += 1
            value: list[str] = []
            while index < len(text):
                char = text[index]
                if char == "\\" and index + 1 < len(text):
                    value.append(text[index + 1])
                    index += 2
                elif char == '"':
                    index += 1
                    break
                else:
                    value.append(char)
                    index += 1
            else:
                raise InputError("unterminated KiCad quoted atom")
            tokens.append("".join(value))
            continue
        end = index
        while end < len(text) and not text[end].isspace() and text[end] not in "()":
            end += 1
        tokens.append(text[index:end])
        index = end
    return tokens


def _parse_sexpr(text: str) -> SExpr:
    tokens = _tokenize(text)
    roots: list[SExpr] = []
    stack: list[list[SExpr]] = []
    for token in tokens:
        if token == "(":
            stack.append([])
        elif token == ")":
            if not stack:
                raise InputError("unexpected KiCad closing parenthesis")
            value = stack.pop()
            if stack:
                stack[-1].append(value)
            else:
                roots.append(value)
        elif stack:
            stack[-1].append(token)
        else:
            roots.append(token)
    if stack:
        raise InputError("unterminated KiCad expression")
    if len(roots) != 1:
        raise InputError("KiCad file must contain exactly one expression")
    return roots[0]


def _head(node: SExpr) -> str | None:
    return node[0] if isinstance(node, list) and node and isinstance(node[0], str) else None


def _children(node: SExpr, name: str) -> Iterator[list[SExpr]]:
    if not isinstance(node, list):
        return
    for child in node[1:]:
        if _head(child) == name:
            yield child  # type: ignore[misc]


def _walk(node: SExpr) -> Iterator[list[SExpr]]:
    if not isinstance(node, list):
        return
    yield node
    for child in node[1:]:
        yield from _walk(child)


def _number(value: SExpr | None) -> float | None:
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _point(node: list[SExpr] | None, name: str = "at") -> tuple[float, float] | None:
    if node is None or len(node) < 3:
        return None
    x = _number(node[1])
    y = _number(node[2])
    return None if x is None or y is None else (x, y)


def _first_child(node: SExpr, name: str) -> list[SExpr] | None:
    return next(_children(node, name), None)


def _bbox(points: Sequence[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _graphic_points(node: list[SExpr]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for tag in ("start", "end", "mid", "center"):
        point = _point(_first_child(node, tag))
        if point is not None:
            points.append(point)
    pts = _first_child(node, "pts")
    if pts is not None:
        for child in pts[1:]:
            point = _point(child, "xy") if isinstance(child, list) else None
            if point is not None:
                points.append(point)
    return points


def _layer(node: list[SExpr]) -> str | None:
    layer = _first_child(node, "layer")
    return layer[1] if layer is not None and len(layer) > 1 and isinstance(layer[1], str) else None


def _layers(node: list[SExpr]) -> list[str]:
    layers = _first_child(node, "layers")
    return [
        value
        for value in (layers[1:] if layers is not None else [])
        if isinstance(value, str)
    ]


def _footprint_data(root: SExpr) -> dict[str, Any]:
    pads: list[dict[str, Any]] = []
    courtyard_points: list[tuple[float, float]] = []
    body_points: list[tuple[float, float]] = []
    courtyard_present = False
    for node in _walk(root):
        head = _head(node)
        if head == "pad":
            if len(node) < 2 or not isinstance(node[1], str):
                continue
            at = _point(_first_child(node, "at"))
            size = _first_child(node, "size")
            if at is None or size is None or len(size) < 3:
                continue
            sx = _number(size[1])
            sy = _number(size[2])
            if sx is None or sy is None:
                continue
            pads.append(
                {
                    "name": node[1],
                    "at": at,
                    "size": (sx, sy),
                    "layers": _layers(node),
                }
            )
        elif head in {"fp_rect", "fp_line", "fp_poly", "fp_circle", "fp_arc"}:
            points = _graphic_points(node)
            layer = _layer(node)
            is_courtyard = layer in {"F.CrtYd", "B.CrtYd"}
            if is_courtyard:
                courtyard_present = True
                courtyard_points.extend(points)
            else:
                body_points.extend(points)
    if not body_points:
        body_points = [
            (x + dx, y + dy)
            for pad in pads
            for x, y in [pad["at"]]
            for dx, dy in [
                (-pad["size"][0] / 2, -pad["size"][1] / 2),
                (pad["size"][0] / 2, pad["size"][1] / 2),
            ]
        ]
    return {
        "pads": pads,
        "courtyard_present": courtyard_present,
        "courtyard_bbox": _bbox(courtyard_points),
        "body_bbox": _bbox(body_points),
    }


def _hash(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _read_graph(path: Path) -> DesignGraph:
    try:
        return DesignGraph.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
        raise InputError(f"graph is invalid: {exc}") from exc


def _read_policy(path: Path) -> LibraryPolicy:
    try:
        return LibraryPolicy.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise InputError(f"library policy is invalid: {exc}") from exc


def _finding(
    check_id: str,
    footprint: str,
    status: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "footprint": footprint,
        "status": status,
        "reason": reason,
        "details": details or {},
    }


def _components(graph: DesignGraph) -> list[Any]:
    return sorted(
        (node for node in graph.nodes if node.kind == "electrical.component"),
        key=lambda node: node.id,
    )


def _rule_for(name: str, rules: Sequence[FootprintRule]) -> FootprintRule | None:
    return next(
        (rule for rule in rules if fnmatch.fnmatchcase(name, rule.package_pattern)),
        None,
    )


def _check_geometry(
    footprint: str,
    data: dict[str, Any],
    rule: FootprintRule,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    pads = data["pads"]
    if not pads:
        return [_finding("pad_geometry", footprint, "unknown", "no parseable pads")]
    if rule.pad_size_mm is not None:
        invalid = [
            pad
            for pad in pads
            if not (
                rule.pad_size_mm.min_x <= pad["size"][0] <= rule.pad_size_mm.max_x
                and rule.pad_size_mm.min_y <= pad["size"][1] <= rule.pad_size_mm.max_y
            )
        ]
        findings.append(
            _finding(
                "pad_geometry",
                footprint,
                "fail" if invalid else "pass",
                "one or more pad sizes are outside the policy range"
                if invalid
                else "all pad sizes are within the policy range",
                {"pads": invalid or pads},
            )
        )
    if rule.courtyard_required:
        present = data["courtyard_present"] and data["courtyard_bbox"] is not None
        findings.append(
            _finding(
                "courtyard",
                footprint,
                "pass" if present else "fail",
                "courtyard geometry is present"
                if present
                else "required courtyard geometry is missing",
            )
        )
    if rule.courtyard_margin_mm is not None:
        courtyard = data["courtyard_bbox"]
        body = data["body_bbox"]
        if courtyard is None or body is None:
            findings.append(
                _finding(
                    "courtyard_margin",
                    footprint,
                    "unknown",
                    "courtyard or body extents are unavailable",
                )
            )
        else:
            margins = [
                body[0] - courtyard[0],
                body[1] - courtyard[1],
                courtyard[2] - body[2],
                courtyard[3] - body[3],
            ]
            valid = all(
                rule.courtyard_margin_mm.min <= margin <= rule.courtyard_margin_mm.max
                for margin in margins
            )
            findings.append(
                _finding(
                    "courtyard_margin",
                    footprint,
                    "pass" if valid else "fail",
                    "courtyard margins are within the policy range"
                    if valid
                    else "courtyard margins are outside the policy range",
                    {"margins_mm": margins},
                )
            )
    if rule.origin is not None:
        if rule.origin == "pin1":
            origin = next((pad["at"] for pad in pads if pad["name"] == "1"), None)
        else:
            origin = (
                sum(pad["at"][0] for pad in pads) / len(pads),
                sum(pad["at"][1] for pad in pads) / len(pads),
            )
        if origin is None:
            findings.append(
                _finding("origin", footprint, "unknown", "pin 1 is not declared")
            )
        else:
            distance = math.hypot(origin[0], origin[1])
            findings.append(
                _finding(
                    "origin",
                    footprint,
                    "pass" if distance <= rule.origin_tolerance_mm else "fail",
                    "footprint origin is within tolerance"
                    if distance <= rule.origin_tolerance_mm
                    else "footprint origin exceeds tolerance",
                    {"origin_mm": origin, "distance_mm": distance},
                )
            )
    if rule.allowed_layers:
        invalid_layers = sorted(
            {
                layer
                for pad in pads
                for layer in pad["layers"]
                if not any(
                    fnmatch.fnmatchcase(layer, allowed)
                    for allowed in rule.allowed_layers
                )
            }
        )
        findings.append(
            _finding(
                "layers",
                footprint,
                "fail" if invalid_layers else "pass",
                "pad layers are outside the policy"
                if invalid_layers
                else "pad layers satisfy the policy",
                {"invalid_layers": invalid_layers},
            )
        )
    return findings


def _classify_source(uri: str) -> str:
    if uri.startswith("/usr/share/kicad") or uri.startswith("${KICAD"):
        return "kicad-official"
    if uri.startswith("${KIPRJMOD}") or not Path(uri).is_absolute():
        return "project-local"
    if "/libraries/" in uri or uri.startswith("libraries/"):
        return "project-local"
    return "package-managed"


def _table_entries(path: Path) -> list[tuple[str, str]]:
    try:
        root = _parse_sexpr(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, InputError) as exc:
        raise InputError(f"fp-lib-table is unreadable: {exc}") from exc
    entries: list[tuple[str, str]] = []
    for node in _walk(root):
        if _head(node) != "lib":
            continue
        name = _first_child(node, "name")
        uri = _first_child(node, "uri")
        if (
            name is not None
            and uri is not None
            and len(name) > 1
            and len(uri) > 1
            and isinstance(name[1], str)
            and isinstance(uri[1], str)
        ):
            entries.append((name[1], uri[1]))
    return sorted(set(entries))


def check_library_governance(
    graph: DesignGraph,
    policy: LibraryPolicy,
    project_dir: Path | None = None,
) -> dict[str, Any]:
    if policy.graph_id is not None and policy.graph_id != graph.graph_id:
        raise InputError("library policy graph_id does not match graph")
    if policy.revision is not None and policy.revision != graph.revision:
        raise InputError("library policy revision does not match graph")
    findings: list[dict[str, Any]] = []
    referenced: dict[str, list[dict[str, Any]]] = {}
    for component in _components(graph):
        footprint = component.attrs.get("footprint")
        footprint_file = component.attrs.get("footprint_file")
        symbol_file = component.attrs.get("symbol_file")
        if not isinstance(footprint, str) or not isinstance(footprint_file, str):
            findings.append(
                _finding(
                    "footprint_reference",
                    component.id,
                    "unknown",
                    "component footprint reference is incomplete",
                )
            )
            continue
        nickname = footprint.split(":", 1)[0] if ":" in footprint else ""
        referenced.setdefault(nickname, []).append(
            {
                "component": component,
                "footprint": footprint.split(":", 1)[1] if ":" in footprint else footprint,
                "footprint_file": Path(footprint_file),
                "symbol_file": Path(symbol_file) if isinstance(symbol_file, str) else None,
            }
        )
        footprint_name = (
            footprint.split(":", 1)[1] if ":" in footprint else footprint
        )
        rule = _rule_for(footprint_name, policy.footprint_rules)
        try:
            data = _footprint_data(
                _parse_sexpr(Path(footprint_file).read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, InputError) as exc:
            findings.append(
                _finding(
                    "footprint_geometry",
                    footprint,
                    "unknown",
                    f"footprint file is unreadable: {exc}",
                )
            )
        else:
            if rule is not None:
                findings.extend(_check_geometry(footprint, data, rule))
            else:
                findings.append(
                    _finding(
                        "footprint_rule",
                        footprint,
                        "pass",
                        "no footprint rule matches; no geometry constraint applies",
                    )
                )
        if policy.hash_pinning.require_footprint_sha256:
            expected = component.attrs.get("footprint_sha256")
            if not isinstance(expected, str):
                findings.append(
                    _finding(
                        "footprint_sha256",
                        footprint,
                        "fail",
                        "footprint sha256 is required but not declared",
                    )
                )
            else:
                try:
                    actual = _hash(Path(footprint_file))
                except OSError as exc:
                    findings.append(
                        _finding(
                            "footprint_sha256",
                            footprint,
                            "unknown",
                            f"footprint hash cannot be read: {exc}",
                        )
                    )
                else:
                    findings.append(
                        _finding(
                            "footprint_sha256",
                            footprint,
                            "pass" if actual == expected else "fail",
                            "footprint sha256 matches declaration"
                            if actual == expected
                            else "footprint sha256 does not match declaration",
                            {"declared": expected, "actual": actual},
                        )
                    )
        if policy.hash_pinning.require_symbol_sha256:
            expected = component.attrs.get("symbol_sha256")
            if not isinstance(expected, str) or not isinstance(symbol_file, str):
                findings.append(
                    _finding(
                        "symbol_sha256",
                        footprint,
                        "fail",
                        "symbol sha256 and file are required but not declared",
                    )
                )
            else:
                try:
                    actual = _hash(Path(symbol_file))
                except OSError as exc:
                    findings.append(
                        _finding(
                            "symbol_sha256",
                            footprint,
                            "unknown",
                            f"symbol hash cannot be read: {exc}",
                        )
                    )
                else:
                    findings.append(
                        _finding(
                            "symbol_sha256",
                            footprint,
                            "pass" if actual == expected else "fail",
                            "symbol sha256 matches declaration"
                            if actual == expected
                            else "symbol sha256 does not match declaration",
                            {"declared": expected, "actual": actual},
                        )
                    )
    if project_dir is not None:
        table_path = project_dir / "fp-lib-table"
        try:
            entries = _table_entries(table_path)
        except InputError as exc:
            findings.append(_finding("fp_lib_table", str(table_path), "unknown", str(exc)))
        else:
            declared = {name for name, _uri in entries}
            if policy.lib_table_rules.require_all_referenced_libraries:
                for nickname in sorted(
                    name for name in referenced if name and name not in declared
                ):
                    findings.append(
                        _finding(
                            "fp_lib_table",
                            nickname,
                            "fail",
                            "referenced footprint library is not declared in fp-lib-table",
                        )
                    )
            allowed = set(policy.lib_table_rules.allowed_sources)
            for nickname, uri in entries:
                source = _classify_source(uri)
                if allowed and source not in allowed:
                    findings.append(
                        _finding(
                            "fp_lib_source",
                            nickname,
                            "fail",
                            "footprint library source is not allowed by policy",
                            {"uri": uri, "source": source},
                        )
                    )
    statuses = {finding["status"] for finding in findings}
    status = "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass"
    return {
        "status": status,
        "authority": "l2_review",
        "findings": findings,
        "input_hashes": {
            "graph": (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        graph.model_dump(mode="json"), sort_keys=True
                    ).encode("utf-8")
                ).hexdigest()
            ),
            "policy": (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        policy.model_dump(mode="json"), sort_keys=True
                    ).encode("utf-8")
                ).hexdigest()
            ),
        },
        "tool_version": TOOL_VERSION,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--project-dir", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        graph = _read_graph(args.graph)
        policy = _read_policy(args.policy)
        report = check_library_governance(graph, policy, args.project_dir)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (InputError, OSError, TypeError, ValueError) as exc:
        print(f"library governance input error: {exc}", file=sys.stderr)
        return 2
    print(report["status"])
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
