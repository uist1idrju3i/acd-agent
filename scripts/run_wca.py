#!/usr/bin/env python3
"""Run the opt-in deterministic worst-case analysis estimate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from acd.core.wca import WcaInputError, evaluate_wca
from acd.schema import (
    DesignGraph,
    SpiceResult,
    ToleranceTable,
    UseEnvironment,
    WcaRequest,
    WcaResult,
)


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _markdown(result: WcaResult) -> str:
    lines = [
        "# Worst-case analysis",
        "",
        "見積（estimate）・発注権限なし",
        "",
        f"- status: `{result.status}`",
        "- composition: `bias_sum_plus_rss`",
        "",
        "| quantity | nominal | bias total (%) | random RSS (%) | worst low | "
        "worst high | status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for quantity in result.quantities:
        lines.append(
            "| "
            + " | ".join(
                (
                    quantity.quantity_id,
                    _optional_value(quantity.nominal),
                    _optional_value(quantity.bias_total_pct),
                    _optional_value(quantity.random_rss_pct),
                    _optional_value(quantity.worst_low),
                    _optional_value(quantity.worst_high),
                    quantity.status,
                )
            )
            + " |"
        )
        for component in quantity.bias_components:
            lines.append(
                f"  - bias `{component.source_refdes}` "
                f"{component.kind}: {component.value_pct}%"
            )
        for component in quantity.random_components:
            lines.append(
                f"  - random `{component.source_refdes}` "
                f"{component.kind}: {component.value_pct}%"
            )
        for finding in quantity.findings:
            lines.append(f"  - finding: {finding}")
    lines.extend(
        (
            "",
            "公差表・環境条件・変動源の分類と合成方法はJSON結果のhashおよび"
            "component一覧に記録する。WCAはauthoritative Evidenceではない。",
            "",
        )
    )
    return "\n".join(lines)


def _optional_value(value: object) -> str:
    return "" if value is None else str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--tolerance-table", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--spice-result", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()
    try:
        graph = DesignGraph.model_validate(_read_json(args.graph))
        request = WcaRequest.model_validate(_read_json(args.request))
        table = ToleranceTable.model_validate(_read_json(args.tolerance_table))
        environment = UseEnvironment.model_validate(_read_json(args.environment))
        spice_result = (
            SpiceResult.model_validate(_read_json(args.spice_result))
            if args.spice_result is not None
            else None
        )
        result = evaluate_wca(graph, request, table, environment, spice_result)
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        WcaInputError,
    ) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    if args.out_md is not None:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(_markdown(result), encoding="utf-8")
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
