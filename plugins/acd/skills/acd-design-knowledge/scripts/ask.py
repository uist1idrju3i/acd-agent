# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@ef8b2f11c1cd73a9014e3a7bd8f81a7146ef2159",
# ]
# ///
"""Answer a design question from the indexed knowledge sources.

Answers restate indexed values with their citations. A question that cannot be
answered from the index is answered ``unknown`` with a reason and a non-zero
exit code, so an unanswered question is never mistaken for a confirmation.
Answers are L2 steering or L3 observations and carry no approval authority.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from acd.core.knowledge_qa import answer_question
from knowledge_inputs import (
    KnowledgeInputError,
    add_input_arguments,
    dump_json,
    load_knowledge_base,
    paths_from_args,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_input_arguments(parser)
    parser.add_argument("--question", required=True)
    parser.add_argument("--audience", choices=("internal", "public"), default="internal")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    try:
        base = load_knowledge_base(paths_from_args(args), args.audience)
    except (KnowledgeInputError, ValueError) as exc:
        print(f"knowledge unavailable: {exc}", file=sys.stderr)
        return 2

    answer = answer_question(base, args.question)
    rendered = dump_json(answer.model_dump(mode="json"))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if answer.status == "answered" else 2


if __name__ == "__main__":
    raise SystemExit(main())
