"""Deterministic workaround application and retirement evaluation."""

from __future__ import annotations

from typing import Literal, cast

from acd.schema.defect_record import DefectDocument
from acd.schema.design_graph import DesignGraph
from acd.schema.eco import EcoCheckResult, EcoDocument
from acd.schema.rework_diff import ReworkDiff
from acd.schema.workaround_ledger import (
    UnitDisposition,
    UnitRef,
    UnitStatus,
    WorkaroundApplication,
    WorkaroundLedger,
    WorkaroundRetirementResult,
)


class WorkaroundLedgerError(ValueError):
    """Raised when workaround-ledger inputs cannot be loaded."""


Verdict = Literal["retired", "active", "unknown"]


def _unit_key(unit: UnitRef) -> tuple[str | None, str | None]:
    return unit.lot, unit.serial


def _unit_label(unit: UnitRef) -> str:
    if unit.serial is not None:
        return f"serial {unit.serial}"
    return f"lot {unit.lot}"


def _affected_units(
    defects: DefectDocument, defect_ids: list[str]
) -> tuple[list[UnitRef] | None, list[str]]:
    by_id = {record.defect_id: record for record in defects.records}
    missing = sorted(set(defect_ids) - set(by_id))
    if missing:
        return None, ["referenced defects are missing: " + ", ".join(missing)]
    records = [by_id[defect_id] for defect_id in defect_ids]
    if any(record.affected_units.scope_status == "unknown" for record in records):
        return None, ["affected units are unknown; cannot enumerate"]
    lots = sorted({lot for record in records for lot in record.affected_units.lots})
    serials = sorted({serial for record in records for serial in record.affected_units.serials})
    return (
        [UnitRef(lot=lot) for lot in lots] + [UnitRef(serial=serial) for serial in serials],
        [],
    )


def _matching_application(
    applications: list[WorkaroundApplication],
    workaround_id: str,
    unit: UnitRef,
) -> WorkaroundApplication | None:
    for application in applications:
        if application.workaround_id != workaround_id:
            continue
        if unit.serial is not None and application.unit.serial == unit.serial:
            return application
        if (
            unit.serial is None
            and application.unit.serial is None
            and application.unit.lot == unit.lot
        ):
            return application
    return None


def _matching_disposition(
    dispositions: list[UnitDisposition], unit: UnitRef
) -> UnitDisposition | None:
    key = _unit_key(unit)
    return next(
        (item for item in dispositions if _unit_key(item.unit) == key),
        None,
    )


def _unknown_result(workaround_id: str, reasons: list[str]) -> WorkaroundRetirementResult:
    return WorkaroundRetirementResult(
        workaround_id=workaround_id,
        verdict="unknown",
        reasons=reasons,
        unit_statuses=[],
        open_units=[],
    )


def _status_for(
    application: WorkaroundApplication | None,
    workaround_id: str,
    unit: UnitRef,
) -> UnitStatus:
    if application is None:
        return UnitStatus(unit=unit, state="unmodified", workaround_ids=[])
    state = cast(
        Literal["applied_verified", "applied_unverified", "applied_failed"],
        {
            "pass": "applied_verified",
            "not_recorded": "applied_unverified",
            "fail": "applied_failed",
        }[application.post_work_inspection],
    )
    return UnitStatus(
        unit=unit,
        state=state,
        workaround_ids=[workaround_id],
    )


def evaluate_workaround_retirement(
    *,
    ledger: WorkaroundLedger,
    workaround_id: str,
    defects: DefectDocument,
    rework: ReworkDiff,
    eco_document: EcoDocument,
    eco_id: str,
    eco_check: EcoCheckResult | None,
    eco_check_sha256: str | None,
    eco_check_error: str | None,
    to_graph: DesignGraph,
) -> WorkaroundRetirementResult:
    """Evaluate whether one workaround can be retired."""
    reasons: list[str] = []
    if rework.workaround_id != workaround_id:
        return _unknown_result(
            workaround_id,
            ["rework workaround_id does not match requested workaround"],
        )
    if rework.graph_id != ledger.graph_id:
        reasons.append("rework graph_id does not match ledger graph_id")
    if to_graph.graph_id != ledger.graph_id:
        reasons.append("to graph graph_id does not match ledger graph_id")
    retirement = next(
        (item for item in ledger.retirements if item.workaround_id == workaround_id),
        None,
    )
    affected, unit_reasons = _affected_units(defects, rework.defect_ids)
    if affected is None:
        return _unknown_result(workaround_id, unit_reasons)

    if retirement is None:
        reasons.append("workaround has no retirement record")
    record = next(
        (
            item
            for item in eco_document.ecos
            if retirement is not None and item.eco_id == retirement.eco_id
        ),
        None,
    )
    if retirement is not None and record is None:
        reasons.append("retirement ECO is not present in the ECO document")
    if retirement is not None and record is not None:
        if record.eco_id != eco_id:
            reasons.append("requested ECO ID does not match retirement ECO")
        if workaround_id not in record.retires_workaround_ids:
            reasons.append("retirement ECO does not list the workaround")
        if to_graph.revision != retirement.resolved_revision:
            reasons.append("to graph revision does not match resolved revision")
        defect_reasons = {reason.ref for reason in record.reasons if reason.kind == "defect"}
        missing_defects = sorted(set(rework.defect_ids) - defect_reasons)
        if missing_defects:
            reasons.append("retirement ECO does not cover defects: " + ", ".join(missing_defects))

    statuses: list[UnitStatus] = []
    open_units: list[UnitRef] = []
    for unit in affected:
        application = _matching_application(
            ledger.applications,
            workaround_id,
            unit,
        )
        status = _status_for(application, workaround_id, unit)
        valid_application = application is not None and (
            application.base_revision == rework.base_revision
            and application.derived_revision == rework.derived_revision
        )
        if application is not None and not valid_application:
            reasons.append(f"{_unit_label(unit)} application revisions do not match rework")
        statuses.append(status)
        verified = status.state == "applied_verified" and valid_application
        disposition = _matching_disposition(ledger.unit_dispositions, unit)
        closed_by_disposition = False
        if disposition is not None:
            if disposition.disposition == "scrapped" or (
                retirement is not None and disposition.revision == retirement.resolved_revision
            ):
                closed_by_disposition = True
            else:
                reasons.append(
                    f"{_unit_label(unit)} upgraded_to_revision does not match resolved revision"
                )
        if not verified and not closed_by_disposition:
            open_units.append(unit)

    extra_dispositions = sorted(
        set(_unit_key(item.unit) for item in ledger.unit_dispositions)
        - set(_unit_key(unit) for unit in affected)
    )
    if extra_dispositions:
        reasons.append("unit dispositions include units outside defect scope")

    if retirement is None:
        if open_units:
            reasons.append(
                "open units lack verified workaround application: "
                + ", ".join(_unit_label(unit) for unit in open_units)
            )
        return WorkaroundRetirementResult(
            workaround_id=workaround_id,
            verdict="active",
            reasons=reasons,
            unit_statuses=statuses,
            open_units=open_units,
        )

    if eco_check_error is not None:
        return WorkaroundRetirementResult(
            workaround_id=workaround_id,
            verdict="unknown",
            reasons=[eco_check_error],
            unit_statuses=statuses,
            open_units=open_units,
        )
    if eco_check is None or eco_check_sha256 is None:
        return WorkaroundRetirementResult(
            workaround_id=workaround_id,
            verdict="unknown",
            reasons=["eco-check.json is missing or unavailable"],
            unit_statuses=statuses,
            open_units=open_units,
        )
    if eco_check_sha256 != retirement.eco_check_sha256:
        reasons.append("eco-check.json sha256 does not match retirement record")
    if eco_check.verdict != "closable":
        reasons.append("eco-check verdict is not closable")
    if eco_check.eco_id != retirement.eco_id:
        reasons.append("eco-check ECO ID does not match retirement record")
    if eco_check.to_revision != retirement.resolved_revision:
        reasons.append("eco-check revision does not match retirement record")

    if reasons or open_units:
        if open_units:
            reasons.append(
                "open units lack verified workaround application: "
                + ", ".join(_unit_label(unit) for unit in open_units)
            )
        return WorkaroundRetirementResult(
            workaround_id=workaround_id,
            verdict="active",
            reasons=reasons,
            unit_statuses=statuses,
            open_units=open_units,
        )
    return WorkaroundRetirementResult(
        workaround_id=workaround_id,
        verdict="retired",
        reasons=[],
        unit_statuses=statuses,
        open_units=[],
    )


__all__ = [
    "WorkaroundLedgerError",
    "evaluate_workaround_retirement",
]
