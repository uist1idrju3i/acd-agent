#!/usr/bin/env python3
"""Verify that repository Dockerfiles parse as well-formed instruction sequences.

BuildKit only reports broken line continuations when an image is actually built,
which for this repository happens in the publish workflow on ``main``. This check
reproduces the instruction-level parse (comments, ``\\`` continuations, heredocs
and the instruction keyword vocabulary) so a dropped trailing backslash fails the
fast verification stage instead of the image publish.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE_GLOBS = ("docker/**/*Dockerfile*",)
INSTRUCTIONS = frozenset(
    {
        "ADD",
        "ARG",
        "CMD",
        "COPY",
        "ENTRYPOINT",
        "ENV",
        "EXPOSE",
        "FROM",
        "HEALTHCHECK",
        "LABEL",
        "MAINTAINER",
        "ONBUILD",
        "RUN",
        "SHELL",
        "STOPSIGNAL",
        "USER",
        "VOLUME",
        "WORKDIR",
    }
)
_HEREDOC = re.compile(r"<<-?\s*['\"]?(?P<word>[A-Za-z_][A-Za-z0-9_]*)['\"]?")


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    detail: str

    def format(self) -> str:
        return f"{self.path.relative_to(REPO_ROOT)}:{self.line}: {self.detail}"


def dockerfiles(root: Path = REPO_ROOT) -> list[Path]:
    return sorted(
        path for pattern in DOCKERFILE_GLOBS for path in root.glob(pattern) if path.is_file()
    )


def check_dockerfile(path: Path) -> list[Violation]:
    """Return one violation per instruction line that BuildKit would reject."""
    violations: list[Violation] = []
    lines = path.read_text(encoding="utf-8").split("\n")
    continuation = False
    heredoc_terminators: list[str] = []
    for number, raw in enumerate(lines, start=1):
        if heredoc_terminators:
            if raw.strip() == heredoc_terminators[0]:
                heredoc_terminators.pop(0)
            continue
        stripped = raw.strip()
        if not stripped or (stripped.startswith("#") and not continuation):
            continue
        if continuation:
            if stripped.startswith("#"):
                continue
        else:
            keyword = stripped.split(maxsplit=1)[0].upper()
            if keyword not in INSTRUCTIONS:
                violations.append(
                    Violation(
                        path,
                        number,
                        f"unknown instruction {keyword!r}; the previous "
                        "instruction probably lost its trailing backslash",
                    )
                )
                continue
        body = stripped[:-1] if stripped.endswith("\\") else stripped
        heredoc_terminators.extend(match.group("word") for match in _HEREDOC.finditer(body))
        continuation = stripped.endswith("\\")
    if continuation:
        violations.append(Violation(path, len(lines), "file ends inside a line continuation"))
    return violations


def main(argv: list[str] | None = None) -> int:
    del argv
    files = dockerfiles()
    if not files:
        print("verify_dockerfiles: no Dockerfiles found")
        return 2
    violations = [violation for path in files for violation in check_dockerfile(path)]
    for violation in violations:
        print(violation.format())
    print(f"verify_dockerfiles: {len(files)} file(s) checked, {len(violations)} violation(s)")
    return 2 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
