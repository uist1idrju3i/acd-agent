"""Inject deterministic external tool probe results into the session."""

from __future__ import annotations

import json
import os
import subprocess

from common import event, project_dir, result


def main() -> int:
    root = project_dir(event())
    try:
        completed = subprocess.run(
            ["uv", "run", "--project", str(root), "python", "scripts/probe_tools.py"],
            cwd=root, text=True, capture_output=True, timeout=120, env=os.environ.copy(),
        )
        report = json.loads(completed.stdout)
        versions = ", ".join(f"{item['tool_name']}={item['version']}" for item in report["results"])
        unknown = any(item["version"] == "unknown" for item in report["results"])
        context = f"External tool probe: {versions}."
        if unknown:
            context += " Unknown or missing tools mean relevant gates fail-closed."
        if completed.returncode != 0:
            context += " Probe failed; relevant gates fail-closed."
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, TypeError):
        context = "External tool probe failed; relevant gates fail-closed."
    result(additionalContext=context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
