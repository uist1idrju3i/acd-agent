#!/usr/bin/env python3
"""Update the pinned ACD package ref and regenerate its contract."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

try:
    from verify_skill_metadata import metadata_body as _metadata_body
except ModuleNotFoundError:
    from scripts.verify_skill_metadata import metadata_body as _metadata_body
from verify_skill_package_ref import (
    acd_symbols,
    canonical,
    discover_scripts,
    fixture_kinds,
    relative,
    resolve_ref,
    schema_contract,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REF_PATH = REPO_ROOT / "plugins" / "acd" / "skills" / "acd-package-ref.txt"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def update(repository: Path, ref: str) -> list[str]:
    """Rewrite all package metadata and the generated contract."""
    errors: list[str] = []
    if SHA_RE.fullmatch(ref) is None:
        return ["ref must be exactly a 40-character lowercase SHA"]
    if resolve_ref(repository, ref, errors) is None:
        return errors
    scripts = discover_scripts(repository, errors)
    if errors:
        return errors
    ref_path = repository / "plugins" / "acd" / "skills" / "acd-package-ref.txt"
    expected = f"acd @ git+https://github.com/uist1idrju3i/acd-agent@{ref}"
    changed: list[str] = []
    old_ref = ref_path.read_text(encoding="utf-8") if ref_path.exists() else None
    new_ref = ref + "\n"
    if old_ref != new_ref:
        ref_path.write_text(new_ref, encoding="utf-8")
        changed.append(relative(ref_path, repository))
    for script in scripts:
        source = script.read_text(encoding="utf-8")
        _, _, metadata_error = _metadata_body(source)
        if metadata_error is not None:
            errors.append(f"{relative(script, repository)}: {metadata_error}")
            continue
        lines = source.splitlines(keepends=True)
        updated = False
        for index, line in enumerate(lines):
            if "acd @ git+https://github.com/uist1idrju3i/acd-agent@" in line:
                replacement = f'#     "{expected}",\n'
                if line != replacement:
                    lines[index] = replacement
                    updated = True
                    changed.append(relative(script, repository))
                break
        else:
            errors.append(f"{relative(script, repository)}: dependency line is missing")
        if updated:
            script.write_text("".join(lines), encoding="utf-8")
    if errors:
        return errors
    schema = schema_contract(repository, ref, errors)
    if schema is None:
        return errors
    schema_tree_sha, node_kinds, edge_kinds = schema
    contract: dict[str, Any] = {
        "ref": ref,
        "schema_tree_sha": schema_tree_sha,
        "node_kinds": node_kinds,
        "edge_kinds": edge_kinds,
        "fixture_kinds": fixture_kinds(repository, errors),
        "scripts": [],
    }
    script_entries: list[dict[str, Any]] = []
    for script in scripts:
        source = script.read_text(encoding="utf-8")
        symbols, _, parse_error = acd_symbols(source, str(script))
        if parse_error:
            errors.append(f"{relative(script, repository)}: {parse_error}")
            continue
        script_entries.append(
            {
                "path": relative(script, repository),
                "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "acd_symbols": symbols,
            }
        )
    script_entries.sort(key=lambda entry: entry["path"])
    contract["scripts"] = script_entries
    contract_path = repository / "plugins" / "acd" / "skills" / "acd-package-contract.json"
    new_contract = canonical(contract)
    old_contract = contract_path.read_text(encoding="utf-8") if contract_path.exists() else None
    if old_contract != new_contract:
        contract_path.write_text(new_contract, encoding="utf-8")
        changed.append(relative(contract_path, repository))
    for path in dict.fromkeys(changed):
        print(f"変更: {path}")
    if not changed:
        print("変更なし")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True)
    args = parser.parse_args(argv)
    try:
        errors = update(REPO_ROOT, args.ref)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"ERROR: fail-closed: {error}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
