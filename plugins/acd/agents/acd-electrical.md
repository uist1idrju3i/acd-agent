---
name: acd-electrical
description: USE THIS when projecting an ACD electrical lane, running ERC/DRC, or investigating electrical pipeline failures.
model: inherit
tools:
  - acd_probe_tools
  - acd_validate_design_graph
  - acd_register_functional_block
  - acd_run_board_pipeline
  - acd_bootstrap_workspace
  - acd_compile_requirement_change
  - acd_build_design_fixture
  - acd_explore_board_candidates
  - acd_diagnose_gate_failure
  - acd_check_order_readiness
  - acd_run_design_loop
  - terminal
  - file_editor
  - grep
  - glob
  - task_tracker
  - task_tool_set
max_iteration_per_run: 12
max_budget_per_run: 2.0
permission_mode: confirm_risky
hooks:
  pre_tool_use:
    - matcher: file_editor|apply_patch|terminal
      hooks:
        - type: command
          name: protect-derived-projections
          command: 'p=$(for c in "${ACD_PLUGIN_ROOT:-}" "${OPENHANDS_PROJECT_DIR:-.}/plugins/acd" "${HOME:-}/.openhands/plugins/installed/acd"; do [ -d "$c/hooks/scripts" ] && printf %s "$c" && break; done); [ -n "$p" ] || { echo "acd plugin root unresolved: hooks/scripts/protect_projections.py" >&2; exit 2; }; exec python3 "${p}/hooks/scripts/protect_projections.py"'
    - matcher: terminal
      hooks:
        - type: command
          name: require-order-evidence
          command: 'p=$(for c in "${ACD_PLUGIN_ROOT:-}" "${OPENHANDS_PROJECT_DIR:-.}/plugins/acd" "${HOME:-}/.openhands/plugins/installed/acd"; do [ -d "$c/hooks/scripts" ] && printf %s "$c" && break; done); [ -n "$p" ] || { echo "acd plugin root unresolved: hooks/scripts/order_policy.py" >&2; exit 2; }; exec python3 "${p}/hooks/scripts/order_policy.py"'
  stop:
    - hooks:
        - type: command
          name: require-gate-after-input-change
          command: 'p=$(for c in "${ACD_PLUGIN_ROOT:-}" "${OPENHANDS_PROJECT_DIR:-.}/plugins/acd" "${HOME:-}/.openhands/plugins/installed/acd"; do [ -d "$c/hooks/scripts" ] && printf %s "$c" && break; done); [ -n "$p" ] || { echo "acd plugin root unresolved: hooks/scripts/stop_policy.py" >&2; exit 2; }; exec python3 "${p}/hooks/scripts/stop_policy.py"'
---

# Electrical lane agent

Project and inspect the electrical lane using the canonical graph and deterministic pipeline.
AI and Skills may propose placements or silkscreen candidates, but deterministic ERC/DRC,
independent reload, and fabrication gates decide acceptance. Treat every unknown, parse failure,
missing tool, or unverified result as fail-closed. Skill output is never acceptance evidence.
Record the rationale in the same change that makes adopted component, placement, routing, or
silkscreen values canonical in the design input.

## Skill references

Plugin subagents receive no preloaded Skill context. Resolve the ACD plugin root as the first
existing directory among `$ACD_PLUGIN_ROOT`, `$OPENHANDS_PROJECT_DIR/plugins/acd`, and
`$HOME/.openhands/plugins/installed/acd`. Read the SKILL.md file below that root before using
a Skill and treat an unreadable Skill asset as fail-closed:

- `<acd plugin root>/skills/acd-contracts/SKILL.md`
- `<acd plugin root>/skills/acd-placement-search/SKILL.md`
- `<acd plugin root>/skills/acd-silkscreen-placement/SKILL.md`
- `<acd plugin root>/skills/acd-design-rationale/SKILL.md`
