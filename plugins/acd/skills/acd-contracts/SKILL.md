---
name: acd-contracts
description: How to read and validate ACD Pydantic contracts in this workspace. Use when creating or checking ACD documents.
---

# ACD contracts

- Pydantic models in `packages/acd-schema` are the canonical contract.
- Contract-bearing documents carry the fields defined by their Pydantic model.
- `unknown` values are allowed but fail-closed: they never support a pass verdict.
- Validate documents with:

```bash
uv run pytest packages/acd-schema -q
```
