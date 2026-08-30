"""Require passing evidence before external order or transmission commands."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, cast

from common import event, project_dir, result, revision


def main() -> int:
    payload = event()
    root = project_dir(payload)
    policy_path = Path(__file__).resolve().parents[1] / "order-policy.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        transmission = policy["transmission_commands"]
        artifact_paths = policy["artifact_paths"]
        order_commands = policy["order_commands"]
        evidence_pattern = policy["evidence_paths"]
        graph_roots = policy["design_graph_roots"]
        required_lanes = policy["required_evidence_lanes"]
        if not all(
            isinstance(value, list)
            for value in (
                transmission,
                artifact_paths,
                graph_roots,
                order_commands,
                required_lanes,
            )
        ) or not isinstance(evidence_pattern, str):
            raise ValueError("invalid policy")
        transmission = cast(list[object], transmission)
        artifact_paths = cast(list[object], artifact_paths)
        graph_roots = cast(list[object], graph_roots)
        order_commands = cast(list[object], order_commands)
        required_lanes = cast(list[object], required_lanes)
        if not all(isinstance(path, str) for path in graph_roots):
            raise ValueError("invalid graph roots")
        graph_roots = [path for path in graph_roots if isinstance(path, str)]
        if (
            not graph_roots
            or len(graph_roots) != len(set(graph_roots))
            or any(
                path.startswith("/")
                or path.endswith("/")
                or "\\" in path
                or ".." in path.split("/")
                or any(not part for part in path.split("/"))
                for path in graph_roots
            )
        ):
            raise ValueError("invalid graph roots")
        if not all(lane in {"electrical", "mechanical"} for lane in required_lanes):
            raise ValueError("invalid evidence lanes")
        required_lanes = [lane for lane in required_lanes if isinstance(lane, str)]
        if len(required_lanes) < 2 or len(required_lanes) != len(set(required_lanes)):
            raise ValueError("invalid evidence lanes")
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
    graph_paths = _graph_paths(root, graph_roots)
    if len(graph_paths) != 1:
        result(
            decision="deny",
            reason="A single design graph under the policy roots is required.",
        )
        return 2
    graph_id = _graph_id(root / graph_paths[0])
    if graph_id is None:
        result(
            decision="deny",
            reason="The design graph under the policy roots is invalid.",
        )
        return 2
    required_ids = [
        _evidence_id(graph_id, lane)
        for lane in required_lanes
    ]
    current = revision(root, graph_paths)
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


def _graph_paths(root: Path, graph_roots: list[str]) -> list[str]:
    paths: set[str] = set()
    for graph_root in graph_roots:
        root_path = root / graph_root
        for path in root_path.glob("**/graph.json"):
            try:
                relative = path.resolve().relative_to(root.resolve()).as_posix()
            except (OSError, ValueError):
                continue
            if _is_design_input(relative):
                paths.add(relative)
    return sorted(paths)


def _graph_id(path: Path) -> str | None:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    payload = cast(dict[str, object], payload)
    graph_id = payload.get("graph_id")
    return graph_id if isinstance(graph_id, str) and graph_id else None


def _evidence_id(graph_id: str, lane: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", graph_id.strip().lower()).strip("-")
    prefix = "gd1" if normalized == "golden-design-1" else normalized
    return f"evidence.{prefix}.{lane}"


def _is_design_input(path: str) -> bool:
    return (
        (path.startswith("fixtures/") and path.endswith("/graph.json"))
        or path.startswith("profiles/")
    )


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
