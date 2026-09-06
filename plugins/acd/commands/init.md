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
python3 "${ACD_PLUGIN_ROOT:-plugins/acd}/skills/acd-install-doctor/scripts/init_workspace.py" \
  --repo-url <repo-url> --revision <commit-or-ref> --workspace <workspace-path>
```

For an installed plugin the plugin root is
`~/.openhands/plugins/installed/acd`, so set
`ACD_PLUGIN_ROOT="$HOME/.openhands/plugins/installed/acd"` there; the
checkout-relative fallback above covers running from a repository checkout.
The script can exceed a 120 s terminal timeout (repository clone, recursive
submodules, and the locked image pull), so invoke it with a longer timeout
or run it in the background and poll its output.

The script performs workspace creation, shallow repository clone or
clean-checkout reuse, shallow recursive submodule initialization, plugin
manifest/assets verification, and the workspace-aware install doctor. It does
not run host `uv sync`; dependencies and EDA/FW tools are provided by the
locked server image. Doctor pulls that image when needed. It writes
`.openhands/bootstrap-record.json` only after every step succeeds.

Preserve the emitted JSON exactly. Any failed or unknown step is fail-closed
with `ok: false`, `fail_closed: true`, `failure_reason`, `failed_step`, and
the preceding step results. The bootstrap record records
`source: "mounted"` and the locked server image digest when available. It is
an L3 observation with `pass_evidence: false`; it does not grant gate
acceptance or preserve any verdict.
