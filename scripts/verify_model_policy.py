"""Generate or verify the deterministic ACD model routing policy."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

from acd.schema.model_routing import ModelRoutingReport

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = REPO_ROOT / "plugins" / "acd" / "model-policy.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify model policy")
    mode.add_argument("--write", action="store_true", help="write model policy")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the model policy check without emitting a traceback."""
    from acd.openhands.session.routing import (
        ModelRoutingError,
        load_model_routing_policy,
        model_routing_policy_report,
        write_model_routing_policy,
    )

    args = _parser().parse_args(argv)
    try:
        policy = load_model_routing_policy(args.policy)
        if args.write:
            policy = write_model_routing_policy(policy, args.policy)
        report = model_routing_policy_report(policy)
    except (OSError, ModelRoutingError, ValueError) as exc:
        report = ModelRoutingReport(
            status="unknown",
            policy_hash="unknown",
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
