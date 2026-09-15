---
name: acd-workaround
description: Plan deterministic firmware, rework, and combined workaround candidates from an eligible defect record, then observe salvage-gate results.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - workaround
  - rework
  - salvage
  - ワークアラウンド
  - 追加工
  - 救済
---

# ACD workaround

This Skill is an L2 steering and observation mechanism. It has no approval
authority and never creates authoritative Evidence or promotes an observation
to an L1 decision. The deterministic ACD gates and revision-matched
authoritative Evidence remain the only approval boundary. Constrained salvage
is not a pass.

The Skill turns an eligible defect record into a deterministic candidate set:

| Script | Purpose |
| --- | --- |
| `workaround.py` | Loads contracts, derives candidates, validates completed proposals, and calls the existing defect and salvage APIs. |
| `propose_workaround.py` | Writes `workaround-candidates.json` with firmware-only, rework-only, and combined strategy entries. |
| `check_workaround.py` | Checks an agent-completed candidate and writes the observed `workaround-evaluation.json`. |

The reusable library is also available as a pinned PEP 723 script:

```bash
uv run --script plugins/acd/skills/acd-workaround/scripts/workaround.py
```

## Propose, complete, check

Run proposal generation against the graph and defect document:

```bash
uv run python plugins/acd/skills/acd-workaround/scripts/propose_workaround.py \
  --graph fixtures/golden-design-1/graph.json \
  --defects fixtures/defect/sample/defects.json \
  --defect-id defect.r4-mpn \
  --out-dir out/workaround
```

The proposal is blocked when the fresh defect-record check does not establish
an eligible root cause. A blocked proposal contains no candidates and exits
non-zero. When eligible, all three strategies are emitted, including explicit
`not_applicable` entries when a strategy has no applicable anchor.

An agent may complete only a `proposed` template from this candidate set. It
must not invent anchors or introduce a node outside the candidate's
`anchor_node_ids`. It must replace placeholder `WA-000` with a real workaround
ID, preserve the graph and base revision, and keep the strategy's operation
contract. DFA assessments must cite their basis. A candidate template is a
skeleton, not an approval or a completed design.

Check the completed proposal through the existing salvage gate:

```bash
uv run python plugins/acd/skills/acd-workaround/scripts/check_workaround.py \
  --graph fixtures/golden-design-1/graph.json \
  --defects fixtures/defect/sample/defects.json \
  --candidates out/workaround/workaround-candidates.json \
  --candidate-id WC-001 \
  --rework fixtures/rework/sample/rework.json \
  --dfa fixtures/rework/sample/rework-dfa.json \
  --fixture-dir fixtures/golden-design-1 \
  --approval fixtures/rework/sample/safety-approval.json \
  --erc-evidence fixtures/rework/sample/evidence/erc.json \
  --drc-evidence fixtures/rework/sample/evidence/drc.json \
  --out-dir out/workaround-check
```

The check re-runs the defect gate and delegates salvageability to
`acd.core.salvage_gate`; it does not duplicate or reinterpret gate logic. The
evaluation JSON reports the result as observed. `salvageable` is the only
zero-exit result. `constrained_salvage` is explicitly not a pass, and
`not_salvageable` remains a fail-closed observation. Safety approvals and
authoritative Evidence must be supplied through their existing governed
paths; this Skill cannot grant them.
