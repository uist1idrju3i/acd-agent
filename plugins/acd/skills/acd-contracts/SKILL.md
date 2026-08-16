---
name: acd-contracts
description: How to read and validate ACD contracts (design graph, evidence, gate matrix) in this workspace. Use when creating or checking ACD documents.
---

# ACD contracts

- Pydantic models in `packages/acd-schema` are the canonical contract.
- Every document carries `schema_version` and a `target_revision` (`r<N>`).
- `unknown` values are allowed but fail-closed: they never support a pass verdict.
- Validate documents with:

```bash
uv run pytest packages/acd-schema -q
```
