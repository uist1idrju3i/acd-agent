"""Reading skill-produced routing candidates as design input.

A routing candidate is produced outside ACD by a skill (subprocess boundary,
see ADR-0007 and ADR-0041) from a vision observation. It is a proposal, not a
verdict: this module only converts it into the tool-neutral ``RoutedDesign``
that the deterministic gates already judge (board injection, DRC, independent
Gerber reload). Nothing here promotes the candidate, its surrogate metrics, or
the vision response into Evidence.

Every deviation from the declared contract is a stop condition: a wrong
artifact kind, a candidate that claims to be Evidence, missing provenance,
unknown nets, non-copper layers, widths below the declared minimum, non-finite
coordinates, or degenerate geometry.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from acd.core.board_model import RoutedDesign, RoutedWire
from acd.core.electrical import ElectricalLane

CANDIDATE_ARTIFACT_KIND = "vision_route_candidates"
COPPER_LAYERS = frozenset({"F.Cu", "B.Cu"})
REQUIRED_PROVENANCE_KEYS = (
    "graph_revision",
    "placements_sha256",
    "proposal_sha256",
    "relaxation_profile_id",
    "relaxation_profile_sha256",
    "script_name",
    "script_sha256",
    "skill_name",
)
REQUIRED_OBSERVATION_KEYS = (
    "image_hash",
    "model",
    "profile_name",
    "projection_id",
    "response_sha256",
    "tool_name",
)


class RouteCandidateError(ValueError):
    """Raised when a routing candidate cannot be used as design input."""


@dataclass(frozen=True)
class RouteCandidateProvenance:
    """Where a candidate came from; recorded, never treated as a verdict."""

    skill_name: str
    script_name: str
    script_sha256: str
    proposal_sha256: str
    relaxation_profile_id: str
    relaxation_profile_sha256: str
    graph_revision: str
    observation_tool: str
    observation_model: str
    observation_image_hash: str
    observation_response_sha256: str

    def record(self) -> dict[str, object]:
        return {
            "skill_name": self.skill_name,
            "script_name": self.script_name,
            "script_sha256": self.script_sha256,
            "proposal_sha256": self.proposal_sha256,
            "relaxation_profile_id": self.relaxation_profile_id,
            "relaxation_profile_sha256": self.relaxation_profile_sha256,
            "graph_revision": self.graph_revision,
            "observation_tool": self.observation_tool,
            "observation_model": self.observation_model,
            "observation_image_hash": self.observation_image_hash,
            "observation_response_sha256": self.observation_response_sha256,
            "pass_evidence": False,
        }


def _mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RouteCandidateError(f"{key!r} must be an object (fail-closed)")
    return cast(dict[str, object], value)


def _text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RouteCandidateError(f"{key!r} must be a non-empty string (fail-closed)")
    return value


def _number(payload: dict[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RouteCandidateError(f"{key!r} must be a number (fail-closed)")
    number = float(value)
    if not math.isfinite(number):
        raise RouteCandidateError(f"{key!r} must be finite (fail-closed)")
    return number


def parse_provenance(payload: dict[str, object]) -> RouteCandidateProvenance:
    """Read the provenance block; anything missing is a stop condition."""
    provenance = _mapping(payload, "provenance")
    missing = [key for key in REQUIRED_PROVENANCE_KEYS if key not in provenance]
    if missing:
        raise RouteCandidateError(f"provenance is missing {missing} (fail-closed)")
    observation = _mapping(provenance, "observation")
    absent = [key for key in REQUIRED_OBSERVATION_KEYS if key not in observation]
    if absent:
        raise RouteCandidateError(f"observation provenance is missing {absent} (fail-closed)")
    return RouteCandidateProvenance(
        skill_name=_text(provenance, "skill_name"),
        script_name=_text(provenance, "script_name"),
        script_sha256=_text(provenance, "script_sha256"),
        proposal_sha256=_text(provenance, "proposal_sha256"),
        relaxation_profile_id=_text(provenance, "relaxation_profile_id"),
        relaxation_profile_sha256=_text(provenance, "relaxation_profile_sha256"),
        graph_revision=_text(provenance, "graph_revision"),
        observation_tool=_text(observation, "tool_name"),
        observation_model=_text(observation, "model"),
        observation_image_hash=_text(observation, "image_hash"),
        observation_response_sha256=_text(observation, "response_sha256"),
    )


def _wire(entry: dict[str, object], lane: ElectricalLane) -> RoutedWire:
    net = _text(entry, "net")
    if net not in {view.name for view in lane.nets}:
        raise RouteCandidateError(f"unknown net {net!r} (fail-closed)")
    layer = _text(entry, "layer")
    if layer not in COPPER_LAYERS:
        raise RouteCandidateError(f"unsupported layer {layer!r} for net {net!r} (fail-closed)")
    width = _number(entry, "width_mm")
    if width < lane.board.min_track_mm - 1e-9:
        raise RouteCandidateError(
            f"net {net!r}: width {width} is below the declared minimum (fail-closed)"
        )
    raw_points = entry.get("points")
    if not isinstance(raw_points, list) or len(cast(list[object], raw_points)) < 2:
        raise RouteCandidateError(f"net {net!r}: at least two points are required (fail-closed)")
    points: list[tuple[float, float]] = []
    for item in cast(list[object], raw_points):
        if not isinstance(item, list) or len(cast(list[object], item)) != 2:
            raise RouteCandidateError(f"net {net!r}: each point must be [x, y] (fail-closed)")
        pair = cast(list[object], item)
        coordinates = {"x_mm": pair[0], "y_mm": pair[1]}
        point = (_number(coordinates, "x_mm"), _number(coordinates, "y_mm"))
        if points and math.dist(points[-1], point) <= 1e-9:
            raise RouteCandidateError(f"net {net!r}: repeated point {point} (fail-closed)")
        points.append(point)
    return RoutedWire(net=net, layer=layer, width_mm=width, points=tuple(points))


def parse_route_candidates(
    payload: dict[str, object], lane: ElectricalLane, graph_revision: str
) -> tuple[RoutedDesign, RouteCandidateProvenance]:
    """Convert a candidate report into routes that the gates can judge."""
    if payload.get("artifact_kind") != CANDIDATE_ARTIFACT_KIND:
        raise RouteCandidateError(
            f"artifact_kind must be {CANDIDATE_ARTIFACT_KIND!r} (fail-closed)"
        )
    if payload.get("pass_evidence") is not False:
        raise RouteCandidateError("routing candidates must declare pass_evidence=false")
    if payload.get("lane") != "electrical":
        raise RouteCandidateError("routing candidates apply to the electrical lane (fail-closed)")
    provenance = parse_provenance(payload)
    if provenance.graph_revision != graph_revision:
        raise RouteCandidateError(
            f"candidate targets revision {provenance.graph_revision!r}, "
            f"not {graph_revision!r} (fail-closed)"
        )
    candidates = _mapping(payload, "candidates")
    raw_wires = candidates.get("vision")
    if not isinstance(raw_wires, list) or not raw_wires:
        raise RouteCandidateError("the candidate report contains no wires (fail-closed)")
    wires: list[RoutedWire] = []
    seen: set[tuple[str, str]] = set()
    for item in cast(list[object], raw_wires):
        if not isinstance(item, dict):
            raise RouteCandidateError("each wire must be an object (fail-closed)")
        wire = _wire(cast(dict[str, object], item), lane)
        if (wire.net, wire.layer) in seen:
            raise RouteCandidateError(
                f"duplicate wire for net {wire.net!r} on {wire.layer} (fail-closed)"
            )
        seen.add((wire.net, wire.layer))
        wires.append(wire)
    vias = candidates.get("vias")
    if vias != []:
        raise RouteCandidateError("candidate vias are not supported yet (fail-closed)")
    ordered = tuple(sorted(wires, key=lambda item: (item.net, item.layer)))
    return RoutedDesign(wires=ordered, vias=()), provenance


def load_route_candidates(
    path: Path, lane: ElectricalLane, graph_revision: str
) -> tuple[RoutedDesign, RouteCandidateProvenance]:
    """Load a candidate report written by a skill run outside ACD."""
    try:
        document = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise RouteCandidateError(f"candidate report {path} is unreadable: {error}") from error
    if not isinstance(document, dict):
        raise RouteCandidateError("the candidate report must be a JSON object (fail-closed)")
    return parse_route_candidates(cast(dict[str, object], document), lane, graph_revision)
