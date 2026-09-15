---
name: acd-library-governance
description: Check declared KiCad footprint and symbol library assets against a deterministic library policy and project library tables. Use when a footprint or symbol library reference is added or changed, or before projecting a board.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - library governance
  - footprint library
  - KiCad library
  - fp-lib-table
  - 部品ライブラリ
  - フットプリント
---

# 部品ライブラリ統治

このSkillはDesign Graphの`library_ref`宣言とKiCadライブラリ資材を、
宣言された`LibraryPolicy`に照合する。出力は`authority="l2_review"`の
L2所見であり、L1ゲートの合否やauthoritative Evidenceを生成・変更しない。
未知、欠落、読めない資材、ハッシュ不一致は合格へ変換せず、`unknown`または
`fail`として記録する。

## CLI

```bash
uv run --script plugins/acd/skills/acd-library-governance/scripts/check_library_governance.py \
  --graph fixtures/golden-design-1/graph.json \
  --policy fixtures/library-policy/gd1-kicad-official.json \
  --project-dir out/gd1/board \
  --out out/library-governance.json
```

`--project-dir`を指定すると、`fp-lib-table`のnicknameとURIも検査する。
出力JSONには入力hash、tool version、`authority: "l2_review"`を記録する。

## 契約と検査

- `LibraryPolicy`は`contracts/library-policy.schema`のPydantic契約である。
- footprint名のglobごとにpad寸法、courtyard、原点、layerを検査する。
- Graphが宣言したfootprint/symbolのsha256 pinningを必要に応じて検査する。
- projectの`fp-lib-table`にGraphが参照するnicknameが無い場合は、
  DRCの`lib_footprint_issues`と同じ欠落として列挙する。
- table URIの出所が`allowed_sources`に無い場合も停止側へ列挙する。

## 境界

このSkillはライブラリ統治のL2レビュー所見だけを返す。所見を設計入力へ
自動反映せず、既存のKiCad ERC/DRC、決定論的L1 gate、Evidence検証、
発注guardを置換しない。ACD coreからこのSkillのPython moduleをimportしない。

## テスト

```bash
uv run pytest plugins/acd/skills/acd-library-governance -q
```
