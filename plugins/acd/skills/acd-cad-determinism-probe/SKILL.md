---
name: acd-cad-determinism-probe
description: Measure whether STEP and 3MF exports from the CAD kernel are byte-identical across runs and which normalization rule makes them comparable. Use when investigating CAD output hashes or updating build123d / cadquery-ocp.
---

# CAD出力の決定性測定

ACD本体のプローブはツールの有無と版だけを見る。出力バイト列の決定性測定はこのSkillが持つ。
測定は記録であり、設計の合否ではない。合否はACDの決定論的ゲート（ERC/DRC、機械ゲート、
独立再読込）だけが決める。

## できること

- `scripts/cad_determinism_probe.py`: 同一の立体をSTEPと3MFで2回出力し、生バイト列のhashと
  `acd_core.cad_normalize`で正規化したあとのhashを比較する。差分の内容と、それを除去する
  正規化規則を併記する。

## 使い方

```bash
uv run python plugins/acd/skills/acd-cad-determinism-probe/scripts/cad_determinism_probe.py
```

JSONを標準出力へ書く。測定値を文書へ残す場合は取得時点とツール版を添える。記録先は
[`../../../../docs/tool-capability-probes.md`](../../../../docs/tool-capability-probes.md)である。

## 前提と限界

- `build123d`と`cadquery-ocp`が必要である。未インストールならimportに失敗する。
- STEPのFILE_NAMEタイムスタンプは秒精度のため、測定は1回の実行に約1秒の待ちを含む。
- 測定はこの環境のツール版に対する観測であり、別版・別OSの結果を保証しない。
- この結果はACDの設計ゲートの合否ではない。

## テスト

```bash
uv run pytest plugins/acd/skills/acd-cad-determinism-probe -q
```

Skillのテストは本体のテスト（`uv run pytest`）とは別に実行する。
