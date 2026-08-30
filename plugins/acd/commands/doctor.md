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
availability, and firmware prerequisites inside the locked server image. These
workspace checks are required and fail closed when unknown. By default doctor
pulls the locked server image when it is not available locally; pass
`--no-pull` to forbid network pulls. The workspace digest check only verifies
local availability after the server image check.
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

Docker and the locked server image are required checks. EDA capabilities and
firmware prerequisites are observed inside that digest-pinned image; doctor
does not observe host KiCad, FreeRouting, ESP-IDF, QEMU, or CMake. Missing image
EDA tools produce `degraded` because that check remains optional, while missing
required firmware tools or unavailable Docker produce `failed`. When running
inside the locked image, container mode probes PATH directly and does not
require Docker-in-Docker. Plugin hooks are invoked through interpreters and
therefore do not depend on hook script executable bits or shebangs. This L3
observation does not grant acceptance authority and does not produce
authoritative Evidence. Report the result as observed; do not turn host or
Skill observations into a passing gate or authoritative Evidence.

The optional host resource preflight check reports MemTotal, MemAvailable, swap,
CPU count, and free disk using the fixed container profile of 8 GiB memory,
512 MiB headroom, 2 CPU cores, 8 GiB free disk, and 2 GiB FreeRouting JVM heap.
Its findings use the same resource vocabulary as container startup. A degraded
or unknown result is an L3 observation only; it does not grant lane-gate or
authoritative Evidence acceptance.
