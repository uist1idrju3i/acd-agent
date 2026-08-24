"""Contracts for declarative functional-block topology templates."""

from __future__ import annotations

from pydantic import Field, model_validator

from acd.schema.common import AcdModel, NonEmptyStr, SchemaVersion
from acd.schema.design_graph import AttrValue
from acd.schema.parts_catalog import ComponentPartRequest


class TopologyTemplateComponent(AcdModel):
    refdes: NonEmptyStr
    part_request: ComponentPartRequest
    pads: dict[NonEmptyStr, NonEmptyStr | None] = Field(default_factory=dict)
    attrs: dict[NonEmptyStr, AttrValue] = Field(default_factory=dict)


class TopologyTemplateNet(AcdModel):
    net_id: NonEmptyStr
    attrs: dict[NonEmptyStr, AttrValue] = Field(default_factory=dict)


class TopologyTemplate(AcdModel):
    template_id: NonEmptyStr
    block_id: NonEmptyStr
    components: list[TopologyTemplateComponent] = Field(
        default_factory=list[TopologyTemplateComponent]
    )
    nets: list[TopologyTemplateNet] = Field(default_factory=list[TopologyTemplateNet])
    constraints: list[NonEmptyStr] = Field(default_factory=list[NonEmptyStr])


class TopologyTemplatesDocument(AcdModel):
    schema_version: SchemaVersion
    templates: list[TopologyTemplate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_declarations(self) -> TopologyTemplatesDocument:
        template_ids = [template.template_id for template in self.templates]
        block_ids = [template.block_id for template in self.templates]
        if len(template_ids) != len(set(template_ids)):
            raise ValueError("topology template IDs must be unique")
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("topology template block IDs must be unique")
        refdes = [
            component.refdes
            for template in self.templates
            for component in template.components
        ]
        if len(refdes) != len(set(refdes)):
            raise ValueError("topology template refdes values must be unique")
        net_ids = [
            net.net_id for template in self.templates for net in template.nets
        ]
        if len(net_ids) != len(set(net_ids)):
            raise ValueError("topology template net IDs must be unique")
        declared_nets = set(net_ids)
        referenced_nets = {
            net_id
            for template in self.templates
            for component in template.components
            for net_id in component.pads.values()
            if net_id is not None
        }
        missing_nets = sorted(referenced_nets - declared_nets)
        if missing_nets:
            raise ValueError(
                "topology template references undeclared nets: " + ", ".join(missing_nets)
            )
        return self


__all__ = [
    "TopologyTemplate",
    "TopologyTemplateComponent",
    "TopologyTemplateNet",
    "TopologyTemplatesDocument",
]
