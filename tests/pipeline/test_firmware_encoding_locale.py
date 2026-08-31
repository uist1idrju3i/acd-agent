"""Regression coverage for firmware artifact I/O under a non-UTF-8 locale."""
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from acd.pipeline.firmware_evidence import write_firmware_evidence
from acd.schema.design_graph import DesignGraph
from tests.helpers.locale import run_under_c_locale

ROOT = Path(__file__).parents[2]
GRAPH = ROOT / "fixtures" / "golden-design-1" / "graph.json"
SCRIPT_SHA256 = "sha256:" + "d" * 64
STARTED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _fixture(tmp_path: Path) -> Path:
    out_dir = tmp_path / "firmware"
    out_dir.mkdir()
    shutil.copyfile(GRAPH, tmp_path / "graph.json")
    graph = DesignGraph.model_validate_json(GRAPH.read_text(encoding="utf-8"))
    (out_dir / "qemu-serial.log").write_text("起動: Bluetooth®\n", encoding="utf-8")
    summary = {
        "target_revision": graph.revision,
        "toolchain_version": "esp-idf 筐体",
        "source_hash": "sha256:" + "a" * 64,
        "artifact_hash": "sha256:" + "b" * 64,
        "qemu_version": "qemu 8.2",
        "measurement_conditions": "仮想実行",
        "virtual_run_termination": "正常終了",
        "virtual_log": str(out_dir / "qemu-serial.log"),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return tmp_path


def _result(root: Path) -> dict[str, object]:
    graph = DesignGraph.model_validate_json(
        (root / "graph.json").read_text(encoding="utf-8")
    )
    out_dir = root / "firmware"
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    path, evidence = write_firmware_evidence(
        graph,
        summary,
        out_dir,
        script_sha256=SCRIPT_SHA256,
        started_at=STARTED_AT,
        finished_at=STARTED_AT,
    )
    stored = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": path.name,
        "status": evidence.status,
        "output_hash": evidence.envelope.output_hash,
        "stored_id": stored["evidence_id"],
        "measurement_conditions": stored["envelope"]["measurement_conditions"],
    }


def test_firmware_artifacts_are_locale_independent(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    expected = _result(root)
    child_code = """
import json
import sys
from pathlib import Path
from acd.pipeline.firmware_evidence import write_firmware_evidence
from acd.schema.design_graph import DesignGraph
root = Path(sys.argv[1])
graph = DesignGraph.model_validate_json((root / "graph.json").read_text(encoding="utf-8"))
out_dir = root / "firmware"
summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
path, evidence = write_firmware_evidence(
    graph, summary, out_dir,
    script_sha256="sha256:" + "d" * 64,
    started_at=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").UTC),
    finished_at=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").UTC),
)
stored = json.loads(path.read_text(encoding="utf-8"))
result = {
    "path": path.name,
    "status": evidence.status,
    "output_hash": evidence.envelope.output_hash,
    "stored_id": stored["evidence_id"],
    "measurement_conditions": stored["envelope"]["measurement_conditions"],
}
print(json.dumps(result, ensure_ascii=True, sort_keys=True))
"""
    completed = run_under_c_locale(child_code, root)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == expected
