"""Tests for the Dockerfile instruction-sequence check."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import verify_dockerfiles

ROOT = Path(__file__).parents[2]


def test_repository_dockerfiles_pass(capsys: pytest.CaptureFixture[str]) -> None:
    assert verify_dockerfiles.main([]) == 0
    assert "0 violation(s)" in capsys.readouterr().out


def test_dropped_continuation_is_reported(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "FROM scratch\nRUN mkdir -p /opt \\\n    && python3 -c 'print(1)'\n    && rm -rf /tmp/x\n",
        encoding="utf-8",
    )
    violations = verify_dockerfiles.check_dockerfile(dockerfile)
    assert [(violation.line, violation.detail.split(";")[0]) for violation in violations] == [
        (4, "unknown instruction '&&'")
    ]


def test_comments_heredocs_and_continuations_are_accepted(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "# syntax=docker/dockerfile:1\n"
        "FROM scratch\n"
        "RUN set -eux \\\n"
        "    # comment inside continuation\n"
        "    && echo one \\\n"
        "\n"
        "    && echo two\n"
        "RUN <<EOF\n"
        "&& not an instruction\n"
        "EOF\n"
        "COPY <<-'EOT' /tmp/x\n"
        "  bogus\n"
        "EOT\n",
        encoding="utf-8",
    )
    assert verify_dockerfiles.check_dockerfile(dockerfile) == []


def test_unterminated_continuation_is_reported(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM scratch\nRUN echo \\\n", encoding="utf-8")
    violations = verify_dockerfiles.check_dockerfile(dockerfile)
    assert [violation.detail for violation in violations] == [
        "file ends inside a line continuation"
    ]
