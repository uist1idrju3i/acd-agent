#!/usr/bin/env python3
"""Print the external tool capability probe report as JSON.

Usage: uv run python scripts/probe_tools.py
Exit code is 0 even when tools are absent: absence is a valid, structured
observation (``version: unknown``), not a script failure. Consumers must
treat unknown versions as fail-closed.
"""

from __future__ import annotations

from acd.openhands import probe_all


def main() -> int:
    report = probe_all()
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
