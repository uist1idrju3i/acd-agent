"""Deterministic Q7 aggregations over gate findings.

The aggregations reorganize findings that already exist (ERC/DRC violations, DFM
notes, review findings, measurements). They rank and stratify; they never decide
pass or fail, and they never assert a cause.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParetoRow:
    """One category of a Pareto ranking."""

    category: str
    count: int
    ratio: float
    cumulative_ratio: float


@dataclass(frozen=True)
class Stratum:
    """One stratum and the finding counts inside it."""

    key: str
    count: int
    categories: dict[str, int]


def _counts(findings: Iterable[Mapping[str, object]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        value = finding.get(field)
        if value is None:
            raise ValueError(f"finding is missing the field {field!r}: {finding!r}")
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def pareto(findings: Sequence[Mapping[str, object]], *, field: str = "category") -> list[ParetoRow]:
    """Rank findings by count, descending, with cumulative ratios.

    Ties are broken by category name so the output is reproducible.
    """
    counts = _counts(findings, field)
    total = sum(counts.values())
    if total == 0:
        return []
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    rows: list[ParetoRow] = []
    cumulative = 0
    for category, count in ordered:
        cumulative += count
        rows.append(
            ParetoRow(
                category=category,
                count=count,
                ratio=count / total,
                cumulative_ratio=cumulative / total,
            )
        )
    return rows


def stratify(
    findings: Sequence[Mapping[str, object]],
    *,
    by: str,
    field: str = "category",
) -> list[Stratum]:
    """Split findings by one field and count categories inside each stratum."""
    groups: dict[str, list[Mapping[str, object]]] = {}
    for finding in findings:
        value = finding.get(by)
        if value is None:
            raise ValueError(f"finding is missing the field {by!r}: {finding!r}")
        groups.setdefault(str(value), []).append(finding)
    return [
        Stratum(key=key, count=len(group), categories=_counts(group, field))
        for key, group in sorted(groups.items())
    ]


def main(argv: Sequence[str]) -> int:
    """Read a JSON list of findings from a path (or stdin) and print a Pareto ranking."""
    text = (
        sys.stdin.read() if len(argv) < 2 else Path(argv[1]).read_text(encoding="utf-8")
    )
    findings = json.loads(text)
    rows = [
        {
            "category": row.category,
            "count": row.count,
            "ratio": round(row.ratio, 6),
            "cumulative_ratio": round(row.cumulative_ratio, 6),
        }
        for row in pareto(findings)
    ]
    print(json.dumps({"pareto": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
