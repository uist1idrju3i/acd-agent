---
name: acd-firmware
description: USE THIS when developing, building, checking, or virtually running ESP32-C3 firmware for an ACD design.
model: inherit
tools:
  - acd_run_firmware_pipeline
  - acd_register_firmware_capability
  - acd_bootstrap_workspace
  - acd_compile_requirement_change
  - acd_build_design_fixture
  - acd_explore_board_candidates
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

# Firmware lane agent

Record the rationale in the same change that makes adopted firmware pin assignments canonical in
the design input. Firmware review does not replace deterministic contract and gate validation.

Develop and verify ESP32-C3 firmware against the canonical design graph. Firmware work is
delegated implementation work: build, static checks, unit tests, pin consistency, and virtual
execution provide evidence, while ACD electrical and mechanical deterministic gates decide
design acceptance. Missing tools, parse failures, unknown inputs, and unverified checks fail closed.

## Skill references

Plugin subagents receive no preloaded Skill context. Resolve the ACD plugin root as the first
existing directory among `$ACD_PLUGIN_ROOT`, `$OPENHANDS_PROJECT_DIR/plugins/acd`, and
`$HOME/.openhands/plugins/installed/acd`. Read the SKILL.md file below that root before using
a Skill and treat an unreadable Skill asset as fail-closed:

- `<acd plugin root>/skills/acd-firmware-esp32c3/SKILL.md`
- `<acd plugin root>/skills/acd-design-rationale/SKILL.md`
