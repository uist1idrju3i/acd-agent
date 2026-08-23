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
When diagnosing a prepared workspace, pass `--workspace <workspace-path>` to
also check its Git repository, submodule, lock synchronization, locked image
availability, and firmware host prerequisites. These workspace checks are
required and fail closed when unknown; they never attempt a network image pull.
An `unknown` result in a required check is fail-closed and means the diagnosis
is `failed`. The required install-location check reports a development
checkout as valid, but fails a store path other than the direct
`~/.openhands/plugins/installed/acd/` directory; reinstall with source
`github:uist1idrju3i/acd-agent` and path `plugins/acd` when it fails.
The prompt manifest check validates its canonical hash and asset hashes, while
`scripts/verify_agent_prompts.py --check` remains authoritative for
SDK-normalized prompt hashes.
The Skill package reference check also validates the offline package contract:
the contract ref, imported-script hashes and symbols, and fixture kinds must
remain compatible with the pinned ACD schema. A missing or malformed contract
is a required failure.

Optional host capabilities may produce `degraded` with exit code 0. Host EDA
absence is observational and does not itself lower the status. Docker
unavailability can produce `degraded`. Plugin hooks are invoked through
interpreters and therefore do not depend on hook script executable bits or
shebangs. This L3 observation does not grant acceptance authority and does not
produce authoritative Evidence. Report the result as observed; do not turn
host or Skill observations into a passing gate or authoritative Evidence.
