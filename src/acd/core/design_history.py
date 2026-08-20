"""Git history extraction for design knowledge answers.

Git is authoritative for "when and why did this change": the history entries are
read from the repository instead of being restated in a document. Git is invoked
as a subprocess and every failure resolves to no history, so an answering path
reports ``unknown`` rather than presenting an empty history as "never changed".
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from acd.core.knowledge_qa import HistoryEntry

# Field separator for the machine-readable git log format.
_RECORD_SEPARATOR = "\x1e"
_FIELD_SEPARATOR = "\x1f"
# The record separator leads each record so the name list of a record stays
# inside that record instead of leaking into the next one.
_LOG_FORMAT = f"{_RECORD_SEPARATOR}%H{_FIELD_SEPARATOR}%s"
DEFAULT_HISTORY_LIMIT = 20


def _git(repo_root: Path, arguments: Sequence[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            capture_output=True,
            # Git emits UTF-8 regardless of the process locale, so the encoding
            # is pinned instead of inherited from the ambient locale.
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, ValueError, UnicodeError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def resolve_head_commit(repo_root: Path) -> str | None:
    """Return the resolved HEAD commit, or None when git is unavailable."""
    output = _git(repo_root, ["rev-parse", "HEAD"])
    if output is None:
        return None
    commit = output.strip()
    return commit or None


def graph_revision_at(repo_root: Path, commit: str, graph_path: str) -> str | None:
    """Return the design graph revision as of a commit, or None when unreadable."""
    output = _git(repo_root, ["show", f"{commit}:{graph_path}"])
    if output is None:
        return None
    try:
        payload: object = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    fields = cast(dict[str, object], payload)
    revision = fields.get("revision")
    return revision if isinstance(revision, str) and revision else None


def design_input_history(
    repo_root: Path,
    paths: Sequence[str],
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
    graph_path: str | None = None,
) -> tuple[HistoryEntry, ...]:
    """Return the recent commits that touched the given design input paths.

    When ``graph_path`` is given, each entry also carries the graph revision as
    of that commit, so an answer can report the revision transition of a change.
    """
    if not paths or limit <= 0:
        return ()
    output = _git(
        repo_root,
        [
            "log",
            f"--max-count={limit}",
            f"--pretty=format:{_LOG_FORMAT}",
            "--name-only",
            "--",
            *paths,
        ],
    )
    if output is None:
        return ()
    entries: list[HistoryEntry] = []
    for record in output.split(_RECORD_SEPARATOR):
        stripped = record.strip("\n")
        if not stripped.strip():
            continue
        header, _, names = stripped.partition("\n")
        commit, separator, subject = header.partition(_FIELD_SEPARATOR)
        if not separator or not commit.strip() or not subject.strip():
            continue
        changed = tuple(sorted({line for line in names.splitlines() if line.strip()}))
        resolved = commit.strip()
        entries.append(
            HistoryEntry(
                commit=resolved,
                subject=subject.strip(),
                changed_paths=changed,
                revision=(
                    graph_revision_at(repo_root, resolved, graph_path)
                    if graph_path is not None
                    else None
                ),
            )
        )
    return tuple(entries)
