---
description: Diagnose ACD plugin installation integrity and local runtime capabilities.
argument-hint: ""
allowed-tools:
  - terminal
---

# ACD install doctor

Run the existing install doctor script and report its JSON result without
inventing, weakening, or replacing any gate:

- GUI install path: `~/.openhands/plugins/installed/acd/skills/acd-install-doctor/scripts/install_doctor.py`
- Development checkout path: `plugins/acd/skills/acd-install-doctor/scripts/install_doctor.py`

Use `python3 <resolved-path>`. Preserve the JSON fields and status exactly.
An `unknown` result in a required check is fail-closed and means the diagnosis
is `failed`. Missing optional host capabilities may produce `degraded` with
exit code 0. This L3 observation does not grant acceptance authority and does
not produce authoritative Evidence. Report the result as observed; do not
turn host or Skill observations into a passing gate or authoritative Evidence.
