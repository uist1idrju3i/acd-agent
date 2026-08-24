"""Pull a digest-pinned image declared in the image lock and print provenance."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acd.openhands.image_pull import (
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_PULL_TIMEOUT,
    LOCK_ENTRIES,
    ImagePullError,
    pull_locked_image,
)


def main(
    argv: list[str] | None = None,
    *,
    default_lock: Path | None = None,
) -> int:
    """Pull a locked image, or return exit code 2 when the pull fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", choices=LOCK_ENTRIES, required=True)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--timeout", type=float, default=DEFAULT_PULL_TIMEOUT)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--backoff", type=float, default=DEFAULT_BACKOFF_SECONDS)
    parser.add_argument(
        "--record",
        type=Path,
        help="Write the pull provenance record to this path.",
    )
    args = parser.parse_args(argv)

    try:
        record = pull_locked_image(
            args.entry,
            lock_path=args.lock if args.lock is not None else default_lock,
            timeout=args.timeout,
            max_attempts=args.max_attempts,
            backoff_seconds=args.backoff,
        )
    except ImagePullError as exc:
        print(f"image pull error ({exc.failure_kind}): {exc}", file=sys.stderr)
        return 2
    payload = json.dumps(record.as_dict(), indent=2, sort_keys=True, ensure_ascii=False)
    if args.record is not None:
        try:
            args.record.parent.mkdir(parents=True, exist_ok=True)
            args.record.write_text(payload + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"pull record could not be written: {exc}", file=sys.stderr)
            return 2
    print(record.reference)
    print(payload, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
