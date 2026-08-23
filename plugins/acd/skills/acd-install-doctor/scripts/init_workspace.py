#!/usr/bin/env python3
"""Initialize an ACD workspace and emit a fail-closed bootstrap record."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload["content_sha256"] = "unknown"
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _git_value(workspace: Path, args: Sequence[str], runner: Runner) -> str | None:
    try:
        result = runner(
            ["git", *args],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _default_repo_url(runner: Runner) -> str | None:
    try:
        result = runner(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _default_revision(runner: Runner) -> str | None:
    return _git_value(Path.cwd(), ["rev-parse", "HEAD"], runner)


def _normalize_repo_url(value: str) -> str:
    normalized = value.strip().removesuffix(".git")
    if normalized.startswith("git@") and ":" in normalized:
        host, path = normalized.split(":", 1)
        normalized = f"https://{host.removeprefix('git@')}/{path}"
    return normalized.rstrip("/")


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    return runner(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,
    )


def _command_result(
    command: Sequence[str],
    *,
    cwd: Path | None,
    runner: Runner,
) -> dict[str, Any]:
    try:
        result = _run(command, cwd=cwd, runner=runner)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "command": list(command),
            "status": "unknown",
            "returncode": None,
            "detail": str(exc),
        }
    return {
        "command": list(command),
        "status": "pass" if result.returncode == 0 else "fail",
        "returncode": result.returncode,
        "stdout": result.stdout.strip()[-4000:],
        "stderr": result.stderr.strip()[-4000:],
    }


def _workspace_state(workspace: Path, repo_url: str, runner: Runner) -> str:
    if not workspace.exists():
        workspace.mkdir(parents=True)
        return "empty"
    if not workspace.is_dir():
        raise ValueError(f"workspace is not a directory: {workspace}")
    entries = list(workspace.iterdir())
    if not entries:
        return "empty"
    top = _git_value(workspace, ["rev-parse", "--show-toplevel"], runner)
    remote = _git_value(workspace, ["config", "--get", "remote.origin.url"], runner)
    if top is None or remote is None:
        raise ValueError("workspace is non-empty but is not a Git checkout")
    if Path(top).resolve() != workspace.resolve():
        raise ValueError("workspace Git root does not match the requested workspace path")
    if _normalize_repo_url(remote) != _normalize_repo_url(repo_url):
        raise ValueError(f"workspace origin does not match requested repository: {remote}")
    status = _command_result(["git", "status", "--porcelain"], cwd=workspace, runner=runner)
    if status["status"] != "pass" or status["stdout"]:
        raise ValueError("workspace is dirty; refusing to reuse it")
    return "checkout"


def _clone_or_reuse(
    workspace: Path,
    repo_url: str,
    revision: str,
    *,
    runner: Runner,
) -> dict[str, Any]:
    state = _workspace_state(workspace, repo_url, runner)
    if state == "empty":
        result = _command_result(
            ["git", "clone", repo_url, str(workspace)],
            cwd=None,
            runner=runner,
        )
        if result["status"] != "pass":
            return result
    current = _git_value(workspace, ["rev-parse", "HEAD"], runner)
    if current != revision:
        fetch = _command_result(
            ["git", "fetch", "origin", revision],
            cwd=workspace,
            runner=runner,
        )
        if fetch["status"] != "pass":
            return fetch
        checkout = _command_result(
            ["git", "checkout", "--detach", revision],
            cwd=workspace,
            runner=runner,
        )
        if checkout["status"] != "pass":
            return checkout
    resolved = _git_value(workspace, ["rev-parse", "HEAD"], runner)
    if resolved is None:
        return {
            "status": "unknown",
            "detail": "cloned workspace revision could not be resolved",
        }
    return {"status": "pass", "resolved_revision": resolved, "state": state}


def _load_lock_digest(workspace: Path) -> str | None:
    path = workspace / "docker" / "image-digests.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        value = document["acd_tools"]["digest"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return None
    return value if isinstance(value, str) else None


def _doctor(
    workspace: Path,
    *,
    runner: Runner,
    python_executable: str,
    include_workspace: bool,
) -> dict[str, Any]:
    script = workspace / "plugins/acd/skills/acd-install-doctor/scripts/install_doctor.py"
    if not script.is_file():
        return {
            "status": "unknown",
            "detail": f"install doctor script is missing: {script}",
        }
    command = [python_executable, str(script)]
    if include_workspace:
        command.extend(["--workspace", str(workspace)])
    result = _command_result(command, cwd=workspace, runner=runner)
    if result["status"] == "unknown":
        return result
    try:
        report = cast(dict[str, Any], json.loads(result.get("stdout", "")))
    except json.JSONDecodeError:
        return {
            **result,
            "status": "unknown",
            "detail": "install doctor did not emit valid JSON",
        }
    status = "pass" if result["returncode"] == 0 and report.get("status") != "failed" else "fail"
    return {
        **result,
        "status": status,
        "report": report,
    }


def initialize(
    *,
    repo_url: str,
    revision: str,
    workspace: Path,
    runner: Runner = subprocess.run,
    python_executable: str = sys.executable,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []

    def fail(step: str, reason: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": False,
            "fail_closed": True,
            "failure_reason": reason,
            "failed_step": step,
            "steps": steps + ([detail] if detail is not None else []),
        }

    try:
        if workspace.exists() and not workspace.is_dir():
            raise ValueError(f"workspace is not a directory: {workspace}")
        workspace.mkdir(parents=True, exist_ok=True)
        steps.append({"name": "workspace_dir", "status": "pass", "path": str(workspace)})
    except (OSError, ValueError) as exc:
        return fail("workspace_dir", str(exc))

    try:
        repository = _clone_or_reuse(workspace, repo_url, revision, runner=runner)
    except (OSError, ValueError) as exc:
        return fail("repository", str(exc))
    repository_step = {"name": "repository", **repository}
    if repository_step.get("status") != "pass":
        return fail("repository", "repository clone/reuse failed", repository_step)
    steps.append(repository_step)

    submodules = _command_result(
        ["git", "submodule", "update", "--init", "--recursive"],
        cwd=workspace,
        runner=runner,
    )
    submodules["name"] = "submodules"
    if submodules["status"] != "pass":
        return fail("submodules", "submodule initialization failed", submodules)
    steps.append(submodules)

    sync = _command_result(["uv", "sync"], cwd=workspace, runner=runner)
    sync["name"] = "uv_sync"
    if sync["status"] != "pass":
        return fail("uv_sync", "uv sync failed", sync)
    steps.append(sync)

    plugin = _doctor(
        workspace,
        runner=runner,
        python_executable=python_executable,
        include_workspace=False,
    )
    plugin["name"] = "plugin_load"
    if plugin["status"] != "pass":
        return fail("plugin_load", "plugin manifest/assets checks failed", plugin)
    steps.append(plugin)

    doctor = _doctor(
        workspace,
        runner=runner,
        python_executable=python_executable,
        include_workspace=True,
    )
    doctor["name"] = "doctor"
    if doctor["status"] != "pass":
        return fail("doctor", "workspace doctor failed closed", doctor)
    steps.append(doctor)

    resolved_revision = str(repository_step["resolved_revision"])
    record = {
        "schema_version": "0.1",
        "workspace_path": str(workspace.resolve()),
        "repo_url": repo_url,
        "requested_revision": revision,
        "resolved_revision": resolved_revision,
        "lock_digest": _load_lock_digest(workspace),
        "pass_evidence": False,
        "record_class": "L3",
        "content_sha256": "unknown",
    }
    record["content_sha256"] = _canonical_hash(record)
    record_path = workspace / ".openhands" / "bootstrap-record.json"
    try:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return fail("bootstrap_record", str(exc))
    steps.append({"name": "bootstrap_record", "status": "pass", "path": str(record_path)})
    return {
        "ok": True,
        "fail_closed": False,
        "failure_reason": None,
        "failed_step": None,
        "steps": steps,
        "bootstrap_record": record,
        "bootstrap_record_path": str(record_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-url", default=None)
    parser.add_argument("--revision", default=None)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_url = args.repo_url or _default_repo_url(subprocess.run)
    revision = args.revision or _default_revision(subprocess.run)
    report: dict[str, Any]
    if not repo_url or not revision:
        report = {
            "ok": False,
            "fail_closed": True,
            "failure_reason": "repo URL and revision must be supplied or discoverable",
            "failed_step": "arguments",
            "steps": [],
        }
    else:
        try:
            report = initialize(
                repo_url=repo_url,
                revision=revision,
                workspace=args.workspace.resolve(),
            )
        except Exception as exc:
            report = {
                "ok": False,
                "fail_closed": True,
                "failure_reason": f"initialization failed unexpectedly: {exc}",
                "failed_step": "execution",
                "steps": [],
            }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
