---
name: acd-contracts
description: How to read and validate ACD contracts (design graph, evidence, gate matrix) in this workspace. Use when creating or checking ACD documents.
---

# ACD contracts

- Contracts are defined by Pydantic models in `packages/acd-schema`.
- Input files and git are the design source of truth.
- `unknown` values are fail-closed: they never support a pass verdict.
- Validate documents with:

```bash
uv run pytest packages/acd-schema -q
```
