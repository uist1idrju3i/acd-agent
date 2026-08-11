"""Round-trip tests between JSON Schemas in ``schemas/`` and acd_schema models.

Every tracked golden fixture must (a) validate against its JSON Schema,
(b) parse into the matching Pydantic model, and (c) serialize back to a
document that still validates against the JSON Schema and re-parses to an
equal model. Negative fixtures must be rejected by both sides (fail-closed).
"""

from __future__ import annotations

import pytest
from conftest import Json, load_fixture, make_validator
from jsonschema import ValidationError as JsonSchemaError
from jsonschema.protocols import Validator
from pydantic import BaseModel, ValidationError
from referencing import Registry
from referencing.jsonschema import Schema

from acd_schema import (
    AcdError,
    DesignGraph,
    Evidence,
    FwPackage,
    GateMatrix,
    ReviewFinding,
    ToolEnvelope,
    parse_event_payload,
)

CONTRACTS: list[tuple[str, str, type[BaseModel]]] = [
    ("design-graph.schema.json", "design-graph.json", DesignGraph),
    ("tool-envelope.schema.json", "tool-envelope.json", ToolEnvelope),
    ("evidence.schema.json", "evidence.json", Evidence),
    ("gate-matrix.schema.json", "gate-matrix.json", GateMatrix),
    ("error-taxonomy.schema.json", "error-taxonomy.json", AcdError),
    ("review-finding.schema.json", "review-finding.json", ReviewFinding),
    ("fw-package.schema.json", "fw-package.json", FwPackage),
]

NEGATIVE: list[tuple[str, str, type[BaseModel]]] = [
    ("design-graph.schema.json", "design-graph-unknown-field.json", DesignGraph),
    ("tool-envelope.schema.json", "tool-envelope-missing-input-hash.json", ToolEnvelope),
    ("evidence.schema.json", "evidence-bad-status.json", Evidence),
    ("gate-matrix.schema.json", "gate-matrix-bad-revision.json", GateMatrix),
    ("error-taxonomy.schema.json", "error-taxonomy-bad-code.json", AcdError),
    ("review-finding.schema.json", "review-finding-bad-disposition.json", ReviewFinding),
    ("fw-package.schema.json", "fw-package-unknown-field.json", FwPackage),
]


def _validator(schema_name: str, registry: Registry[Schema]) -> Validator:
    return make_validator(schema_name, registry)


@pytest.mark.parametrize(("schema_name", "fixture_name", "model_type"), CONTRACTS)
def test_golden_fixture_roundtrip(
    schema_name: str,
    fixture_name: str,
    model_type: type[BaseModel],
    registry: Registry[Schema],
) -> None:
    data = load_fixture("valid", fixture_name)
    validator = _validator(schema_name, registry)
    validator.validate(data)

    model = model_type.model_validate(data)
    dumped = model.model_dump(mode="json", exclude_none=True)
    validator.validate(dumped)
    assert model_type.model_validate(dumped) == model


@pytest.mark.parametrize(("schema_name", "fixture_name", "model_type"), NEGATIVE)
def test_negative_fixture_rejected_by_both(
    schema_name: str,
    fixture_name: str,
    model_type: type[BaseModel],
    registry: Registry[Schema],
) -> None:
    data = load_fixture("invalid", fixture_name)
    validator = _validator(schema_name, registry)
    with pytest.raises(JsonSchemaError):
        validator.validate(data)
    with pytest.raises(ValidationError):
        model_type.model_validate(data)


def test_event_payload_roundtrip(registry: Registry[Schema]) -> None:
    data = load_fixture("valid", "event-payload.json")
    validator = _validator("event-payload.schema.json", registry)
    validator.validate(data)
    payload = parse_event_payload(data)
    dumped = payload.model_dump(mode="json", exclude_none=True)
    validator.validate(dumped)
    assert parse_event_payload(dumped) == payload


def test_unknown_event_kind_rejected_by_both(
    registry: Registry[Schema],
) -> None:
    data = load_fixture("invalid", "event-payload-unknown-kind.json")
    validator = _validator("event-payload.schema.json", registry)
    with pytest.raises(JsonSchemaError):
        validator.validate(data)
    with pytest.raises(ValidationError):
        parse_event_payload(data)


def test_design_graph_rejects_dangling_dependency() -> None:
    data = load_fixture("valid", "design-graph.json")
    nodes = data["nodes"]
    assert isinstance(nodes, list)
    orphan: Json = {"id": "orphan.node", "kind": "requirement", "depends_on": ["no.such"]}
    broken: list[Json] = [*nodes, orphan]
    with pytest.raises(ValidationError, match="unknown node"):
        DesignGraph.model_validate({**data, "nodes": broken})


def test_mechanical_node_kinds_roundtrip_between_schema_and_model(
    registry: Registry[Schema],
) -> None:
    data = load_fixture("valid", "design-graph.json")
    base_nodes: list[Json] = [
        {
            "id": "board.gd1",
            "kind": "electrical.board",
            "attrs": {"width_mm": 80.0, "height_mm": 50.0, "unit": "mm"},
        },
    ]
    mechanical_nodes: list[Json] = [
        {
            "id": "mechanical.outline.1",
            "kind": "mechanical.outline",
            "attrs": {
                "width_mm": 80.0,
                "depth_mm": 50.0,
                "thickness_mm": 1.6,
                "corner_radius_mm": 2.0,
                "unit": "mm",
                "origin": "board_upper_left",
                "y_axis": "down",
                "mount_hole_positions": "10,10;70,10;10,40;70,40",
            },
            "depends_on": ["board.gd1"],
        },
        {
            "id": "mechanical.component_body.1",
            "kind": "mechanical.component_body",
            "attrs": {
                "component": "component.u1",
                "height_mm": 3.2,
                "body_width_mm": 10.0,
                "body_depth_mm": 8.0,
                "mounting_face": "top",
                "rotation_deg": 0.0,
                "unit": "mm",
            },
            "depends_on": ["comp.mcu"],
        },
        {
            "id": "mechanical.connector_opening.1",
            "kind": "mechanical.connector_opening",
            "attrs": {
                "connector": "comp.mcu",
                "face": "front",
                "center_x_mm": 40.0,
                "center_z_mm": 5.0,
                "width_mm": 12.0,
                "height_mm": 6.0,
                "margin_mm": 0.5,
                "unit": "mm",
            },
            "depends_on": ["comp.mcu"],
        },
        {
            "id": "mechanical.enclosure.1",
            "kind": "mechanical.enclosure",
            "attrs": {
                "wall_thickness_mm": 2.0,
                "internal_clearance_mm": 1.0,
                "lid_fit_gap_mm": 0.2,
                "standoff_height_mm": 5.0,
                "material": "PETG",
                "unit": "mm",
            },
            "depends_on": [
                "mechanical.outline.1",
                "mechanical.component_body.1",
                "mechanical.connector_opening.1",
            ],
        },
    ]
    nodes = data["nodes"]
    assert isinstance(nodes, list)
    all_nodes: list[Json] = [*nodes, *base_nodes, *mechanical_nodes]
    candidate: dict[str, Json] = {**data, "nodes": all_nodes}
    validator = _validator("design-graph.schema.json", registry)
    validator.validate(candidate)
    model = DesignGraph.model_validate(candidate)
    dumped = model.model_dump(mode="json", exclude_none=True)
    validator.validate(dumped)
    assert DesignGraph.model_validate(dumped) == model
