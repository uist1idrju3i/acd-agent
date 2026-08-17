---
name: acd-design-rationale
description: Record and validate typed design rationale for adopted ACD values.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - rationale
  - design decision
  - justification
  - provenance
---

# ACD design rationale

Record a rationale in the same change that makes an adopted value canonical.
Use the script below to calculate the subject hash, append the record, and run
the deterministic coverage gate:

```bash
uv run python plugins/acd/skills/acd-design-rationale/scripts/record_rationale.py \
  --graph fixtures/golden-design-1/graph.json \
  --rationale fixtures/golden-design-1/rationale.json \
  --record record.json
```

The graph and rationale document are authoritative. This Skill cannot approve
a design, and malformed input, missing subjects, stale records, or duplicate
coverage must stop the operation.

When a requirement exists as a graph node, use `driving_requirements`. When it
exists only in the design document, use `driving_requirement_refs` with a
reference such as `docs/golden-design-1.md#GD1-REQ-012`; do not invent a graph
node to satisfy coverage.
