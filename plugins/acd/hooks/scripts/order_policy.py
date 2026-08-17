"""Require passing evidence before external order or transmission commands."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import cast

from common import event, project_dir, result, revision, strings


def main() -> int:
    payload = event()
    root = project_dir(payload)
    policy_path = Path(__file__).resolve().parents[1] / "order-policy.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        raw_commands = policy["commands"]
        evidence = root / policy["evidence"]
        if not isinstance(raw_commands, list) or not isinstance(policy["evidence"], str):
            raise ValueError("invalid policy")
        commands = cast(list[object], raw_commands)
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError):
        result(decision="deny", reason="Order policy is unavailable or invalid; operation denied.")
        return 2
    command = " ".join(strings(payload.get("tool_input")))
    if not any(isinstance(pattern, str) and pattern in command for pattern in commands):
        return 0
    current = revision(root)
    if current is None or not evidence.exists():
        result(
            decision="deny",
            reason="A passing gate evidence for the current revision is required.",
        )
        return 2
    try:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(root),
                "acd-evidence-check",
                "--revision",
                current,
                "--evidence",
                str(evidence),
            ],
            cwd=root, text=True, capture_output=True, timeout=120, env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired):
        completed = None
    if completed is None or completed.returncode != 0:
        result(
            decision="deny",
            reason="A passing gate evidence for the current revision is required.",
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
