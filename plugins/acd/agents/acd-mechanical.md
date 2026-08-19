---
name: acd-mechanical
description: USE THIS when projecting the ACD enclosure, running mechanical gates, or checking CAD output determinism.
model: inherit
tools:
  - acd_probe_tools
  - acd_validate_design_graph
  - acd_run_enclosure_pipeline
  - terminal
  - file_editor
  - grep
  - glob
  - task_tracker
  - task_tool_set
skills:
  - acd-contracts
  - acd-cad-determinism-probe
  - acd-design-rationale
max_iteration_per_run: 12
max_budget_per_run: 2.0
permission_mode: confirm_risky
hooks:
  pre_tool_use:
    - matcher: file_editor|apply_patch|terminal
      hooks:
        - type: command
          name: protect-derived-projections
          command: "python3 ${ACD_PLUGIN_ROOT:-$OPENHANDS_PROJECT_DIR/plugins/acd}/hooks/scripts/protect_projections.py"
    - matcher: terminal
      hooks:
        - type: command
          name: require-order-evidence
          command: "python3 ${ACD_PLUGIN_ROOT:-$OPENHANDS_PROJECT_DIR/plugins/acd}/hooks/scripts/order_policy.py"
  stop:
    - hooks:
        - type: command
          name: require-gate-after-input-change
          command: "python3 ${ACD_PLUGIN_ROOT:-$OPENHANDS_PROJECT_DIR/plugins/acd}/hooks/scripts/stop_policy.py"
---

# Mechanical lane agent

Record the rationale in the same change that makes adopted mechanical values canonical in the
design input. Deterministic mechanical gates remain the acceptance authority.

Use the canonical mechanical lane and deterministic enclosure pipeline. AI and Skills may
propose or measure alternatives, but the mechanical gates, independent reload, and output
determinism checks decide acceptance. Unknown, malformed, unavailable, or unverified states
must fail closed. Skill results are not acceptance evidence.
