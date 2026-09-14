"""Sample host and container resources while a lane run executes.

Replaces throwaway per-run shell scripts: the checkout path, image digest,
downloads, and sampling interval are arguments. The record is an L3
observation with no gate or Evidence authority.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from acd.openhands.host_resources import read_meminfo

REPO_ROOT = Path(__file__).resolve().parents[1]
_IMAGE_REF = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}\Z")
_DOCKER_STATS_TIMEOUT = 2.0
_MEM_USAGE = re.compile(
    r"([0-9.]+)\s*(B|KiB|MiB|GiB|TiB|KB|MB|GB|TB|kB|mB|gB)\s*/"
)
_MEMORY_UNITS = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}


class _Process(Protocol):
    returncode: int | None

    def poll(self) -> int | None: ...
    def wait(self) -> int: ...


HostSample = dict[str, float | int]
HostSampler = Callable[[], HostSample]
DockerSampler = Callable[[], int | None]
Spawn = Callable[[Sequence[str], Path], _Process]


def parse_docker_mem_usage(value: str) -> int:
    """Parse the used side of a docker stats MemUsage value into bytes."""
    match = _MEM_USAGE.search(value.strip())
    if match is None:
        raise ValueError(f"docker MemUsage is unparsable: {value!r}")
    return int(float(match.group(1)) * _MEMORY_UNITS[match.group(2).lower()])


def _cpu_stat(path: Path = Path("/proc/stat")) -> tuple[int, int] | None:
    try:
        line = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    fields = line.split()
    if len(fields) < 5 or fields[0] != "cpu":
        return None
    ticks = [int(field) for field in fields[1:] if field.isdigit()]
    idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    return sum(ticks) - idle, sum(ticks)


def make_host_sampler(
    *,
    stat_path: Path = Path("/proc/stat"),
    meminfo_path: Path = Path("/proc/meminfo"),
    cpu_count: int | None = None,
) -> HostSampler:
    """Return a sampler reporting host CPU cores in use and memory usage."""
    cores = os.cpu_count() if cpu_count is None else cpu_count
    previous = _cpu_stat(stat_path)

    def sample() -> HostSample:
        nonlocal previous
        current = _cpu_stat(stat_path)
        busy_cores = 0.0
        if previous is not None and current is not None and cores:
            delta_busy = current[0] - previous[0]
            delta_total = current[1] - previous[1]
            if delta_total > 0:
                busy_cores = delta_busy / delta_total * cores
        previous = current
        meminfo = read_meminfo(meminfo_path)
        mem_total = meminfo.get("MemTotal", 0)
        mem_available = meminfo.get("MemAvailable", 0)
        swap_total = meminfo.get("SwapTotal", 0)
        swap_free = meminfo.get("SwapFree", 0)
        return {
            "cpu_cores": busy_cores,
            "mem_total_bytes": mem_total,
            "mem_used_bytes": mem_total - mem_available,
            "mem_available_bytes": mem_available,
            "swap_used_bytes": swap_total - swap_free,
        }

    return sample


def make_docker_sampler() -> DockerSampler:
    """Return a sampler summing container memory usage; None when unavailable."""

    def sample() -> int | None:
        try:
            completed = subprocess.run(
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{json .}}",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=_DOCKER_STATS_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        total = 0
        for line in completed.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                total += parse_docker_mem_usage(str(entry["MemUsage"]))
            except (json.JSONDecodeError, KeyError, ValueError):
                return None
        return total

    return sample


def _spawn(argv: Sequence[str], cwd: Path) -> _Process:
    return subprocess.Popen(list(argv), cwd=str(cwd))


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="checkout to run")
    parser.add_argument(
        "--image",
        default=None,
        help="digest-pinned image reference (required unless --local-provisional)",
    )
    parser.add_argument(
        "--local-provisional",
        action="store_true",
        help="run host-provisional and skip docker stats sampling",
    )
    parser.add_argument(
        "--download",
        dest="download_files",
        action="append",
        metavar="PATH",
        help="forwarded to run_in_workspace --download",
    )
    parser.add_argument(
        "--download-root",
        dest="download_roots",
        action="append",
        metavar="PATH",
        help="forwarded to run_in_workspace --download-root",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="sampling interval in seconds (must be positive)",
    )
    parser.add_argument("--out", type=Path, required=True, help="record JSON path")
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="forwarded to run_in_workspace --log",
    )
    parser.add_argument("--label", default=None, help="condition label")
    parser.add_argument("--memory-limit", default=None)
    parser.add_argument("--jvm-max-heap", default=None)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.local_provisional and args.image:
        parser.error("--image cannot be used with --local-provisional")
    if not args.local_provisional and not args.image:
        parser.error("--image is required unless --local-provisional")
    if args.image is not None and _IMAGE_REF.fullmatch(args.image) is None:
        parser.error("--image must be digest-pinned (name@sha256:<64 hex>)")
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return args


def measure(
    args: argparse.Namespace,
    *,
    spawn: Spawn | None = None,
    host_sampler: HostSampler | None = None,
    docker_sampler: DockerSampler | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Run run_in_workspace under sampling and write the record. Returns rc."""
    argv: list[str] = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_in_workspace.py"),
        "--repo",
        str(args.repo),
    ]
    if args.local_provisional:
        argv.append("--local-provisional")
    else:
        argv.extend(["--image", args.image])
    for entry in args.download_files or ():
        argv.extend(["--download", entry])
    for entry in args.download_roots or ():
        argv.extend(["--download-root", entry])
    if args.log is not None:
        argv.extend(["--log", str(args.log)])
    if args.memory_limit is not None:
        argv.extend(["--memory-limit", args.memory_limit])
    if args.jvm_max_heap is not None:
        argv.extend(["--jvm-max-heap", args.jvm_max_heap])
    argv.extend(args.command)

    spawn_fn = spawn or _spawn
    sample_host = host_sampler or make_host_sampler()
    sample_docker = docker_sampler or make_docker_sampler()

    started = _utc_now()
    begin = monotonic()
    process = spawn_fn(argv, args.repo)
    samples: list[HostSample] = []
    docker_peaks: list[int] = []
    docker_available = False
    while process.poll() is None:
        samples.append(sample_host())
        if not args.local_provisional:
            usage = sample_docker()
            if usage is not None:
                docker_available = True
                docker_peaks.append(usage)
        sleep(args.interval)
    samples.append(sample_host())
    if not args.local_provisional:
        usage = sample_docker()
        if usage is not None:
            docker_available = True
            docker_peaks.append(usage)
    exit_code = process.wait()
    finished = _utc_now()
    wall_clock = monotonic() - begin

    mem_totals = [int(sample["mem_total_bytes"]) for sample in samples]
    record = {
        "schema_version": "0.1",
        "record_class": "L3",
        "pass_evidence": False,
        "authority": (
            "Resource measurement is an L3 observation; it grants no gate "
            "pass and is not authoritative Evidence."
        ),
        "label": args.label,
        "image": args.image,
        "repo": str(args.repo.resolve()),
        "command": " ".join(args.command),
        "downloads": {
            "files": list(args.download_files or ()),
            "roots": list(args.download_roots or ()),
        },
        "interval_seconds": args.interval,
        "sample_count": len(samples),
        "started_at": started,
        "finished_at": finished,
        "wall_clock_seconds": wall_clock,
        "exit_code": exit_code,
        "host": {
            "cpu_count": os.cpu_count(),
            "cpu_cores_peak": max(
                (float(sample["cpu_cores"]) for sample in samples), default=0.0
            ),
            "mem_total_bytes": max(mem_totals, default=0),
            "mem_used_peak_bytes": max(
                (int(sample["mem_used_bytes"]) for sample in samples), default=0
            ),
            "mem_available_min_bytes": min(
                (int(sample["mem_available_bytes"]) for sample in samples),
                default=0,
            ),
            "swap_used_peak_bytes": max(
                (int(sample["swap_used_bytes"]) for sample in samples),
                default=0,
            ),
        },
        "docker": {
            "stats_available": docker_available,
            "mem_usage_peak_bytes": max(docker_peaks) if docker_peaks else None,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    spawn: Spawn | None = None,
    host_sampler: HostSampler | None = None,
    docker_sampler: DockerSampler | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    args = _parse_args(argv or sys.argv[1:])
    return measure(
        args,
        spawn=spawn,
        host_sampler=host_sampler,
        docker_sampler=docker_sampler,
        sleep=sleep,
        monotonic=monotonic,
    )


if __name__ == "__main__":
    raise SystemExit(main())
