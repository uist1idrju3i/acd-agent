"""Replay the tracked ACD event view from its source EventLog."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")

from acd.schema.context import EventViewCheckReport

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVENT_LOG = REPO_ROOT / "fixtures" / "context" / "valid" / "event-log.json"
DEFAULT_EVENT_VIEW = REPO_ROOT / "fixtures" / "context" / "valid" / "event-view.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify the event view")
    mode.add_argument("--write", action="store_true", help="write the event view")
    parser.add_argument("--event-log", type=Path, default=DEFAULT_EVENT_LOG)
    parser.add_argument("--event-view", type=Path, default=DEFAULT_EVENT_VIEW)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the display-only view replay without emitting a traceback."""
    from acd.openhands.session.context import (
        AcdContextError,
        event_view_check_report,
        event_view_projection,
        load_event_log,
        load_event_view_projection,
    )

    args = _parser().parse_args(argv)
    try:
        events = load_event_log(args.event_log)
        if args.write:
            projection = event_view_projection(events)
            args.event_view.write_text(
                json.dumps(
                    projection.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        report = event_view_check_report(
            load_event_view_projection(args.event_view), events
        )
    except (OSError, AcdContextError, ValueError) as exc:
        report = EventViewCheckReport(
            status="unknown",
            canonical_hash="unknown",
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
