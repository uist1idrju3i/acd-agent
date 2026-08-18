"""Generate or verify the deterministic ACD role prompt manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

from acd.schema.prompt_manifest import PromptDriftReport

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AGENT_DIR = REPO_ROOT / "plugins" / "acd" / "agents"
DEFAULT_MANIFEST = DEFAULT_AGENT_DIR / "prompt-manifest.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify prompt manifest drift")
    mode.add_argument("--write", action="store_true", help="write the prompt manifest")
    parser.add_argument("--agent-dir", type=Path, default=DEFAULT_AGENT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    return parser


def _print_report(report: PromptDriftReport) -> None:
    print(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def main(argv: list[str] | None = None) -> int:
    """Run the prompt manifest check without emitting a traceback."""
    from acd.openhands.session.prompts import (
        PromptManifestError,
        check_prompt_manifest,
        write_prompt_manifest,
    )

    args = _parser().parse_args(argv)
    try:
        if args.write:
            write_prompt_manifest(
                args.agent_dir,
                args.manifest,
                root=args.root,
            )
            report = PromptDriftReport(status="pass")
        else:
            report = check_prompt_manifest(
                args.agent_dir,
                args.manifest,
                root=args.root,
            )
    except (OSError, PromptManifestError, ValueError) as exc:
        report = PromptDriftReport(status="unknown", reason=str(exc))
    _print_report(report)
    return 0 if report.status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
