---
name: acd-qc-seven-tools
description: Apply QC seven tools (Q7) and new QC seven tools (N7) to ACD design findings — Pareto ranking, stratification, cause candidates, tree and matrix diagrams. Use when organizing ERC/DRC, DFM, review, or measurement findings before deciding what to fix first.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - Pareto
  - QC seven tools
  - stratification
  - DFM findings
  - root cause
---

# Q7／N7による所見の整理

Q7は件数・測定値などの数量データ、N7は要求・意見・計画などの言語データを扱う。手法の定義と
ACDでの入力は[`../../../../docs/qc-tools.md`](../../../../docs/qc-tools.md)を正とする。
このSkillは所見の整理と優先度付けだけを行う。合否はACDの決定論的ゲート（ERC/DRC、機械ゲート、
独立再読込）だけが決める。図表や傾向を原因の確定にも合格根拠にも使わない。

## できること

- `scripts/qc_analysis.py`
  - `pareto(findings, field="category")`: 所見を件数降順で順位付けし、比率と累積比率を返す。
    同数はカテゴリ名昇順で決めるため出力は再現する。
  - `stratify(findings, by=..., field="category")`: 工程、rule ID、部品、variant、fab profile、
    ライブラリcommitなどで層別し、層ごとのカテゴリ件数を返す。
  - CLIとしても使える。所見のJSON配列を渡すとパレート順位をJSONで返す。

```bash
uv run python plugins/acd/skills/acd-qc-seven-tools/scripts/qc_analysis.py findings.json
```

所見1件は少なくとも集計軸のフィールドを持つオブジェクトである（例:
`{"category": "clearance", "stage": "drc", "refdes": "U1"}`）。フィールドが欠けていれば
例外で停止する（fail-closed）。

## 手順

1. ゲート出力とレビュー所見をJSON配列へ正規化する。出所（ツール名、版、入力hash）を添える。
2. `stratify()`で工程・rule ID・部品などに層別し、自動ゲートで検出できない設計意図の誤りは
   別の層として集計する。
3. `pareto()`で優先度を出し、上位カテゴリだけを是正の候補にする。
4. N7（親和図、系統図、マトリックス図、PDPC）で原因候補と是正計画を自然文で整理する。
5. 是正後は再投影して決定論的ゲートを再実行する。Q7の改善傾向を合格根拠にしない。

## 前提と限界

- 追加の外部ツールは不要である。標準ライブラリだけで動く。
- 数量が不足する場合は傾向を断定せず`unknown`または参考として扱う。
- 管理図、ヒストグラム、散布図、マトリックス・データ解析法は十分なサンプルが必要であり、
  少数の所見に適用しない。
- パレートの上位は「件数が多い」ことしか示さない。重大度や安全影響は別に扱う。
- この Skill の結果はACDの設計ゲートの合否ではない。

## テスト

```bash
uv run pytest plugins/acd/skills/acd-qc-seven-tools -q
```

Skillのテストは本体のテスト（`uv run pytest`）とは別に実行する。
