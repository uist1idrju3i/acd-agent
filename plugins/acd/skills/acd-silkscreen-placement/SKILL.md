---
name: acd-silkscreen-placement
description: Resolve silkscreen label positions for an ACD board by deterministic perimeter search, recording accepted and rejected candidates as evidence. Use when functional labels must be positioned before the board projection and DRC.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - silkscreen
  - label placement
  - board edge
  - footprint clearance
  - DRC
---

# Silkscreen label placement search

The ACD core does not search for silkscreen text. It only extracts graph
declarations with `acd.core.silkscreen.extract_silkscreen_lane`; this Skill
performs placement search. Its output is candidate data, while deterministic
ACD gates (DRC and independent reload) decide acceptance.

## Capabilities

- `scripts/silkscreen_search.py` scans around the declared datum (the board
  outline or a referenced footprint) using the declared order, step, and
  limit. It considers 0/90/180/270-degree rotations.
- It uses measured context values and rejects candidates that overlap pads,
  mask openings, existing footprint silk, fixed silk, same-side body or
  courtyard geometry, or the board-edge margin. A candidate is also rejected
  when its nearest component is not the declared reference. Every rejection is
  retained with a reason in the evidence, and no candidate is a fail-closed
  result.
- Candidates are ordered by distance to the datum, then declaration order,
  rotation order, courtyard overlap area, and offset. Text roles beginning
  with `functional_label_`, plus `connector_identifier`, `board_type`, and
  `board_part_number`, are search targets. This includes backside branding and
  identification text: `B.SilkS` is retained as the layer, while the position
  is selected by the same deterministic search and measured-clearance gates as
  other search targets.
- Other text roles are not search targets and must carry declared coordinates.
  Missing coordinates for such a role fail closed; a provisional coordinate is
  never acceptance evidence.

## Usage

```python
import sys

sys.path.insert(0, "plugins/acd/skills/acd-silkscreen-placement/scripts")

uv run --script plugins/acd/skills/acd-silkscreen-placement/scripts/silkscreen_search.py --input silkscreen-input.json --output silkscreen-output.json

resolved = resolve_silkscreen_placements(lane, board_projection.model)
```

`--script` resolves dependencies from the PEP 723 metadata. Use
`uv run --script <path>` for PEP 723 scripts, including local checkouts.

`lane` is the result of `extract_silkscreen_lane()`, and
`board_projection.model` is the `BoardModel` after placement resolution. The
reference implementation is `scripts/run_gd1_pipeline.py`.

## Assumptions and limits

- No additional external tool is required; the script imports `acd-core`.
- Text geometry is conservatively estimated from glyph advance, stroke width,
  descenders, and rotation, and does not understate measured projection
  geometry. It does not replace final Gerber measurement.
- Component rotations are limited to 0/90/180/270 degrees.
- This Skill's result is not an ACD design-gate result.

## Tests

```bash
uv run pytest plugins/acd/skills/acd-silkscreen-placement -q
```

Run Skill tests separately from the ACD core tests (`uv run pytest`).
