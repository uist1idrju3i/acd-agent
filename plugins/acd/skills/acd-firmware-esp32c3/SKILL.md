---
name: acd-firmware-esp32c3
description: Develop, build and virtually run ESP32-C3 (ESP-IDF) firmware for an ACD design, with a pin-consistency check against the design graph. Use when firmware work is part of an ACD design task.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - firmware
  - ESP32-C3
  - ESP-IDF
  - QEMU
  - GPIO
---

# ACD firmware (ESP32-C3 / ESP-IDF)

ACD does not gate firmware. Build, static analysis, unit tests, pin
consistency and log expectations are ordinary software development work, so
they are done here with the normal bash/edit/test capability. The design's
pass/fail is still decided only by the ACD electrical and mechanical gates.

## What this skill gives you

Reference implementations in `scripts/`, reusable as-is or as a starting point:

| File | Purpose |
|---|---|
| `fw_project.py` | Projects an ESP-IDF project from the design graph firmware lane; pin macros are generated into `acd_pins.h`, so the graph stays the only source of pin assignments. |
| `fw_build.py` | Runs `idf.py build` / `merge-bin` through the pinned `IDF_PYTHON_ENV_PATH` interpreter and reports toolchain version plus source/artifact hashes. |
| `fw_checks.py` | Cross-checks graph GPIO assignments against the electrical lane pads via a pinned module pad map, and checks the generated header against the graph. |
| `fw_qemu.py` | Builds a flash image, runs QEMU esp32c3 for a bounded time, captures the serial log, and checks boot line, LED toggles and sensor read attempt. |
| `run_fw_pipeline.py` | Runs the whole sequence for Golden Design #1. |

## Usage

```bash
# Full reference pipeline (needs ESP-IDF and qemu-system-riscv32).
uv run python plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py \
    --fixture fixtures/golden-design-1 --out out/gd1-fw

# Skill tests (kept separate from the ACD test suite).
uv run pytest plugins/acd/skills/acd-firmware-esp32c3 -q
```

Requirements: `IDF_PATH` and `IDF_PYTHON_ENV_PATH` for building,
`qemu-system-riscv32` on `PATH` for the virtual run. Both probes fail loudly
when a tool is missing; tests that need the tools skip instead.

## Rules that still apply

- The design graph is the only source of pin assignments. Never edit
  `acd_pins.h` by hand: change the graph and re-project.
- A QEMU log is virtual verification. It never counts as real-device
  measurement evidence; state real-device measurement as unavailable when no
  probe is attached.
- The pinned pad map in `fw_checks.py` covers only the ESP32-C3-MINI-1 pads
  used by Golden Design #1, sourced from the module datasheet. Extend it from
  the datasheet, not from guesses, and keep the citation.
- When you find a firmware check that the ACD gates genuinely need, propose it
  as an ADR before moving it into `packages/`.
