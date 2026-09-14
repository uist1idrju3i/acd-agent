---
name: acd-dfa-review
description: Review design-for-assembly observations from graph, placement, and enclosure declarations. Use for DFA, assembly access, hand soldering, connector order, enclosure effort, and fixture review.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - DFA
  - design for assembly
  - assembly
  - 組立性
  - 手はんだ
  - コネクタ
  - ケーブル組付け
  - 筐体組立
  - 治具
---

# DFAレビュー

このSkillはgraph、配置、筐体形状の宣言から、組立性・作業性・生産性に関する
L2所見を構造化する。所見は設計の操舵・停止にだけ使い、合否やEvidenceには使わない。
未知、未宣言、破損した入力はunknownとして報告し、情報を推測しない。

## CLI

```bash
uv run --script plugins/acd/skills/acd-dfa-review/scripts/dfa_review.py \
  --graph fixtures/golden-design-1/graph.json \
  --out out/dfa-review
```

任意の配置reportは`--placement-report`で渡す。出力は`dfa-review.json`と
`dfa-review.md`であり、JSONにはgraph revision、入力hash、tool versionを記録する。

## 観点

- 極性部品の向きの統一
- 片面実装可否
- 手はんだ部品へのアクセス
- コネクタとケーブルの組付け順序
- 筐体組立の工数
- 治具の要否

`rules/dfa_rules.json`は手はんだclearanceのスクリーニング閾値を保持する。これは
合否閾値ではなく、詳細な製造性解析を促すためのSkillデータである。

## 制約

この結果は`record_class="L2"`であり、既存のERC、DRC、機械ゲート、独立再読込、
発注ガードを変更しない。`info`であっても設計合格を意味しない。

## テスト

```bash
uv run pytest plugins/acd/skills/acd-dfa-review -q
```
