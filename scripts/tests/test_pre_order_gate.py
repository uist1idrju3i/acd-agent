"""CLI tests for the pre-order gate."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import scripts.pre_order_gate as pre_order_gate

from acd.core.order_total import OrderTotalResult
from acd.schema import QuoteAmount
from acd.schema.common import canonical_json_sha256

ROOT = Path(__file__).parents[2]
GRAPH = ROOT / "fixtures/golden-design-1/graph.json"
POLICY = ROOT / "fixtures/contracts/valid/order-policy.json"
EVIDENCE = ROOT / "fixtures/contracts/valid/evidence.json"
def _repository(tmp_path: Path) -> Path:
    graph = tmp_path / "fixtures/golden-design-1/graph.json"
    graph.parent.mkdir(parents=True)
    shutil.copyfile(GRAPH, graph)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=test",
            "commit",
            "-qm",
            "test",
        ],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def _evidence(tmp_path: Path, evidence_id: str) -> Path:
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    value["evidence_id"] = evidence_id
    value["target_revision"] = "r1"
    envelope = value["envelope"]
    assert isinstance(envelope, dict)
    envelope["target_revision"] = "r1"
    path = tmp_path / f"{evidence_id.replace('.', '-')}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _inputs(tmp_path: Path) -> tuple[Path, list[Path]]:
    order_total = OrderTotalResult(
        subtotals=(),
        total=QuoteAmount(
            amount_minor=10000,
            currency="USD",
            minor_unit_digits=2,
        ),
        target_revision="r1",
        quote_hashes=(),
        breakdown_hash="sha256:" + "a" * 64,
    )
    total_json = order_total.total.model_dump(mode="json")
    subtotals_json = [{"category": "board", "amount": total_json}]
    breakdown_hash = canonical_json_sha256(
        {
            "quote_hashes": [],
            "subtotals": subtotals_json,
            "target_revision": order_total.target_revision,
            "total": total_json,
        }
    )
    order_total_path = tmp_path / "order-total.json"
    order_total_path.write_text(
        json.dumps(
            {
                "subtotals": subtotals_json,
                "total": total_json,
                "target_revision": order_total.target_revision,
                "quote_hashes": [],
                "breakdown_hash": breakdown_hash,
            }
        ),
        encoding="utf-8",
    )
    evidence_paths = [
        _evidence(tmp_path, "evidence.gd1.electrical"),
        _evidence(tmp_path, "evidence.gd1.mechanical"),
    ]
    return order_total_path, evidence_paths


def _args(
    repository: Path,
    order_total: Path,
    evidence_paths: list[Path],
) -> list[str]:
    return [
        "--repo-root",
        str(repository),
        "--policy",
        str(POLICY),
        "--order-total",
        str(order_total),
        "--evidence",
        str(evidence_paths[0]),
        "--evidence",
        str(evidence_paths[1]),
        "--evaluated-at",
        datetime(2026, 8, 14, tzinfo=UTC).isoformat(),
        "--check-only",
    ]


def test_check_only_cli_evaluates_existing_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = _repository(tmp_path)
    order_total, evidence_paths = _inputs(tmp_path)
    assert (
        pre_order_gate.main(_args(repository, order_total, evidence_paths)) == 0
    )
    output = capsys.readouterr()
    assert '"authorization_hash"' in output.out


def test_rerun_cli_uses_explicit_authoritative_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    order_total, evidence_paths = _inputs(tmp_path)
    calls: list[tuple[Path, str]] = []

    def fake_rerun(*, repository: Path, image: str) -> None:
        calls.append((repository, image))

    monkeypatch.setattr(pre_order_gate, "_rerun_authoritative", fake_rerun)
    args = [
        argument
        for argument in _args(repository, order_total, evidence_paths)
        if argument != "--check-only"
    ]
    assert (
        pre_order_gate.main(
            [*args, "--rerun-authoritative", "--image", "acd:locked"]
        )
        == 0
    )
    assert calls == [(repository.resolve(), "acd:locked")]
