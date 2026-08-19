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
treated as a failure. Host EDA execution remains provisional and cannot be
reported as authoritative Evidence.
