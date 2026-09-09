"""Prevent stopping with changed design inputs before their gate runs.

Stopping is permitted in two cases only. Either a newer valid Evidence record
covers every changed design input, or a stop report declares the fail-closed
state explicitly (failure reason, failed stage, and absent Evidence). Neither
case grants pass authority: a permitted stop keeps the design in its failed or
unknown state. Repeated identical denials escalate to a human handoff so the
agent cannot loop on the same denial, and the escalated stop still reports the
failure state.

Stopping also requires the bootstrap record written by /acd:init
(``acd_bootstrap_workspace``): without ``.openhands/bootstrap-record.json`` the
source revision drift check cannot run, so the stop is denied unless the stop
report declares ``bootstrap_record_missing: true``. The declaration permits the
stop but grants no pass authority; the missing record keeps every produced
artifact provisional.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, cast

from common import STOP_REPORT_PATH, event, project_dir, result

DENIAL_STATE_PATH = "out/stop-denials.json"
REPEATED_DENIAL_LIMIT = 3
REQUIRED_REPORT_FIELDS = ("failure_reason", "failed_stage")
BOOTSTRAP_RECORD_PATH = ".openhands/bootstrap-record.json"
DRIFT_LOG_PATHS = ("src", "scripts", "plugins", "pyproject.toml", "uv.lock", "docker")
DRIFT_LOG_MAX_CHARS = 4000
_DRIFT_COMMIT_LINE = re.compile(r"^([0-9a-f]{40}) ", re.MULTILINE)


def main() -> int:
    root = project_dir(event())
    revision = _bootstrap_revision(root)
    bootstrap_missing_declared = False
    if revision is None:
        report = _load_stop_report(root)
        if report is not None and report.get("bootstrap_record_missing") is True:
            bootstrap_missing_declared = True
        else:
            return _deny(
                root,
                (
                    "No bootstrap record at .openhands/bootstrap-record.json: "
                    "this project dir was not prepared by /acd:init "
                    "(acd_bootstrap_workspace), so source revision drift "
                    "cannot be checked. Move to the bootstrapped workspace, or "
                    "declare bootstrap_record_missing: true in "
                    f"{STOP_REPORT_PATH} before stopping; the missing record "
                    "grants no pass authority."
                ),
            )
    drift = _source_drift(root, revision) if revision is not None else None
    drift_allowed: tuple[str, str, list[str]] | None = None
    if drift is not None:
        record_sha, detail, commit_shas = drift
        report = _load_stop_report(root)
        recorded = report.get("source_revision_drift") if report is not None else None
        if (
            isinstance(recorded, str)
            and recorded.strip()
            and all(sha in recorded for sha in commit_shas)
        ):
            drift_allowed = drift
        else:
            preview = "\n".join(detail.splitlines()[:5])
            return _deny(
                root,
                (
                    "Source revision deviates from the bootstrap record "
                    f"{record_sha}: {preview}. Record the full `git log --stat "
                    f"{record_sha}..HEAD` output as source_revision_drift in "
                    f"{STOP_REPORT_PATH} before stopping; the deviation grants "
                    "no pass authority."
                ),
            )
    try:
        changed = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            text=True,
            encoding="utf-8",
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
        if drift_allowed is not None:
            record_sha, _detail, commit_shas = drift_allowed
            reason = (
                "Stopping with recorded source revision drift from "
                f"bootstrap {record_sha}: {len(commit_shas)} commit(s) "
                "under source paths. No pass authority is granted."
            )
            if bootstrap_missing_declared:
                reason += (
                    " Additionally, bootstrap record missing was declared; "
                    "no pass authority is granted."
                )
            result(decision="allow", reason=reason)
        elif bootstrap_missing_declared:
            result(
                decision="allow",
                reason=(
                    "Stopping is permitted: bootstrap record missing was "
                    "declared; no pass authority is granted."
                ),
            )
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


def _load_stop_report(root: Path) -> dict[str, Any] | None:
    path = root / STOP_REPORT_PATH
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, Any], payload)


def _bootstrap_revision(root: Path) -> str | None:
    """Return the revision recorded by the bootstrap record, else ``None``.

    ``None`` means the record is missing, unreadable, or has no
    ``resolved_revision``: the drift check cannot run and the caller decides
    whether the stop may proceed.
    """
    record_path = root / BOOTSTRAP_RECORD_PATH
    try:
        payload: Any = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    record = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
    revision = record.get("resolved_revision")
    if not isinstance(revision, str) or not revision:
        return None
    return revision


def _source_drift(
    root: Path, revision: str
) -> tuple[str, str, list[str]] | None:
    """Return (bootstrap sha, git log output, commit shas) when commits under
    the source paths exist past the bootstrapped revision, else ``None``.
    """
    try:
        log = subprocess.run(
            [
                "git",
                "log",
                "--stat",
                "--format=%H%x20%s",
                f"{revision}..HEAD",
                "--",
                *DRIFT_LOG_PATHS,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError:
        return (
            revision,
            f"bootstrap revision {revision} is not an ancestor of HEAD",
            [],
        )
    if log.returncode != 0:
        return (
            revision,
            f"bootstrap revision {revision} is not an ancestor of HEAD",
            [],
        )
    output = log.stdout.strip()
    if not output:
        return None
    commit_shas = [
        match.group(1) for match in _DRIFT_COMMIT_LINE.finditer(output)
    ]
    if len(output) > DRIFT_LOG_MAX_CHARS:
        output = output[:DRIFT_LOG_MAX_CHARS]
    return revision, output, commit_shas


def _stop_report_reason(root: Path, newest_input: float) -> str | None:
    path = root / STOP_REPORT_PATH
    try:
        # The report must not predate the newest design input change. Filesystem
        # timestamps can be equal for writes in the same tick, so an equal
        # timestamp still counts as current.
        if path.stat().st_mtime < newest_input:
            return None
    except OSError:
        return None
    report = _load_stop_report(root)
    if report is None:
        return None
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
