"""Knowledge index, question answering and FAQ generation tests."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from ask import main as ask_main
from build_knowledge_index import main as index_main
from generate_faq import main as faq_main
from knowledge_inputs import KnowledgeInputError, load_knowledge_base, paths_from_args

REPO_ROOT = Path(__file__).resolve().parents[5]
GRAPH = REPO_ROOT / "fixtures" / "golden-design-1" / "graph.json"
RATIONALE = REPO_ROOT / "fixtures" / "golden-design-1" / "rationale.json"

PINS_HEADER = """\
#define ACD_PIN_LED 7
#define ACD_PIN_I2C_SDA 8
#define ACD_PIN_I2C_SCL 9
#define ACD_PIN_UART_TX 21
#define ACD_PIN_UART_RX 20
#define ACD_PIN_BOOT 9
#define ACD_PIN_USB_DN 18
#define ACD_PIN_USB_DP 19
#define ACD_SHT40_I2C_ADDRESS 0x44
#define ACD_LED_BLINK_PERIOD_MS 1000
#define ACD_LOG_PERIOD_MS 2000
"""


@pytest.fixture
def pins_header(tmp_path: Path) -> Path:
    path = tmp_path / "acd_pins.h"
    path.write_text(PINS_HEADER, encoding="utf-8")
    return path


def _common_args(pins_header: Path) -> list[str]:
    return [
        "--graph",
        str(GRAPH),
        "--rationale",
        str(RATIONALE),
        "--pins-header",
        str(pins_header),
        "--repo-root",
        str(REPO_ROOT),
    ]


def test_index_and_troubleshooting_are_written(tmp_path: Path, pins_header: Path) -> None:
    out_dir = tmp_path / "knowledge"

    assert index_main([*_common_args(pins_header), "--out-dir", str(out_dir)]) == 0

    index = json.loads((out_dir / "knowledge-index.json").read_text(encoding="utf-8"))
    assert index["artifact_kind"] == "knowledge_index"
    assert index["pass_evidence"] is False
    assert index["payload"]["target_revision"] == "r1"
    knowledge = json.loads(
        (out_dir / "troubleshooting-knowledge.json").read_text(encoding="utf-8")
    )
    assert knowledge["pass_evidence"] is False
    assert [entry["status"] for entry in knowledge["payload"]["entries"]] == ["derived"] * 5


def test_public_index_drops_conversation_logs(tmp_path: Path, pins_header: Path) -> None:
    logs = tmp_path / "conversation"
    logs.mkdir()
    (logs / "session.md").write_text("internal discussion\n", encoding="utf-8")
    out_dir = tmp_path / "knowledge"

    assert (
        index_main(
            [
                *_common_args(pins_header),
                "--conversation-logs",
                str(logs),
                "--audience",
                "public",
                "--out-dir",
                str(out_dir),
            ]
        )
        == 0
    )

    payload = json.loads(
        (out_dir / "knowledge-index.json").read_text(encoding="utf-8")
    )["payload"]
    assert payload["excluded_kinds"] == ["conversation_log"]
    assert all(source["kind"] != "conversation_log" for source in payload["sources"])


def test_ask_answers_with_citations(tmp_path: Path, pins_header: Path) -> None:
    out = tmp_path / "answer.json"

    exit_code = ask_main(
        [
            *_common_args(pins_header),
            "--question",
            "LEDが点滅しない場合の確認手順は?",
            "--out",
            str(out),
        ]
    )

    assert exit_code == 0
    answer = json.loads(out.read_text(encoding="utf-8"))
    assert answer["status"] == "answered"
    assert answer["category"] == "troubleshooting"
    assert answer["pass_evidence"] is False
    assert answer["citations"]


def test_ask_reports_unknown_with_nonzero_exit(pins_header: Path) -> None:
    exit_code = ask_main(
        [*_common_args(pins_header), "--question", "この筐体の塗装色は?"]
    )

    assert exit_code == 2


def test_ask_stops_on_malformed_graph(tmp_path: Path, pins_header: Path) -> None:
    broken = tmp_path / "graph.json"
    broken.write_text("{", encoding="utf-8")

    exit_code = ask_main(
        [
            "--graph",
            str(broken),
            "--pins-header",
            str(pins_header),
            "--repo-root",
            str(REPO_ROOT),
            "--question",
            "仕様は?",
        ]
    )

    assert exit_code == 2


def test_faq_is_deterministic_and_marks_unknowns(
    tmp_path: Path, pins_header: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    assert faq_main([*_common_args(pins_header), "--out-dir", str(first)]) == 0
    assert faq_main([*_common_args(pins_header), "--out-dir", str(second)]) == 0

    body = (first / "faq.md").read_text(encoding="utf-8")
    assert body == (second / "faq.md").read_text(encoding="utf-8")
    assert "### LEDが点滅しない場合の確認手順は?" in body
    assert "出所:" in body
    provenance = json.loads(
        (first / "faq.md.provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["pass_evidence"] is False
    assert provenance["audience"] == "public"
    assert provenance["excluded_source_kinds"] == ["conversation_log"]


def test_faq_publishes_unknown_when_pin_projection_is_missing(tmp_path: Path) -> None:
    out_dir = tmp_path / "docs"

    exit_code = faq_main(
        [
            "--graph",
            str(GRAPH),
            "--rationale",
            str(RATIONALE),
            "--pins-header",
            str(tmp_path / "absent.h"),
            "--repo-root",
            str(REPO_ROOT),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    body = (out_dir / "faq.md").read_text(encoding="utf-8")
    assert "unknown: matching troubleshooting entry is not derivable" in body
    assert "人手で確認して決定する" in body


def test_malformed_rationale_fails_closed(tmp_path: Path, pins_header: Path) -> None:
    broken = tmp_path / "rationale.json"
    broken.write_text(json.dumps({"records": "invalid"}), encoding="utf-8")

    args = Namespace(
        graph=GRAPH,
        rationale=broken,
        documents=None,
        evidence=None,
        gate_results=None,
        conversation_logs=None,
        pins_header=pins_header,
        repo_root=REPO_ROOT,
    )

    with pytest.raises(KnowledgeInputError):
        load_knowledge_base(paths_from_args(args), "internal")
