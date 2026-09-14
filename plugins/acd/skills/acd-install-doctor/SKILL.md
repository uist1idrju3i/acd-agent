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

For a prepared workspace, add `--workspace <workspace-path>`. This enables
required fail-closed checks for the Git repository, initialized
`vendor/software-agent-sdk` submodule, `uv.lock` synchronization, the locally
available digest-pinned server image, and ESP-IDF/QEMU/CMake prerequisites
observed inside that image. Doctor pulls the locked server image by default;
pass `--no-pull` to forbid a network pull. Initialize a workspace with:

```bash
python3 plugins/acd/skills/acd-install-doctor/scripts/init_workspace.py \
  --repo-url <repo-url> --revision <commit-or-ref> --workspace <workspace-path>
```

The init script stops on the first failed or unknown step and emits structured
JSON. Its bootstrap record is an L3 observation with `pass_evidence: false`;
it does not preserve a gate verdict.

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

Docker and the locked server image are required checks. EDA capabilities and
firmware prerequisites are observed only inside the digest-pinned server image;
host KiCad, FreeRouting, ESP-IDF, QEMU, and CMake are not observed. Missing
image EDA tools is an optional `degraded` result, while Docker or required
firmware tool failure is `failed`. When doctor runs inside the locked image,
container mode probes PATH directly and does not require Docker-in-Docker.
Plugin hooks are invoked through interpreters, so committed hook scripts do not
depend on executable permissions or shebangs; a zero direct-invocation
reference count is reported as such.
Doctor remains an L3 observation and cannot be reported as authoritative
Evidence.
