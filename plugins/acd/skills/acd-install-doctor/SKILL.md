---
name: acd-install-doctor
description: Check whether the ACD plugin was installed correctly and report runtime and host capability observations. Use after ACD installation or when checking the Local GUI environment.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - install check
  - installation check
  - environment check
  - plugin diagnosis
  - Local GUI
---

# ACD install doctor

Run `scripts/install_doctor.py` to inspect the installed ACD plugin tree and the
local execution prerequisites. The script uses only the Python standard library
and does not import `acd`, so it observes the user's environment rather than an
isolated `uv run --script` environment.

```bash
python3 plugins/acd/skills/acd-install-doctor/scripts/install_doctor.py
```

This is an L3 observation only. It has no authority to accept or reject a
design, generate authoritative Evidence, or replace the deterministic ACD
gates. Required installation checks are fail-closed; an `unknown` result is
treated as a failure. The required install-location check distinguishes a
development checkout from the direct
`~/.openhands/plugins/installed/acd/` root and detects a missing
`repo_path: plugins/acd` installation. The prompt manifest check validates the
canonical manifest hash and byte-exact asset hashes; SDK-normalized
`prompt_hash` values remain authoritative in
`scripts/verify_agent_prompts.py --check`.

Optional capability checks observe Docker, host EDA tools, and direct hook
invocability. Host EDA absence is observational and does not lower the
status. Docker unavailability can produce `degraded`. Plugin hooks are invoked
through interpreters, so committed hook scripts do not depend on executable
permissions or shebangs; a zero direct-invocation reference count is reported
as such.
Host EDA execution remains provisional and cannot be reported as authoritative
Evidence.
