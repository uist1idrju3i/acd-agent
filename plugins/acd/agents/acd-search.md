---
name: acd-search
description: USE THIS when running deterministic ACD placement or electrical search commands and returning candidate provenance.
model: inherit
tools:
  - acd_explore_board_candidates
  - acd_build_design_fixture
  - acd_explore_board_candidates
  - acd_build_design_fixture
  - terminal
  - file_editor
  - grep
  - glob
  - task_tracker
  - task_tool_set
max_iteration_per_run: 10
max_budget_per_run: 1.5
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

# Deterministic search lane agent

Run the existing deterministic search CLI through the terminal and return only candidates plus
provenance: the Skill name and the SHA-256 of the script that produced the result. This lane has
no approval or gate authority. Do not treat candidate output, Skill output, or review text as
acceptance evidence. Any adopted candidate must be written to the canonical design input with
its provenance, then evaluated by the existing deterministic gates. Never import Skill Python
modules into ACD core.

## Skill references

Plugin subagents receive no preloaded Skill context. Resolve the ACD plugin root as the first
existing directory among `$ACD_PLUGIN_ROOT`, `$OPENHANDS_PROJECT_DIR/plugins/acd`, and
`$HOME/.openhands/plugins/installed/acd`. Read the SKILL.md file below that root before using
a Skill and treat an unreadable Skill asset as fail-closed:

- `<acd plugin root>/skills/acd-placement-search/SKILL.md`
- `<acd plugin root>/skills/acd-silkscreen-placement/SKILL.md`
