---
description: Initialize an ACD workspace and record its prepared revision.
argument-hint: "--repo-url <url> --revision <commit-or-ref> --workspace <path>"
allowed-tools:
  - terminal
---

# ACD workspace initialization

Run the bundled initialization script with explicit repository, revision, and
workspace arguments:

```bash
python3 plugins/acd/skills/acd-install-doctor/scripts/init_workspace.py \
  --repo-url <repo-url> --revision <commit-or-ref> --workspace <workspace-path>
```

The script performs workspace creation, repository clone or clean-checkout
reuse, recursive submodule initialization, `uv sync`, plugin manifest/assets
verification, and the workspace-aware install doctor. It writes
`.openhands/bootstrap-record.json` only after every step succeeds.

Preserve the emitted JSON exactly. Any failed or unknown step is fail-closed
with `ok: false`, `fail_closed: true`, `failure_reason`, `failed_step`, and
the preceding step results. The bootstrap record is an L3 observation and
contains `pass_evidence: false`; it does not grant gate acceptance or preserve
any verdict.
