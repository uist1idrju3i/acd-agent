---
name: acd-contracts
description: How to read and validate ACD Pydantic contracts in this workspace. Use when creating or checking ACD documents.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - contract
  - Pydantic
  - design graph
  - schema validation
  - 契約
  - スキーマ
---

# ACD contracts

- Pydantic models in `src/acd/schema` are the canonical contract.
- Contract-bearing documents carry the fields defined by their Pydantic model.
- `unknown` values are allowed but fail-closed: they never support a pass verdict.
- Design decisions are recorded in the typed `rationale.json` contract.
- Validate documents with:

```bash
uv run pytest tests/schema -q
```

Validate rationale coverage with:

```bash
uv run python scripts/check_rationale.py \
  --graph fixtures/<design>/graph.json \
  --rationale fixtures/<design>/rationale.json
```

## Adding a parts catalog entry

Create `entry.json` with `library_ref` and omit `symbol_sha256` and
`footprint_sha256`. Run the registration inside the locked image so the
container can resolve and hash its KiCad library files:

```bash
uv run python scripts/run_in_workspace.py --repo "$PWD" \
  'uv run python scripts/register_part_catalog_entry.py --entry entry.json --pin-hashes --dry-run --pinned-entry-out entry.pinned.json'
uv run python scripts/run_in_workspace.py --repo "$PWD" \
  'uv run python scripts/register_part_catalog_entry.py --entry entry.json --pin-hashes --pinned-entry-out entry.pinned.json'
```

The mounted repository makes the catalog write land in the checkout. Never
edit `contracts/parts-catalog.json` by hand. Commit the catalog change and open
a pull request; `--allow-dirty` does not cover `contracts/`. Registration is a
declaration, not evidence.

For JLCPCB BOM/CPL output, every component with `assembly: "fitted"` must declare
an `lcsc` part number. Declare hand-soldered or otherwise off-BOM parts as not
fitted so they are excluded from the JLCPCB BOM and CPL:

```json
{ "refdes": "J1", "assembly": "not_fitted", "jlcpcb_class": "none" }
```

## Verify an LCSC number right after declaring it

Fetch the LCSC response immediately after declaring a part number and compare
the record's `Manufacturer Part` with the declared MPN:

```bash
uv run python scripts/fetch_lcsc_footprint_orientation.py \
  --refdes D1 \
  --lcsc C12624 \
  --expect-mpn <mpn> \
  --out evidence/cpl-orientation/<graph_id>/D1.json
```

Check the existing `cpl_rotation_record_path` layout before selecting the
output path. Read the summary line; exit code `2` means the number is a typo
or identifies a different part, so correct the spec and re-fetch. The
`evidence.cpl_rotation.mpn_mismatch` stop reports the same content mismatch
when the CPL declaration is preflighted.

For catalog-less parts, searching or browsing LCSC/JLCPCB is an L2 activity.
Record the selected part as a declaration plus a fetched record, never as a
hand-written record.
