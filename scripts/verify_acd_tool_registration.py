"""Generate or verify the ACD ToolDefinition registration manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

from acd.schema.tool_registration import ToolRegistrationReport

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AGENT_DIR = REPO_ROOT / "plugins" / "acd" / "agents"
DEFAULT_MANIFEST = REPO_ROOT / "plugins" / "acd" / ".plugin" / "acd-tool-definitions.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify registration drift")
    mode.add_argument("--write", action="store_true", help="write the registration manifest")
    parser.add_argument("--agent-dir", type=Path, default=DEFAULT_AGENT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--command",
        type=Path,
        help="check whether a conversation exposes the tools this command declares",
    )
    parser.add_argument(
        "--available",
        action="append",
        default=None,
        metavar="TOOL",
        help=(
            "tool name available in the calling conversation; repeatable. "
            "Omit to inspect the registration surface of this process instead."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the registration check without emitting a traceback."""
    from acd.openhands.tools.ambient import (
        AmbientToolError,
        check_ambient_tool_availability,
        registered_tool_names,
        render_tool_availability,
    )
    from acd.openhands.tools.registration import (
        ToolRegistrationError,
        check_tool_registration,
        write_tool_registration_manifest,
    )

    args = _parser().parse_args(argv)
    if args.command is not None:
        available = (
            registered_tool_names() if args.available is None else tuple(args.available)
        )
        try:
            availability = check_ambient_tool_availability(args.command, available)
        except (AmbientToolError, OSError, ValueError) as exc:
            print(f"ACD tool availability could not be determined: {exc}")
            return 2
        print(render_tool_availability(availability))
        print(availability.model_dump_json(indent=2))
        return 0 if availability.status == "pass" else 2
    try:
        if args.write:
            manifest = write_tool_registration_manifest(args.manifest)
            report = ToolRegistrationReport(
                status="pass",
                manifest_hash=manifest.canonical_hash,
                registered_tools=[tool.tool_name for tool in manifest.tools],
            )
        else:
            report = check_tool_registration(
                agent_dir=args.agent_dir,
                manifest_path=args.manifest,
            )
    except (OSError, ToolRegistrationError, ValueError) as exc:
        report = ToolRegistrationReport(status="unknown", reason=str(exc))
    print(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report.status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
