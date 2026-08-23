#!/usr/bin/env python3
"""Verify the pinned ACD package contract and detect implementation skew."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

try:
    import verify_skill_metadata as _metadata
except ModuleNotFoundError:
    from scripts import verify_skill_metadata as _metadata

metadata_body = _metadata.metadata_body
metadata_block = _metadata.metadata_block
read_ref = _metadata.read_ref
read_requires_python = _metadata.read_requires_python
relative = _metadata.relative

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugins" / "acd"
SKILLS_ROOT = PLUGIN_ROOT / "skills"
REF_PATH = SKILLS_ROOT / "acd-package-ref.txt"
CONTRACT_PATH = SKILLS_ROOT / "acd-package-contract.json"
PROBE_PATH = REPO_ROOT / "scripts" / "probe_pinned_acd_graph.py"


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def acd_symbols(source: str, filename: str) -> tuple[list[str], bool, str | None]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as error:
        return [], False, str(error)
    symbols: set[str] = set()
    imports_acd = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "acd" or alias.name.startswith("acd."):
                    imports_acd = True
                    symbols.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module
            if module is None or not (module == "acd" or module.startswith("acd.")):
                continue
            imports_acd = True
            for alias in node.names:
                if alias.name == "*":
                    symbols.add(module)
                else:
                    symbols.add(f"{module}.{alias.name}")
    return sorted(symbols), imports_acd, None


def _script_paths(repository: Path) -> list[Path]:
    paths = sorted((repository / "plugins" / "acd" / "skills").glob("*/scripts/*.py"))
    probe = repository / "scripts" / "probe_pinned_acd_graph.py"
    if probe.is_file():
        paths.append(probe)
    return paths


def discover_scripts(repository: Path, errors: list[str]) -> list[Path]:
    probe_path = repository / "scripts" / "probe_pinned_acd_graph.py"
    discovered: list[Path] = []
    for path in _script_paths(repository):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"{relative(path, repository)}: cannot read script: {error}")
            continue
        _symbols, imports_acd, parse_error = acd_symbols(source, str(path))
        if parse_error is not None:
            errors.append(f"{relative(path, repository)}: cannot parse script: {parse_error}")
            continue
        if imports_acd:
            discovered.append(path)
        elif path == probe_path:
            errors.append(f"{relative(path, repository)}: probe must import acd")
    if not discovered:
        errors.append("fail-closed: no ACD-importing scripts discovered")
    return discovered


def _literal_members(source: str, name: str, filename: str) -> list[str] | None:
    tree = ast.parse(source, filename=filename)
    values: list[str] = []
    found = False
    for node in ast.walk(tree):
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            if any(isinstance(item, ast.Name) and item.id == name for item in node.targets):
                target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if not isinstance(target, ast.Name) or target.id != name:
            continue
        found = True
        if not isinstance(value, ast.Subscript):
            raise ValueError(f"{name} is not a Literal alias")
        slice_value = value.slice
        members = (
            slice_value.elts if isinstance(slice_value, ast.Tuple) else [slice_value]
        )
        for member in members:
            if isinstance(member, ast.Constant) and isinstance(member.value, str):
                values.append(member.value)
            else:
                raise ValueError(f"{name} contains a non-string member")
    return sorted(set(values)) if found else None


def _git_show(repository: Path, ref: str, path: str) -> str:
    completed = _git(repository, "show", f"{ref}:{path}")
    if completed.returncode != 0:
        raise ValueError(f"git show {ref}:{path} failed: {completed.stderr.strip()}")
    return completed.stdout


def resolve_ref(repository: Path, ref: str | None, errors: list[str]) -> str | None:
    if ref is None:
        return None
    shallow = _git(repository, "rev-parse", "--is-shallow-repository")
    if shallow.returncode != 0 or shallow.stdout.strip() != "false":
        errors.append("repository history is shallow or cannot be determined")
        return None
    resolved = _git(repository, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if resolved.returncode != 0:
        errors.append(f"pinned ref {ref!r} does not resolve to a local commit")
        return None
    commit = resolved.stdout.strip()
    ancestor = _git(repository, "merge-base", "--is-ancestor", commit, "HEAD")
    if ancestor.returncode != 0:
        errors.append(f"pinned ref {ref!r} is not an ancestor of HEAD")
        return None
    return commit


def _schema_matches_ref(repository: Path, ref: str, errors: list[str]) -> None:
    diff = _git(repository, "diff", "--quiet", ref, "--", "src/acd/schema")
    if diff.returncode != 0:
        errors.append("src/acd/schema differs from the pinned ref")
    untracked = _git(
        repository,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        "src/acd/schema",
    )
    if untracked.returncode != 0:
        errors.append("cannot determine untracked files under src/acd/schema")
    elif untracked.stdout.strip():
        errors.append("untracked files exist under src/acd/schema")


def schema_contract(
    repository: Path, ref: str, errors: list[str]
) -> tuple[str, list[str], list[str] | None] | None:
    try:
        tree = _git(repository, "rev-parse", f"{ref}:src/acd/schema")
        if tree.returncode != 0:
            raise ValueError(tree.stderr.strip())
        source = _git_show(repository, ref, "src/acd/schema/design_graph.py")
        node_kinds = _literal_members(source, "NodeKind", "design_graph.py")
        if not node_kinds:
            raise ValueError("pinned schema NodeKind is missing or empty")
        return (
            tree.stdout.strip(),
            node_kinds,
            _literal_members(source, "EdgeKind", "design_graph.py"),
        )
    except (OSError, ValueError, SyntaxError) as error:
        errors.append(f"pinned schema cannot be read: {error}")
        return None


def fixture_kinds(repository: Path, errors: list[str]) -> list[str]:
    kinds: set[str] = set()
    for path in sorted((repository / "fixtures").glob("**/graph.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            errors.append(f"{relative(path, repository)}: fixture cannot be parsed: {error}")
            continue
        if not isinstance(document, dict):
            errors.append(f"{relative(path, repository)}: fixture root is not an object")
            continue
        document = cast(dict[str, Any], document)
        for collection_name in ("nodes", "edges"):
            collection = document.get(collection_name, [])
            if not isinstance(collection, list):
                errors.append(f"{relative(path, repository)}: {collection_name} is not a list")
                continue
            for index, item in enumerate(cast(list[Any], collection)):
                item_dict = cast(dict[str, Any], item) if isinstance(item, dict) else {}
                if not isinstance(item, dict) or not isinstance(item_dict.get("kind"), str):
                    errors.append(
                        f"{relative(path, repository)}: {collection_name}[{index}].kind "
                        "is missing or not a string"
                    )
                else:
                    kinds.add(cast(str, item["kind"]))
    return sorted(kinds)


def _top_level_names(source: str, filename: str) -> set[str]:
    tree = ast.parse(source, filename=filename)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(target.id for target in targets if isinstance(target, ast.Name))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _git_show_module(repository: Path, ref: str, module: str) -> tuple[str, str]:
    base = "src/" + "/".join(module.split("."))
    for path in (base + ".py", base + "/__init__.py"):
        try:
            return _git_show(repository, ref, path), path
        except ValueError:
            continue
    raise ValueError(f"module {module!r} is absent from pinned tree")


def _api_matches_ref(
    repository: Path, ref: str, scripts: list[Path], errors: list[str]
) -> None:
    for script in scripts:
        try:
            source = script.read_text(encoding="utf-8")
            symbols, _, parse_error = acd_symbols(source, str(script))
            if parse_error is not None:
                continue
            for symbol in symbols:
                try:
                    _git_show_module(repository, ref, symbol)
                    continue
                except ValueError:
                    pass
                parts = symbol.split(".")
                if len(parts) < 2:
                    errors.append(
                        f"{relative(script, repository)}: invalid ACD symbol {symbol!r}"
                    )
                    continue
                module = ".".join(parts[:-1])
                pinned_source, path = _git_show_module(repository, ref, module)
                if parts[-1] not in _top_level_names(pinned_source, path):
                    errors.append(
                        f"{relative(script, repository)}: pinned API symbol {symbol!r} "
                        f"is absent from {path}"
                    )
        except (OSError, ValueError, SyntaxError) as error:
            errors.append(
                f"{relative(script, repository)}: pinned API cannot be inspected: {error}"
            )


def _contract_for(
    repository: Path,
    ref: str,
    scripts: list[Path],
    errors: list[str],
) -> dict[str, Any] | None:
    schema = schema_contract(repository, ref, errors)
    if schema is None:
        return None
    schema_tree_sha, node_kinds, edge_kinds = schema
    fixture_values = fixture_kinds(repository, errors)
    entries: list[dict[str, Any]] = []
    for script in scripts:
        try:
            source = script.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"{relative(script, repository)}: cannot hash script: {error}")
            continue
        symbols, _, parse_error = acd_symbols(source, str(script))
        if parse_error is not None:
            continue
        entries.append(
            {
                "path": relative(script, repository),
                "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "acd_symbols": symbols,
            }
        )
    contract: dict[str, Any] = {
        "ref": ref,
        "schema_tree_sha": schema_tree_sha,
        "node_kinds": node_kinds,
        "fixture_kinds": fixture_values,
        "scripts": sorted(entries, key=lambda entry: cast(str, entry["path"])),
    }
    if edge_kinds is not None:
        contract["edge_kinds"] = edge_kinds
    return contract


def canonical(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def verify_metadata(repository: Path = REPO_ROOT) -> list[str]:
    """Return metadata and PEP 723 block errors without using git."""
    errors: list[str] = []
    ref = read_ref(repository, errors)
    requires_python = read_requires_python(repository, errors)
    scripts = discover_scripts(repository, errors)
    metadata_blocks: set[str] = set()
    expected_dependency = (
        f"acd @ git+https://github.com/uist1idrju3i/acd-agent@{ref}"
        if ref is not None
        else None
    )
    for script in scripts:
        relative_path = relative(script, repository)
        try:
            source = script.read_text(encoding="utf-8")
            script_requires, dependencies, metadata_error = metadata_body(source)
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"{relative_path}: cannot read metadata: {error}")
            continue
        if metadata_error is not None:
            errors.append(f"{relative_path}: {metadata_error}")
        elif requires_python is not None and script_requires != requires_python:
            errors.append(f"{relative_path}: requires-python does not match pyproject.toml")
        if expected_dependency is not None and dependencies != [expected_dependency]:
            errors.append(f"{relative_path}: dependency does not match package ref")
        block = metadata_block(source)
        if block is None:
            errors.append(f"{relative_path}: cannot extract PEP 723 metadata block")
        else:
            metadata_blocks.add(block)
    if len(metadata_blocks) > 1:
        errors.append("ACD-importing scripts do not share one PEP 723 metadata block")
    return errors


def verify_repository(repository: Path = REPO_ROOT) -> list[str]:
    """Return all package contract errors found in a repository tree."""
    errors = verify_metadata(repository)
    ref = read_ref(repository, errors)
    scripts = discover_scripts(repository, errors)

    resolved = resolve_ref(repository, ref, errors)
    contract_path = (
        repository / "plugins" / "acd" / "skills" / "acd-package-contract.json"
    )
    if ref is not None and resolved is not None:
        _schema_matches_ref(repository, ref, errors)
        _api_matches_ref(repository, ref, scripts, errors)
        contract = _contract_for(repository, ref, scripts, errors)
        if contract is not None:
            kinds = set(cast(list[str], contract["node_kinds"])) | set(
                cast(list[str], contract.get("edge_kinds", []))
            )
            missing = sorted(set(cast(list[str], contract["fixture_kinds"])) - kinds)
            if missing:
                errors.append(
                    "fixture kinds are absent from pinned schema: " + ", ".join(missing)
                )
            try:
                actual = contract_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                errors.append(f"{relative(contract_path, repository)}: cannot read: {error}")
            else:
                if actual != canonical(contract):
                    errors.append(f"{relative(contract_path, repository)}: contract drift")
    return errors


def write_contract(repository: Path = REPO_ROOT) -> list[str]:
    """Regenerate the contract after metadata and ref validation."""
    errors: list[str] = []
    ref = read_ref(repository, errors)
    scripts = discover_scripts(repository, errors)
    if ref is None:
        return errors
    if resolve_ref(repository, ref, errors) is None:
        return errors
    contract = _contract_for(repository, ref, scripts, errors)
    if contract is not None:
        (repository / "plugins" / "acd" / "skills" / "acd-package-contract.json").write_text(
            canonical(contract), encoding="utf-8"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify the committed contract")
    mode.add_argument("--write", action="store_true", help="regenerate the contract")
    mode.add_argument(
        "--metadata-only",
        action="store_true",
        help="verify metadata and PEP 723 blocks without using git",
    )
    args = parser.parse_args(argv)
    try:
        if args.metadata_only:
            errors = verify_metadata()
        elif args.write:
            errors = write_contract()
        else:
            errors = verify_repository()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: fail-closed: {error}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Skill package contract verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
