"""CLI tests for the pre-order gate."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import scripts.pre_order_gate as pre_order_gate

from acd.core.order_total import (
    OrderSubtotal,
    OrderTotalResult,
    QuoteCanonicalHash,
    order_total_breakdown_hash,
    order_total_result_to_document,
)
from acd.schema import QuoteAmount

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
    amount = QuoteAmount(
        amount_minor=10000,
        currency="USD",
        minor_unit_digits=2,
    )
    order_total = OrderTotalResult(
        subtotals=(
            OrderSubtotal(
                category="board",
                amount=amount,
            ),
        ),
        total=amount,
        target_revision="r1",
        quote_hashes=(
            QuoteCanonicalHash(
                quote_id="quote-test",
                canonical_hash="sha256:" + "a" * 64,
            ),
        ),
        breakdown_hash=order_total_breakdown_hash(
            quote_hashes=(("quote-test", "sha256:" + "a" * 64),),
            subtotals=(("board", amount),),
            target_revision="r1",
            total=amount,
        ),
    )
    order_total_path = tmp_path / "order-total.json"
    order_total_path.write_text(
        order_total_result_to_document(order_total).model_dump_json(),
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
        "--design-graph",
        str(repository / "fixtures/golden-design-1/graph.json"),
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

    def fake_rerun(
        *,
        repository: Path,
        image: str,
        design_graph_path: Path,
        out_root: Path,
    ) -> None:
        assert design_graph_path == repository / "fixtures/golden-design-1/graph.json"
        assert out_root == repository / "out"
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


@pytest.mark.parametrize(
    ("design_graph_path", "out_root", "expected_fixture", "expected_board"),
    [
        (
            Path("fixtures/golden-design-1/graph.json"),
            Path("out"),
            "fixtures/golden-design-1",
            "out/gd1",
        ),
        (
            Path("/repository/fixtures/golden-design-1/graph.json"),
            Path("/repository/out"),
            "fixtures/golden-design-1",
            "out/gd1",
        ),
    ],
)
def test_authoritative_commands_resolve_relative_and_absolute_paths(
    tmp_path: Path,
    design_graph_path: Path,
    out_root: Path,
    expected_fixture: str,
    expected_board: str,
) -> None:
    repository = _repository(tmp_path)
    if design_graph_path.is_absolute():
        design_graph_path = repository / design_graph_path.relative_to(
            Path("/repository")
        )
        out_root = repository / out_root.relative_to(Path("/repository"))
    commands = pre_order_gate.authoritative_commands(
        repository=repository,
        design_graph_path=design_graph_path,
        out_root=out_root,
    )
    assert commands == (
        (
            "uv run python scripts/run_gd1_pipeline.py "
            f"--fixture {expected_fixture} --out {expected_board}",
            (f"{expected_board}/evidence-electrical.json",),
        ),
        (
            "uv run python scripts/run_gd1_enclosure_pipeline.py "
            f"--fixture {expected_fixture} --out {expected_board}-enclosure",
            (f"{expected_board}-enclosure/evidence-mechanical.json",),
        ),
    )


def test_authoritative_commands_reject_absolute_path_outside_repository(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    with pytest.raises(ValueError, match="outside repository"):
        pre_order_gate.authoritative_commands(
            repository=repository,
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            out_root=tmp_path.parent / "out",
        )
