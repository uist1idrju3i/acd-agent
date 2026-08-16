---
name: acd-reliability-review
description: Screen a design against reliability practices — derating and part stress analysis, worst-case analysis, single point of failure review, and evidence validity. Use when reviewing margins before ordering or when a rule table's validity domain is in question.
---

# 信頼性設計のスクリーニング

手法の定義、出典、適用区分は[`../../../../docs/reliability-practices.md`](../../../../docs/reliability-practices.md)を正とする。
このSkillはスクリーニングと所見の整理だけを行う。設計の合否はACDの決定論的ゲート（ERC/DRC、
機械ゲート、独立再読込、発注ガード）だけが決める。基準表の推奨値は合否ではなくスクリーニングで
あり、有効域を外れた入力は不合格ではなく「要詳細解析」として扱う。

## できること

- `scripts/derating_check.py`
  - `evaluate(items)`: 部品ごとの定格、基準表のディレーティング係数、公差と環境を織り込んだ
    最悪値ストレス、基準表の有効域を入力に、`pass`／`needs_analysis`／`fail`の三値で判定する。
  - 定格・係数・条件が不明、または有効域外の入力は`needs_analysis`とし、合格にしない。
  - CLIとしても使える。

```bash
uv run python plugins/acd/skills/acd-reliability-review/scripts/derating_check.py stresses.json
```

入力1件の例:

```json
{
  "refdes": "C1",
  "parameter": "voltage",
  "rating": 16.0,
  "derating_factor": 0.5,
  "applied_worst_case": 5.5,
  "conditions": { "ambient_c": 45.0 },
  "validity_domain": { "ambient_c": [-40.0, 85.0] }
}
```

## 手順

1. ディレーティング基準表を版管理された入力として用意する。固定値をスクリプトへ埋め込まない。
2. 公称値ではなく公差上限と環境条件を織り込んだ最悪値でストレスを算出する。
3. `evaluate()`で三値判定を得る。`fail`は設計変更、`needs_analysis`は解析Evidenceで閉じる。
4. 単一故障点、波及故障、保護素子、絶縁、ESD、EMCの観点は文書のチェック項目で自然文の所見に
   まとめる。
5. 設計変更が起きたら解析をやり直す。古い解析結果を根拠にしない。

## 前提と限界

- 追加の外部ツールは不要である。標準ライブラリだけで動く。
- 入力の定格・係数・最悪値の妥当性は検証しない。出所（データシート版、基準表の版、取得時点）を
  添えるのは呼び出し側の責務である。
- 熱モデル、回路シミュレーション、実測は行わない。`needs_analysis`はそれらの解析を要求する印である。
- 検証された範囲外への外挿は行わない。
- この Skill の結果はACDの設計ゲートの合否ではない。

## テスト

```bash
uv run pytest plugins/acd/skills/acd-reliability-review -q
```

Skillのテストは本体のテスト（`uv run pytest`）とは別に実行する。
