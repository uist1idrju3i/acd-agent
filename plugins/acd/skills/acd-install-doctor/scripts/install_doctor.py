#!/usr/bin/env python3
"""Inspect ACD installation integrity and local capabilities.

This command is an L3 observation only. It has no authority to accept or reject
an ACD design and never generates or promotes authoritative Evidence. Required
checks fail closed: an unknown result is treated as a failure.

The script intentionally uses only the standard library and does not import
``acd``. In particular, importing ``acd`` from a ``uv run --script`` isolated
environment would inspect the isolated environment instead of the user's
environment and could produce a false diagnosis.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

SHA256_RE = re.compile(r"^[0-9a-f]{40}$")
SEMVER_RE = re.compile(r"^v\d+\.\d+\.\d+$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HOOK_PLUGIN_PATH_RE = re.compile(r"\$\{[^}]+\}(/[^\s'\";]+\.py)")
HOOK_PATH_RE = re.compile(r"(?:^|\s)([A-Za-z0-9_.-]+/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.py)")
LIST_ITEM_RE = re.compile(r"^\s+-\s*(\S+)\s*$")
HOOK_INTERPRETER_RE = re.compile(r"(?:uv run python|python3?)\s+[\"']?$")


def _check(
    name: str,
    required: bool,
    result: str,
    detail: str,
    observed_version: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "required": required,
        "result": result,
        "detail": detail,
        "observed_version": observed_version,
    }


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _front_matter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("front-matter must start with ---")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("front-matter closing --- is missing") from exc
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def _manifest_check(plugin_root: Path) -> dict[str, Any]:
    path = plugin_root / ".plugin" / "plugin.json"
    try:
        document = _read_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _check(
            "plugin manifest",
            True,
            "unknown",
            f"{_relative(path, plugin_root)} could not be parsed: {exc}",
        )
    if not isinstance(document, dict):
        return _check("plugin manifest", True, "fail", "manifest root is not an object")
    document = cast(dict[str, Any], document)
    name = document.get("name")
    if name != "acd":
        return _check(
            "plugin manifest",
            True,
            "fail",
            f"manifest name must be 'acd', found {name!r}; a path omission can infer "
            "acd-agent-<hash>",
            str(name) if name is not None else None,
        )
    return _check("plugin manifest", True, "pass", "manifest name is acd", "acd")


def _install_location_check(plugin_root: Path) -> dict[str, Any]:
    store = Path.home() / ".openhands" / "plugins" / "installed"
    manifest_path = plugin_root / ".plugin" / "plugin.json"
    try:
        manifest = _read_json(manifest_path)
        if not isinstance(manifest, dict):
            return _check(
                "plugin install location",
                True,
                "unknown",
                "could not determine the plugin manifest name",
            )
        manifest = cast(dict[str, Any], manifest)
        manifest_name = manifest.get("name")
        if not isinstance(manifest_name, str):
            return _check(
                "plugin install location",
                True,
                "unknown",
                "could not determine the plugin manifest name",
            )
        root = plugin_root.resolve()
        store_root = store.resolve()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        return _check(
            "plugin install location",
            True,
            "unknown",
            f"could not inspect the plugin install location: {exc}",
        )
    try:
        relative = root.relative_to(store_root)
    except ValueError:
        return _check(
            "plugin install location",
            True,
            "pass",
            "plugin root is outside the installed plugin store; treated as a development checkout",
            "development checkout",
        )
    if len(relative.parts) == 1 and relative.name == manifest_name:
        return _check(
            "plugin install location",
            True,
            "pass",
            f"plugin root is the direct installed plugin directory {relative.name}",
            relative.name,
        )
    return _check(
        "plugin install location",
        True,
        "fail",
        "plugin was most likely installed without repo_path: plugins/acd or under an "
        "unexpected directory name. OpenHands loads the outer directory and none of these "
        "assets. Reinstall with source github:uist1idrju3i/acd-agent and path plugins/acd.",
        str(root),
    )


def _hook_references(
    document: Any, plugin_root: Path
) -> tuple[list[str], list[str], list[tuple[str, Path]]]:
    plugin_refs: list[str] = []
    external_refs: list[str] = []
    direct_plugin_refs: list[tuple[str, Path]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for child in cast(dict[str, Any], value).values():
                visit(child)
        elif isinstance(value, list):
            for child in cast(list[Any], value):
                visit(child)
        elif isinstance(value, str) and ".py" in value:
            for match in HOOK_PLUGIN_PATH_RE.finditer(value):
                relative = match.group(1).lstrip("/")
                target = plugin_root / relative
                plugin_refs.append(f"{relative}: {'present' if target.is_file() else 'missing'}")
                if HOOK_INTERPRETER_RE.search(value[: match.start()]) is None:
                    direct_plugin_refs.append((relative, target))
            for match in HOOK_PATH_RE.finditer(value):
                relative = match.group(1)
                if not relative.startswith(("hooks/", "skills/", "agents/")):
                    external_refs.append(relative)

    visit(document)
    return plugin_refs, sorted(set(external_refs)), direct_plugin_refs


def _assets_check(plugin_root: Path) -> dict[str, Any]:
    skills = sorted(path for path in (plugin_root / "skills").glob("*/SKILL.md"))
    agents = sorted((plugin_root / "agents").glob("*.md"))
    commands = sorted((plugin_root / "commands").glob("*.md"))
    hooks_path = plugin_root / "hooks" / "hooks.json"
    errors: list[str] = []
    skill_names: list[str] = []
    for skill in skills:
        try:
            fields = _front_matter(skill.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"{_relative(skill, plugin_root)}: {exc}")
            continue
        name = fields.get("name", "")
        if not name:
            errors.append(f"{_relative(skill, plugin_root)}: front-matter name is missing")
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
        hooks = _read_json(hooks_path)
        plugin_refs, external_refs, _ = _hook_references(hooks, plugin_root)
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
        return _check("plugin assets", True, "fail", "; ".join(errors), None)
    return _check("plugin assets", True, "pass", detail, ", ".join(sorted(skill_names)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _plugin_asset_path(asset_path: str) -> str:
    prefix = "plugins/acd/"
    return asset_path[len(prefix) :] if asset_path.startswith(prefix) else asset_path


def _prompt_manifest_check(plugin_root: Path) -> dict[str, Any]:
    manifest_path = plugin_root / "agents" / "prompt-manifest.json"
    try:
        document = _read_json(manifest_path)
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
        return _check("agent prompt manifest", True, "unknown", f"manifest is invalid: {exc}")
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
        relative_asset_path = _plugin_asset_path(asset_path)
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
            actual_asset_hash = _sha256(target)
            fields = _front_matter(target.read_text(encoding="utf-8"))
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
        _relative(path, plugin_root)
        for path in (plugin_root / "agents").glob("acd-*.md")
    }
    if actual_paths != listed_paths:
        errors.append(
            f"manifest agent set differs; missing={sorted(listed_paths - actual_paths)}, "
            f"unlisted={sorted(actual_paths - listed_paths)}"
        )
    if errors:
        return _check("agent prompt manifest", True, "fail", "; ".join(errors))
    return _check(
        "agent prompt manifest",
        True,
        "pass",
        f"{len(entries)} agent asset hashes and canonical hash match; "
        "scripts/verify_agent_prompts.py --check is authoritative for SDK-normalized "
        "prompt hashes",
        str(len(entries)),
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
        line[2:] if line.startswith("# ") else "" if line == "#" else line
        for line in lines[1:end]
    )
    return body, "\n".join(lines[end + 1 :])


def _package_ref_check(plugin_root: Path) -> dict[str, Any]:
    ref_path = plugin_root / "skills" / "acd-package-ref.txt"
    try:
        lines = ref_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return _check("Skill package reference", True, "unknown", f"ref cannot be read: {exc}")
    ref = lines[0].strip() if len(lines) == 1 else ""
    if len(lines) != 1 or not ref or not (SHA256_RE.fullmatch(ref) or SEMVER_RE.fullmatch(ref)):
        return _check(
            "Skill package reference",
            True,
            "fail",
            "ref must be exactly one 40-character SHA or v<semver> line",
            ref or None,
        )
    errors: list[str] = []
    importing_scripts = 0
    expected_dependency = f"acd @ git+https://github.com/uist1idrju3i/acd-agent@{ref}"
    for script in sorted((plugin_root / "skills").glob("*/scripts/*.py")):
        try:
            source = script.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(script))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            errors.append(f"{_relative(script, plugin_root)} cannot be parsed: {exc}")
            continue
        imports_acd = any(
            (
                isinstance(node, ast.Import)
                and any(
                    alias.name == "acd" or alias.name.startswith("acd.")
                    for alias in node.names
                )
            )
            or (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and (node.module == "acd" or node.module.startswith("acd."))
            )
            for node in ast.walk(tree)
        )
        if not imports_acd:
            continue
        importing_scripts += 1
        try:
            metadata, _ = _metadata_body(source)
        except ValueError as exc:
            errors.append(f"{_relative(script, plugin_root)}: {exc}")
            continue
        requires = re.findall(r'(?m)^requires-python\s*=\s*"([^"]+)"\s*$', metadata)
        dependencies = re.findall(r'(?m)^\s*"([^"]+)"\s*,?\s*$', metadata)
        if len(requires) != 1 or len(dependencies) != 1:
            errors.append(f"{_relative(script, plugin_root)}: invalid PEP 723 dependency metadata")
        elif dependencies[0] != expected_dependency:
            errors.append(
                f"{_relative(script, plugin_root)}: dependency does not match package ref"
            )
    if importing_scripts == 0:
        errors.append("no Skill script importing acd was found")
    if errors:
        return _check("Skill package reference", True, "fail", "; ".join(errors), ref)
    return _check(
        "Skill package reference",
        True,
        "pass",
        f"{importing_scripts} acd-importing Skill script(s) match the pinned ref",
        ref,
    )


def _runtime_check() -> dict[str, Any]:
    version = ".".join(str(value) for value in sys.version_info[:3])
    errors: list[str] = []
    if (sys.version_info.major, sys.version_info.minor) < (3, 12):
        errors.append(f"Python {version} is below required 3.12")
    uv_path = shutil.which("uv")
    if uv_path is None:
        errors.append("uv is not present on PATH")
    else:
        try:
            completed = subprocess.run(
                [uv_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if completed.returncode != 0:
                errors.append("uv --version failed")
            else:
                uv_version = (
                    completed.stdout.strip().splitlines()[0]
                    if completed.stdout
                    else "unknown"
                )
                version = f"Python {version}; {uv_version}"
        except (OSError, subprocess.TimeoutExpired):
            errors.append("uv --version could not be executed")
    if errors:
        return _check("runtime prerequisites", True, "fail", "; ".join(errors), version)
    return _check(
        "runtime prerequisites",
        True,
        "pass",
        "Python >=3.12 and uv are available",
        version,
    )


def _run_version(
    command: str,
    args: list[str],
    version_pattern: str,
    *,
    allow_nonzero_exit: bool = False,
) -> str | None:
    path = shutil.which(command)
    if path is None:
        return None
    try:
        completed = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    output = f"{completed.stdout}\n{completed.stderr}".strip()
    match = re.search(version_pattern, output)
    if match is None or (completed.returncode != 0 and not allow_nonzero_exit):
        return "unknown"
    return match.group(1)


def _docker_check() -> dict[str, Any]:
    docker = shutil.which("docker")
    if docker is None:
        return _check(
            "docker capability",
            False,
            "fail",
            "docker CLI is absent; authoritative Evidence from a digest-fixed container "
            "cannot be generated. Host execution must not be used as a passing substitute.",
            "not installed",
        )
    version = _run_version("docker", ["--version"], r"Docker version ([^,\s]+)") or "unknown"
    try:
        completed = subprocess.run(
            [docker, "info"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        completed = None
    if completed is None or completed.returncode != 0:
        return _check(
            "docker capability",
            False,
            "fail",
            "docker info is not reachable; authoritative Evidence from a digest-fixed "
            "container cannot be generated. Host execution must not be used as a "
            "passing substitute.",
            version,
        )
    return _check(
        "docker capability",
        False,
        "pass",
        "docker CLI and docker info are reachable; this does not itself run a gate",
        version,
    )


def _eda_check() -> dict[str, Any]:
    probes = {
        "kicad-cli": (["version"], r"([0-9]+\.[0-9]+\.[0-9]+)", False),
        "freerouting": (["--version"], r"Freerouting v([0-9]+\.[0-9]+\.?[0-9]*)", True),
    }
    observations = {
        tool: _run_version(tool, args, pattern, allow_nonzero_exit=allow_nonzero)
        for tool, (args, pattern, allow_nonzero) in probes.items()
    }
    present = [
        f"{tool}={version}" for tool, version in observations.items() if version is not None
    ]
    missing = [tool for tool, version in observations.items() if version is None]
    detail = (
        f"present: {', '.join(present) if present else 'none'}; "
        f"missing: {', '.join(missing) if missing else 'none'}. "
        "Host EDA execution is provisional only and cannot produce authoritative Evidence. "
        "build123d / cadquery-ocp are not probed from this isolated script; "
        "scripts/probe_tools.py is authoritative for the application tool probe."
    )
    result = "pass"
    observed_version = ", ".join(
        f"{tool}={version or 'unavailable'}" for tool, version in observations.items()
    )
    return _check("host EDA capabilities", False, result, detail, observed_version)


def _hook_invocability_check(plugin_root: Path) -> dict[str, Any]:
    hooks_path = plugin_root / "hooks" / "hooks.json"
    try:
        hooks = _read_json(hooks_path)
        _, _, direct_refs = _hook_references(hooks, plugin_root)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _check(
            "hook invocability",
            False,
            "unknown",
            f"hooks/hooks.json could not be inspected: {exc}",
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
            f"{relative}: executable={str(executable).lower()}, "
            f"shebang={str(has_shebang).lower()}"
        )
        if not executable or not has_shebang:
            failures.append(relative)
    if not direct_refs:
        return _check(
            "hook invocability",
            False,
            "pass",
            "all plugin hooks are invoked through an interpreter and do not depend on "
            "executable bits",
            "0",
        )
    if failures:
        return _check(
            "hook invocability",
            False,
            "fail",
            "A non-executable or shebang-less hook command cannot run, so hook policy "
            f"would not be enforced: {', '.join(failures)}. "
            f"Observations: {'; '.join(observations)}",
        )
    return _check(
        "hook invocability",
        False,
        "pass",
        f"direct plugin hook scripts are executable with shebangs: {'; '.join(observations)}",
        str(len(seen)),
    )


def _front_matter_list(text: str, key: str) -> list[str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("front-matter must start with ---")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("front-matter closing --- is missing") from exc
    items: list[str] = []
    inside = False
    for line in lines[1:end]:
        if not inside:
            inside = line.strip() == f"{key}:"
            continue
        item = LIST_ITEM_RE.match(line)
        if item is None:
            break
        items.append(item.group(1))
    return items


def _agent_skills_check(plugin_root: Path) -> dict[str, Any]:
    """Reject declared subagent Skill names, which the SDK cannot resolve.

    The SDK subagent registry resolves ``skills:`` names against the user and
    project Skill stores only and raises when a name is absent, so a declared
    plugin-bundled Skill name aborts conversation startup.
    """
    agents = sorted((plugin_root / "agents").glob("acd-*.md"))
    if not agents:
        return _check(
            "agent skill declarations",
            True,
            "fail",
            "agents/acd-*.md: no agent definition found",
        )
    errors: list[str] = []
    for agent in agents:
        try:
            declared = _front_matter_list(agent.read_text(encoding="utf-8"), "skills")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"{_relative(agent, plugin_root)}: {exc}")
            continue
        if declared:
            errors.append(
                f"{_relative(agent, plugin_root)}: declares Skill names the SDK "
                f"subagent registry cannot resolve: {', '.join(declared)}"
            )
    if errors:
        return _check("agent skill declarations", True, "fail", "; ".join(errors))
    return _check(
        "agent skill declarations",
        True,
        "pass",
        f"{len(agents)} agent definition(s) reference plugin Skill assets by path "
        "and declare no subagent Skill names",
        str(len(agents)),
    )


def _hook_root_resolution_check(plugin_root: Path) -> dict[str, Any]:
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
        document = _read_json(hooks_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _check(
            "hook plugin root resolution",
            True,
            "fail",
            f"hooks/hooks.json could not be parsed: {exc}",
        )
    commands: dict[str, str] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            mapping = cast(dict[str, Any], value)
            name = mapping.get("name")
            command = mapping.get("command")
            if (
                isinstance(name, str)
                and isinstance(command, str)
                and "/hooks/scripts/" in command
            ):
                commands[name] = command
            for child in mapping.values():
                visit(child)
        elif isinstance(value, list):
            for child in cast(list[Any], value):
                visit(child)

    visit(document)
    if not commands:
        return _check(
            "hook plugin root resolution",
            True,
            "fail",
            "hooks/hooks.json: no plugin hook command found",
        )
    errors = [
        f"{name}: {candidate} is not a resolution candidate"
        for name, command in sorted(commands.items())
        for candidate in candidates
        if candidate not in command
    ]
    if errors:
        return _check("hook plugin root resolution", True, "fail", "; ".join(errors))
    return _check(
        "hook plugin root resolution",
        True,
        "pass",
        f"{len(commands)} plugin hook command(s) resolve the plugin root from "
        "ACD_PLUGIN_ROOT, the workspace plugin tree, and the installed plugin store",
        str(len(commands)),
    )


def _store_check(plugin_root: Path) -> dict[str, Any]:
    store = Path.home() / ".openhands" / "plugins" / "installed"
    try:
        if not store.exists():
            return _check(
                "installed plugin store",
                False,
                "pass",
                f"{store} is absent; current root is treated as a development checkout",
                "not present",
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
        return _check(
            "installed plugin store",
            False,
            "pass",
            f"store plugins: {plugins}; current plugin root is {route}",
            ", ".join(plugins) or "empty",
        )
    except OSError as exc:
        return _check(
            "installed plugin store",
            False,
            "unknown",
            f"store cannot be inspected: {exc}",
        )


def diagnose() -> dict[str, Any]:
    """Return the machine-readable doctor report for this plugin root."""
    plugin_root = Path(__file__).resolve().parents[3]
    checks = [
        _manifest_check(plugin_root),
        _install_location_check(plugin_root),
        _assets_check(plugin_root),
        _prompt_manifest_check(plugin_root),
        _agent_skills_check(plugin_root),
        _package_ref_check(plugin_root),
        _runtime_check(),
        _docker_check(),
        _eda_check(),
        _hook_root_resolution_check(plugin_root),
        _hook_invocability_check(plugin_root),
        _store_check(plugin_root),
    ]
    required_failed = any(
        check["required"] and check["result"] in {"fail", "unknown"} for check in checks
    )
    optional_failed = any(
        not check["required"] and check["result"] in {"fail", "unknown"} for check in checks
    )
    status = "failed" if required_failed else "degraded" if optional_failed else "ok"
    return {
        "status": status,
        "plugin_root": str(plugin_root),
        "checks": checks,
        "authority": "L3 observation only; no acceptance authority and no authoritative Evidence",
    }


def main() -> int:
    """Print a JSON report and fail only when required checks fail."""
    try:
        report = diagnose()
    except Exception as exc:
        report = {
            "status": "failed",
            "plugin_root": str(Path(__file__).resolve().parents[3]),
            "checks": [
                _check("doctor execution", True, "unknown", f"diagnosis failed: {exc}")
            ],
            "authority": (
                "L3 observation only; no acceptance authority and no authoritative Evidence"
            ),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
