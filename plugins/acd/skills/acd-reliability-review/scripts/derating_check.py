"""Three-valued derating screening for declared part stresses.

Each item declares a rating, the derating factor taken from a version-controlled
criteria table, the worst-case applied stress, and the validity domain of the
table row. The verdict is one of:

- ``pass``: worst-case stress is within rating x factor and the declared
  conditions are inside the table's validity domain;
- ``needs_analysis``: the input is outside the validity domain, or a rating,
  factor, or condition is missing — recommended values screen, they do not
  decide, so this closes only with analysis evidence;
- ``fail``: worst-case stress exceeds rating x factor inside the validity
  domain.

Screening is advisory. ACD gates decide design pass/fail, and a ``pass`` here is
not an ACD gate result.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

Verdict = Literal["pass", "needs_analysis", "fail"]


@dataclass(frozen=True)
class DeratingResult:
    """Screening result for one part parameter."""

    refdes: str
    parameter: str
    verdict: Verdict
    allowed: float | None
    applied: float | None
    margin_ratio: float | None
    reason: str


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(Mapping[str, object], value)


def _pair(value: object) -> tuple[object, object] | None:
    if isinstance(value, str) or not isinstance(value, Sequence):
        return None
    items = cast(Sequence[object], value)
    if len(items) != 2:
        return None
    return items[0], items[1]


def _domain_reason(item: Mapping[str, object]) -> str | None:
    if item.get("validity_domain") is None:
        return "validity domain is not declared"
    domain = _mapping(item.get("validity_domain"))
    if domain is None:
        return "validity domain is not a mapping"
    conditions = _mapping(item.get("conditions"))
    if conditions is None:
        return "applied conditions are not declared"
    for name, bounds in domain.items():
        value = _number(conditions.get(name))
        if value is None:
            return f"condition {name!r} is unknown"
        pair = _pair(bounds)
        if pair is None:
            return f"validity domain of {name!r} is not a [low, high] pair"
        low = _number(pair[0])
        high = _number(pair[1])
        if low is None or high is None:
            return f"validity domain of {name!r} is not numeric"
        if not low <= value <= high:
            return f"condition {name!r}={value} is outside [{low}, {high}]"
    return None


def evaluate_item(item: Mapping[str, object]) -> DeratingResult:
    """Screen one declared part parameter."""
    refdes = str(item.get("refdes", ""))
    parameter = str(item.get("parameter", ""))
    if not refdes or not parameter:
        raise ValueError(f"item must declare refdes and parameter: {item!r}")

    rating = _number(item.get("rating"))
    factor = _number(item.get("derating_factor"))
    applied = _number(item.get("applied_worst_case"))
    if rating is None or factor is None or applied is None:
        return DeratingResult(
            refdes=refdes,
            parameter=parameter,
            verdict="needs_analysis",
            allowed=None,
            applied=applied,
            margin_ratio=None,
            reason="rating, derating factor, or worst-case stress is unknown",
        )
    if not 0.0 < factor <= 1.0:
        raise ValueError(f"derating factor must be in (0, 1]: {item!r}")

    allowed = rating * factor
    margin_ratio = applied / allowed if allowed != 0 else None
    domain_reason = _domain_reason(item)
    if domain_reason is not None:
        return DeratingResult(
            refdes=refdes,
            parameter=parameter,
            verdict="needs_analysis",
            allowed=allowed,
            applied=applied,
            margin_ratio=margin_ratio,
            reason=domain_reason,
        )
    if applied > allowed:
        return DeratingResult(
            refdes=refdes,
            parameter=parameter,
            verdict="fail",
            allowed=allowed,
            applied=applied,
            margin_ratio=margin_ratio,
            reason="worst-case stress exceeds rating x derating factor",
        )
    return DeratingResult(
        refdes=refdes,
        parameter=parameter,
        verdict="pass",
        allowed=allowed,
        applied=applied,
        margin_ratio=margin_ratio,
        reason="worst-case stress is within rating x derating factor",
    )


def evaluate(items: Sequence[Mapping[str, object]]) -> list[DeratingResult]:
    """Screen every declared part parameter, sorted by refdes then parameter."""
    results = [evaluate_item(item) for item in items]
    return sorted(results, key=lambda result: (result.refdes, result.parameter))


def main(argv: Sequence[str]) -> int:
    """Read a JSON list of declared stresses from a path (or stdin) and print verdicts."""
    text = (
        sys.stdin.read() if len(argv) < 2 else Path(argv[1]).read_text(encoding="utf-8")
    )
    results = evaluate(json.loads(text))
    payload = [
        {
            "refdes": result.refdes,
            "parameter": result.parameter,
            "verdict": result.verdict,
            "allowed": result.allowed,
            "applied": result.applied,
            "margin_ratio": None if result.margin_ratio is None else round(result.margin_ratio, 6),
            "reason": result.reason,
        }
        for result in results
    ]
    print(json.dumps({"derating": payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
