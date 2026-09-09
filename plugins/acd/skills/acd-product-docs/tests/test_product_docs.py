"""Generated product document determinism and fail-closed tests.

Uses the Golden Design #1 fixture graph plus a synthetic visual projection set,
including deliberately broken inputs that must stop generation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from acd.schema.common import canonical_json_sha256
from acd.schema.design_graph import DesignGraph
from acd.schema.theme_song import (
    ThemeSongArtifact,
    ThemeSongArtifactInput,
    ThemeSongProjection,
    ThemeSongRegenerationCheck,
)
from acd.schema.visual_projection import (
    VisualProjectionSet,
    VisualRegenerationCheck,
)
from doc_inputs import (
    DocumentGenerationError,
    load_graph,
    load_projection_figures,
    load_theme_song,
    sha256_file,
)
from generate_instruction_manual import main as manual_main
from generate_instruction_manual import parse_pins_header, render_manual
from generate_product_readme import TEMPLATE_ID, render_readme
from generate_product_readme import main as readme_main

REPO_ROOT = Path(__file__).resolve().parents[5]
GRAPH = REPO_ROOT / "fixtures" / "golden-design-1" / "graph.json"
PROJECTION_TEMPLATE = (
    REPO_ROOT / "fixtures" / "contracts" / "valid" / "visual-projection-set.json"
)


@pytest.fixture(scope="module")
def graph() -> DesignGraph:
    return DesignGraph.model_validate(json.loads(GRAPH.read_text(encoding="utf-8")))


def _write_projection_set(
    directory: Path,
    revision: str,
    mutate: Callable[[VisualProjectionSet], VisualProjectionSet] | None = None,
) -> Path:
    template = VisualProjectionSet.model_validate(
        json.loads(PROJECTION_TEMPLATE.read_text(encoding="utf-8"))
    )
    records = [
        record.model_copy(
            update={
                "source_revision": revision,
                "image_path": f"visual/{record.projection_id}.svg",
            }
        )
        for record in template.projections
    ]
    projection_set = template.model_copy(
        update={
            "source_revision": revision,
            "projections": records,
            "identity_hash": "unknown",
            "canonical_hash": "unknown",
        }
    )
    if mutate is not None:
        projection_set = mutate(projection_set)
    projection_set = projection_set.with_computed_hashes()
    for record in projection_set.projections:
        image = directory / record.image_path
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    path = directory / "visual-projections.json"
    path.write_text(projection_set.model_dump_json(), encoding="utf-8")
    return path


def _pins_header(directory: Path, revision: str) -> Path:
    lines = [
        "#pragma once",
        "",
        f'#define ACD_TARGET_REVISION "{revision}"',
        "",
        "#define ACD_PIN_LED 7",
        "#define ACD_PIN_I2C_SDA 4",
        "#define ACD_PIN_I2C_SCL 5",
        "#define ACD_PIN_UART_TX 21",
        "#define ACD_PIN_UART_RX 20",
        "#define ACD_PIN_BOOT 9",
        "#define ACD_PIN_USB_DN 18",
        "#define ACD_PIN_USB_DP 19",
        "",
        "#define ACD_SHT40_I2C_ADDRESS 0x44",
        "#define ACD_LED_BLINK_PERIOD_MS 1000",
        "#define ACD_LOG_PERIOD_MS 2000",
        "",
    ]
    path = directory / "acd_pins.h"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _theme_song_projection(
    directory: Path,
    graph: DesignGraph,
    *,
    graph_id: str | None = None,
    revision: str | None = None,
    midi_payload: bytes = b"MIDI-BYTES",
    midi_hash: str | None = None,
    write_midi: bool = True,
) -> Path:
    midi_path = directory / "theme-song" / "theme-song.mid"
    if write_midi:
        midi_path.parent.mkdir(parents=True, exist_ok=True)
        midi_path.write_bytes(midi_payload)
    actual_hash = "sha256:" + hashlib.sha256(midi_payload).hexdigest()
    projection = ThemeSongProjection(
        projection_id="theme-song.dual-beacon",
        graph_id=graph_id or graph.graph_id,
        source_revision=revision or graph.revision,
        graph_input=ThemeSongArtifactInput(
            path="graph.json", content_hash=sha256_file(GRAPH)
        ),
        source="deterministic",
        skill_script_path="plugins/acd/skills/acd-theme-song/scripts/compose_theme_song.py",
        skill_script_sha256="sha256:" + "0" * 64,
        composer_id="acd-theme-song-composer-v1",
        seed="sha256:" + "1" * 64,
        bpm=95,
        bars=16,
        key="g minor",
        title="Theme test",
        artifacts=[
            ThemeSongArtifact(
                path="theme-song/theme-song.mid",
                media_type="audio/midi",
                content_hash=midi_hash or actual_hash,
            )
        ],
        regeneration_check=ThemeSongRegenerationCheck(
            status="reproduced",
            first_hash=midi_hash or actual_hash,
            second_hash=midi_hash or actual_hash,
        ),
        canonical_hash="unknown",
    )
    payload = projection.model_dump(mode="json")
    payload["canonical_hash"] = canonical_json_sha256(
        projection.model_dump(mode="json", exclude={"canonical_hash"})
    )
    path = directory / "theme-song-projection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_product_readme_is_generated_from_graph_values(
    graph: DesignGraph, tmp_path: Path
) -> None:
    projections = _write_projection_set(tmp_path, graph.revision)
    out_dir = tmp_path / "docs"
    assert readme_main(
        [
            "--graph",
            str(GRAPH),
            "--projections",
            str(projections),
            "--out-dir",
            str(out_dir),
            "--base-dir",
            str(tmp_path),
        ]
    ) == 0
    body = (out_dir / "product-readme.md").read_text(encoding="utf-8")
    assert f"# 製品説明: {graph.graph_id}" in body
    assert "ESP32-C3-MINI-1-N4" in body
    assert "| +3V3 | 3.3 V |" in body
    assert "| net.led | IO7 |" in body
    assert "https://github.com/espressif/kicad-libraries" in body
    assert "![schematic](../visual/schematic.svg)" in body

    provenance = json.loads(
        (out_dir / "product-readme.md.provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["artifact_kind"] == "generated_document"
    assert provenance["pass_evidence"] is False
    assert provenance["target_revision"] == graph.revision
    assert provenance["template_id"] == TEMPLATE_ID
    assert TEMPLATE_ID == "acd-product-readme-ja-v2"
    assert "| fw.state.boot | boot | yes |" in body
    assert "boot_complete" in body
    assert "fw.state.boot → fw.state.sensor_init" in body
    assert "| 1 | fw.module.main | comp.u1 | initialize_firmware |" in body
    assert "## 生成物と判定の関係" in body
    assert "テーマソング投影: 未入力" in body
    assert "テーマソング（L3投影" not in body.split("## 図解")[-1]
    assert [item["path"] for item in provenance["inputs"]] == [
        Path(GRAPH).resolve().as_posix(),
        "visual-projections.json",
    ]


def test_product_readme_is_deterministic(graph: DesignGraph, tmp_path: Path) -> None:
    projections = _write_projection_set(tmp_path, graph.revision)
    loaded, _ = load_graph(GRAPH)
    figures, _ = load_projection_figures([projections], graph.revision)
    out_dir = tmp_path / "docs"
    first = render_readme(loaded, figures, out_dir)
    second = render_readme(loaded, figures, out_dir)
    assert first == second


def test_projection_set_of_another_revision_fails_closed(tmp_path: Path) -> None:
    projections = _write_projection_set(tmp_path, "r99")
    with pytest.raises(DocumentGenerationError, match="targets revision"):
        load_projection_figures([projections], "r1")


def test_missing_projection_image_fails_closed(tmp_path: Path) -> None:
    projections = _write_projection_set(tmp_path, "r1")
    for image in sorted((tmp_path / "visual").iterdir()):
        image.unlink()
    with pytest.raises(DocumentGenerationError, match=r"image .* is missing"):
        load_projection_figures([projections], "r1")


def test_unreproduced_projection_fails_closed(tmp_path: Path) -> None:
    def mutate(projection_set: VisualProjectionSet) -> VisualProjectionSet:
        check = VisualRegenerationCheck(
            status="unknown",
            first_image_hash="unknown",
            second_image_hash="unknown",
            reason="not rerun",
        )
        records = [
            record.model_copy(update={"regeneration_check": check})
            for record in projection_set.projections
        ]
        return projection_set.model_copy(update={"projections": records})

    projections = _write_projection_set(tmp_path, "r1", mutate)
    with pytest.raises(DocumentGenerationError, match="was not reproduced"):
        load_projection_figures([projections], "r1")


def test_no_projection_set_fails_closed() -> None:
    with pytest.raises(DocumentGenerationError, match="no visual projection set"):
        load_projection_figures([], "r1")


def test_instruction_manual_is_generated_from_graph_and_pin_projection(
    graph: DesignGraph, tmp_path: Path
) -> None:
    header = _pins_header(tmp_path, graph.revision)
    out_dir = tmp_path / "docs"
    assert manual_main(
        [
            "--graph",
            str(GRAPH),
            "--pins-header",
            str(header),
            "--out-dir",
            str(out_dir),
            "--base-dir",
            str(tmp_path),
        ]
    ) == 0
    body = (out_dir / "instruction-manual.md").read_text(encoding="utf-8")
    assert f"# 取扱説明書: {graph.graph_id}" in body
    assert "周期1000 msの点滅" in body
    assert "IO7のLED" in body
    assert "`0x44`" in body
    assert "TYPE-C-31-M-12" in body
    assert "最大ネット電圧5 V" in body

    provenance = json.loads(
        (out_dir / "instruction-manual.md.provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["document_kind"] == "instruction_manual"
    assert provenance["pass_evidence"] is False
    assert len(provenance["inputs"]) == 2


def test_instruction_manual_is_deterministic(graph: DesignGraph, tmp_path: Path) -> None:
    header = _pins_header(tmp_path, graph.revision)
    macros = parse_pins_header(header)
    loaded, _ = load_graph(GRAPH)
    assert render_manual(loaded, macros) == render_manual(loaded, macros)


def test_pin_projection_of_another_revision_fails_closed(tmp_path: Path) -> None:
    header = _pins_header(tmp_path, "r99")
    macros = parse_pins_header(header)
    loaded, _ = load_graph(GRAPH)
    with pytest.raises(DocumentGenerationError, match="targets revision"):
        render_manual(loaded, macros)


def test_missing_pin_macro_fails_closed(tmp_path: Path) -> None:
    header = _pins_header(tmp_path, "r1")
    kept = [
        line
        for line in header.read_text(encoding="utf-8").splitlines()
        if not line.startswith("#define ACD_PIN_LED")
    ]
    header.write_text("\n".join(kept), encoding="utf-8")
    with pytest.raises(DocumentGenerationError, match="ACD_PIN_LED"):
        parse_pins_header(header)


def test_invalid_graph_fails_closed(tmp_path: Path) -> None:
    broken = tmp_path / "graph.json"
    broken.write_text("{}", encoding="utf-8")
    with pytest.raises(DocumentGenerationError, match="is not valid"):
        load_graph(broken)


def test_theme_song_section_is_rendered(
    graph: DesignGraph, tmp_path: Path
) -> None:
    projections = _write_projection_set(tmp_path, graph.revision)
    theme_path = _theme_song_projection(tmp_path, graph)
    out_dir = tmp_path / "docs"
    assert readme_main(
        [
            "--graph",
            str(GRAPH),
            "--projections",
            str(projections),
            "--theme-song-projection",
            str(theme_path),
            "--out-dir",
            str(out_dir),
            "--base-dir",
            str(tmp_path),
        ]
    ) == 0
    body = (out_dir / "product-readme.md").read_text(encoding="utf-8")
    assert "## テーマソング（L3投影）" in body
    assert "Theme test" in body
    assert "[theme-song.mid](../theme-song/theme-song.mid)" in body
    assert "sha256:" + hashlib.sha256(b"MIDI-BYTES").hexdigest() in body
    assert "g minor" in body
    assert "pass_evidence=false" in body

    provenance = json.loads(
        (out_dir / "product-readme.md.provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["inputs"][-1]["path"] == "theme-song-projection.json"


def test_theme_song_absent_omits_section_and_notes_undeclared(
    graph: DesignGraph, tmp_path: Path
) -> None:
    projections = _write_projection_set(tmp_path, graph.revision)
    loaded, _ = load_graph(GRAPH)
    figures, _ = load_projection_figures([projections], graph.revision)
    body = render_readme(loaded, figures, tmp_path / "docs")
    assert "## テーマソング" not in body
    assert "#テーマソング" not in body
    assert "テーマソング投影: 未入力（`--theme-song-projection`未指定）" in body


def test_theme_song_of_another_graph_fails_closed(
    graph: DesignGraph, tmp_path: Path
) -> None:
    theme_path = _theme_song_projection(tmp_path, graph, graph_id="other-graph")
    loaded, _ = load_graph(GRAPH)
    with pytest.raises(DocumentGenerationError, match="targets graph"):
        load_theme_song(theme_path, loaded)


def test_theme_song_of_another_revision_fails_closed(
    graph: DesignGraph, tmp_path: Path
) -> None:
    theme_path = _theme_song_projection(tmp_path, graph, revision="r99")
    loaded, _ = load_graph(GRAPH)
    with pytest.raises(DocumentGenerationError, match="targets revision"):
        load_theme_song(theme_path, loaded)


def test_theme_song_midi_hash_mismatch_fails_closed(
    graph: DesignGraph, tmp_path: Path
) -> None:
    theme_path = _theme_song_projection(
        tmp_path, graph, midi_hash="sha256:" + "f" * 64
    )
    loaded, _ = load_graph(GRAPH)
    with pytest.raises(DocumentGenerationError, match="hash mismatch"):
        load_theme_song(theme_path, loaded)


def test_theme_song_missing_midi_fails_closed(
    graph: DesignGraph, tmp_path: Path
) -> None:
    theme_path = _theme_song_projection(tmp_path, graph, write_midi=False)
    loaded, _ = load_graph(GRAPH)
    with pytest.raises(DocumentGenerationError, match="is missing"):
        load_theme_song(theme_path, loaded)


def test_theme_song_not_reproduced_fails_closed(
    graph: DesignGraph, tmp_path: Path
) -> None:
    theme_path = _theme_song_projection(tmp_path, graph)
    payload = json.loads(theme_path.read_text(encoding="utf-8"))
    payload["regeneration_check"]["status"] = "unknown"
    payload["regeneration_check"]["first_hash"] = "unknown"
    payload["regeneration_check"]["second_hash"] = "unknown"
    payload["canonical_hash"] = "unknown"
    theme_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    loaded, _ = load_graph(GRAPH)
    with pytest.raises(DocumentGenerationError):
        load_theme_song(theme_path, loaded)


def test_product_readme_is_deterministic_with_theme(
    graph: DesignGraph, tmp_path: Path
) -> None:
    projections = _write_projection_set(tmp_path, graph.revision)
    theme_path = _theme_song_projection(tmp_path, graph)
    loaded, _ = load_graph(GRAPH)
    figures, _ = load_projection_figures([projections], graph.revision)
    theme, theme_input = load_theme_song(theme_path, loaded)
    out_dir = tmp_path / "docs"
    first = render_readme(
        loaded, figures, out_dir, theme=theme, inputs=[theme_input]
    )
    second = render_readme(
        loaded, figures, out_dir, theme=theme, inputs=[theme_input]
    )
    assert first == second
