"""Run the theme-song Skill as a subprocess and record its projection.

The Skill CLI composes the song; this module owns the subprocess invocation,
the regeneration check (two independent runs must produce identical MIDI
bytes), the provenance cross-check and the deterministic
``theme-song-projection.json`` write. When the design directory carries an
adopted agent proposal (``theme-song.json`` next to ``graph.json``) the Skill
renders that proposal; otherwise it composes deterministically from the graph.
The projection is an L3 artifact of the design outputs, like Gerbers are of
the board, and never pass Evidence. Every failure is fail-closed and reported
as :class:`ThemeSongProjectionError`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

from acd.schema.theme_song import (
    ThemeSongArtifact,
    ThemeSongArtifactInput,
    ThemeSongProjection,
    ThemeSongRegenerationCheck,
    ThemeSongSource,
)

THEME_SONG_DIR_NAME = "theme-song"
THEME_SONG_PROJECTION_NAME = "theme-song-projection.json"
THEME_SONG_PROPOSAL_NAME = "theme-song.json"
THEME_SONG_TIMEOUT_SECONDS = 300
_MIDI_NAME = "theme-song.mid"
_PROVENANCE_NAME = "theme-song.provenance.json"
_SCRIPT_RELATIVE = "plugins/acd/skills/acd-theme-song/scripts/compose_theme_song.py"


class ThemeSongProjectionError(RuntimeError):
    """The theme-song projection failed; the message is the failure reason."""


def theme_song_script_path(repository: Path) -> Path:
    return repository / _SCRIPT_RELATIVE


def theme_song_proposal_path(graph_path: Path) -> Path | None:
    """Return the adopted proposal next to the graph, or ``None`` when absent."""
    candidate = graph_path.parent / THEME_SONG_PROPOSAL_NAME
    return candidate if candidate.is_file() else None


def _file_sha256(path: Path) -> str:
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError as exc:
        raise ThemeSongProjectionError(f"cannot read {path}: {exc}") from exc


def _run_skill(
    script: Path, graph_path: Path, proposal_path: Path | None, target: Path, repository: Path
) -> None:
    command = [
        sys.executable,
        str(script),
        "--graph",
        str(graph_path),
        "--out-dir",
        str(target),
        "--base-dir",
        str(target),
    ]
    if proposal_path is not None:
        command.extend(["--proposal", str(proposal_path)])
    completed = subprocess.run(
        command,
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=THEME_SONG_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise ThemeSongProjectionError(
            completed.stderr.strip() or f"theme-song Skill exited with code {completed.returncode}"
        )
    for name in (_MIDI_NAME, _PROVENANCE_NAME):
        if not (target / name).is_file():
            raise ThemeSongProjectionError(f"theme-song Skill did not write {name}")


def _load_provenance(path: Path) -> dict[str, object]:
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ThemeSongProjectionError(f"theme-song provenance is invalid: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ThemeSongProjectionError("theme-song provenance must be an object")
    return cast(dict[str, object], loaded)


def _require_str(record: dict[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise ThemeSongProjectionError(f"theme-song provenance {key} is missing")
    return value


def _require_int(record: dict[str, object], key: str) -> int:
    value = record.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ThemeSongProjectionError(f"theme-song provenance {key} is missing")
    return value


def _input_hashes(provenance: dict[str, object]) -> list[str]:
    inputs = provenance.get("inputs")
    if not isinstance(inputs, list):
        raise ThemeSongProjectionError("theme-song provenance inputs are missing")
    hashes: list[str] = []
    for entry in cast(list[object], inputs):
        if not isinstance(entry, dict):
            raise ThemeSongProjectionError("theme-song provenance input is not an object")
        hashes.append(_require_str(cast(dict[str, object], entry), "content_hash"))
    return hashes


def _relative_input(path: Path, repository: Path) -> str:
    return path.relative_to(repository).as_posix() if path.is_relative_to(repository) else path.name


def generate_theme_song_projection(
    *,
    project_name: str,
    repository: Path,
    graph_path: Path,
    out_dir: Path,
    source_revision: str,
) -> tuple[Path, ThemeSongProjection]:
    """Compose the theme song into ``out_dir/theme-song`` and record the projection.

    Returns the projection path and the validated record. Raises
    ``ThemeSongProjectionError`` when the Skill is missing or fails, the adopted
    proposal is rejected, the two runs differ, or the Skill provenance disagrees
    with the graph, the proposal or the written artifacts.
    """
    script = theme_song_script_path(repository)
    if not script.is_file():
        raise ThemeSongProjectionError(f"theme-song Skill script is missing: {script}")
    proposal_path = theme_song_proposal_path(graph_path)
    song_dir = out_dir / THEME_SONG_DIR_NAME
    recheck_dir = out_dir / f".{THEME_SONG_DIR_NAME}-recheck"
    shutil.rmtree(song_dir, ignore_errors=True)
    shutil.rmtree(recheck_dir, ignore_errors=True)
    try:
        _run_skill(script, graph_path, proposal_path, song_dir, repository)
        _run_skill(script, graph_path, proposal_path, recheck_dir, repository)
        first_hash = _file_sha256(song_dir / _MIDI_NAME)
        second_hash = _file_sha256(recheck_dir / _MIDI_NAME)
    finally:
        shutil.rmtree(recheck_dir, ignore_errors=True)
    if first_hash != second_hash:
        raise ThemeSongProjectionError(
            "theme-song regeneration did not reproduce identical MIDI (fail-closed)"
        )

    provenance = _load_provenance(song_dir / _PROVENANCE_NAME)
    if provenance.get("pass_evidence") is not False:
        raise ThemeSongProjectionError("theme-song provenance must declare pass_evidence false")
    if _require_str(provenance, "target_revision") != source_revision:
        raise ThemeSongProjectionError("theme-song provenance revision does not match the graph")
    expected_source: ThemeSongSource = (
        "deterministic" if proposal_path is None else "agent_proposal"
    )
    if _require_str(provenance, "source") != expected_source:
        raise ThemeSongProjectionError("theme-song provenance source does not match the inputs")
    graph_hash = _file_sha256(graph_path)
    expected_inputs = [graph_hash]
    proposal_input: ThemeSongArtifactInput | None = None
    if proposal_path is not None:
        proposal_hash = _file_sha256(proposal_path)
        expected_inputs.append(proposal_hash)
        proposal_input = ThemeSongArtifactInput(
            path=_relative_input(proposal_path, repository), content_hash=proposal_hash
        )
    if _input_hashes(provenance) != expected_inputs:
        raise ThemeSongProjectionError("theme-song provenance input hashes do not match")
    artifacts = provenance.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ThemeSongProjectionError("theme-song provenance artifacts are missing")
    recorded = cast(dict[str, object], artifacts)
    if list(recorded) != ["midi"]:
        raise ThemeSongProjectionError(
            "theme-song provenance must record exactly one MIDI artifact"
        )
    midi_entry = recorded.get("midi")
    if (
        not isinstance(midi_entry, dict)
        or cast(dict[str, object], midi_entry).get("content_hash") != first_hash
    ):
        raise ThemeSongProjectionError("theme-song provenance midi hash does not match")
    composition = provenance.get("composition")
    if not isinstance(composition, dict):
        raise ThemeSongProjectionError("theme-song provenance composition is missing")
    composition_record = cast(dict[str, object], composition)

    projection = ThemeSongProjection(
        projection_id=f"{project_name}-theme-song",
        graph_id=_require_str(provenance, "graph_id"),
        source_revision=source_revision,
        graph_input=ThemeSongArtifactInput(
            path=_relative_input(graph_path, repository), content_hash=graph_hash
        ),
        source=expected_source,
        proposal_input=proposal_input,
        skill_script_path=_SCRIPT_RELATIVE,
        skill_script_sha256=_file_sha256(script),
        composer_id=_require_str(provenance, "composer_id"),
        seed=_require_str(composition_record, "seed"),
        bpm=_require_int(composition_record, "bpm"),
        bars=_require_int(composition_record, "bars"),
        key=_require_str(composition_record, "key"),
        title=_require_str(composition_record, "title"),
        artifacts=[
            ThemeSongArtifact(
                path=f"{THEME_SONG_DIR_NAME}/{_MIDI_NAME}",
                media_type="audio/midi",
                content_hash=first_hash,
            ),
        ],
        regeneration_check=ThemeSongRegenerationCheck(
            status="reproduced", first_hash=first_hash, second_hash=second_hash
        ),
    ).with_computed_hash()
    projection_path = out_dir / THEME_SONG_PROJECTION_NAME
    projection_path.write_text(
        json.dumps(projection.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return projection_path, projection
