"""Prevent stopping with changed design inputs before their gate runs."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

from common import event, project_dir, result


def main() -> int:
    root = project_dir(event())
    try:
        changed = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        result(
            decision="deny",
            reason=(
                "Design input state is unknown; run the relevant gate or commit "
                "changes before generating evidence."
            ),
        )
        return 2
    design_inputs = [
        root / path
        for path in (
            line[3:] for line in changed.splitlines() if len(line) > 3
        )
        if (path.startswith("fixtures/") and path.endswith("/graph.json"))
        or path.startswith("profiles/")
    ]
    if design_inputs:
        missing_inputs = [
            path for path in design_inputs if not path.exists()
        ]
        if missing_inputs:
            causes = ", ".join(str(path.relative_to(root)) for path in missing_inputs)
            result(
                decision="deny",
                reason=f"Changed design input paths cannot be resolved: {causes}.",
            )
            return 2
        evidence_paths = _evidence_paths(root)
        newest_input = max(
            path.stat().st_mtime for path in design_inputs
        )
        has_recent_evidence = any(
            path.stat().st_mtime > newest_input for path in evidence_paths
        )
        has_recent_valid = has_recent_evidence and _valid_evidence(root)
        if has_recent_valid:
            return 0
        causes = ", ".join(str(path.relative_to(root)) for path in design_inputs)
        result(
            decision="deny",
            reason=(
                f"Changed design inputs require a newer valid evidence record: {causes}. "
                "Run the relevant pipeline gate, or commit changes before generating evidence."
            ),
        )
        return 2
    return 0


def _valid_evidence(root: Path) -> bool:
    try:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(root),
                "acd-evidence-check",
                *[
                    argument
                    for item in _evidence_paths(root)
                    for argument in ("--evidence", str(item))
                ],
                "--valid-only",
            ],
            cwd=root,
            capture_output=True,
            timeout=120,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _evidence_paths(root: Path) -> list[Path]:
    policy_path = Path(__file__).resolve().parents[1] / "order-policy.json"
    try:
        policy: Any = json.loads(policy_path.read_text(encoding="utf-8"))
        pattern = cast(dict[str, Any], policy)["evidence_paths"]
        if not isinstance(pattern, str):
            raise ValueError("invalid evidence path pattern")
    except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError):
        return []
    return sorted(root.glob(pattern))


if __name__ == "__main__":
    raise SystemExit(main())
