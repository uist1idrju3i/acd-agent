---
name: acd-contracts
description: How to read and validate ACD Pydantic contracts in this workspace. Use when creating or checking ACD documents.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - contract
  - Pydantic
  - design graph
  - schema validation
---

# ACD contracts

- Pydantic models in `src/acd/schema` are the canonical contract.
- Contract-bearing documents carry the fields defined by their Pydantic model.
- `unknown` values are allowed but fail-closed: they never support a pass verdict.
- Design decisions are recorded in the typed `rationale.json` contract.
- Validate documents with:

```bash
uv run pytest tests/schema -q
```

Validate rationale coverage with:

```bash
uv run python scripts/check_rationale.py
```
