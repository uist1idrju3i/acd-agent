"""Require passing evidence before external order or transmission commands."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, cast

from common import event, project_dir, result, revision


def main() -> int:
    payload = event()
    root = project_dir(payload)
    plugin_root = os.environ.get("ACD_PLUGIN_ROOT")
    policy_path = (
        Path(plugin_root) / "hooks/order-policy.json"
        if plugin_root
        else Path(__file__).resolve().parents[1] / "order-policy.json"
    )
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        transmission = policy["transmission_commands"]
        artifact_paths = policy["artifact_paths"]
        order_commands = policy["order_commands"]
        evidence_pattern = policy["evidence_paths"]
        graph_paths = policy["design_graph_paths"]
        required_ids = policy["required_evidence_ids"]
        if not all(
            isinstance(value, list)
            for value in (
                transmission,
                artifact_paths,
                graph_paths,
                order_commands,
                required_ids,
            )
        ) or not isinstance(evidence_pattern, str):
            raise ValueError("invalid policy")
        transmission = cast(list[object], transmission)
        artifact_paths = cast(list[object], artifact_paths)
        graph_paths = cast(list[object], graph_paths)
        order_commands = cast(list[object], order_commands)
        required_ids = cast(list[object], required_ids)
        if not all(isinstance(path, str) for path in graph_paths):
            raise ValueError("invalid graph paths")
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError):
        result(decision="deny", reason="Order policy is unavailable or invalid; operation denied.")
        return 2
    tool_input: Any = payload.get("tool_input")
    command = (
        cast(dict[str, Any], tool_input).get("command", "")
        if isinstance(tool_input, dict)
        else ""
    )
    if not isinstance(command, str):
        return 0
    try:
        tokens = shlex.split(command)
    except ValueError:
        is_order = any(
            isinstance(pattern, str) and pattern in command for pattern in order_commands
        )
        is_transmission = any(
            isinstance(pattern, str) and pattern in command for pattern in transmission
        )
        if not is_order and not (is_transmission and "out/" in command):
            return 0
        result(
            decision="deny",
            reason="A passing gate evidence for the current revision is required.",
        )
        return 2
    is_order = any(
        isinstance(pattern, str) and pattern in command for pattern in order_commands
    )
    is_transmission = any(
        isinstance(pattern, str)
        and any(Path(token).name == pattern for token in tokens)
        for pattern in transmission
    )
    artifact = any(
        _is_artifact_token(token, root, artifact_paths) for token in tokens
    )
    if not is_order and not (is_transmission and artifact):
        return 0
    current = revision(root, cast(list[str], graph_paths))
    evidence = sorted(root.glob(evidence_pattern))
    if current is None or not evidence:
        result(
            decision="deny",
            reason="A passing gate evidence for the current revision is required.",
        )
        return 2
    try:
        required_args = [
            argument
            for evidence_id in required_ids
            if isinstance(evidence_id, str)
            for argument in ("--require-id", evidence_id)
        ]
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(root),
                "acd-evidence-check",
                "--revision",
                current,
                *[argument for path in evidence for argument in ("--evidence", str(path))],
                *required_args,
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


def _is_artifact_token(token: str, root: Path, patterns: list[object]) -> bool:
    if token.startswith(("http://", "https://")):
        return False
    candidate = Path(token)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.resolve(strict=False).relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    if relative.parts and relative.parts[0] == "out":
        return True
    relative_text = relative.as_posix()
    return any(
        isinstance(pattern, str)
        and (
            fnmatch(relative_text, pattern)
            or (
                "/**/" in pattern
                and fnmatch(relative_text, pattern.replace("/**/", "/"))
            )
        )
        for pattern in patterns
    )


if __name__ == "__main__":
    raise SystemExit(main())
