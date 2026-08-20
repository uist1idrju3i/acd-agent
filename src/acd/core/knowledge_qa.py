"""Deterministic question answering over the indexed design knowledge.

Answering is a lookup, not a generation step: a question is classified into a
category by declared keywords, the matching values are read from the indexed
knowledge sources, and every statement carries the source it came from. A
question whose category or values cannot be resolved is answered ``unknown``.
Answers never modify design inputs and never carry approval authority.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from acd.schema.design_graph import DesignGraph, GraphNode
from acd.schema.knowledge_answer import (
    KnowledgeAnswer,
    KnowledgeCategory,
    KnowledgeCitation,
)
from acd.schema.knowledge_index import KnowledgeIndex, KnowledgeSource
from acd.schema.rationale import RationaleDocument, RationaleRecord
from acd.schema.troubleshooting import TroubleshootingKnowledge

# Keyword vocabulary per category. Japanese questions have no word boundaries,
# so matching is substring based on the lower-cased question text.
CATEGORY_KEYWORDS: dict[KnowledgeCategory, tuple[str, ...]] = {
    "history": (
        "history",
        "changed",
        "change log",
        "when did",
        "履歴",
        "経緯",
        "いつ変",
        "変更された",
        "変わった",
    ),
    "design_rationale": (
        "why",
        "rationale",
        "reason",
        "decision",
        "なぜ",
        "理由",
        "根拠",
        "判断",
    ),
    "troubleshooting": (
        "not work",
        "does not",
        "doesn't",
        "no output",
        "troubleshoot",
        "problem",
        "fail",
        "動かない",
        "しない",
        "できない",
        "出ない",
        "ない場合",
        "無反応",
        "トラブル",
        "不具合",
        "故障",
    ),
    "usage": (
        "how do i",
        "how to",
        "usage",
        "operate",
        "flash",
        "start",
        "使い方",
        "使用方法",
        "操作",
        "手順",
        "書き込み",
        "起動",
    ),
    "product_spec": (
        "spec",
        "dimension",
        "size",
        "voltage",
        "power",
        "requirement",
        "仕様",
        "寸法",
        "サイズ",
        "電圧",
        "電源",
        "要求",
        "要件",
    ),
}
_TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}")
# Frequent words that carry no design meaning and must not match a symptom.
_STOPWORDS = frozenset(
    {
        "after",
        "and",
        "any",
        "are",
        "but",
        "can",
        "check",
        "confirm",
        "does",
        "doesn",
        "each",
        "every",
        "for",
        "from",
        "has",
        "have",
        "host",
        "its",
        "not",
        "only",
        "open",
        "out",
        "stays",
        "that",
        "the",
        "their",
        "then",
        "this",
        "use",
        "used",
        "was",
        "watch",
        "were",
        "what",
        "when",
        "which",
        "with",
        "you",
        "your",
    }
)
# Categories are tested in this order so a more specific intent wins.
CATEGORY_ORDER: tuple[KnowledgeCategory, ...] = (
    "history",
    "design_rationale",
    "troubleshooting",
    "usage",
    "product_spec",
)


@dataclass(frozen=True)
class HistoryEntry:
    """One git history record about the indexed design inputs.

    ``revision`` is the design graph revision as of the commit, so an answer can
    state which revision transition a change belongs to. It stays None when the
    revision cannot be read from the commit instead of being guessed.
    """

    commit: str
    subject: str
    changed_paths: tuple[str, ...]
    revision: str | None = None


@dataclass(frozen=True)
class KnowledgeBase:
    """The resolved knowledge an answering path may cite."""

    index: KnowledgeIndex
    graph: DesignGraph
    rationale: RationaleDocument | None = None
    troubleshooting: TroubleshootingKnowledge | None = None
    history: tuple[HistoryEntry, ...] = field(default_factory=tuple)


def classify_question(question: str) -> KnowledgeCategory:
    """Return the question category, or ``unknown`` when no keyword matches."""
    text = question.strip().lower()
    if not text:
        return "unknown"
    for category in CATEGORY_ORDER:
        if any(keyword in text for keyword in CATEGORY_KEYWORDS[category]):
            return category
    return "unknown"


def _nodes_of_kind(graph: DesignGraph, kind: str) -> tuple[GraphNode, ...]:
    return tuple(
        sorted((node for node in graph.nodes if node.kind == kind), key=lambda n: n.id)
    )


def _number(node: GraphNode, key: str) -> float | None:
    value = node.attrs.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _text(node: GraphNode, key: str) -> str | None:
    value = node.attrs.get(key)
    return value if isinstance(value, str) and value else None


def _answered(
    base: KnowledgeBase,
    question: str,
    category: KnowledgeCategory,
    statements: Sequence[str],
    citations: Sequence[KnowledgeCitation],
) -> KnowledgeAnswer:
    return KnowledgeAnswer(
        question=question,
        category=category,
        audience=base.index.audience,
        graph_id=base.graph.graph_id,
        target_revision=base.graph.revision,
        status="answered",
        statements=list(statements),
        citations=list(citations),
    )


def _unknown(
    base: KnowledgeBase,
    question: str,
    category: KnowledgeCategory,
    reason: str,
    citations: Sequence[KnowledgeCitation] = (),
) -> KnowledgeAnswer:
    return KnowledgeAnswer(
        question=question,
        category=category,
        audience=base.index.audience,
        graph_id=base.graph.graph_id,
        target_revision=base.graph.revision,
        status="unknown",
        citations=list(citations),
        reason=reason,
    )


def _graph_citation(base: KnowledgeBase, node_id: str) -> KnowledgeCitation:
    sources = base.index.available("design_graph")
    reference = sources[0].reference if sources else "design_graph"
    return KnowledgeCitation(kind="design_graph", reference=reference, locator=node_id)


def _spec_answer(base: KnowledgeBase, question: str) -> KnowledgeAnswer:
    statements: list[str] = []
    citations: list[KnowledgeCitation] = []
    for board in _nodes_of_kind(base.graph, "electrical.board"):
        width = _number(board, "width_mm")
        height = _number(board, "height_mm")
        if width is None or height is None:
            continue
        statements.append(f"Board outline: {width:g} x {height:g} mm ({board.id}).")
        citations.append(_graph_citation(base, board.id))
    for net in _nodes_of_kind(base.graph, "electrical.net"):
        if net.attrs.get("power_rail") is not True:
            continue
        voltage = _number(net, "voltage_nominal_v")
        if voltage is None:
            continue
        name = _text(net, "name") or net.id
        statements.append(f"Power rail {name}: {voltage:g} V nominal ({net.id}).")
        citations.append(_graph_citation(base, net.id))
    for requirement in _nodes_of_kind(base.graph, "requirement"):
        text = _text(requirement, "text")
        if text is None:
            continue
        statements.append(f"Requirement {requirement.id}: {text}")
        citations.append(_graph_citation(base, requirement.id))
    if not statements:
        return _unknown(
            base,
            question,
            "product_spec",
            "the design graph declares no specification value for this question",
        )
    return _answered(base, question, "product_spec", statements, citations)


def _usage_answer(base: KnowledgeBase, question: str) -> KnowledgeAnswer:
    modules = _nodes_of_kind(base.graph, "firmware.module")
    steps = _nodes_of_kind(base.graph, "firmware.sequence_step")
    if not modules or not steps:
        return _unknown(
            base,
            question,
            "usage",
            "the design graph declares no firmware startup sequence",
        )
    statements: list[str] = []
    citations: list[KnowledgeCitation] = []
    for module in modules:
        entry_state = _text(module, "entry_state")
        name = _text(module, "module_name") or module.id
        if entry_state is None:
            return _unknown(
                base,
                question,
                "usage",
                f"firmware module {module.id} declares no entry state",
            )
        statements.append(f"{name} starts in state {entry_state} ({module.id}).")
        citations.append(_graph_citation(base, module.id))
    ordered: list[tuple[int, GraphNode]] = []
    for step in steps:
        index = step.attrs.get("step_index")
        if isinstance(index, bool) or not isinstance(index, int):
            return _unknown(
                base,
                question,
                "usage",
                f"sequence step {step.id} declares no step index",
            )
        ordered.append((index, step))
    for index, step in sorted(ordered, key=lambda item: (item[0], item[1].id)):
        action = _text(step, "action")
        target = _text(step, "target")
        if action is None or target is None:
            return _unknown(
                base,
                question,
                "usage",
                f"sequence step {step.id} declares no action or target",
            )
        statements.append(f"Step {index}: {action} on {target} ({step.id}).")
        citations.append(_graph_citation(base, step.id))
    return _answered(base, question, "usage", statements, citations)


def _salient_tokens(text: str) -> set[str]:
    """Return the salient latin tokens of a text.

    Latin tokens are extracted by pattern instead of by whitespace so a
    Japanese question without word boundaries still matches identifiers such as
    ``LED``, ``I2C`` or ``UART`` that appear inside it.
    """
    return {
        token for token in _TOKEN_PATTERN.findall(text.lower()) if token not in _STOPWORDS
    }


def _matches(question: str, text: str) -> bool:
    """Return whether a question and an indexed text share a salient token."""
    return bool(_salient_tokens(question) & _salient_tokens(text))


def _troubleshooting_answer(base: KnowledgeBase, question: str) -> KnowledgeAnswer:
    knowledge = base.troubleshooting
    if knowledge is None:
        return _unknown(
            base,
            question,
            "troubleshooting",
            "troubleshooting knowledge is not indexed for this revision",
        )
    if knowledge.target_revision != base.graph.revision:
        return _unknown(
            base,
            question,
            "troubleshooting",
            "troubleshooting knowledge targets another revision",
        )
    matched = [
        entry
        for entry in knowledge.entries
        if _matches(question, entry.symptom)
        or any(_matches(question, check) for check in entry.checks)
    ]
    if not matched:
        return _unknown(
            base,
            question,
            "troubleshooting",
            "no indexed troubleshooting entry matches this symptom",
        )
    unknown_entries = [entry for entry in matched if entry.status == "unknown"]
    if unknown_entries:
        reasons = "; ".join(
            f"{entry.entry_id}: {entry.reason}" for entry in unknown_entries
        )
        return _unknown(
            base,
            question,
            "troubleshooting",
            f"matching troubleshooting entry is not derivable ({reasons})",
        )
    statements: list[str] = []
    citations: list[KnowledgeCitation] = []
    for entry in matched:
        statements.append(f"Symptom: {entry.symptom}")
        statements.extend(f"Check: {check}" for check in entry.checks)
        for expectation in entry.expectations:
            statements.append(
                f"Expected: {expectation.description} = {expectation.expected} "
                f"({expectation.citation})"
            )
        citations.append(
            KnowledgeCitation(
                kind="design_graph",
                reference=f"troubleshooting:{knowledge.graph_id}",
                locator=entry.entry_id,
            )
        )
    return _answered(base, question, "troubleshooting", statements, citations)


def _rationale_citation(
    base: KnowledgeBase, record: RationaleRecord
) -> KnowledgeCitation:
    sources = base.index.available("rationale")
    reference = sources[0].reference if sources else "rationale"
    return KnowledgeCitation(
        kind="rationale", reference=reference, locator=record.rationale_id
    )


def _rationale_answer(base: KnowledgeBase, question: str) -> KnowledgeAnswer:
    document = base.rationale
    if document is None:
        return _unknown(
            base,
            question,
            "design_rationale",
            "rationale records are not indexed for this revision",
        )
    if document.revision != base.graph.revision:
        return _unknown(
            base,
            question,
            "design_rationale",
            "indexed rationale records target another revision",
        )
    matched = [
        record
        for record in sorted(document.records, key=lambda item: item.rationale_id)
        if _matches(question, record.decision)
        or _matches(question, record.rationale_id.replace("-", " "))
        or any(_matches(question, node) for node in record.subject_nodes)
    ]
    if not matched:
        return _unknown(
            base,
            question,
            "design_rationale",
            "no indexed rationale record matches this question",
        )
    statements: list[str] = []
    citations: list[KnowledgeCitation] = []
    for record in matched:
        statements.append(f"Decision ({record.rationale_id}): {record.decision}")
        statements.append(f"Justification: {record.justification}")
        citations.append(_rationale_citation(base, record))
    return _answered(base, question, "design_rationale", statements, citations)


def _revision_transition(previous: str | None, current: str | None) -> str:
    if current is None:
        return " (revision unknown)"
    if previous is None or previous == current:
        return f" (revision {current})"
    return f" (revision {previous} -> {current})"


def _eco_sources(base: KnowledgeBase) -> tuple[KnowledgeSource, ...]:
    """Return indexed engineering change records, if any are available.

    ECO records are kept as generated documents until an ECO contract exists, so
    they are recognised by reference name rather than by their own source kind.
    """
    return tuple(
        source
        for source in base.index.available("generated_document")
        if "eco" in Path(source.reference).name.lower()
    )


def _history_answer(base: KnowledgeBase, question: str) -> KnowledgeAnswer:
    if not base.index.available("git_history"):
        return _unknown(
            base,
            question,
            "history",
            "git history is not indexed for this revision",
        )
    if not base.history:
        return _unknown(
            base,
            question,
            "history",
            "git history records no change to the indexed design inputs",
        )
    statements: list[str] = []
    citations: list[KnowledgeCitation] = []
    previous: str | None = None
    for entry in reversed(base.history):
        paths = ", ".join(entry.changed_paths)
        revision = _revision_transition(previous, entry.revision)
        statements.append(f"{entry.commit}: {entry.subject} [{paths}]{revision}")
        citations.append(
            KnowledgeCitation(
                kind="git_history",
                reference=f"git:{entry.commit}",
                locator=paths or None,
            )
        )
        if entry.revision is not None:
            previous = entry.revision
    statements.reverse()
    citations.reverse()
    # Internal narrative sources explain "why" beyond the commit subject. They
    # are cited only when the audience already indexes them, so a public answer
    # never quotes an internal conversation.
    for source in (*base.index.available("conversation_log"), *_eco_sources(base)):
        citations.append(
            KnowledgeCitation(kind=source.kind, reference=source.reference, locator=None)
        )
    return _answered(base, question, "history", statements, citations)


def answer_question(base: KnowledgeBase, question: str) -> KnowledgeAnswer:
    """Answer one question from the indexed knowledge, or report unknown."""
    if base.index.target_revision != base.graph.revision:
        return _unknown(
            base,
            question,
            "unknown",
            "knowledge index and design graph target different revisions",
        )
    category = classify_question(question)
    if category == "unknown":
        return _unknown(
            base,
            question,
            "unknown",
            "question does not match a supported knowledge category",
        )
    if category == "product_spec":
        return _spec_answer(base, question)
    if category == "usage":
        return _usage_answer(base, question)
    if category == "troubleshooting":
        return _troubleshooting_answer(base, question)
    if category == "design_rationale":
        return _rationale_answer(base, question)
    return _history_answer(base, question)
