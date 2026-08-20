# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "acd @ git+https://github.com/uist1idrju3i/acd-agent@4cca489171ac53e6e55639b791c8571482167bd2",
# ]
# ///
"""Write the design knowledge index and the derived troubleshooting knowledge.

The index enumerates which knowledge sources exist for the indexed revision and
which ones are unknown, so a later answer can cite a source or report unknown
instead of guessing. Both artifacts are L3 observations.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from knowledge_inputs import (
    INDEX_NAME,
    TROUBLESHOOTING_NAME,
    KnowledgeInputError,
    add_input_arguments,
    load_knowledge_base,
    paths_from_args,
    write_knowledge_artifact,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_input_arguments(parser)
    parser.add_argument("--audience", choices=("internal", "public"), default="internal")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        base = load_knowledge_base(paths_from_args(args), args.audience)
    except (KnowledgeInputError, ValueError) as exc:
        print(f"knowledge index unavailable: {exc}", file=sys.stderr)
        return 2

    index_path = write_knowledge_artifact(
        artifact_kind="knowledge_index",
        payload=base.index.model_dump(mode="json"),
        out_dir=args.out_dir,
        name=INDEX_NAME,
    )
    troubleshooting = base.troubleshooting
    if troubleshooting is None:  # pragma: no cover - always derived by the loader
        print("troubleshooting knowledge unavailable", file=sys.stderr)
        return 2
    troubleshooting_path = write_knowledge_artifact(
        artifact_kind="troubleshooting_knowledge",
        payload=troubleshooting.model_dump(mode="json"),
        out_dir=args.out_dir,
        name=TROUBLESHOOTING_NAME,
    )
    print(f"knowledge index: {index_path}")
    print(f"troubleshooting knowledge: {troubleshooting_path}")
    for source in base.index.unknown_sources():
        print(f"unknown source: {source.kind} {source.reference} ({source.reason})")
    for entry in troubleshooting.unknown_entries():
        print(f"unknown troubleshooting entry: {entry.entry_id} ({entry.reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
