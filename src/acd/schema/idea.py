"""Idea record, dialogue history, and progress observation contracts (ADR-0049).

An idea record is a git-managed design input captured before requirements exist.
Every item is either ``confirmed`` (agreed by the user) or ``open`` (undecided);
undeclared items are unknown and block promotion to requirement records.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from acd.schema.common import (
    CURRENT_SCHEMA_VERSION,
    AcdModel,
    NodeId,
    NonEmptyStr,
    Revision,
    SchemaVersion,
    Timestamp,
)

IdeaFieldStatus = Literal["confirmed", "open"]

IdeaSourceKind = Literal[
    "user_statement",
    "design_graph",
    "rationale",
    "gate_threshold",
    "evidence",
    "design_example",
    "parts_catalog",
    "fab_profile",
]


class IdeaSource(AcdModel):
    """A citation of where an idea item or proposal originated."""

    kind: IdeaSourceKind
    ref: NonEmptyStr


class IdeaField(AcdModel):
    """One idea item: either confirmed by the user or still open."""

    status: IdeaFieldStatus = "open"
    value: NonEmptyStr | FiniteFloat | None = None
    unit: NonEmptyStr | None = None
    sources: list[IdeaSource] = Field(default_factory=list[IdeaSource])
    confirmed_at: Timestamp | None = None

    @model_validator(mode="after")
    def validate_status_consistency(self) -> IdeaField:
        if self.status == "confirmed":
            if self.value is None:
                raise ValueError("confirmed field must carry a value")
            if self.confirmed_at is None:
                raise ValueError("confirmed field must carry confirmed_at")
            if not any(
                source.kind == "user_statement" for source in self.sources
            ):
                raise ValueError(
                    "confirmed field requires a user_statement source"
                )
        else:
            if self.value is not None:
                raise ValueError("open field must not carry a value")
            if self.confirmed_at is not None:
                raise ValueError("open field must not carry confirmed_at")
        return self


class IdeaConstraints(AcdModel):
    """Known constraints on the idea; every entry starts open."""

    cost: IdeaField = Field(default_factory=IdeaField)
    dimensions: IdeaField = Field(default_factory=IdeaField)
    power: IdeaField = Field(default_factory=IdeaField)
    communication: IdeaField = Field(default_factory=IdeaField)
    regulatory: IdeaField = Field(default_factory=IdeaField)


class IdeaSuccessCriterion(AcdModel):
    """One success criterion of the idea."""

    criterion_id: NodeId
    statement: IdeaField = Field(default_factory=IdeaField)


class IdeaFunction(AcdModel):
    """One function the idea must or should provide."""

    function_id: NodeId
    description: IdeaField = Field(default_factory=IdeaField)
    priority: Literal["must", "should"] = "must"


class IdeaRecord(AcdModel):
    """The idea record contract: declaration input, never approval evidence."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    idea_id: NodeId
    revision: Revision
    title: NonEmptyStr
    purpose: IdeaField = Field(default_factory=IdeaField)
    target_users: IdeaField = Field(default_factory=IdeaField)
    experience: IdeaField = Field(default_factory=IdeaField)
    environment: IdeaField = Field(default_factory=IdeaField)
    constraints: IdeaConstraints = Field(default_factory=IdeaConstraints)
    success_criteria: list[IdeaSuccessCriterion] = Field(
        default_factory=list[IdeaSuccessCriterion]
    )
    functions: list[IdeaFunction] = Field(default_factory=list[IdeaFunction])

    @model_validator(mode="after")
    def _unique_item_ids(self) -> IdeaRecord:
        criterion_ids = [item.criterion_id for item in self.success_criteria]
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("success_criteria criterion_id entries must be unique")
        function_ids = [item.function_id for item in self.functions]
        if len(set(function_ids)) != len(function_ids):
            raise ValueError("functions function_id entries must be unique")
        return self

    def _scalar_fields(self) -> list[tuple[str, IdeaField]]:
        return [
            ("purpose", self.purpose),
            ("target_users", self.target_users),
            ("experience", self.experience),
            ("environment", self.environment),
            ("constraints.cost", self.constraints.cost),
            ("constraints.dimensions", self.constraints.dimensions),
            ("constraints.power", self.constraints.power),
            ("constraints.communication", self.constraints.communication),
            ("constraints.regulatory", self.constraints.regulatory),
        ]

    def _item_fields(self) -> list[tuple[str, IdeaField]]:
        items: list[tuple[str, IdeaField]] = [
            (f"success_criteria.{item.criterion_id}", item.statement)
            for item in self.success_criteria
        ]
        items.extend(
            (f"functions.{item.function_id}", item.description)
            for item in self.functions
        )
        return items

    def open_items(self) -> list[str]:
        """Dotted paths of open items in declaration order."""
        open_paths = [
            path
            for path, field in self._scalar_fields() + self._item_fields()
            if field.status == "open"
        ]
        if not self.success_criteria:
            open_paths.append("success_criteria")
        if not self.functions:
            open_paths.append("functions")
        return open_paths

    def confirmed_items(self) -> list[str]:
        """Dotted paths of confirmed items in declaration order."""
        return [
            path
            for path, field in self._scalar_fields() + self._item_fields()
            if field.status == "confirmed"
        ]

    def ready_for_promotion(self) -> bool:
        """Precondition for promotion to requirements; never an approval."""
        return not self.open_items()


class IdeaOption(AcdModel):
    """One option offered for a dialogue question."""

    label: NonEmptyStr
    tradeoff: NonEmptyStr
    recommended: bool = False
    sources: list[IdeaSource] = Field(min_length=1)


class IdeaQuestion(AcdModel):
    """One prioritized question posed to the user."""

    field: NonEmptyStr
    prompt: NonEmptyStr
    priority: int = Field(ge=1)
    options: list[IdeaOption] = Field(default_factory=list[IdeaOption])

    @model_validator(mode="after")
    def _at_most_one_recommended(self) -> IdeaQuestion:
        if sum(option.recommended for option in self.options) > 1:
            raise ValueError("at most one option may be recommended")
        return self


class IdeaAnswer(AcdModel):
    """A user answer that confirms an idea field."""

    field: NonEmptyStr
    value: NonEmptyStr | FiniteFloat
    unit: NonEmptyStr | None = None
    answered_by: Literal["user"] = "user"
    sources: list[IdeaSource] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_user_source(self) -> IdeaAnswer:
        if not any(source.kind == "user_statement" for source in self.sources):
            raise ValueError("answers require a user_statement source")
        return self


class IdeaTurn(AcdModel):
    """One append-only dialogue turn."""

    turn_no: int = Field(ge=1)
    asked: list[IdeaQuestion] = Field(default_factory=list[IdeaQuestion])
    answers: list[IdeaAnswer] = Field(default_factory=list[IdeaAnswer])
    recorded_at: Timestamp


class IdeaDialogueHistory(AcdModel):
    """Append-only history of dialogue turns for one idea record."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    idea_id: NodeId
    turns: list[IdeaTurn] = Field(default_factory=list[IdeaTurn])

    @model_validator(mode="after")
    def _contiguous_turns(self) -> IdeaDialogueHistory:
        for index, turn in enumerate(self.turns):
            if turn.turn_no != index + 1:
                raise ValueError("turn_no must be contiguous starting at 1")
        return self


class IdeaProgress(AcdModel):
    """L3 progress observation for an idea record; never approval."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    artifact_kind: Literal["idea_progress"] = "idea_progress"
    record_class: Literal["L3"] = "L3"
    pass_evidence: Literal[False] = False
    idea_id: NodeId
    revision: Revision
    turn_count: int = Field(ge=0)
    confirmed_count: int = Field(ge=0)
    open_count: int = Field(ge=0)
    open_items: list[str] = Field(default_factory=list[str])
    blocking_unknowns: list[str] = Field(default_factory=list[str])
    ready_for_promotion: bool


__all__ = [
    "IdeaAnswer",
    "IdeaConstraints",
    "IdeaDialogueHistory",
    "IdeaField",
    "IdeaFieldStatus",
    "IdeaFunction",
    "IdeaOption",
    "IdeaProgress",
    "IdeaQuestion",
    "IdeaRecord",
    "IdeaSource",
    "IdeaSourceKind",
    "IdeaSuccessCriterion",
    "IdeaTurn",
]
