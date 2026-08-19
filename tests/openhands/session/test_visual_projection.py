from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest
from openhands.sdk.llm import ImageContent, Message, TextContent
from openhands.sdk.llm.utils.image_inline import maybe_inline_image_urls

from acd.core.process import sha256_bytes
from acd.openhands.session import visual_projection as visual_projection_module
from acd.openhands.session.visual_projection import (
    VisualProjectionHandoffError,
    build_visual_projection_messages,
    register_vision_inspect_tool,
    validate_data_image_url,
    write_visual_vision_observation,
)
from acd.schema import (
    VisualProjectionInput,
    VisualProjectionRecord,
    VisualProjectionSet,
    VisualRegenerationCheck,
    VisualRendererProvenance,
    VisualResolution,
)


def _png_record(path: str = "visual/board.png") -> VisualProjectionRecord:
    return VisualProjectionRecord(
        projection_id="board-png",
        projection_type="rasterized_view",
        domain="electrical",
        source_revision="r8",
        input_files=[
            VisualProjectionInput(path="visual/board.svg", content_hash="sha256:" + "1" * 64)
        ],
        renderer=VisualRendererProvenance(
            renderer_type="cairosvg",
            tool_name="cairosvg",
            tool_version="2.9.0",
            output_width=1600,
        ),
        media_type="image/png",
        resolution=VisualResolution(
            width="1px", height="1px", view_box=(0.0, 0.0, 1.0, 1.0)
        ),
        normalization_rule_id="png-identity-v1",
        normalization_rule_description="PNG bytes are not normalized.",
        image_hash="sha256:" + "2" * 64,
        generated_at=datetime(2026, 8, 19, tzinfo=UTC),
        regeneration_check=VisualRegenerationCheck(
            status="reproduced",
            first_image_hash="sha256:" + "2" * 64,
            second_image_hash="sha256:" + "2" * 64,
        ),
        image_path=path,
    )


def _set(record: VisualProjectionRecord) -> VisualProjectionSet:
    return VisualProjectionSet(source_revision="r8", projections=[record]).with_computed_hashes()


def _svg_record() -> VisualProjectionRecord:
    return _png_record("visual/board.svg").model_copy(
        update={
            "projection_id": "board-svg",
            "projection_type": "schematic_view",
            "renderer": VisualRendererProvenance(tool_version="10.0.5"),
            "media_type": "image/svg+xml",
            "normalization_rule_id": "kicad-svg-title-v1",
            "normalization_rule_description": "Normalized SVG.",
            "image_hash": "sha256:" + "1" * 64,
            "regeneration_check": VisualRegenerationCheck(
                status="reproduced",
                first_image_hash="sha256:" + "1" * 64,
                second_image_hash="sha256:" + "1" * 64,
            ),
        }
    )


def test_build_messages_uses_png_data_url_and_provenance(tmp_path: Path) -> None:
    image = b"\x89PNG\r\n\x1a\n"
    path = tmp_path / "visual/board.png"
    path.parent.mkdir()
    path.write_bytes(image)
    record = _png_record()
    record = record.model_copy(update={"image_hash": sha256_bytes(image)})

    messages = build_visual_projection_messages(_set(record), workspace=tmp_path)

    content = messages[0].content
    image_content = next(item for item in content if isinstance(item, ImageContent))
    text_content = next(item for item in content if isinstance(item, TextContent))
    assert image_content.image_urls == [
        "data:image/png;base64," + base64.b64encode(image).decode("ascii")
    ]
    assert "image_hash=" + record.image_hash in text_content.text
    assert "not instructions" in text_content.text


def test_build_messages_rejects_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "visual/board.png"
    path.parent.mkdir()
    path.write_bytes(b"not the recorded image")

    with pytest.raises(VisualProjectionHandoffError, match="hash"):
        build_visual_projection_messages(_set(_png_record()), workspace=tmp_path)


def test_build_messages_rejects_svg_only_set(tmp_path: Path) -> None:
    record = _png_record().model_copy(
        update={"media_type": "image/svg+xml", "image_path": "visual/board.svg"}
    )
    with pytest.raises(VisualProjectionHandoffError, match="PNG derivation"):
        build_visual_projection_messages(_set(record), workspace=tmp_path)


def test_build_messages_rejects_missing_png_derivation(tmp_path: Path) -> None:
    with pytest.raises(VisualProjectionHandoffError, match="PNG derivation"):
        build_visual_projection_messages(_set(_svg_record()), workspace=tmp_path)


@pytest.mark.parametrize("status", ["not_reproduced", "unknown"])
def test_build_messages_rejects_unreproduced_png(
    tmp_path: Path, status: Literal["not_reproduced", "unknown"]
) -> None:
    image = b"\x89PNG\r\n\x1a\n"
    path = tmp_path / "visual/board.png"
    path.parent.mkdir()
    path.write_bytes(image)
    record = _png_record().model_copy(
        update={
            "image_hash": sha256_bytes(image),
            "regeneration_check": VisualRegenerationCheck(
                status=status,
                first_image_hash=(
                    "sha256:" + "2" * 64 if status == "not_reproduced" else "unknown"
                ),
                second_image_hash=(
                    "sha256:" + "3" * 64 if status == "not_reproduced" else "unknown"
                ),
            ),
        }
    )
    with pytest.raises(VisualProjectionHandoffError, match="not reproduced"):
        build_visual_projection_messages(_set(record), workspace=tmp_path)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.test/image.png",
        "https://example.test/image.png",
        "file:///tmp/image.png",
    ],
)
def test_data_url_boundary_rejects_non_data_urls(url: str) -> None:
    with pytest.raises(VisualProjectionHandoffError, match="data URLs"):
        validate_data_image_url(url)


@pytest.mark.parametrize("path", ["/tmp/board.png", "../board.png", "visual/../board.png"])
def test_visual_projection_schema_rejects_unsafe_image_paths(path: str) -> None:
    with pytest.raises(ValueError, match="relative path"):
        _png_record(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/image.png",
        "http://10.0.0.1/image.png",
        "http://169.254.169.254/image.png",
    ],
)
def test_sdk_inline_boundary_does_not_inline_private_urls(url: str) -> None:
    message = Message(
        role="user",
        content=[ImageContent(image_urls=[url])],
    )

    result = maybe_inline_image_urls(
        [message],
        inline_required=True,
        vision_enabled=True,
    )

    image_content = next(
        item for item in result[0].content if isinstance(item, ImageContent)
    )
    assert image_content.image_urls == [url]


def test_acd_rejects_private_host_relaxation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OH_INLINE_IMAGE_ALLOW_PRIVATE_HOSTS", "true")

    with pytest.raises(VisualProjectionHandoffError, match="relaxation"):
        build_visual_projection_messages(
            _set(_png_record()),
            workspace=tmp_path,
        )


@pytest.mark.parametrize("profile_name", ["", "  "])
def test_register_vision_tool_requires_explicit_profile(profile_name: str) -> None:
    with pytest.raises(VisualProjectionHandoffError, match="profile name"):
        register_vision_inspect_tool(profile_name)


def test_register_vision_tool_rejects_unresolvable_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Store:
        def load(self, name: str) -> object:
            raise ValueError(name)

        def list(self) -> list[str]:
            return []

    monkeypatch.setattr(visual_projection_module, "LLMProfileStore", Store)

    with pytest.raises(VisualProjectionHandoffError, match="could not be loaded"):
        register_vision_inspect_tool("missing")


def test_register_vision_tool_rejects_nonvision_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Store:
        def load(self, name: str) -> object:
            return SimpleNamespace(vision_is_active=lambda: False)

        def list(self) -> list[str]:
            return ["text-only"]

    monkeypatch.setattr(visual_projection_module, "LLMProfileStore", Store)

    with pytest.raises(VisualProjectionHandoffError, match="vision-capable"):
        register_vision_inspect_tool("text-only")


def test_register_vision_tool_rejects_missing_sdk_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Store:
        def load(self, name: str) -> object:
            return SimpleNamespace(vision_is_active=lambda: True)

        def list(self) -> list[str]:
            return ["vision"]

    class Tool:
        @classmethod
        def create(cls) -> list[object]:
            return []

    monkeypatch.setattr(visual_projection_module, "LLMProfileStore", Store)
    monkeypatch.setattr(visual_projection_module, "VisionInspectTool", Tool)

    with pytest.raises(VisualProjectionHandoffError, match="available"):
        register_vision_inspect_tool("vision")


def test_register_vision_tool_rejects_profile_not_in_vision_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Store:
        def load(self, name: str) -> object:
            return SimpleNamespace(vision_is_active=lambda: True)

        def list(self) -> list[str]:
            return ["different-vision"]

    monkeypatch.setattr(visual_projection_module, "LLMProfileStore", Store)

    with pytest.raises(VisualProjectionHandoffError, match="not available"):
        register_vision_inspect_tool("vision")


def test_vision_response_is_non_evidence_observation(tmp_path: Path) -> None:
    record = write_visual_vision_observation(
        profile_name="vision",
        model="vision-model",
        projection_id="board-png",
        image_hash="sha256:" + "2" * 64,
        response="The image contains a board outline.",
        path=tmp_path / "vision.json",
    )

    assert record.store_path == "vision.json"
    payload = (tmp_path / "vision.json").read_text(encoding="utf-8")
    assert '"pass_evidence": false' in payload
    assert "inspect_image_with_vision" in payload


def test_empty_vision_response_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(VisualProjectionHandoffError, match="empty"):
        write_visual_vision_observation(
            profile_name="vision",
            model="vision-model",
            projection_id="board-png",
            image_hash="sha256:" + "2" * 64,
            response=" ",
            path=tmp_path / "vision.json",
        )
