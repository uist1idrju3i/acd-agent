"""CLI tests for the idea-dialogue, estimate, and promotion scripts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPOSITORY / "fixtures" / "idea" / "sample-usb-thermometer"
BANK = (
    REPOSITORY / "plugins" / "acd" / "skills" / "acd-ideate" / "question-bank.json"
)


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPOSITORY / "scripts" / script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _copy_inputs(tmp_path: Path) -> tuple[Path, Path]:
    idea = tmp_path / "idea.json"
    history = tmp_path / "idea-dialogue.json"
    idea.write_bytes((FIXTURE_DIR / "idea.json").read_bytes())
    history.write_bytes((FIXTURE_DIR / "idea-dialogue.json").read_bytes())
    return idea, history


def test_next_questions_cli(tmp_path: Path) -> None:
    idea, history = _copy_inputs(tmp_path)
    result = _run(
        "idea_next_questions.py",
        "--idea",
        str(idea),
        "--history",
        str(history),
        "--bank",
        str(BANK),
    )
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["artifact_kind"] == "idea_questions"
    assert body["record_class"] == "L3"
    assert body["pass_evidence"] is False
    assert body["turn_no"] == 2
    assert body["questions"]


def test_record_turn_cli_rewrites_and_fails_clean(tmp_path: Path) -> None:
    idea, history = _copy_inputs(tmp_path)
    turn = tmp_path / "turn.json"
    turn.write_text(
        json.dumps(
            {
                "turn_no": 2,
                "answers": [
                    {
                        "field": "constraints.cost",
                        "value": 3000,
                        "unit": "JPY",
                        "sources": [
                            {
                                "kind": "user_statement",
                                "ref": "conversation:evt-0010",
                            }
                        ],
                    }
                ],
                "recorded_at": "2026-09-13T14:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = _run(
        "idea_record_turn.py",
        "--idea",
        str(idea),
        "--history",
        str(history),
        "--turn",
        str(turn),
    )
    assert result.returncode == 0, result.stderr
    progress = json.loads(result.stdout)
    assert progress["turn_count"] == 2
    assert "constraints.cost" not in progress["open_items"]
    updated = json.loads(idea.read_text(encoding="utf-8"))
    assert updated["constraints"]["cost"]["status"] == "confirmed"

    # A failing turn leaves both files untouched.
    before_idea = idea.read_bytes()
    before_history = history.read_bytes()
    bad_turn = tmp_path / "bad-turn.json"
    bad_turn.write_text(
        json.dumps(
            {
                "turn_no": 9,
                "answers": [],
                "recorded_at": "2026-09-13T15:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    result = _run(
        "idea_record_turn.py",
        "--idea",
        str(idea),
        "--history",
        str(history),
        "--turn",
        str(bad_turn),
    )
    assert result.returncode == 1
    assert idea.read_bytes() == before_idea
    assert history.read_bytes() == before_history


def test_estimate_cli(tmp_path: Path) -> None:
    idea, _ = _copy_inputs(tmp_path)
    out = tmp_path / "estimate.json"
    result = _run(
        "idea_estimate.py",
        "--idea",
        str(idea),
        "--catalog",
        str(FIXTURE_DIR / "estimate-catalog.json"),
        "--out",
        str(out),
    )
    assert result.returncode == 0, result.stderr
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["artifact_kind"] == "idea_rough_estimate"
    assert body["estimate"] is True
    assert body["pass_evidence"] is False


def test_promote_idea_cli(tmp_path: Path) -> None:
    result = _run(
        "promote_idea.py",
        "--idea",
        str(FIXTURE_DIR / "idea-confirmed.json"),
        "--rationale",
        str(FIXTURE_DIR / "promotion-rationale.json"),
        "--graph-id",
        "golden-design-1",
        "--revision",
        "r1",
        "--out-dir",
        str(tmp_path / "out"),
    )
    assert result.returncode == 0, result.stderr
    requirements = json.loads(
        (tmp_path / "out" / "requirements.json").read_text(encoding="utf-8")
    )
    assert len(requirements["records"]) == 3
    provenance = json.loads(
        (tmp_path / "out" / "idea-promotion-provenance.json").read_text(
            encoding="utf-8"
        )
    )
    assert provenance["artifact_kind"] == "idea_promotion"
    assert provenance["pass_evidence"] is False


def test_promote_idea_cli_fails_on_open_items(tmp_path: Path) -> None:
    result = _run(
        "promote_idea.py",
        "--idea",
        str(FIXTURE_DIR / "idea.json"),
        "--rationale",
        str(FIXTURE_DIR / "promotion-rationale.json"),
        "--graph-id",
        "golden-design-1",
        "--revision",
        "r1",
        "--out-dir",
        str(tmp_path / "out"),
    )
    assert result.returncode == 1
    assert not (tmp_path / "out" / "requirements.json").exists()
