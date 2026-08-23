# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@c0b012140a0c1d0f4bfef8e10072c319d7056546",
# ]
# ///
"""Generate the publishable FAQ document from the indexed design knowledge.

The FAQ answers a fixed question set for the ``public`` audience: conversation
logs are never indexed, and the exclusion is recorded in the provenance. A
question that cannot be answered from the indexed sources is published as
``unknown`` with its reason instead of an estimated answer. The document is an
L3 observation and contains no timestamp, so identical inputs render identically.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from acd.core.knowledge_qa import KnowledgeBase, answer_question
from acd.schema.knowledge_answer import KnowledgeAnswer
from acd.schema.knowledge_index import INTERNAL_ONLY_KINDS
from knowledge_inputs import (
    KnowledgeInputError,
    add_input_arguments,
    load_knowledge_base,
    paths_from_args,
    write_document_provenance,
)

DOCUMENT_NAME = "faq.md"
TEMPLATE_ID = "acd-design-knowledge-faq-ja-v1"
# The published question set. Every question must classify into a category of
# the answering path; a question outside the index is published as unknown.
FAQ_QUESTIONS: tuple[str, ...] = (
    "この製品の仕様（寸法・電源電圧・要求）は?",
    "使い方の手順は?",
    "LEDが点滅しない場合の確認手順は?",
    "I2Cセンサが応答しない場合の確認手順は?",
    "serial consoleにログが出ない場合の確認手順は?",
    "USBで認識されない場合の確認手順は?",
    "なぜこのboard envelopeなのか、その理由は?",
    "設計入力はいつ変更されたのか、その履歴は?",
)


def _render_answer(answer: KnowledgeAnswer) -> list[str]:
    lines = [f"### {answer.question}", ""]
    if answer.status == "unknown":
        lines += [
            f"unknown: {answer.reason}",
            "",
            "この項目は知識源から導出できないため、人手で確認して決定する。",
            "",
        ]
        return lines
    lines += [f"- {statement}" for statement in answer.statements]
    lines += ["", "出所:"]
    for citation in answer.citations:
        locator = f"#{citation.locator}" if citation.locator else ""
        lines.append(f"- `{citation.kind}` {citation.reference}{locator}")
    lines.append("")
    return lines


def render_faq(base: KnowledgeBase, questions: tuple[str, ...] = FAQ_QUESTIONS) -> str:
    """Render the FAQ body for one graph revision."""
    excluded = ", ".join(sorted(INTERNAL_ONLY_KINDS))
    lines = [
        f"# {base.graph.graph_id} FAQ",
        "",
        f"対象revision: `{base.graph.revision}`",
        "",
        "本FAQは設計入力・rationale・ゲート結果・Evidence・生成文書・git履歴から",
        "決定論的に生成したL3観測であり、合否権限を持たない。導出できない項目は",
        f"unknownと明記する。公開FAQの知識源からは`{excluded}`を除外している。",
        "",
        "## 質問と回答",
        "",
    ]
    for question in questions:
        lines += _render_answer(answer_question(base, question))
    unknown_sources = base.index.unknown_sources()
    lines += ["## 知識源の状態", ""]
    if unknown_sources:
        lines += [
            f"- unknown: `{source.kind}` {source.reference} ({source.reason})"
            for source in unknown_sources
        ]
    else:
        lines.append("- 索引した知識源はすべて解決済みである。")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_input_arguments(parser)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        base = load_knowledge_base(paths_from_args(args), "public")
    except (KnowledgeInputError, ValueError) as exc:
        print(f"FAQ generation stopped: {exc}", file=sys.stderr)
        return 2

    body = render_faq(base)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    document_path = args.out_dir / DOCUMENT_NAME
    document_path.write_text(body, encoding="utf-8")
    provenance_path = write_document_provenance(
        document_kind=TEMPLATE_ID,
        document_path=document_path,
        body=body,
        base=base,
        generator=Path(__file__).resolve(),
        base_dir=args.repo_root,
        excluded_kinds=list(base.index.excluded_kinds),
    )
    print(f"faq: {document_path}")
    print(f"provenance: {provenance_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
