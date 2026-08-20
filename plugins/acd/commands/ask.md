---
description: Answer a design question from the indexed design knowledge with source citations.
argument-hint: "\"<question>\" [--audience internal|public]"
allowed-tools:
  - terminal
---

# ACD design knowledge question

Answer the question with the existing knowledge QA script; do not answer from
memory and do not restate values that are not indexed:

- GUI install path: `~/.openhands/plugins/installed/acd/skills/acd-design-knowledge/scripts/ask.py`
- Development checkout path: `plugins/acd/skills/acd-design-knowledge/scripts/ask.py`

Pass the design graph, the rationale document and the generated `acd_pins.h`
projection of the target revision. Report the returned JSON as observed: every
statement keeps its citation, and an `unknown` status keeps its reason and its
non-zero exit code. Do not fill an `unknown` answer with an estimate, do not
promote an answer to acceptance evidence, and do not write an answer back into
the design inputs. Conversation logs are internal only and must not be used for
a `public` audience answer.
