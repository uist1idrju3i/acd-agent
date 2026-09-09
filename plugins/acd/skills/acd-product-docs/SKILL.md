---
name: acd-product-docs
description: Generate deterministic product description and instruction manual documents from the design graph and recorded projections.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - product readme
  - product description
  - instruction manual
  - user manual
  - generated document
  - 製品説明
  - 取扱説明書
---

# ACD product documents

Generate publication documents from the design graph, the recorded visual
projections and the generated firmware pin projection. The documents are L3
observations: they present values that already exist in the design inputs, they
cannot approve a design, and they never flow back into design inputs.

| Script | Purpose |
| --- | --- |
| `doc_inputs.py` | Loads graph, projection sets and images fail-closed, and writes the provenance record. |
| `generate_product_readme.py` | Renders the product description README with an overview, evidence-relation note, requirements, specifications, firmware behavior, BOM, grouped figures, an optional theme-song projection and attribution. |
| `generate_instruction_manual.py` | Renders the instruction manual from the graph and the `acd_pins.h` pin projection. |

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

# Shared input loader module (dependency self-resolution check).
uv run --script plugins/acd/skills/acd-product-docs/scripts/doc_inputs.py

# Skill tests (kept separate from the ACD test suite).
uv run pytest plugins/acd/skills/acd-product-docs -q
```

`--script`はPEP 723のメタデータから依存を自己解決します。ローカルcheckoutで
開発する場合は、従来どおり`uv run python <path>`を使用します。

Both generators write the document plus a `<document>.provenance.json` record
that carries the input hashes, the template id, the generator script hash and
the target revision. Documents contain no timestamp, so reruns with identical
inputs produce byte-identical output.

Generation stops instead of reporting "no problem" when an input is missing or
inconsistent: an invalid graph, a projection set from another revision, a
projection whose regeneration check is not `reproduced`, a missing projection
image, a theme-song projection for another graph or revision, a theme-song
MIDI artifact that is missing or whose sha256 differs from the declared hash,
a pin projection for another revision, or a missing macro in
`acd_pins.h` all fail closed. When `--theme-song-projection` is not given, the
README omits the theme-song section and notes the undeclared input in the
evidence-relation section; the projection path is never guessed.
