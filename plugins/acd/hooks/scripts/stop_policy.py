"""Prevent stopping with changed design inputs before their gate runs."""

from __future__ import annotations

import subprocess

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
    inputs = tuple(line[3:] for line in changed.splitlines() if len(line) > 3)
    if any(
        (path.startswith("fixtures/") and path.endswith("/graph.json"))
        or path.startswith("profiles/")
        for path in inputs
    ):
        result(
            decision="deny",
            reason=(
                "Run the relevant pipeline gate or revert the design-input changes "
                "before stopping."
            ),
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
