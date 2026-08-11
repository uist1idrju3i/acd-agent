"""Command-line entrypoint for the SessionStart hook.

Reads the SDK ``HookEvent`` JSON on stdin, runs the startup checks, and
follows the SDK hook contract: exit 0 with a JSON decision on stdout, or
exit 2 (blocking deny) with the reasons on stderr. Any internal error also
exits 2 (fail-closed).

Expectations are read from ``acd-startup.json`` next to the working
directory's ``plugins/acd`` directory when present; otherwise defaults apply.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

from openhands.sdk.extensions.installation.metadata import InstallationMetadata
from openhands.sdk.hooks.types import HookDecision

from acd_runtime.startup import StartupExpectations, validate_session_start


def main() -> int:
    try:
        event = cast(object, json.loads(sys.stdin.read() or "{}"))
        working_dir: object = None
        if isinstance(event, dict):
            working_dir = cast(dict[str, object], event).get("working_dir")
        expectations = StartupExpectations()
        metadata = InstallationMetadata()
        if isinstance(working_dir, str):
            expectations_path = Path(working_dir) / "acd-startup.json"
            if expectations_path.exists():
                expectations = StartupExpectations.model_validate_json(
                    expectations_path.read_text(encoding="utf-8")
                )
            installed = Path(working_dir) / ".openhands" / ".installed.json"
            if installed.exists():
                metadata = InstallationMetadata.model_validate_json(
                    installed.read_text(encoding="utf-8")
                )
        report = validate_session_start(
            expectations,
            tool_versions={},
            metadata=metadata,
            actual_mcp_config_hash=None,
        )
    except Exception as exc:
        print(f"ACD SessionStart validation error: {exc}", file=sys.stderr)
        return 2
    if report.decision is HookDecision.DENY:
        for check in report.failures():
            print(f"deny: {check.name}: {check.detail}", file=sys.stderr)
        return 2
    print(json.dumps({"decision": "allow"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
