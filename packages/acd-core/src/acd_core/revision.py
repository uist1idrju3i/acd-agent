"""Design-graph revision handling."""

from __future__ import annotations

import re

_REVISION_RE = re.compile(r"^r([0-9]+)$")


def revision_number(revision: str) -> int:
    match = _REVISION_RE.match(revision)
    if match is None:
        raise ValueError(f"invalid revision: {revision!r}")
    return int(match.group(1))


def next_revision(revision: str) -> str:
    return f"r{revision_number(revision) + 1}"
