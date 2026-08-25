"""Prevent stopping with changed design inputs before their gate runs.

Stopping is permitted in two cases only. Either a newer valid Evidence record
covers every changed design input, or a stop report declares the fail-closed
state explicitly (failure reason, failed stage, and absent Evidence). Neither
case grants pass authority: a permitted stop keeps the design in its failed or
unknown state. Repeated identical denials escalate to a human handoff so the
agent cannot loop on the same denial, and the escalated stop still reports the
failure state.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

from common import event, project_dir, result

STOP_REPORT_PATH = "out/stop-report.json"
DENIAL_STATE_PATH = "out/stop-denials.json"
REPEATED_DENIAL_LIMIT = 3
REQUIRED_REPORT_FIELDS = ("failure_reason", "failed_stage")


def main() -> int:
    root = project_dir(event())
    try:
        changed = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return _deny(
            root,
            "Design input state is unknown; run the relevant gate before stopping.",
        )
    design_inputs = [
        root / path
        for path in (
            line[3:] for line in changed.splitlines() if len(line) > 3
        )
        if (path.startswith("fixtures/") and path.endswith("/graph.json"))
        or path.startswith("profiles/")
    ]
    if not design_inputs:
        _clear_denials(root)
        return 0
    missing_inputs = [path for path in design_inputs if not path.exists()]
    if missing_inputs:
        causes = ", ".join(str(path.relative_to(root)) for path in missing_inputs)
        return _deny(root, f"Changed design input paths cannot be resolved: {causes}.")
    evidence_paths = _evidence_paths(root)
    newest_input = max(path.stat().st_mtime for path in design_inputs)
    has_recent_evidence = any(
        path.stat().st_mtime > newest_input for path in evidence_paths
    )
    if has_recent_evidence and _valid_evidence(root):
        _clear_denials(root)
        return 0
    report_reason = _stop_report_reason(root, newest_input)
    if report_reason is not None:
        _clear_denials(root)
        result(
            decision="allow",
            reason=(
                f"Stopping is permitted on the declared fail-closed state: "
                f"{report_reason} This permission grants no pass authority; the "
                "design remains failed until a gate produces valid Evidence."
            ),
        )
        return 0
    causes = ", ".join(str(path.relative_to(root)) for path in design_inputs)
    return _deny(
        root,
        (
            f"Changed design inputs require a newer valid evidence record: {causes}. "
            "Run the relevant pipeline gate, or record the fail-closed state in "
            f"{STOP_REPORT_PATH} with failure_reason, failed_stage, and "
            "evidence_absent."
        ),
    )


def _stop_report_reason(root: Path, newest_input: float) -> str | None:
    path = root / STOP_REPORT_PATH
    try:
        # The report must not predate the newest design input change. Filesystem
        # timestamps can be equal for writes in the same tick, so an equal
        # timestamp still counts as current.
        if path.stat().st_mtime < newest_input:
            return None
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    report = cast(dict[str, Any], payload)
    if report.get("status") not in ("failed", "unknown"):
        return None
    if report.get("evidence_absent") is not True:
        return None
    fields = [report.get(name) for name in REQUIRED_REPORT_FIELDS]
    if any(not isinstance(value, str) or not value.strip() for value in fields):
        return None
    reason, stage = (str(value).strip() for value in fields)
    return f"stage {stage} failed: {reason}."


def _deny(root: Path, reason: str) -> int:
    count = _record_denial(root, reason)
    if count > REPEATED_DENIAL_LIMIT:
        result(
            decision="allow",
            reason=(
                f"The same stop denial repeated {count} times: {reason} "
                "Escalating to a human handoff. The design state remains failed "
                "or unknown and no gate has passed."
            ),
            escalation="human_handoff",
        )
        return 0
    result(decision="deny", reason=reason)
    return 2


def _denial_state_path(root: Path) -> Path:
    return root / DENIAL_STATE_PATH


def _record_denial(root: Path, reason: str) -> int:
    path = _denial_state_path(root)
    previous: dict[str, Any] = {}
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            previous = cast(dict[str, Any], loaded)
    except (OSError, ValueError, json.JSONDecodeError):
        previous = {}
    count = 1
    if previous.get("reason") == reason and isinstance(previous.get("count"), int):
        count = int(previous["count"]) + 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"reason": reason, "count": count}, ensure_ascii=True),
            encoding="utf-8",
        )
    except OSError:
        return count
    return count


def _clear_denials(root: Path) -> None:
    try:
        _denial_state_path(root).unlink(missing_ok=True)
    except OSError:
        return


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
