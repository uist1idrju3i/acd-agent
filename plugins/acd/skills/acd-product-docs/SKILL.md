---
name: acd-product-docs
description: Generate deterministic product, interface, and shipping inspection documents from the design graph and recorded projections. Use when product documentation or a shipping inspection sheet is requested for a design.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - product readme
  - product description
  - instruction manual
  - user manual
  - generated document
  - shipping inspection
  - 出荷検査
  - 製品説明
  - 取扱説明書
---

# ACD product documents

Generate publication documents from the design graph, the recorded visual
projections and the generated firmware pin projection. The documents are L3
observations: they present values that already exist in the design inputs, they
cannot approve a design, and they never flow back into design inputs.

Text templates are stored in `templates/ja.json` and `templates/en.json`.
All generators accept `--lang ja|en` (default `ja`); Japanese output remains
directly under `--out-dir`, while English output is written under
`--out-dir/en/`. Labels are translated by the templates, but graph-derived
values, identifiers, units, revisions, hashes, and projection metadata are
always emitted verbatim.

| Script | Purpose |
| --- | --- |
| `doc_inputs.py` | Loads graph, projection sets and images fail-closed, and writes the provenance record. |
| `generate_product_readme.py` | Renders the product description README with an overview, evidence-relation note, requirements, specifications, firmware behavior, BOM, grouped figures, an optional theme-song projection and attribution. |
| `generate_instruction_manual.py` | Renders the instruction manual from the graph and the `acd_pins.h` pin projection. |
| `generate_interface_spec.py` | Projects the device interface contract (GPIO table, I2C address table, UART log lines, command list) as `interface-spec.md` and `interface-spec.json` from the graph, `acd_pins.h`, and `firmware-config-report.json`. Undeclared aspects are marked `unknown`. |
| `generate_shipping_inspection.py` | Projects the L3 shipping inspection document (`shipping-inspection.md` and `shipping-inspection.json`) from the graph, `acd_pins.h`, and `firmware-config-report.json`. Criteria come only from graph attributes, gate thresholds, or firmware projections; unavailable criteria are emitted as `unknown` for human decision. |
| `generate_bringup_plan.py` | Re-projects the 18.4 shipping inspection contract as the milestone-5 bring-up checklist (`bringup-test-plan.md` and `bringup-test-plan.json`), including measurement templates, instruments, stop-on-fail phases, probe points, optional inspection sequence, and feedback-rule coverage. |
| `generate_work_instruction.py` | Projects a fail-closed L3 workaround work instruction, required parts/tools, ordered rework and firmware steps, graph-diff highlight, and post-work inspection from a salvageable 13.3 result. |
| `generate_quality_report.py` | Projects the inspection report, traceability report, and machine-readable `quality-report.json` from authoritative lane Evidence, rationale coverage reports, design-predicate observations, the DFM report, and the fixture rationale. Non-authoritative Evidence or any revision/graph mismatch fails closed. |
| `generate_review_package.py` | Projects `review-package.md`, `review-package.json`, and `graph-diff.json` from the graph, recorded visual projections, design predicates, DFM observations, and an explicitly declared previous revision. The graph diff contract is defined by `acd.schema.graph_diff`; the package is L3 with no authority. |
| `generate_idea_allocation_docs.py` | Projects the idea record (`idea-record.md`), the rough estimate (`rough-estimate.md`/`.json`), the responsibility allocation (`responsibility-allocation.md`/`.json`), and a cross-domain block diagram SVG from the graph, idea record, estimate catalog, and responsibility declaration. Declaration/idea mismatches fail closed; a failing responsibility gate still renders with its findings. |

## Usage

```bash
# Product description README. Pass every recorded projection set of the loop
# (board + firmware + mechanical lanes) so the figures section covers all
# domains, and add --theme-song-projection when the design loop recorded a
# theme-song projection for the same graph and revision.
uv run --script plugins/acd/skills/acd-product-docs/scripts/generate_product_readme.py \
    --graph fixtures/golden-design-1/graph.json \
    --projections out/gd1/visual-projections-electrical.json \
                  out/gd1/visual-projections-layout.json \
                  out/gd1/visual-projections-system.json \
                  out/gd1/visual-projections-firmware.json \
                  out/gd1-enclosure/visual-projections-mechanical.json \
    --theme-song-projection out/gd1/theme-song-projection.json \
    --out-dir out/docs

# Instruction manual.
uv run --script plugins/acd/skills/acd-product-docs/scripts/generate_instruction_manual.py \
    --graph fixtures/golden-design-1/graph.json \
    --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
    --out-dir out/docs

# Device interface spec (JSON + Markdown).
uv run --script plugins/acd/skills/acd-product-docs/scripts/generate_interface_spec.py \
    --graph fixtures/golden-design-1/graph.json \
    --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
    --firmware-config-report out/gd1-fw/firmware-config-report.json \
    --out-dir out/docs

# Shipping inspection document (JSON + Markdown).
uv run --script plugins/acd/skills/acd-product-docs/scripts/generate_shipping_inspection.py \
    --graph fixtures/golden-design-1/graph.json \
    --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
    --firmware-config-report out/gd1-fw/firmware-config-report.json \
    --out-dir out/docs

# Bring-up test plan (JSON + Markdown).
uv run --script plugins/acd/skills/acd-product-docs/scripts/generate_bringup_plan.py \
    --graph fixtures/golden-design-1/graph.json \
    --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
    --firmware-config-report out/gd1-fw/firmware-config-report.json \
    --feedback-policy fixtures/feedback/policy.json \
    --out-dir out/docs

# Workaround work instruction and post-work inspection (JSON + Markdown).
uv run --script plugins/acd/skills/acd-product-docs/scripts/generate_work_instruction.py \
    --graph fixtures/golden-design-1/graph.json \
    --defects fixtures/defect/sample/defects.json \
    --rework fixtures/rework/sample/rework.json \
    --dfa fixtures/rework/sample/rework-dfa.json \
    --salvage-dir out/workaround \
    --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
    --firmware-config-report out/gd1-fw/firmware-config-report.json \
    --out-dir out/docs

# Quality documents (inspection report + traceability report + JSON).
uv run --script plugins/acd/skills/acd-product-docs/scripts/generate_quality_report.py \
    --graph fixtures/golden-design-1/graph.json \
    --evidence out/gd1/evidence-electrical.json \
    --evidence out/gd1-enclosure/evidence-mechanical.json \
    --evidence out/gd1-fw/evidence-firmware.json \
    --rationale-coverage out/gd1/rationale-coverage.json \
    --rationale-coverage out/gd1-enclosure/rationale-coverage.json \
    --rationale fixtures/golden-design-1/rationale.json \
    --design-predicates out/gd1/gate-evidence/design-predicates.json \
    --dfm-report out/gd1/fab/dfm-report.json \
    --out-dir out/docs

# Idea refinement and responsibility-allocation documents (L3).
uv run --script plugins/acd/skills/acd-product-docs/scripts/generate_idea_allocation_docs.py \
    --graph fixtures/responsibility/sample/graph.json \
    --idea fixtures/idea/sample-usb-thermometer/idea.json \
    --estimate-catalog fixtures/idea/sample-usb-thermometer/estimate-catalog.json \
    --responsibility fixtures/responsibility/sample/responsibility.json \
    --out-dir out/docs \
    --base-dir .

# Shared input loader module (dependency self-resolution check).
uv run --script plugins/acd/skills/acd-product-docs/scripts/doc_inputs.py

# Review package. Declare either --previous-graph or --no-previous-revision.
uv run --script plugins/acd/skills/acd-product-docs/scripts/generate_review_package.py \
    --graph fixtures/golden-design-1/graph.json \
    --projections out/gd1/visual-projections-electrical.json \
    --design-predicates out/gd1/gate-evidence/design-predicates.json \
    --dfm-report out/gd1/fab/dfm-report.json \
    --no-previous-revision \
    --out-dir out/docs \
    --base-dir out

# Skill tests (kept separate from the ACD test suite).
uv run pytest plugins/acd/skills/acd-product-docs -q
```

## Analysis result inputs

品質文書とレビュー資料へ解析結果を取り込む場合は、各generatorへ
`--analysis <JSON-or-directory>`を指定する（複数指定可）。入力は
`artifact_kind`で識別され、次の6種類をサポートする。

- `spice_result`
- `pdn_result`
- `wca_result`
- `thermal_result`
- `fem_result`
- `firmware_analysis_result`

各入力は`acd.schema`のstrict modelで検証され、文書対象の`graph_id`と`revision`へ一致する
必要がある。不正JSON、schema違反、重複、graph／revision不一致はfail-closedで生成を止める。
ファイルが無い種類はエラーにせず、品質文書・レビュー資料の固定6行に`未実施`（英語は
`not executed`）として明示し、passを推測しない。

解析結果はL2/L3のprovisional `estimate`またはnested `observation`であり、L1 verdictや
authoritative Evidenceを変更しない。quality reportでは測定値、status、authority、tool
version、input hash、fail／unknownの停止側所見を表示する。review packageでは
`analysis/`にraw JSONをbyte-preservingでコピーし、`analysis-summary.md`、hash manifest、
6種類のchecked／unchecked checklist項目を生成する。結果ファイルのhashとartifact kindは
document provenanceにも記録される。`--lang ja`と`--lang en`は同じ契約で、見出しと
not-executed表記だけがtemplate catalogにより切り替わる。

`--script`はPEP 723のメタデータから依存を自己解決します。ローカルcheckoutで
開発する場合は、従来どおり`uv run python <path>`を使用します。

Both generators write the document plus a `<document>.provenance.json` record
that carries the input hashes, the template id, the generator script hash and
the target revision. The template path, hash, and language are also recorded
and the template participates in the provenance inputs. Documents contain no
timestamp, so reruns with identical inputs produce byte-identical output.

Shipping inspection documents are L3 observations and never constitute
authoritative shipping approval Evidence. A criterion is emitted only when its
value is declared by the graph, a gate threshold, or a firmware projection;
otherwise the row is `unknown` and requires a human decision. Japanese output
is the default and `--lang en` writes the English tree with the same provenance
contract.

The instruction manual derives sections from graph declarations: firmware actions
control capability text, pin assignments control wiring and flashing details,
and every declared mechanical connector opening is rendered in node-id order.
When a declared capability lacks its generated macro, generation fails closed
with the missing macro named. Undeclared capabilities are omitted rather than
estimated, and the Japanese document records each omission and reason under
`## 省略した項目`.

`run_design_loop` invokes both generators in its `projection-docs` stage after
the visual-review manifest. The stage writes these documents and provenance
records under `out/docs/`, together with a flat `hashes.json`. The manual CLI
above remains available when an operator needs to regenerate the documents
independently.

Generation stops instead of reporting "no problem" when an input is missing or
inconsistent: an invalid graph, a projection set from another revision, a
projection whose regeneration check is not `reproduced`, a missing projection
image, a theme-song projection for another graph or revision, a theme-song
MIDI artifact that is missing or whose sha256 differs from the declared hash,
a pin projection for another revision, or a macro required by a graph-declared
capability missing from `acd_pins.h` all fail closed. When `--theme-song-projection` is not given, the
README omits the theme-song section and notes the undeclared input in the
evidence-relation section; the projection path is never guessed.

Review-package generation additionally fails closed when previous-revision mode
is missing or declared more than once, graph identity or revision differs,
predicate/DFM revisions differ, or review inputs are malformed or unavailable.
