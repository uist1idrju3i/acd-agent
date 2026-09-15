# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@4cfc06874ae93b6e18bf22adcdabfcfff1140fd1",
# ]
# ///
"""Parse GCC stack usage and ESP-IDF size reports deterministically."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

_SU = re.compile(r"^(.*?):(\d+):(\d+):([^\t]+)\t(\d+)\t(static|dynamic|dynamic,bounded)$")


@dataclass(frozen=True)
class StackFunction:
    file: str
    line: int
    col: int
    function: str
    bytes: int
    kind: str


def parse_su(text: str, root: Path) -> list[StackFunction]:
    values: list[StackFunction] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        match = _SU.match(raw.strip())
        if match is None:
            raise ValueError(f"malformed .su line: {raw!r}")
        path = Path(match.group(1))
        try:
            file = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            file = path.as_posix()
        values.append(
            StackFunction(
                file=file,
                line=int(match.group(2)),
                col=int(match.group(3)),
                function=match.group(4),
                bytes=int(match.group(5)),
                kind=match.group(6),
            )
        )
    if not values:
        raise ValueError("no stack usage records")
    return sorted(values, key=lambda item: (item.file, item.line, item.col, item.function))


def parse_size_json(text: str) -> dict[str, int]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("idf size JSON must be an object")
    typed_data = cast(dict[str, object], data)
    result: dict[str, int] = {}
    for name in ("flash_bytes", "dram_bytes"):
        value = typed_data.get(name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"invalid {name}")
        result[name] = value
    if not result:
        raise ValueError("size JSON has no supported totals")
    return result


def evaluate_stack_usage(
    functions: list[StackFunction],
    *,
    task_budgets: dict[str, tuple[int, float]],
    size: dict[str, int],
    size_budgets: dict[str, int] | None = None,
) -> dict[str, object]:
    findings: list[str] = []
    dynamic_findings = [
            f"unbounded_dynamic_stack:{item.function}"
            for item in functions
            if item.kind == "dynamic"
    ]
    findings.extend(dynamic_findings)
    tasks: list[dict[str, object]] = []
    for task, (stack_bytes, margin_pct) in sorted(task_budgets.items()):
        worst = max(
            (
                item.bytes
                for item in functions
                if item.kind == "static" and item.file.startswith(task)
            ),
            default=0,
        )
        budget = stack_bytes * (1.0 - margin_pct / 100.0)
        status = "fail" if worst > budget else "pass"
        tasks.append(
            {
                "task": task,
                "stack_bytes": stack_bytes,
                "margin_pct": margin_pct,
                "worst_static_bytes": worst,
                "budget_bytes": budget,
                "status": status,
            }
        )
    if size_budgets:
        for name, budget in sorted(size_budgets.items()):
            if name in size and size[name] > budget:
                findings.append(f"{name}_budget_exceeded")
    budget_fail = any(item["status"] == "fail" for item in tasks) or any(
        name in size and size[name] > budget
        for name, budget in (size_budgets or {}).items()
    )
    status = "fail" if budget_fail else "unknown" if findings else "pass"
    return {
        "status": status,
        "authority": "estimate",
        "functions": [asdict(item) for item in functions],
        "tasks": tasks,
        "size": {
            **size,
            **{f"{key}_budget_bytes": value for key, value in (size_budgets or {}).items()},
            "status": "fail" if any(
                name in size and size[name] > budget
                for name, budget in (size_budgets or {}).items()
            ) else "pass",
        },
        "findings": sorted(findings),
    }


__all__ = ["StackFunction", "evaluate_stack_usage", "parse_size_json", "parse_su"]
