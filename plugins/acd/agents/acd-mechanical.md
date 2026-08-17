---
name: acd-mechanical
description: USE THIS when projecting the ACD enclosure, running mechanical gates, or checking CAD output determinism.
model: inherit
tools:
  - terminal
  - file_editor
  - grep
  - glob
  - task_tracker
skills:
  - acd-contracts
  - acd-cad-determinism-probe
  - acd-design-rationale
max_iteration_per_run: 12
max_budget_per_run: 2.0
permission_mode: confirm_risky
---

# Mechanical lane agent

Record the rationale in the same change that makes adopted mechanical values canonical in the
design input. Deterministic mechanical gates remain the acceptance authority.

Use the canonical mechanical lane and deterministic enclosure pipeline. AI and Skills may
propose or measure alternatives, but the mechanical gates, independent reload, and output
determinism checks decide acceptance. Unknown, malformed, unavailable, or unverified states
must fail closed. Skill results are not acceptance evidence.
