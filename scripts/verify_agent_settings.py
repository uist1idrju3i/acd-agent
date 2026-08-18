"""Generate or verify the ACD agent settings, profile, and credential manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

from acd.schema.agent_settings import AcdSettingsReport

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS = REPO_ROOT / "plugins" / "acd" / "agent-settings.json"
DEFAULT_POLICY = REPO_ROOT / "plugins" / "acd" / "model-policy.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify agent settings")
    mode.add_argument("--write", action="store_true", help="write agent settings")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the agent settings check without emitting a traceback."""
    from acd.openhands.session.routing import (
        ModelRoutingError,
        load_model_routing_policy,
    )
    from acd.openhands.session.settings import (
        AcdSettingsError,
        acd_settings_report,
        load_acd_settings_manifest,
        write_acd_settings_manifest,
    )

    args = _parser().parse_args(argv)
    try:
        manifest = load_acd_settings_manifest(args.settings)
        if args.write:
            manifest = write_acd_settings_manifest(manifest, args.settings)
        policy = load_model_routing_policy(args.policy)
        report = acd_settings_report(manifest, policy)
    except (OSError, AcdSettingsError, ModelRoutingError, ValueError) as exc:
        report = AcdSettingsReport(
            status="unknown",
            manifest_hash="unknown",
            reason=str(exc),
        )
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
