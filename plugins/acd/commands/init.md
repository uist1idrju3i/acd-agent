---
description: Initialize an ACD workspace and record its prepared revision.
argument-hint: "--repo-url <url> --revision <commit-or-ref> --workspace <path>"
allowed-tools:
  - terminal
---

# ACD workspace initialization

Run the bundled initialization script with explicit repository, revision, and
workspace arguments. Use the invocation that matches how the plugin is
installed:

```bash
# Installed plugin (absolute path, no variable required):
python3 "$HOME/.openhands/plugins/installed/acd/skills/acd-install-doctor/scripts/init_workspace.py" \
  --repo-url <repo-url> --revision <commit-or-ref> --workspace <workspace-path>

# Repository checkout (run from the checkout root):
python3 plugins/acd/skills/acd-install-doctor/scripts/init_workspace.py \
  --repo-url <repo-url> --revision <commit-or-ref> --workspace <workspace-path>
```

Do not set `ACD_PLUGIN_ROOT` and use it in the same terminal call — the
variable must be exported in an earlier call before it can expand. Prefer the
two explicit forms above so no variable is needed at all.

The script can exceed a 120 s terminal timeout (repository clone, recursive
submodules, and the locked image pull), so invoke it with a longer timeout
or run it in the background and poll its progress log:

```bash
nohup python3 "$HOME/.openhands/plugins/installed/acd/skills/acd-install-doctor/scripts/init_workspace.py" \
  --repo-url <repo-url> --revision <commit-or-ref> --workspace <workspace-path> \
  > /tmp/acd-init.log 2>&1 &
# then poll:
tail -n 20 /tmp/acd-init.log
```

The script writes `[init] <step>: start` / `[init] <step>: ok|failed (<seconds>s)`
progress lines to stderr (interleaved into the log above); keep polling
`tail -n 20 /tmp/acd-init.log` until the final JSON report appears. The JSON
report is the last block of stdout — everything else in the log is progress.
The script itself emits only the JSON report on stdout.

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
