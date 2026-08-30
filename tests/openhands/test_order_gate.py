"""Pre-order gate tests."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from openhands.sdk.git.exceptions import GitError

import acd.openhands.order_gate as order_gate
from acd.core.order_total import OrderTotalResult
from acd.openhands.order_gate import PreOrderGateError, evaluate_pre_order_gate
from acd.schema import OrderPolicy, QuoteAmount

ROOT = Path(__file__).parents[2]
GRAPH = ROOT / "fixtures/golden-design-1/graph.json"
POLICY = ROOT / "fixtures/contracts/valid/order-policy.json"
EVIDENCE = ROOT / "fixtures/contracts/valid/evidence.json"
REVISION = "r1"
HASH = "sha256:" + "a" * 64
EVALUATED_AT = datetime(2026, 8, 14, tzinfo=UTC)


def _repository(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
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


def _repository_with_graph(
    tmp_path: Path,
    *,
    graph_id: str,
    relative_path: str,
) -> Path:
    repository = _repository(tmp_path)
    source = repository / "fixtures/golden-design-1/graph.json"
    target = repository / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    graph = json.loads(source.read_text(encoding="utf-8"))
    graph["graph_id"] = graph_id
    target.write_text(json.dumps(graph), encoding="utf-8")
    source.unlink()
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=test",
            "commit",
            "-qm",
            "test graph",
        ],
        cwd=repository,
        check=True,
    )
    return repository


def _policy() -> OrderPolicy:
    return OrderPolicy.model_validate_json(POLICY.read_text(encoding="utf-8"))


def _order_total(amount_minor: int = 9300) -> OrderTotalResult:
    amount = QuoteAmount(
        amount_minor=amount_minor,
        currency="USD",
        minor_unit_digits=2,
    )
    return OrderTotalResult(
        subtotals=(),
        total=amount,
        target_revision=REVISION,
        quote_hashes=(),
        breakdown_hash=HASH,
    )


def _evidence(tmp_path: Path, evidence_id: str, **updates: object) -> Path:
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    value["evidence_id"] = evidence_id
    value["target_revision"] = REVISION
    envelope = value["envelope"]
    assert isinstance(envelope, dict)
    envelope["target_revision"] = REVISION
    value.update(updates)
    path = tmp_path / f"{evidence_id.replace('.', '-')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _evidence_paths(tmp_path: Path) -> list[Path]:
    return [
        _evidence(tmp_path, "evidence.gd1.electrical"),
        _evidence(tmp_path, "evidence.gd1.mechanical"),
    ]


def test_pre_order_gate_allows_equal_limit_and_is_reproducible(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    policy = _policy().model_copy(
        update={
            "order_total_limit": QuoteAmount(
                amount_minor=10000,
                currency="USD",
                minor_unit_digits=2,
            )
        }
    )
    order_total = _order_total(10000)
    paths = _evidence_paths(tmp_path)

    first = evaluate_pre_order_gate(
        repository=repository,
        policy=policy,
        design_graph_path=repository / "fixtures/golden-design-1/graph.json",
        order_total=order_total,
        evidence_paths=paths,
        evaluated_at=EVALUATED_AT,
    )
    second = evaluate_pre_order_gate(
        repository=repository,
        policy=policy,
        design_graph_path=repository / "fixtures/golden-design-1/graph.json",
        order_total=order_total,
        evidence_paths=list(reversed(paths)),
        evaluated_at=EVALUATED_AT,
    )

    assert first == second
    assert first.authorization_hash.startswith("sha256:")
    assert [item.evidence_id for item in first.evidence] == [
        "evidence.gd1.electrical",
        "evidence.gd1.mechanical",
    ]


def test_pre_order_gate_authorization_hash_accepts_non_utc_timestamp(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    record = evaluate_pre_order_gate(
        repository=repository,
        policy=_policy(),
        design_graph_path=repository / "fixtures/golden-design-1/graph.json",
        order_total=_order_total(),
        evidence_paths=_evidence_paths(tmp_path / "evidence"),
        evaluated_at=datetime(
            2026,
            8,
            14,
            5,
            30,
            tzinfo=timezone(timedelta(hours=5, minutes=30)),
        ),
    )

    assert record.authorization_hash.startswith("sha256:")


def test_pre_order_gate_rejects_total_over_limit(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    with pytest.raises(PreOrderGateError, match="exceeds"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            order_total=_order_total(10001),
            evidence_paths=_evidence_paths(tmp_path),
            evaluated_at=EVALUATED_AT,
        )


def test_pre_order_gate_rejects_missing_or_duplicate_evidence(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    paths = _evidence_paths(tmp_path)
    with pytest.raises(PreOrderGateError, match="missing"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            order_total=_order_total(),
            evidence_paths=paths[:1],
            evaluated_at=EVALUATED_AT,
        )
    with pytest.raises(PreOrderGateError, match="duplicate"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            order_total=_order_total(),
            evidence_paths=[paths[0], paths[0], paths[1]],
            evaluated_at=EVALUATED_AT,
        )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"status": "stale"}, "authoritative"),
        ({"target_revision": "r2"}, "authoritative"),
        (
            {
                "claims": [
                    {
                        "subject_node": "net.x",
                        "property": "ok",
                        "value": 0,
                        "verified": False,
                    }
                ]
            },
            "verified",
        ),
        (
            {
                "claims": [
                    {
                        "subject_node": "net.x",
                        "property": "ok",
                        "value": "unknown",
                        "verified": True,
                    }
                ]
            },
            "verified",
        ),
    ],
)
def test_pre_order_gate_rejects_non_authoritative_or_unknown_claims(
    tmp_path: Path,
    updates: dict[str, object],
    message: str,
) -> None:
    repository = _repository(tmp_path)
    paths = _evidence_paths(tmp_path)
    paths[0] = _evidence(tmp_path, "evidence.gd1.electrical", **updates)
    with pytest.raises(PreOrderGateError, match=message):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            order_total=_order_total(),
            evidence_paths=paths,
            evaluated_at=EVALUATED_AT,
        )


def test_pre_order_gate_rejects_dirty_design_input_and_revision_mismatch(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    graph = repository / "fixtures/golden-design-1/graph.json"
    graph.write_text(graph.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(PreOrderGateError, match="dirty"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=graph,
            order_total=_order_total(),
            evidence_paths=_evidence_paths(tmp_path),
            evaluated_at=EVALUATED_AT,
        )


def test_pre_order_gate_wraps_git_observation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)

    def fail_git_observation(
        repository: Path,
        *,
        ref: str | None = "HEAD",
    ) -> tuple[str, ...]:
        raise GitError("git unavailable")

    monkeypatch.setattr(
        order_gate,
        "design_input_changes",
        fail_git_observation,
    )
    with pytest.raises(PreOrderGateError, match="git observation failed"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            order_total=_order_total(),
            evidence_paths=_evidence_paths(tmp_path / "evidence"),
            evaluated_at=EVALUATED_AT,
        )


def test_pre_order_gate_rejects_graph_declaration_errors(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    paths = _evidence_paths(tmp_path)
    policy = _policy().model_copy(
        update={"design_graph_roots": ["fixtures/missing"]}
    )
    with pytest.raises(PreOrderGateError, match="design graph"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=policy,
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            order_total=_order_total(),
            evidence_paths=paths,
            evaluated_at=EVALUATED_AT,
        )
def test_pre_order_gate_allows_non_gd1_graph(tmp_path: Path) -> None:
    repository = _repository_with_graph(
        tmp_path,
        graph_id="led-only-tag",
        relative_path="fixtures/led-only-tag/graph.json",
    )
    paths = [
        _evidence(tmp_path, "evidence.led-only-tag.electrical"),
        _evidence(tmp_path, "evidence.led-only-tag.mechanical"),
    ]
    record = evaluate_pre_order_gate(
        repository=repository,
        policy=_policy(),
        design_graph_path=repository / "fixtures/led-only-tag/graph.json",
        order_total=_order_total(),
        evidence_paths=paths,
        evaluated_at=EVALUATED_AT,
    )
    assert [item.evidence_id for item in record.evidence] == [
        "evidence.led-only-tag.electrical",
        "evidence.led-only-tag.mechanical",
    ]


def test_pre_order_gate_rejects_graph_outside_declared_root(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    graph = repository / "other/graph.json"
    graph.parent.mkdir()
    shutil.copyfile(GRAPH, graph)
    with pytest.raises(PreOrderGateError, match="outside declared"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=graph,
            order_total=_order_total(),
            evidence_paths=_evidence_paths(tmp_path),
            evaluated_at=EVALUATED_AT,
        )


def test_pre_order_gate_rejects_non_design_input_path(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    path = repository / "fixtures/x/other.json"
    path.parent.mkdir()
    shutil.copyfile(GRAPH, path)
    with pytest.raises(PreOrderGateError, match="not a design input"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=path,
            order_total=_order_total(),
            evidence_paths=_evidence_paths(tmp_path),
            evaluated_at=EVALUATED_AT,
        )


def test_pre_order_gate_rejects_graph_outside_repository(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-graph.json"
    shutil.copyfile(GRAPH, outside)
    with pytest.raises(PreOrderGateError, match="within repository"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=outside,
            order_total=_order_total(),
            evidence_paths=_evidence_paths(tmp_path),
            evaluated_at=EVALUATED_AT,
        )


def test_pre_order_gate_rejects_graph_symlink_escape(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-symlink-target.json"
    shutil.copyfile(GRAPH, outside)
    escaped = repository / "fixtures/escape/graph.json"
    escaped.parent.mkdir(parents=True)
    try:
        escaped.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    with pytest.raises(PreOrderGateError, match="within repository"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=escaped,
            order_total=_order_total(),
            evidence_paths=_evidence_paths(tmp_path),
            evaluated_at=EVALUATED_AT,
        )


def test_pre_order_gate_rejects_malformed_graph(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    graph = repository / "fixtures/golden-design-1/graph.json"
    graph.write_text("{", encoding="utf-8")
    with pytest.raises(PreOrderGateError, match="design graph policy validation"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=graph,
            order_total=_order_total(),
            evidence_paths=_evidence_paths(tmp_path),
            evaluated_at=EVALUATED_AT,
        )


def test_pre_order_gate_rejects_malformed_evidence_and_amount_units(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    paths = _evidence_paths(tmp_path)
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(PreOrderGateError, match="parse Evidence"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            order_total=_order_total(),
            evidence_paths=[malformed, paths[1]],
            evaluated_at=EVALUATED_AT,
        )


def test_pre_order_gate_rejects_unknown_or_missing_container_digest(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    paths = _evidence_paths(tmp_path)
    record = json.loads(paths[0].read_text(encoding="utf-8"))
    envelope = record["envelope"]
    assert isinstance(envelope, dict)
    envelope["container_image_digest"] = "unknown"
    paths[0].write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(PreOrderGateError, match="authoritative"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            order_total=_order_total(),
            evidence_paths=paths,
            evaluated_at=EVALUATED_AT,
        )

    record = json.loads(paths[0].read_text(encoding="utf-8"))
    envelope = record["envelope"]
    assert isinstance(envelope, dict)
    envelope["container_image_digest"] = None
    paths[0].write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(PreOrderGateError, match="parse Evidence"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            order_total=_order_total(),
            evidence_paths=paths,
            evaluated_at=EVALUATED_AT,
        )
    with pytest.raises(PreOrderGateError, match="currency"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            order_total=OrderTotalResult(
                subtotals=(),
                total=QuoteAmount(
                    amount_minor=9300,
                    currency="EUR",
                    minor_unit_digits=2,
                ),
                target_revision=REVISION,
                quote_hashes=(),
                breakdown_hash=HASH,
            ),
            evidence_paths=paths,
            evaluated_at=EVALUATED_AT,
        )
    with pytest.raises(PreOrderGateError, match="currency"):
        evaluate_pre_order_gate(
            repository=repository,
            policy=_policy(),
            design_graph_path=repository / "fixtures/golden-design-1/graph.json",
            order_total=OrderTotalResult(
                subtotals=(),
                total=QuoteAmount(
                    amount_minor=9300,
                    currency="USD",
                    minor_unit_digits=0,
                ),
                target_revision=REVISION,
                quote_hashes=(),
                breakdown_hash=HASH,
            ),
            evidence_paths=paths,
            evaluated_at=EVALUATED_AT,
        )

    clean_repository = _repository(tmp_path / "clean")
    with pytest.raises(PreOrderGateError, match="order total target revision"):
        evaluate_pre_order_gate(
            repository=clean_repository,
            policy=_policy(),
            design_graph_path=clean_repository / "fixtures/golden-design-1/graph.json",
            order_total=OrderTotalResult(
                subtotals=(),
                total=_order_total().total,
                target_revision="r2",
                quote_hashes=(),
                breakdown_hash=HASH,
            ),
            evidence_paths=_evidence_paths(tmp_path / "clean-evidence"),
            evaluated_at=EVALUATED_AT,
        )
