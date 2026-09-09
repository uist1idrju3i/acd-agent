"""Source-tree git provenance for authoritative Evidence.

The container runner records which git revision of the source tree produced a
run and whether that tree was clean, so Evidence written inside the digest
locked container cannot silently diverge from the recorded revision. Any git
failure yields the ``unknown`` state instead of raising: callers decide whether
to refuse (the runner refuses a dirty tree unconditionally; ``allow_dirty``
only covers the unknown state) or to record the
unknown state (the envelope marks it and the verifier rejects it).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from acd.schema.tool_envelope import SourceTreeState

SOURCE_TREE_PATHS: tuple[str, ...] = (
    "src",
    "scripts",
    "plugins",
    "contracts",
    "libraries",
    "docker",
    "pyproject.toml",
    "uv.lock",
)

_GIT_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
_GIT_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class SourceProvenance:
    """Observed git state of the source tree that produced a run."""

    revision: str
    tree_state: SourceTreeState
    dirty_digest: str | None
    changed_paths: tuple[str, ...]


_UNKNOWN = SourceProvenance(
    revision="unknown",
    tree_state="unknown",
    dirty_digest=None,
    changed_paths=(),
)


def _git(
    repo: Path,
    args: Sequence[str],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    return run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )


def collect_source_provenance(
    repo: Path,
    *,
    paths: Sequence[str] = SOURCE_TREE_PATHS,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SourceProvenance:
    """Return the git provenance of ``repo`` restricted to the source tree.

    ``tree_state`` is ``"dirty"`` when ``git status --porcelain`` reports a
    change under ``paths``; the ``dirty_digest`` then pins the porcelain
    listing, the ``git diff HEAD`` output, and the bytes of every untracked
    file so the same dirty state reproduces the same digest. Any git failure —
    missing binary, non-git directory, non-zero exit, timeout — yields the
    unknown state; this helper never raises.
    """
    existing = [path for path in paths if (repo / path).exists()]
    try:
        head = _git(repo, ["rev-parse", "HEAD"], run=run)
        if head.returncode != 0:
            return _UNKNOWN
        revision = head.stdout.strip()
        if not _GIT_SHA.fullmatch(revision):
            return _UNKNOWN
        if not existing:
            return SourceProvenance(
                revision=revision,
                tree_state="clean",
                dirty_digest=None,
                changed_paths=(),
            )
        status = _git(
            repo,
            [
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                *existing,
            ],
            run=run,
        )
        if status.returncode != 0:
            return _UNKNOWN
        porcelain = status.stdout
        if not porcelain.strip():
            return SourceProvenance(
                revision=revision,
                tree_state="clean",
                dirty_digest=None,
                changed_paths=(),
            )
        diff = _git(repo, ["diff", "HEAD", "--", *existing], run=run)
        if diff.returncode != 0:
            return _UNKNOWN
        untracked = sorted(
            line[3:]
            for line in porcelain.splitlines()
            if line.startswith("?? ")
        )
        digest = hashlib.sha256()
        digest.update(porcelain.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(diff.stdout.encode("utf-8"))
        digest.update(b"\x00")
        for relative in untracked:
            candidate = repo / relative
            if not candidate.is_file():
                return _UNKNOWN
            digest.update(relative.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(candidate.read_bytes())
            digest.update(b"\x00")
        changed = tuple(
            sorted(line[3:] for line in porcelain.splitlines() if line.strip())
        )
        return SourceProvenance(
            revision=revision,
            tree_state="dirty",
            dirty_digest="sha256:" + digest.hexdigest(),
            changed_paths=changed,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _UNKNOWN


def source_provenance_env(provenance: SourceProvenance) -> dict[str, str]:
    """Return the environment variables that carry provenance into a container."""
    env = {
        "ACD_SOURCE_GIT_SHA": provenance.revision,
        "ACD_SOURCE_TREE_STATE": provenance.tree_state,
    }
    if provenance.tree_state == "dirty" and provenance.dirty_digest is not None:
        env["ACD_SOURCE_DIRTY_DIGEST"] = provenance.dirty_digest
    return env
