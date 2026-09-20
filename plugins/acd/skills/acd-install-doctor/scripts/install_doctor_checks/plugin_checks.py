"""Checks over the installed ACD plugin tree (manifest, assets, prompts, tools).

This package is part of the install doctor L3 observation and uses only the
standard library; it never imports ``acd``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, cast

from install_doctor_checks.common import (
    HASH_RE,
    SEMVER_RE,
    SHA256_RE,
    check_result,
    front_matter,
    front_matter_list,
    hook_references,
    plugin_asset_path,
    read_json,
    relative_path,
    sha256,
)


def manifest_check(plugin_root: Path) -> dict[str, Any]:
    path = plugin_root / ".plugin" / "plugin.json"
    try:
        document = read_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return check_result(
            "plugin manifest",
            True,
            "unknown",
            f"{relative_path(path, plugin_root)} could not be parsed: {exc}",
            path="plugin",
        )
    if not isinstance(document, dict):
        return check_result(
            "plugin manifest", True, "fail", "manifest root is not an object", path="plugin"
        )
    document = cast(dict[str, Any], document)
    name = document.get("name")
    if name != "acd":
        return check_result(
            "plugin manifest",
            True,
            "fail",
            f"manifest name must be 'acd', found {name!r}; a path omission can infer "
            "acd-agent-<hash>",
            str(name) if name is not None else None,
            path="plugin",
        )
    return check_result(
        "plugin manifest", True, "pass", "manifest name is acd", "acd", path="plugin"
    )


def install_location_check(plugin_root: Path) -> dict[str, Any]:
    store = Path.home() / ".openhands" / "plugins" / "installed"
    manifest_path = plugin_root / ".plugin" / "plugin.json"
    try:
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict):
            return check_result(
                "plugin install location",
                True,
                "unknown",
                "could not determine the plugin manifest name",
                path="plugin",
            )
        manifest = cast(dict[str, Any], manifest)
        manifest_name = manifest.get("name")
        if not isinstance(manifest_name, str):
            return check_result(
                "plugin install location",
                True,
                "unknown",
                "could not determine the plugin manifest name",
                path="plugin",
            )
        root = plugin_root.resolve()
        store_root = store.resolve()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        return check_result(
            "plugin install location",
            True,
            "unknown",
            f"could not inspect the plugin install location: {exc}",
            path="plugin",
        )
    try:
        relative = root.relative_to(store_root)
    except ValueError:
        return check_result(
            "plugin install location",
            True,
            "pass",
            "plugin root is outside the installed plugin store; treated as a development checkout",
            "development checkout",
            path="plugin",
        )
    if len(relative.parts) == 1 and relative.name == manifest_name:
        return check_result(
            "plugin install location",
            True,
            "pass",
            f"plugin root is the direct installed plugin directory {relative.name}",
            relative.name,
            path="plugin",
        )
    return check_result(
        "plugin install location",
        True,
        "fail",
        "plugin was most likely installed without repo_path: plugins/acd or under an "
        "unexpected directory name. OpenHands loads the outer directory and none of these "
        "assets. Reinstall with source github:uist1idrju3i/acd-agent and path plugins/acd.",
        str(root),
        path="plugin",
    )


def assets_check(plugin_root: Path) -> dict[str, Any]:
    skills = sorted(path for path in (plugin_root / "skills").glob("*/SKILL.md"))
    agents = sorted((plugin_root / "agents").glob("*.md"))
    commands = sorted((plugin_root / "commands").glob("*.md"))
    hooks_path = plugin_root / "hooks" / "hooks.json"
    errors: list[str] = []
    skill_names: list[str] = []
    for skill in skills:
        try:
            fields = front_matter(skill.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"{relative_path(skill, plugin_root)}: {exc}")
            continue
        name = fields.get("name", "")
        if not name:
            errors.append(f"{relative_path(skill, plugin_root)}: front-matter name is missing")
        else:
            skill_names.append(name)
    if not skills:
        errors.append("skills/*/SKILL.md: no Skill files found")
    if not agents:
        errors.append("agents/*.md: at least one agent definition is required")
    if not commands:
        errors.append("commands/*.md: at least one command is required")
    plugin_refs: list[str] = []
    external_refs: list[str] = []
    try:
        hooks = read_json(hooks_path)
        plugin_refs, external_refs, _ = hook_references(hooks, plugin_root)
        missing = [item for item in plugin_refs if item.endswith(": missing")]
        if missing:
            errors.extend(f"hooks/hooks.json: referenced plugin script {item}" for item in missing)
        if not plugin_refs:
            errors.append("hooks/hooks.json: no plugin script references found")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"hooks/hooks.json could not be parsed: {exc}")
    detail = (
        f"{len(skills)} Skill(s) with names, {len(agents)} agent file(s), "
        f"{len(commands)} command file(s), {len(plugin_refs)} plugin hook script reference(s)"
    )
    if external_refs:
        detail += (
            "; external workspace script references are not part of the copied plugin "
            f"tree and were not evaluated: {', '.join(external_refs)}"
        )
    if errors:
        return check_result("plugin assets", True, "fail", "; ".join(errors), None, path="plugin")
    return check_result(
        "plugin assets", True, "pass", detail, ", ".join(sorted(skill_names)), path="plugin"
    )


def prompt_manifest_check(plugin_root: Path) -> dict[str, Any]:
    manifest_path = plugin_root / "agents" / "prompt-manifest.json"
    try:
        document = read_json(manifest_path)
        if not isinstance(document, dict):
            raise ValueError("manifest root is not an object")
        document = cast(dict[str, Any], document)
        entries = document["entries"]
        if not isinstance(entries, list):
            raise ValueError("entries is not a list")
        entries = cast(list[Any], entries)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return check_result(
            "agent prompt manifest", True, "unknown", f"manifest is invalid: {exc}", path="plugin"
        )
    errors: list[str] = []
    canonical_hash = document.get("canonical_hash")
    if not isinstance(canonical_hash, str) or not HASH_RE.fullmatch(canonical_hash):
        errors.append("canonical_hash is invalid")
    else:
        canonical_value = dict(document)
        canonical_value["canonical_hash"] = "unknown"
        try:
            canonical_json = json.dumps(
                canonical_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            actual_canonical_hash = f"sha256:{hashlib.sha256(canonical_json).hexdigest()}"
        except (TypeError, ValueError) as exc:
            errors.append(f"canonical_hash cannot be computed: {exc}")
        else:
            if canonical_hash != actual_canonical_hash:
                errors.append("canonical_hash does not match the manifest contents")
    listed_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("manifest entry is not an object")
            continue
        entry = cast(dict[str, Any], entry)
        asset_path = entry.get("asset_path")
        role = entry.get("role", "<unknown>")
        if not isinstance(asset_path, str):
            errors.append(f"{role}: asset_path is missing")
            continue
        relative_asset_path = plugin_asset_path(asset_path)
        listed_paths.add(relative_asset_path)
        target = (plugin_root / relative_asset_path).resolve()
        try:
            target.relative_to(plugin_root.resolve())
        except ValueError:
            errors.append(f"{role}: asset path escapes plugin root")
            continue
        if not target.is_file():
            errors.append(f"{role}: asset is missing: {asset_path}")
            continue
        try:
            actual_asset_hash = sha256(target)
            fields = front_matter(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"{role}: asset cannot be read: {exc}")
            continue
        expected_asset_hash = entry.get("asset_hash")
        expected_prompt_hash = entry.get("prompt_hash")
        if not isinstance(expected_asset_hash, str) or not HASH_RE.fullmatch(expected_asset_hash):
            errors.append(f"{role}: asset_hash is invalid")
        elif expected_asset_hash != actual_asset_hash:
            errors.append(f"{role}: asset_hash does not match {asset_path}")
        if not isinstance(expected_prompt_hash, str) or not HASH_RE.fullmatch(expected_prompt_hash):
            errors.append(f"{role}: prompt_hash is invalid")
        if fields.get("name") != role:
            errors.append(f"{role}: front-matter name does not match manifest role")
    actual_paths = {
        relative_path(path, plugin_root) for path in (plugin_root / "agents").glob("acd-*.md")
    }
    if actual_paths != listed_paths:
        errors.append(
            f"manifest agent set differs; missing={sorted(listed_paths - actual_paths)}, "
            f"unlisted={sorted(actual_paths - listed_paths)}"
        )
    if errors:
        return check_result("agent prompt manifest", True, "fail", "; ".join(errors), path="plugin")
    return check_result(
        "agent prompt manifest",
        True,
        "pass",
        f"{len(entries)} agent asset hashes and canonical hash match; "
        "scripts/verify_agent_prompts.py --check is authoritative for SDK-normalized "
        "prompt hashes",
        str(len(entries)),
        path="plugin",
    )


def _metadata_body(source: str) -> tuple[str, str]:
    lines = source.splitlines()
    if not lines or lines[0].strip() != "# /// script":
        raise ValueError("missing PEP 723 block at the top")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "# ///")
    except StopIteration as exc:
        raise ValueError("PEP 723 block has no closing marker") from exc
    body = "\n".join(
        line[2:] if line.startswith("# ") else "" if line == "#" else line for line in lines[1:end]
    )
    return body, "\n".join(lines[end + 1 :])


def _acd_symbols(source: str, filename: str) -> tuple[set[str], str | None]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return set(), str(exc)
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "acd" or alias.name.startswith("acd."):
                    symbols.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module
            if module is None or not (module == "acd" or module.startswith("acd.")):
                continue
            for alias in node.names:
                symbols.add(module if alias.name == "*" else f"{module}.{alias.name}")
    return symbols, None


def package_ref_check(plugin_root: Path) -> dict[str, Any]:
    ref_path = plugin_root / "skills" / "acd-package-ref.txt"
    contract_path = plugin_root / "skills" / "acd-package-contract.json"
    try:
        lines = ref_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return check_result(
            "Skill package reference", True, "unknown", f"ref cannot be read: {exc}", path="plugin"
        )
    ref = lines[0].strip() if len(lines) == 1 else ""
    if len(lines) != 1 or not ref or not (SHA256_RE.fullmatch(ref) or SEMVER_RE.fullmatch(ref)):
        return check_result(
            "Skill package reference",
            True,
            "fail",
            "ref must be exactly one 40-character SHA or v<semver> line",
            ref or None,
            path="plugin",
        )
    errors: list[str] = []
    importing_scripts = 0
    imported_script_data: dict[str, tuple[str, set[str]]] = {}
    expected_dependency = f"acd @ git+https://github.com/uist1idrju3i/acd-agent@{ref}"
    scripts = sorted((plugin_root / "skills").glob("*/scripts/*.py"))
    scripts.extend(sorted((plugin_root / "mcp").glob("*.py")))
    for script in scripts:
        try:
            source = script.read_text(encoding="utf-8")
            symbols, parse_error = _acd_symbols(source, str(script))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            errors.append(f"{relative_path(script, plugin_root)} cannot be parsed: {exc}")
            continue
        if parse_error is not None:
            errors.append(f"{relative_path(script, plugin_root)} cannot be parsed: {parse_error}")
            continue
        if not symbols:
            continue
        importing_scripts += 1
        relative_script = relative_path(script, plugin_root)
        imported_script_data[relative_script] = (
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
            symbols,
        )
        try:
            metadata, _ = _metadata_body(source)
        except ValueError as exc:
            errors.append(f"{relative_script}: {exc}")
            continue
        requires = re.findall(r'(?m)^requires-python\s*=\s*"([^"]+)"\s*$', metadata)
        dependencies = re.findall(r'(?m)^\s*"([^"]+)"\s*,?\s*$', metadata)
        if len(requires) != 1 or len(dependencies) != 1:
            errors.append(f"{relative_script}: invalid PEP 723 dependency metadata")
        elif dependencies[0] != expected_dependency:
            errors.append(f"{relative_script}: dependency does not match package ref")
    if importing_scripts == 0:
        errors.append("no Skill script importing acd was found")
    try:
        contract = read_json(contract_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return check_result(
            "Skill package reference",
            True,
            "fail",
            f"contract is missing or cannot be parsed: {exc}",
            ref,
            path="plugin",
        )
    if not isinstance(contract, dict):
        return check_result(
            "Skill package reference",
            True,
            "fail",
            "contract root is not an object",
            ref,
            path="plugin",
        )
    contract = cast(dict[str, Any], contract)
    if contract.get("ref") != ref:
        errors.append("contract.ref does not match the package ref")
    entries = contract.get("scripts")
    entry_map: dict[str, dict[str, Any]] = {}
    if not isinstance(entries, list):
        errors.append("contract.scripts is not a list")
        contract_entries: list[Any] = []
    else:
        contract_entries = cast(list[Any], entries)
    for index, entry in enumerate(contract_entries):
        if not isinstance(entry, dict):
            errors.append(f"contract.scripts[{index}] is not an object")
            continue
        entry = cast(dict[str, Any], entry)  # pyright: ignore[reportUnnecessaryCast]
        path = entry.get("path")
        if not isinstance(path, str):
            errors.append(f"contract.scripts[{index}].path is not a string")
            continue
        entry_map[path] = entry
    for relative, (digest, symbols) in imported_script_data.items():
        entry = entry_map.get(f"plugins/acd/{relative}")
        if entry is None:
            errors.append(f"{relative}: missing contract script entry")
            continue
        if entry.get("sha256") != digest:
            errors.append(f"{relative}: script sha256 does not match contract")
        contract_symbols = entry.get("acd_symbols")
        contract_symbol_items = (
            cast(list[Any], contract_symbols) if isinstance(contract_symbols, list) else []
        )
        if not isinstance(contract_symbols, list) or not all(
            isinstance(item, str) for item in contract_symbol_items
        ):
            errors.append(f"{relative}: contract acd_symbols is invalid")
        elif not symbols.issubset(set(cast(list[str], contract_symbol_items))):
            errors.append(f"{relative}: imported acd symbols exceed contract symbols")
    node_kinds_value = contract.get("node_kinds")
    edge_kinds_present = "edge_kinds" in contract
    edge_kinds_value = contract.get("edge_kinds")
    fixture_kinds_value = contract.get("fixture_kinds")
    node_kinds_valid = isinstance(node_kinds_value, list) and all(
        isinstance(item, str) for item in cast(list[Any], node_kinds_value)
    )
    fixture_kinds_valid = isinstance(fixture_kinds_value, list) and all(
        isinstance(item, str) for item in cast(list[Any], fixture_kinds_value)
    )
    edge_kinds_valid = not edge_kinds_present or (
        isinstance(edge_kinds_value, list)
        and all(isinstance(item, str) for item in cast(list[Any], edge_kinds_value))
    )
    if not (node_kinds_valid and edge_kinds_valid and fixture_kinds_valid):
        errors.append("contract kind lists are invalid")
    node_kinds = cast(list[str], node_kinds_value) if node_kinds_valid else []
    edge_kinds = (
        cast(list[str], edge_kinds_value) if edge_kinds_present and edge_kinds_valid else []
    )
    fixture_kinds = cast(list[str], fixture_kinds_value) if fixture_kinds_valid else []
    missing_kinds = sorted(set(fixture_kinds) - (set(node_kinds) | set(edge_kinds)))
    if missing_kinds:
        errors.append("contract fixture kinds are absent from schema: " + ", ".join(missing_kinds))
    counts = (
        f"scripts={importing_scripts};contract_scripts={len(contract_entries)};"
        f"fixture_kinds={len(fixture_kinds)};"
        f"node_kinds={len(node_kinds)};"
        f"edge_kinds={len(edge_kinds)}"
    )
    if errors:
        return check_result(
            "Skill package reference",
            True,
            "fail",
            f"{counts};errors=" + "; ".join(errors),
            ref,
            path="plugin",
        )
    return check_result(
        "Skill package reference",
        True,
        "pass",
        counts,
        ref,
        path="plugin",
    )


def _run_mcp_tool_listing(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )


def mcp_server_check(plugin_root: Path) -> dict[str, Any]:
    """Check the ambient MCP server and pre-warm its uv environment."""
    config_path = plugin_root / ".mcp.json"
    try:
        document = read_json(config_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return check_result(
            "ACD MCP server",
            True,
            "unknown",
            f"{relative_path(config_path, plugin_root)} could not be inspected: {exc}",
            path="plugin",
        )
    if not isinstance(document, dict):
        return check_result(
            "ACD MCP server",
            True,
            "unknown",
            "MCP configuration root is not an object",
            path="plugin",
        )
    document = cast(dict[str, Any], document)
    raw_servers = document.get("mcpServers")
    servers = cast(dict[str, Any], raw_servers) if isinstance(raw_servers, dict) else None
    server = servers.get("acd") if servers is not None else None
    if not isinstance(server, dict):
        return check_result(
            "ACD MCP server",
            True,
            "fail",
            "mcpServers.acd is missing or invalid",
            path="plugin",
        )
    server = cast(dict[str, Any], server)
    command = server.get("command")
    args = server.get("args")
    if (
        command != "uv"
        or not isinstance(args, list)
        or not all(isinstance(item, str) for item in cast(list[Any], args))
    ):
        return check_result(
            "ACD MCP server",
            True,
            "fail",
            "mcpServers.acd must use the uv command and string args",
            path="plugin",
        )
    args = cast(list[str], args)
    try:
        script_index = args.index("--script") + 1
        script_value = args[script_index]
    except (ValueError, IndexError):
        return check_result(
            "ACD MCP server",
            True,
            "fail",
            "mcpServers.acd args must include --script and a script path",
            path="plugin",
        )
    script_value = script_value.replace("${SKILL_ROOT}", str(plugin_root))
    script_path = Path(script_value)
    if not script_path.is_absolute():
        script_path = plugin_root / script_path
    script_path = script_path.resolve()
    try:
        script_path.relative_to(plugin_root.resolve())
    except ValueError:
        return check_result(
            "ACD MCP server",
            True,
            "fail",
            "MCP server script must remain under the plugin root",
            path="plugin",
        )
    if not script_path.is_file():
        return check_result(
            "ACD MCP server",
            True,
            "fail",
            f"MCP server script is missing: {relative_path(script_path, plugin_root)}",
            path="plugin",
        )

    resolved_args = [argument.replace("${SKILL_ROOT}", str(plugin_root)) for argument in args]
    try:
        completed = _run_mcp_tool_listing([command, *resolved_args, "--list-tools"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return check_result(
            "ACD MCP server",
            True,
            "unknown",
            f"tool listing could not complete: {exc}",
            path="plugin",
        )
    if completed.returncode != 0:
        return check_result(
            "ACD MCP server",
            True,
            "unknown",
            f"tool listing exited with {completed.returncode}: "
            f"{completed.stderr.strip() or 'no stderr'}",
            path="plugin",
        )
    try:
        listing = json.loads(completed.stdout)
        if not isinstance(listing, dict):
            raise ValueError("tool listing must be an object")
        listing = cast(dict[str, Any], listing)
        listed_names = listing.get("tools")
        if not isinstance(listed_names, list) or not all(
            isinstance(name, str) for name in cast(list[Any], listed_names)
        ):
            raise ValueError("tool listing tools must be a string list")
        manifest = read_json(plugin_root / ".plugin" / "acd-tool-definitions.json")
        manifest_tools = manifest["tools"]
        expected_names = sorted(
            cast(dict[str, Any], item)["tool_name"]
            for item in cast(list[Any], manifest_tools)
            if isinstance(item, dict)
        )
        actual_names = sorted(cast(list[str], listed_names))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return check_result(
            "ACD MCP server",
            True,
            "unknown",
            f"tool listing was invalid: {exc}",
            path="plugin",
        )
    if actual_names != expected_names:
        missing = sorted(set(expected_names) - set(actual_names))
        extra = sorted(set(actual_names) - set(expected_names))
        return check_result(
            "ACD MCP server",
            True,
            "fail",
            f"tool names differ from .plugin/acd-tool-definitions.json; "
            f"missing={missing}, extra={extra}",
            ", ".join(actual_names),
            path="plugin",
        )
    return check_result(
        "ACD MCP server",
        True,
        "pass",
        f"{len(actual_names)} tool(s) exposed through the ambient .mcp.json stdio server. "
        "The SDK lists MCP tools with a 30s timeout, so this pre-warm must pass before "
        "a GUI conversation starts; tool calls time out at 300s.",
        ", ".join(actual_names),
        path="plugin",
    )


def hook_invocability_check(plugin_root: Path) -> dict[str, Any]:
    hooks_path = plugin_root / "hooks" / "hooks.json"
    try:
        hooks = read_json(hooks_path)
        _, _, direct_refs = hook_references(hooks, plugin_root)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return check_result(
            "hook invocability",
            False,
            "unknown",
            f"hooks/hooks.json could not be inspected: {exc}",
            path="plugin",
        )
    observations: list[str] = []
    failures: list[str] = []
    seen: set[str] = set()
    for relative, target in direct_refs:
        if relative in seen:
            continue
        seen.add(relative)
        executable = os.access(target, os.X_OK)
        try:
            has_shebang = target.read_bytes().startswith(b"#!")
        except (OSError, UnicodeDecodeError):
            has_shebang = False
        observations.append(
            f"{relative}: executable={str(executable).lower()}, shebang={str(has_shebang).lower()}"
        )
        if not executable or not has_shebang:
            failures.append(relative)
    if not direct_refs:
        return check_result(
            "hook invocability",
            False,
            "pass",
            "all plugin hooks are invoked through an interpreter and do not depend on "
            "executable bits",
            "0",
            path="plugin",
        )
    if failures:
        return check_result(
            "hook invocability",
            False,
            "fail",
            "A non-executable or shebang-less hook command cannot run, so hook policy "
            f"would not be enforced: {', '.join(failures)}. "
            f"Observations: {'; '.join(observations)}",
            path="plugin",
        )
    return check_result(
        "hook invocability",
        False,
        "pass",
        f"direct plugin hook scripts are executable with shebangs: {'; '.join(observations)}",
        str(len(seen)),
        path="plugin",
    )


def agent_skills_check(plugin_root: Path) -> dict[str, Any]:
    """Reject declared subagent Skill names, which the SDK cannot resolve.

    The SDK subagent registry resolves ``skills:`` names against the user and
    project Skill stores only and raises when a name is absent, so a declared
    plugin-bundled Skill name aborts conversation startup.
    """
    agents = sorted((plugin_root / "agents").glob("acd-*.md"))
    if not agents:
        return check_result(
            "agent skill declarations",
            True,
            "fail",
            "agents/acd-*.md: no agent definition found",
            path="plugin",
        )
    errors: list[str] = []
    for agent in agents:
        try:
            declared = front_matter_list(agent.read_text(encoding="utf-8"), "skills")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"{relative_path(agent, plugin_root)}: {exc}")
            continue
        if declared:
            errors.append(
                f"{relative_path(agent, plugin_root)}: declares Skill names the SDK "
                f"subagent registry cannot resolve: {', '.join(declared)}"
            )
    if errors:
        return check_result(
            "agent skill declarations", True, "fail", "; ".join(errors), path="plugin"
        )
    return check_result(
        "agent skill declarations",
        True,
        "pass",
        f"{len(agents)} agent definition(s) reference plugin Skill assets by path "
        "and declare no subagent Skill names",
        str(len(agents)),
        path="plugin",
    )


def hook_root_resolution_check(plugin_root: Path) -> dict[str, Any]:
    """Require every plugin hook command to resolve the installed plugin root.

    The SDK exports only ``OPENHANDS_PROJECT_DIR`` to hooks, which points at the
    conversation workspace. On the installed-plugin path the plugin tree lives in
    the installed plugin store instead, so a workspace-only path makes every hook
    exit with a missing script and block all tool calls.
    """
    hooks_path = plugin_root / "hooks" / "hooks.json"
    candidates = (
        "${ACD_PLUGIN_ROOT",
        "${OPENHANDS_PROJECT_DIR",
        ".openhands/plugins/installed/acd",
    )
    try:
        document = read_json(hooks_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return check_result(
            "hook plugin root resolution",
            True,
            "fail",
            f"hooks/hooks.json could not be parsed: {exc}",
            path="plugin",
        )
    commands: dict[str, str] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            mapping = cast(dict[str, Any], value)
            name = mapping.get("name")
            command = mapping.get("command")
            if isinstance(name, str) and isinstance(command, str) and "/hooks/scripts/" in command:
                commands[name] = command
            for child in mapping.values():
                visit(child)
        elif isinstance(value, list):
            for child in cast(list[Any], value):
                visit(child)

    visit(document)
    if not commands:
        return check_result(
            "hook plugin root resolution",
            True,
            "fail",
            "hooks/hooks.json: no plugin hook command found",
            path="plugin",
        )
    errors = [
        f"{name}: {candidate} is not a resolution candidate"
        for name, command in sorted(commands.items())
        for candidate in candidates
        if candidate not in command
    ]
    if errors:
        return check_result(
            "hook plugin root resolution", True, "fail", "; ".join(errors), path="plugin"
        )
    return check_result(
        "hook plugin root resolution",
        True,
        "pass",
        f"{len(commands)} plugin hook command(s) resolve the plugin root from "
        "ACD_PLUGIN_ROOT, the workspace plugin tree, and the installed plugin store",
        str(len(commands)),
        path="plugin",
    )


def tool_registration_check(plugin_root: Path) -> dict[str, Any]:
    """Diagnose whether agent definitions match the ACD tool registration surface.

    Conversations see ACD tools only when ``register_acd_tools()`` has run in the
    conversation process and the agent definition declares the registered names.
    This check compares the declared names against the manifest asset generated
    from the code contract; scripts/verify_acd_tool_registration.py --check is
    authoritative for the live SDK registry.
    """
    manifest_path = plugin_root / ".plugin" / "acd-tool-definitions.json"
    try:
        document = read_json(manifest_path)
        if not isinstance(document, dict):
            raise ValueError("manifest root is not an object")
        document = cast(dict[str, Any], document)
        entry_point = document["entry_point"]
        tools = document["tools"]
        if not isinstance(entry_point, str) or not isinstance(tools, list):
            raise ValueError("entry_point or tools is invalid")
        tool_names = {
            cast(dict[str, Any], tool)["tool_name"]
            for tool in cast(list[Any], tools)
            if isinstance(tool, dict)
        }
        if len(tool_names) != len(cast(list[Any], tools)) or not tool_names:
            raise ValueError("tool names are missing or duplicated")
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return check_result(
            "ACD tool registration",
            True,
            "unknown",
            f"{relative_path(manifest_path, plugin_root)} could not be inspected: {exc}",
            path="plugin",
        )
    agents = sorted((plugin_root / "agents").glob("acd-*.md"))
    if not agents:
        return check_result(
            "ACD tool registration",
            True,
            "fail",
            "agents/acd-*.md: no agent definition found",
            path="plugin",
        )
    errors: list[str] = []
    declaring_agents = 0
    for agent in agents:
        try:
            declared = front_matter_list(agent.read_text(encoding="utf-8"), "tools")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"{relative_path(agent, plugin_root)}: {exc}")
            continue
        acd_tools = [name for name in declared if name.startswith("acd_")]
        if acd_tools:
            declaring_agents += 1
        unknown = sorted(set(acd_tools) - tool_names)
        if unknown:
            errors.append(
                f"{relative_path(agent, plugin_root)}: declares ACD tools that "
                f"{entry_point} never registers: {', '.join(unknown)}"
            )
    if declaring_agents == 0:
        errors.append(
            "no agent definition declares an ACD tool, so conversations reach the "
            "deterministic entrypoints through terminal only"
        )
    if errors:
        return check_result("ACD tool registration", True, "fail", "; ".join(errors), path="plugin")
    return check_result(
        "ACD tool registration",
        True,
        "pass",
        f"{len(tool_names)} ACD tool name(s) registered by {entry_point} and declared by "
        f"{declaring_agents} agent definition(s); a conversation must call {entry_point} "
        "and use either register_acd_tools() (explicit path) or the plugin .mcp.json "
        "server (ambient path) for these tools to appear. "
        "scripts/verify_acd_tool_registration.py --check is authoritative for the live "
        "SDK registry.",
        ", ".join(sorted(tool_names)),
        path="plugin",
    )


def store_check(plugin_root: Path) -> dict[str, Any]:
    store = Path.home() / ".openhands" / "plugins" / "installed"
    try:
        if not store.exists():
            return check_result(
                "installed plugin store",
                False,
                "pass",
                f"{store} is absent; current root is treated as a development checkout",
                "not present",
                path="plugin",
            )
        plugins = sorted(path.name for path in store.iterdir() if path.is_dir())
        root = plugin_root.resolve()
        store_root = store.resolve()
        try:
            relative = root.relative_to(store_root)
        except ValueError:
            relative = None
        if relative is None:
            route = "development checkout"
        elif len(relative.parts) == 1 and relative.name == "acd":
            route = "direct GUI installed plugin root"
        else:
            route = "nested or unexpectedly named store path; not a valid GUI plugin root"
        return check_result(
            "installed plugin store",
            False,
            "pass",
            f"store plugins: {plugins}; current plugin root is {route}",
            ", ".join(plugins) or "empty",
            path="plugin",
        )
    except OSError as exc:
        return check_result(
            "installed plugin store",
            False,
            "unknown",
            f"store cannot be inspected: {exc}",
            path="plugin",
        )
