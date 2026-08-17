"""Prevent stopping with changed design inputs before their gate runs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

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
        evidence_paths = sorted(root.glob("out/**/evidence-*.json"))
        newest_input = max(
            path.stat().st_mtime for path in design_inputs
        )
        has_recent_valid = any(
            path.stat().st_mtime > newest_input and _valid_evidence(root, path)
            for path in evidence_paths
        )
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


def _valid_evidence(root: Path, path: Path) -> bool:
    try:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(root),
                "acd-evidence-check",
                "--revision",
                "unused-while-dirty",
                "--evidence",
                str(path),
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


if __name__ == "__main__":
    raise SystemExit(main())
