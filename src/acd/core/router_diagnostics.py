"""Router non-convergence diagnostics surfaced through ``loop-summary.json``.

These observations are L3 only: the reader never raises and every entry is
annotated as having no gate authority.  Router convergence remains decided by
``assert_converged`` and the KiCad DRC gates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

OPEN_NET_LIMIT = 10

_ROUTER_PROGRESS_PATH = Path("l3") / "router-pass-progress.json"
_CONNECTIVITY_PATH = Path("gate-evidence") / "routing-connectivity.json"
_CONVERGENCE_STATES = frozenset(
    {"converged", "not_converged", "timed_out", "unknown"}
)


@dataclass(frozen=True)
class RouterDiagnostics:
    """Board-output router observations for the design-loop summary."""

    convergence_state: str
    unrouted_progression: tuple[int, ...]
    final_unrouted: int | None
    plateau_passes: int
    open_net_count: int | None
    open_nets: tuple[str, ...]
    read_errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-serialisable L3 record."""
        return {
            "convergence_state": self.convergence_state,
            "unrouted_progression": list(self.unrouted_progression),
            "final_unrouted": self.final_unrouted,
            "plateau_passes": self.plateau_passes,
            "open_net_count": self.open_net_count,
            "open_nets": list(self.open_nets),
            "read_errors": list(self.read_errors),
            "authority": "L3 observation; not gate authority",
        }


def _read_json(path: Path, errors: list[str]) -> object | None:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{path.name}: missing")
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
        return None
    return payload


def _progression(payload: dict[str, object], errors: list[str]) -> tuple[int, ...]:
    unrouted = payload.get("unrouted")
    if not isinstance(unrouted, list):
        errors.append(f"{_ROUTER_PROGRESS_PATH.name}: 'unrouted' must be a list")
        return ()
    progression: list[int] = []
    for index, value in enumerate(cast(list[object], unrouted)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(
                f"{_ROUTER_PROGRESS_PATH.name}: 'unrouted[{index}]' is not a "
                "non-negative integer"
            )
            return ()
        progression.append(value)
    return tuple(progression)


def _convergence_state(payload: dict[str, object], errors: list[str]) -> str:
    state = payload.get("convergence_state")
    if not isinstance(state, str) or state not in _CONVERGENCE_STATES:
        errors.append(
            f"{_ROUTER_PROGRESS_PATH.name}: 'convergence_state' is missing or invalid"
        )
        return "unknown"
    return state


def _open_nets(
    payload: object | None, errors: list[str]
) -> tuple[int | None, tuple[str, ...]]:
    if payload is None:
        return None, ()
    if not isinstance(payload, dict):
        errors.append(f"{_CONNECTIVITY_PATH.name}: top level is not an object")
        return None, ()
    observation = cast(dict[str, object], payload).get("observation")
    nets = (
        cast(dict[str, object], observation).get("nets")
        if isinstance(observation, dict)
        else None
    )
    if not isinstance(nets, list):
        errors.append(
            f"{_CONNECTIVITY_PATH.name}: 'observation.nets' is missing or not a list"
        )
        return None, ()
    open_names: list[str] = []
    for index, entry in enumerate(cast(list[object], nets)):
        if not isinstance(entry, dict):
            errors.append(
                f"{_CONNECTIVITY_PATH.name}: 'observation.nets[{index}]' is not an "
                "object"
            )
            return None, ()
        net = cast(dict[str, object], entry).get("net")
        status = cast(dict[str, object], entry).get("status")
        if not isinstance(net, str) or not isinstance(status, str):
            errors.append(
                f"{_CONNECTIVITY_PATH.name}: 'observation.nets[{index}]' has "
                "non-string 'net' or 'status'"
            )
            return None, ()
        if status == "fail":
            open_names.append(net)
    return len(open_names), tuple(sorted(open_names)[:OPEN_NET_LIMIT])


def read_router_diagnostics(board_output: Path) -> RouterDiagnostics:
    """Read router progression and connectivity observations without raising."""
    errors: list[str] = []
    progress_payload = _read_json(board_output / _ROUTER_PROGRESS_PATH, errors)
    if progress_payload is None:
        progression: tuple[int, ...] = ()
        convergence_state = "unknown"
    elif not isinstance(progress_payload, dict):
        errors.append(f"{_ROUTER_PROGRESS_PATH.name}: top level is not an object")
        progression = ()
        convergence_state = "unknown"
    else:
        progress_record = cast(dict[str, object], progress_payload)
        progression = _progression(progress_record, errors)
        convergence_state = _convergence_state(progress_record, errors)

    final_unrouted = progression[-1] if progression else None
    plateau_passes = 0
    if progression:
        for value in reversed(progression):
            if value != final_unrouted:
                break
            plateau_passes += 1

    connectivity_payload = _read_json(board_output / _CONNECTIVITY_PATH, errors)
    open_net_count, open_nets = _open_nets(connectivity_payload, errors)

    return RouterDiagnostics(
        convergence_state=convergence_state,
        unrouted_progression=progression,
        final_unrouted=final_unrouted,
        plateau_passes=plateau_passes,
        open_net_count=open_net_count,
        open_nets=open_nets,
        read_errors=tuple(errors),
    )


def router_diagnostics_hint(diag: RouterDiagnostics | None) -> str | None:
    """Return an actionable next-step hint for a non-converged router run."""
    if diag is None:
        return None
    if diag.convergence_state == "timed_out":
        return (
            "router timed out; raise --router-timeout-s or reduce routing load"
        )
    if diag.convergence_state != "not_converged" or not diag.unrouted_progression:
        return None
    if diag.plateau_passes >= 3:
        return (
            f"router unrouted plateaued at {diag.final_unrouted} for "
            f"{diag.plateau_passes} passes; broaden candidate axes within "
            "declared constraints (outline size, layer count, component "
            "spacing/placement) or make the constraint explicit in the design "
            "input; do not relax DRC or routing rules"
        )
    return (
        f"router still converging (unrouted progression "
        f"{list(diag.unrouted_progression)}); raise the router pass budget "
        "(--max-passes) before changing the design"
    )


__all__ = [
    "OPEN_NET_LIMIT",
    "RouterDiagnostics",
    "read_router_diagnostics",
    "router_diagnostics_hint",
]
