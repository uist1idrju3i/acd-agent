"""Tests for deterministic design knowledge question answering."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from acd.core.design_history import design_input_history, resolve_head_commit
from acd.core.knowledge_index import KnowledgeSourceLocation, build_knowledge_index
from acd.core.knowledge_qa import (
    HistoryEntry,
    KnowledgeBase,
    answer_question,
    classify_question,
)
from acd.core.troubleshooting import derive_troubleshooting_knowledge, parse_pin_macros
from acd.schema.design_graph import DesignGraph
from acd.schema.knowledge_index import KnowledgeAudience, KnowledgeIndex
from acd.schema.rationale import RationaleDocument

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = REPO_ROOT / "fixtures/golden-design-1/graph.json"
RATIONALE_PATH = REPO_ROOT / "fixtures/golden-design-1/rationale.json"
COMMIT = "1" * 40

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


def _graph() -> DesignGraph:
    return DesignGraph.model_validate(
        json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    )


def _index(audience: KnowledgeAudience = "internal") -> KnowledgeIndex:
    return build_knowledge_index(
        graph_path=GRAPH_PATH,
        locations=[KnowledgeSourceLocation(kind="rationale", path=RATIONALE_PATH)],
        audience=audience,
        base_dir=REPO_ROOT,
        git_commit=COMMIT,
    )


def _base(**overrides: object) -> KnowledgeBase:
    graph = _graph()
    rationale = RationaleDocument.model_validate(
        json.loads(RATIONALE_PATH.read_text(encoding="utf-8"))
    )
    defaults: dict[str, object] = {
        "index": _index(),
        "graph": graph,
        "rationale": rationale,
        "troubleshooting": derive_troubleshooting_knowledge(
            graph, pin_macros=parse_pin_macros(PINS_HEADER)
        ),
        "history": (
            HistoryEntry(
                commit=COMMIT,
                subject="基板外形を確定した",
                changed_paths=("fixtures/golden-design-1/graph.json",),
            ),
        ),
    }
    defaults.update(overrides)
    return KnowledgeBase(**defaults)  # type: ignore[arg-type]


def test_classification_covers_japanese_and_english() -> None:
    assert classify_question("この基板の仕様は?") == "product_spec"
    assert classify_question("What is the board size?") == "product_spec"
    assert classify_question("使い方を教えて") == "usage"
    assert classify_question("LEDが点滅しない") == "troubleshooting"
    assert classify_question("なぜこの配線幅なのか") == "design_rationale"
    assert classify_question("いつ変更されたのか") == "history"
    assert classify_question("空") == "unknown"
    assert classify_question("   ") == "unknown"


def test_spec_answer_cites_graph_nodes() -> None:
    answer = answer_question(_base(), "電源電圧の仕様は?")

    assert answer.status == "answered"
    assert answer.category == "product_spec"
    assert answer.pass_evidence is False
    assert any("3.3 V nominal" in statement for statement in answer.statements)
    locators = {citation.locator for citation in answer.citations}
    assert "net.p3v3" in locators
    assert all(citation.kind == "design_graph" for citation in answer.citations)


def test_usage_answer_follows_the_declared_sequence() -> None:
    answer = answer_question(_base(), "使い方の手順は?")

    assert answer.status == "answered"
    assert answer.category == "usage"
    assert answer.statements[0].endswith("(fw.module.main).")
    steps = [item for item in answer.statements if item.startswith("Step ")]
    assert [item.split(":")[0] for item in steps] == [
        f"Step {index}" for index in range(1, len(steps) + 1)
    ]


def test_troubleshooting_answer_reports_expected_values() -> None:
    answer = answer_question(_base(), "status LED does not blink")

    assert answer.status == "answered"
    assert answer.category == "troubleshooting"
    assert any("Expected: Status LED GPIO number = 7" in s for s in answer.statements)
    assert [citation.locator for citation in answer.citations] == [
        "ts-led-not-blinking"
    ]


def test_troubleshooting_answer_is_unknown_without_derivable_values() -> None:
    graph = _graph()
    base = _base(
        troubleshooting=derive_troubleshooting_knowledge(graph, pin_macros={}),
    )

    answer = answer_question(base, "status LED does not blink")

    assert answer.status == "unknown"
    assert answer.reason is not None
    assert "not derivable" in answer.reason
    assert answer.statements == []


def test_troubleshooting_answer_is_unknown_without_indexed_knowledge() -> None:
    answer = answer_question(_base(troubleshooting=None), "the sensor does not answer")

    assert answer.status == "unknown"
    assert answer.reason == "troubleshooting knowledge is not indexed for this revision"


def test_unmatched_symptom_is_unknown() -> None:
    answer = answer_question(_base(), "the housing latch does not close")

    assert answer.status == "unknown"
    assert answer.reason == "no indexed troubleshooting entry matches this symptom"


def test_rationale_answer_cites_rationale_ids() -> None:
    answer = answer_question(_base(), "なぜ board envelope をこの寸法にした理由は?")

    assert answer.status == "answered"
    assert answer.category == "design_rationale"
    assert all(citation.kind == "rationale" for citation in answer.citations)
    assert any(
        citation.locator == "gd1-board-envelope" for citation in answer.citations
    )


def test_rationale_answer_is_unknown_without_records() -> None:
    answer = answer_question(_base(rationale=None), "なぜこの部品を選んだのか")

    assert answer.status == "unknown"
    assert answer.reason == "rationale records are not indexed for this revision"


def test_history_answer_cites_commits() -> None:
    answer = answer_question(_base(), "いつ変更されたのか")

    assert answer.status == "answered"
    assert answer.category == "history"
    assert answer.citations[0].kind == "git_history"
    assert answer.citations[0].reference == f"git:{COMMIT}"


def test_history_answer_is_unknown_without_history() -> None:
    answer = answer_question(_base(history=()), "変更された履歴は?")

    assert answer.status == "unknown"
    assert answer.reason == "git history records no change to the indexed design inputs"


def test_unclassified_question_is_unknown() -> None:
    answer = answer_question(_base(), "?")

    assert answer.status == "unknown"
    assert answer.category == "unknown"
    assert answer.reason == "question does not match a supported knowledge category"


def test_revision_mismatch_between_index_and_graph_is_unknown() -> None:
    payload = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    payload["revision"] = "r2"
    for node in payload["nodes"]:
        attrs = node["attrs"]
        for key, value in list(attrs.items()):
            if value == "r1":
                attrs[key] = "r2"
    base = _base(graph=DesignGraph.model_validate(payload))

    answer = answer_question(base, "仕様は?")

    assert answer.status == "unknown"
    assert answer.reason == (
        "knowledge index and design graph target different revisions"
    )


def test_design_history_reads_the_repository(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    graph = tmp_path / "graph.json"
    graph.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "graph.json"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "graphを追加した"], cwd=tmp_path, check=True
    )

    commit = resolve_head_commit(tmp_path)
    history = design_input_history(tmp_path, ["graph.json"])

    assert commit is not None and len(commit) == 40
    assert [entry.subject for entry in history] == ["graphを追加した"]
    assert history[0].changed_paths == ("graph.json",)


def test_history_answer_reports_revision_transitions() -> None:
    history = (
        HistoryEntry(
            commit="2" * 40,
            subject="外形を修正した",
            changed_paths=("fixtures/golden-design-1/graph.json",),
            revision="r2",
        ),
        HistoryEntry(
            commit=COMMIT,
            subject="基板外形を確定した",
            changed_paths=("fixtures/golden-design-1/graph.json",),
            revision="r1",
        ),
    )

    answer = answer_question(_base(history=history), "いつ変更されたのか")

    assert answer.status == "answered"
    assert "(revision r1 -> r2)" in answer.statements[0]
    assert "(revision r1)" in answer.statements[1]


def test_history_answer_cites_internal_and_eco_sources(tmp_path: Path) -> None:
    logs = tmp_path / "conversation.md"
    logs.write_text("internal discussion\n", encoding="utf-8")
    eco = tmp_path / "eco-0001.md"
    eco.write_text("engineering change order\n", encoding="utf-8")
    index = build_knowledge_index(
        graph_path=GRAPH_PATH,
        locations=[
            KnowledgeSourceLocation(kind="conversation_log", path=logs),
            KnowledgeSourceLocation(kind="generated_document", path=eco),
        ],
        audience="internal",
        base_dir=REPO_ROOT,
        git_commit=COMMIT,
    )

    answer = answer_question(_base(index=index), "いつ変更されたのか")

    kinds = [citation.kind for citation in answer.citations]
    assert kinds == ["git_history", "conversation_log", "generated_document"]


def test_public_history_answer_omits_conversation_logs(tmp_path: Path) -> None:
    logs = tmp_path / "conversation.md"
    logs.write_text("internal discussion\n", encoding="utf-8")
    index = build_knowledge_index(
        graph_path=GRAPH_PATH,
        locations=[KnowledgeSourceLocation(kind="conversation_log", path=logs)],
        audience="public",
        base_dir=REPO_ROOT,
        git_commit=COMMIT,
    )

    answer = answer_question(_base(index=index), "いつ変更されたのか")

    assert all(citation.kind != "conversation_log" for citation in answer.citations)


def test_design_history_reads_graph_revision_of_each_commit(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    graph = tmp_path / "graph.json"
    for revision in ("r1", "r2"):
        graph.write_text(json.dumps({"revision": revision}), encoding="utf-8")
        subprocess.run(["git", "add", "graph.json"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "--quiet", "-m", f"{revision}へ更新した"],
            cwd=tmp_path,
            check=True,
        )

    history = design_input_history(tmp_path, ["graph.json"], graph_path="graph.json")

    assert [entry.revision for entry in history] == ["r2", "r1"]


def test_design_history_revision_is_unknown_for_unreadable_graph(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    graph = tmp_path / "graph.json"
    graph.write_text("{ broken", encoding="utf-8")
    subprocess.run(["git", "add", "graph.json"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "壊れたgraphを追加した"],
        cwd=tmp_path,
        check=True,
    )

    history = design_input_history(tmp_path, ["graph.json"], graph_path="graph.json")

    assert [entry.revision for entry in history] == [None]


def test_design_history_without_repository_is_empty(tmp_path: Path) -> None:
    assert resolve_head_commit(tmp_path / "absent") is None
    assert design_input_history(tmp_path, ["graph.json"]) == ()
    assert design_input_history(tmp_path, []) == ()
