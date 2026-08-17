---
description: Run the deterministic ACD electrical and mechanical gates.
argument-hint: "[--fixture PATH] [--out PATH]"
allowed-tools:
  - terminal
---

Run the requested deterministic ACD gate pipelines using the repository's existing CLI
entrypoints. Do not invent or weaken gates, thresholds, expected values, or evidence rules.
Report each stage, tool version, input/output evidence path, and failure reason. Treat missing
tools, malformed inputs, unknown states, and unverified stages as fail-closed. Skill output and
AI review are not acceptance evidence.
