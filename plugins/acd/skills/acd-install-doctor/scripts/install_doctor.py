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

import argparse
import json
from pathlib import Path
from typing import Any

from install_doctor_checks.common import PLUGIN_ROOT, check_result
from install_doctor_checks.host_checks import (
    docker_check,
    eda_check,
    host_resource_check,
    runtime_check,
    server_image_check,
)
from install_doctor_checks.plugin_checks import (
    agent_skills_check,
    assets_check,
    hook_invocability_check,
    hook_root_resolution_check,
    install_location_check,
    manifest_check,
    mcp_server_check,
    package_ref_check,
    prompt_manifest_check,
    store_check,
    tool_registration_check,
)
from install_doctor_checks.workspace_checks import (
    workspace_checks,
)


def diagnose(workspace: Path | None = None, *, pull: bool = True) -> dict[str, Any]:
    """Return the machine-readable doctor report for this plugin root."""
    plugin_root = PLUGIN_ROOT
    checks = [
        manifest_check(plugin_root),
        install_location_check(plugin_root),
        assets_check(plugin_root),
        prompt_manifest_check(plugin_root),
        agent_skills_check(plugin_root),
        tool_registration_check(plugin_root),
        mcp_server_check(plugin_root),
        package_ref_check(plugin_root),
        runtime_check(),
        docker_check(),
        server_image_check(workspace, pull=pull),
        eda_check(workspace),
        host_resource_check(),
        hook_root_resolution_check(plugin_root),
        hook_invocability_check(plugin_root),
        store_check(plugin_root),
    ]
    if workspace is not None:
        checks.extend(workspace_checks(workspace.resolve()))
    required_failed = any(
        check["required"] and check["result"] in {"fail", "unknown"} for check in checks
    )
    optional_failed = any(
        not check["required"] and check["result"] in {"fail", "unknown"} for check in checks
    )
    status = "failed" if required_failed else "degraded" if optional_failed else "ok"
    paths: dict[str, dict[str, Any]] = {}
    for check in checks:
        entry = paths.setdefault(check["path"], {"status": "ok", "checks": []})
        entry["checks"].append(check["name"])
        failed = check["result"] in {"fail", "unknown"}
        if check["required"] and failed:
            entry["status"] = "failed"
        elif failed and entry["status"] != "failed":
            entry["status"] = "degraded"
        elif check["result"] == "unavailable" and entry["status"] == "ok":
            entry["status"] = "unavailable"
    paths_summary = {
        path: paths.get(path, {"status": "ok", "checks": []})
        for path in ("authoritative-path", "provisional-path", "plugin")
    }
    return {
        "status": status,
        "plugin_root": str(plugin_root),
        "checks": checks,
        "paths": paths_summary,
        "authority": (
            "L3 observation only; no acceptance authority and no authoritative "
            "Evidence; provisional-path observations never substitute for the "
            "authoritative-path"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """Print a JSON report and fail only when required checks fail."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="workspace checkout to inspect in addition to plugin capabilities",
    )
    parser.add_argument(
        "--no-pull",
        action="store_true",
        help="do not pull the locked server image when it is absent locally",
    )
    try:
        args = parser.parse_args(argv)
        report = diagnose(args.workspace, pull=not args.no_pull)
    except Exception as exc:
        report: dict[str, Any] = {
            "status": "failed",
            "plugin_root": str(PLUGIN_ROOT),
            "checks": [
                check_result(
                    "doctor execution",
                    True,
                    "unknown",
                    f"diagnosis failed: {exc}",
                    path="plugin",
                )
            ],
            "paths": {
                "authoritative-path": {"status": "ok", "checks": []},
                "provisional-path": {"status": "ok", "checks": []},
                "plugin": {"status": "failed", "checks": ["doctor execution"]},
            },
            "authority": (
                "L3 observation only; no acceptance authority and no authoritative "
                "Evidence; provisional-path observations never substitute for the "
                "authoritative-path"
            ),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
