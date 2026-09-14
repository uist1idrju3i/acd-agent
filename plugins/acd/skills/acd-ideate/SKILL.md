---
name: acd-ideate
description: Refine a product idea through a sourced, append-only dialogue with the user.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - ideate
  - idea
  - brainstorm
  - concept
---

# ACD idea refinement

Refine an idea record over multiple turns. The record (`idea.json`) and its
append-only history (`idea-dialogue.json`) are git-managed design inputs;
the question bank `question-bank.json` in this directory supplies the
prioritized questions and options.

Per turn:

1. Ask the next questions from the bank:

   ```bash
   uv run python scripts/idea_next_questions.py \
     --idea <idea-dir>/idea.json \
     --history <idea-dir>/idea-dialogue.json \
     --bank plugins/acd/skills/acd-ideate/question-bank.json
   ```

2. Present at most `--max` questions (default 3) with their options,
   tradeoffs, the recommended option, and the cited sources. Report
   `uncovered_open_items` as human-decision items with no banked options.
3. Record only the answers the user gave, each carrying a `user_statement`
   source, as a turn JSON (`turn_no` = the reported next turn), then apply it:

   ```bash
   uv run python scripts/idea_record_turn.py \
     --idea <idea-dir>/idea.json \
     --history <idea-dir>/idea-dialogue.json \
     --turn turn.json
   ```

4. Show the printed `IdeaProgress` (open items, blocking unknowns). Progress
   is an L3 observation and never an approval.

Rules:

- Never fill a field by inference; never mark a field `confirmed` without the
  user's own statement as a `user_statement` source.
- The rough estimate is an estimate, not evidence:

  ```bash
  uv run python scripts/idea_estimate.py \
    --idea <idea-dir>/idea.json \
    --catalog <idea-dir>/estimate-catalog.json
  ```

- Promote only when progress reports `ready_for_promotion` and a promotion
  rationale exists:

  ```bash
  uv run python scripts/promote_idea.py \
    --idea <idea-dir>/idea.json \
    --rationale <idea-dir>/promotion-rationale.json \
    --graph-id <graph-id> --revision <rev> --out-dir <out>
  ```

Malformed inputs, mismatched ids or revisions, and re-answering confirmed
fields fail closed.
