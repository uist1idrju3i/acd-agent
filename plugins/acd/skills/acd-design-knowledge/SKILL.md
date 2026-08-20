---
name: acd-design-knowledge
description: Answer product, usage, troubleshooting, rationale and history questions from the indexed design knowledge with source citations.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - ask the design
  - design knowledge
  - knowledge index
  - faq
  - troubleshooting
  - why was this decided
  - when did this change
  - 設計知識
  - 仕様は
  - 使い方
  - 不具合
  - 経緯
  - 根拠
---

# ACD design knowledge QA

Answer questions about a finished design from its own knowledge sources: the
design graph, rationale records, gate results, Evidence, generated documents and
git history. Conversation logs are an internal-only source and are never indexed
for a public audience.

Answers are L2 steering or L3 observations. They restate indexed values with
citations, they cannot approve a design, they never flow back into design
inputs, and a question that cannot be answered from the index is answered
`unknown` with a reason instead of an estimate.

| Script | Purpose |
| --- | --- |
| `knowledge_inputs.py` | Builds the knowledge index, resolves the knowledge sources and writes provenance. |
| `build_knowledge_index.py` | Writes the knowledge index and the derived troubleshooting knowledge. |
| `ask.py` | Answers one question with citations, or reports `unknown` with a non-zero exit code. |
| `generate_faq.py` | Renders the publishable FAQ for the `public` audience into `out/docs/`. |

## Usage

```bash
# Knowledge index and troubleshooting knowledge.
uv run --script plugins/acd/skills/acd-design-knowledge/scripts/build_knowledge_index.py \
    --graph fixtures/golden-design-1/graph.json \
    --rationale fixtures/golden-design-1/rationale.json \
    --documents out/docs \
    --evidence evidence \
    --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
    --out-dir out/knowledge

# One question with citations (exit code 2 when the answer is unknown).
uv run --script plugins/acd/skills/acd-design-knowledge/scripts/ask.py \
    --graph fixtures/golden-design-1/graph.json \
    --rationale fixtures/golden-design-1/rationale.json \
    --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
    --question "LEDが点滅しない場合の確認手順は?"

# Publishable FAQ (public audience: conversation logs are excluded).
uv run --script plugins/acd/skills/acd-design-knowledge/scripts/generate_faq.py \
    --graph fixtures/golden-design-1/graph.json \
    --rationale fixtures/golden-design-1/rationale.json \
    --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
    --out-dir out/docs

# Shared input loader module (dependency self-resolution check).
uv run --script plugins/acd/skills/acd-design-knowledge/scripts/knowledge_inputs.py

# Skill tests (kept separate from the ACD test suite).
uv run pytest plugins/acd/skills/acd-design-knowledge -q
```

`--script`はPEP 723のメタデータから依存を自己解決します。ローカルcheckoutで
開発する場合は`uv run python <path>`を使用します。

## Answering rules

- A question is classified by declared keywords into product specification,
  usage, troubleshooting, design rationale or history. An unmatched question is
  `unknown`.
- Troubleshooting expectations (LED GPIO, blink period, I2C address, log period,
  rail voltages) are derived from the graph and from the generated `acd_pins.h`
  projection. A missing input makes the entry `unknown`.
- History answers come from git and cite commit hashes.
- The knowledge index records missing sources as `unknown` with a reason, so an
  answer is never derived from a source that was not available.
- Conversation logs are indexed only for the `internal` audience. The published
  FAQ records the exclusion in its provenance record.
