"""Tests for PEP 723 Skill metadata verification."""

from __future__ import annotations

from pathlib import Path

from scripts import verify_skill_metadata

REF = "4cca489171ac53e6e55639b791c8571482167bd2"
DEPENDENCY = f"acd @ git+https://github.com/uist1idrju3i/acd-agent@{REF}"
SCRIPT = "plugins/acd/skills/example/scripts/example.py"


def _write_tree(
    root: Path,
    *,
    dependency: str = DEPENDENCY,
    metadata: str | None = "valid",
    skill_command: str = "uv run --script",
    ref: str = REF,
) -> None:
    script = root / SCRIPT
    script.parent.mkdir(parents=True)
    (script.parent.parent / "SKILL.md").write_text(
        f"# Example\n\n{skill_command} {SCRIPT}\n",
        encoding="utf-8",
    )
    (root / "plugins/acd/skills/acd-package-ref.txt").parent.mkdir(
        parents=True, exist_ok=True
    )
    (root / "plugins/acd/skills/acd-package-ref.txt").write_text(
        f"{ref}\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    if metadata == "valid":
        header = (
            "# /// script\n"
            '# requires-python = ">=3.12"\n'
            "# dependencies = [\n"
            f'#     "{dependency}",\n'
            "# ]\n"
            "# ///\n"
        )
    else:
        header = ""
    script.write_text(f'{header}from acd.core import thing\n', encoding="utf-8")


def test_real_repository_metadata_is_valid() -> None:
    assert verify_skill_metadata.verify_repository() == []


def test_mismatched_ref_fails_closed(tmp_path: Path) -> None:
    _write_tree(tmp_path, dependency="acd @ git+https://example.invalid/acd@main")
    errors = verify_skill_metadata.verify_repository(tmp_path)
    assert any("dependencies must be exactly" in error for error in errors)


def test_missing_block_fails_closed(tmp_path: Path) -> None:
    _write_tree(tmp_path, metadata=None)
    errors = verify_skill_metadata.verify_repository(tmp_path)
    assert any("missing PEP 723 script block" in error for error in errors)


def test_branch_name_ref_fails_closed(tmp_path: Path) -> None:
    _write_tree(tmp_path, ref="main", dependency="acd @ git+https://github.com/uist1idrju3i/acd-agent@main")
    errors = verify_skill_metadata.verify_repository(tmp_path)
    assert any("invalid pinned ref" in error for error in errors)


def test_python_script_invocation_fails_closed(tmp_path: Path) -> None:
    _write_tree(tmp_path, skill_command="uv run python")
    errors = verify_skill_metadata.verify_repository(tmp_path)
    assert any("missing 'uv run --script" in error for error in errors)
    assert any("forbidden 'uv run python" in error for error in errors)
