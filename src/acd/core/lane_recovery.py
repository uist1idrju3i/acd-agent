"""Declaration-driven resolution of per-lane recovery from rejection.

Recovery is an L2 steering mechanism. Resolving a lane's recovery capability
never decides a gate; a lane without a declared recoverable dimension is
reported as an L3 diagnostic and left rejected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acd.core.design_freedom import (
    DesignFreedomDeclaration,
    load_design_freedom_declaration,
)
from acd.pipeline.repository import repository_root
from acd.schema.common import canonical_json_sha256
from acd.schema.lane_recovery import (
    LaneRecoveryDeclaration,
    LaneRecoveryDeclarationDocument,
)


class LaneRecoveryDeclarationError(ValueError):
    """Raised when lane recovery declarations cannot be resolved safely."""


@dataclass(frozen=True)
class LaneRecoveryDeclarations:
    """The loaded lane recovery declaration and its content hash."""

    document: LaneRecoveryDeclarationDocument
    declaration_hash: str
    path: Path

    def lane(self, lane_id: str) -> LaneRecoveryDeclaration | None:
        return next(
            (item for item in self.document.lanes if item.lane_id == lane_id), None
        )


@dataclass(frozen=True)
class LaneRecoveryPlan:
    """Resolved recovery capability of one rejected lane."""

    lane_id: str
    supported: bool
    explorer: str
    dimensions: tuple[str, ...]
    next_step_action: str
    reason: str | None
    declaration_hash: str

    def as_diagnostic(self) -> dict[str, Any]:
        """Return the L3 diagnostic payload of this resolution."""
        return {
            "record_class": "L3",
            "pass_evidence": False,
            "lane_id": self.lane_id,
            "recovery_supported": self.supported,
            "recovery_explorer": self.explorer,
            "recovery_dimensions": list(self.dimensions),
            "next_step_action": self.next_step_action,
            "recovery_unsupported_reason": self.reason,
            "declaration_hash": self.declaration_hash,
        }


def load_lane_recovery_declarations(
    path: Path | None = None,
) -> LaneRecoveryDeclarations:
    """Load the lane recovery declaration, failing closed on malformed input."""
    declaration_path = (
        path or repository_root() / "contracts" / "lane-recovery-declaration.json"
    )
    try:
        value = json.loads(declaration_path.read_text(encoding="utf-8"))
        document = LaneRecoveryDeclarationDocument.model_validate(value)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise LaneRecoveryDeclarationError(
            f"lane recovery declaration is invalid: {declaration_path}: {exc}"
        ) from exc
    return LaneRecoveryDeclarations(
        document=document,
        declaration_hash=canonical_json_sha256(document.model_dump(mode="json")),
        path=declaration_path,
    )


def resolve_lane_recovery(
    lane_id: str,
    *,
    declarations: LaneRecoveryDeclarations | None = None,
    freedom: DesignFreedomDeclaration | None = None,
) -> LaneRecoveryPlan:
    """Resolve one lane's declared recovery dimensions against design freedom.

    A lane that is undeclared, declared without an explorer, or declared with
    dimensions that design freedom disables is resolved as unsupported so the
    caller stops instead of exploring an undeclared change.
    """
    loaded = declarations or load_lane_recovery_declarations()
    declaration = loaded.lane(lane_id)
    if declaration is None:
        return LaneRecoveryPlan(
            lane_id=lane_id,
            supported=False,
            explorer="none",
            dimensions=(),
            next_step_action=(
                "Declare this lane in contracts/lane-recovery-declaration.json "
                "before requesting recovery."
            ),
            reason=f"lane {lane_id!r} has no recovery declaration",
            declaration_hash=loaded.declaration_hash,
        )
    if declaration.explorer == "none":
        return LaneRecoveryPlan(
            lane_id=lane_id,
            supported=False,
            explorer="none",
            dimensions=(),
            next_step_action=declaration.next_step_action,
            reason=declaration.unsupported_reason,
            declaration_hash=loaded.declaration_hash,
        )
    freedom_declaration = freedom or load_design_freedom_declaration()
    enabled = {
        item.dimension_id: item.search_enabled
        for item in freedom_declaration.dimensions
    }
    disabled = sorted(
        dimension
        for dimension in declaration.recovery_dimensions
        if not enabled.get(dimension, False)
    )
    if disabled:
        return LaneRecoveryPlan(
            lane_id=lane_id,
            supported=False,
            explorer="none",
            dimensions=(),
            next_step_action=declaration.next_step_action,
            reason=(
                "declared recovery dimensions are not searchable in design freedom: "
                + ", ".join(disabled)
            ),
            declaration_hash=loaded.declaration_hash,
        )
    return LaneRecoveryPlan(
        lane_id=lane_id,
        supported=True,
        explorer=declaration.explorer,
        dimensions=tuple(sorted(declaration.recovery_dimensions)),
        next_step_action=declaration.next_step_action,
        reason=None,
        declaration_hash=loaded.declaration_hash,
    )


__all__ = [
    "LaneRecoveryDeclarationError",
    "LaneRecoveryDeclarations",
    "LaneRecoveryPlan",
    "load_lane_recovery_declarations",
    "resolve_lane_recovery",
]
