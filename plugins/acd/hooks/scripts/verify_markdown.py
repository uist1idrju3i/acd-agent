"""Run documentation verification after Markdown edits without blocking."""

from __future__ import annotations

import os
import subprocess

from common import event, project_dir, result, strings


def main() -> int:
    payload = event()
    if not any(
        value.lower().endswith(".md") or ".md/" in value.lower()
        for value in strings(payload.get("tool_input"))
    ):
        return 0
    root = project_dir(payload)
    try:
        completed = subprocess.run(
            ["uv", "run", "--project", str(root), "python", "scripts/verify_docs.py"],
            cwd=root,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=120,
            env=os.environ.copy(),
        )
        detail = (completed.stdout + completed.stderr).strip()[-2000:]
        result(
            additionalContext=f"Documentation verification exit={completed.returncode}: {detail}"
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result(additionalContext=f"Documentation verification could not run: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
