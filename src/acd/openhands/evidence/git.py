"""Evidence checks using OpenHands SDK git observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from openhands.sdk.git.exceptions import GitError
from openhands.sdk.git.git_changes import get_git_changes

from acd.schema import Evidence


def check_evidence_with_git(
    evidence_path: Path,
    evidence_id: str,
    revision: str,
    repo_root: Path,
    *,
    ref: str | None = "HEAD",
) -> dict[str, Any]:
    """Check Evidence semantics and reject changed design inputs fail-closed."""
    try:
        evidence = Evidence.model_validate_json(
            evidence_path.read_text(encoding="utf-8")
        )
        if evidence.evidence_id != evidence_id:
            return {"passed": False, "reason": "evidence_id mismatch"}
        changed_paths = design_input_changes(repo_root, ref=ref)
        if changed_paths:
            return {
                "passed": False,
                "reason": "design input is stale",
                "changed_paths": list(changed_paths),
            }
        if not evidence.supports_authoritative_pass(revision):
            return {
                "passed": False,
                "reason": "evidence does not support authoritative revision",
            }
        return {"passed": True, "reason": "evidence supports revision"}
    except (OSError, ValueError, GitError) as exc:
        return {"passed": False, "reason": f"git evidence check failed: {exc}"}


def is_design_input(path: str) -> bool:
    return (
        (path.startswith("fixtures/") and path.endswith("/graph.json"))
        or path.startswith("profiles/")
    )


def design_input_changes(
    repo_root: Path,
    *,
    ref: str | None = "HEAD",
) -> tuple[str, ...]:
    """Return changed design-input paths using the SDK git observation."""
    changes = get_git_changes(repo_root, ref=ref)
    return tuple(
        sorted(
            str(change.path)
            for change in changes
            if is_design_input(str(change.path))
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("evidence_id")
    parser.add_argument("revision")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    result = check_evidence_with_git(
        args.evidence,
        args.evidence_id,
        args.revision,
        args.repo_root,
        ref=args.ref,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1
