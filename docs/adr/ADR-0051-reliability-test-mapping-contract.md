# ADR-0051: 信頼性試験対応表契約と被覆ゲート

> ステータス: Accepted
> 日付: 2026-09-14
> 関連: [`ADR-0023-deterministic-gate-authority.md`](ADR-0023-deterministic-gate-authority.md)、[`ADR-0028-execution-provenance.md`](ADR-0028-execution-provenance.md)、[`../roadmap-future.md`](../roadmap-future.md)

## コンテキスト

EMC、環境、機械的な信頼性試験は、規格の本文を再現することではなく、規格項目が
模擬する実使用stressと製品の設計要求を対応付ける必要がある。試験項目だけを記録すると、
実使用環境の未被覆、過剰試験、出所不明の背景を合格側へ取り込む危険がある。

## 決定

1. 対応表はDesign Graph nodeではなく、`ReliabilityTestPlan`として独立したopt-in
   contractとする。plan、graph、`UseEnvironment`は`graph_id`と`revision`を一致させる。
2. 各試験項目は`source_reference`を持つ。値は`identifier`、`edition`、`kind`からなり、
   `kind`は`standard`、`incident_report`、`internal_analysis`、`datasheet`のいずれかと
   する。背景記述は項目が存在する理由と出所から導いた根拠を説明する。
3. 規格本文や再配布可能な抜粋はcontractへ保存しない。識別子と版だけを保存し、本文の
   取得・解釈は契約外とする。
4. 実使用stressは試験項目の`covers`／`over`または明示的なaccepted gapで被覆する。
   被覆なし、`under`、環境との不一致、出所不足、predicate resultの未実行は停止条件であり、
   unknownまたはfailをpassへ変換しない。`over`項目は記録するだけで別の失敗を緩和しない。
5. 寿命モデルは推定値であり、計算結果へ`authority: "estimate"`を付ける。推定は
   authoritative Evidence、認証適合、合否verdictの根拠にしない。
6. measured Evidenceは条件、設備、日時、供試体revisionを必須とし、planのrevisionと一致
   する場合だけschema上受け付け、結果は観測として記録する。不足metadataまたはrevision
   不一致は入力をrejectし、合格側へ進めない。
7. 本contractは規格適合や認証verdictを行わない。resultの`certification_claim`は常に
   `false`とする。

## 結果

`environment_consistency`、`stress_coverage`、`test_item_provenance`、
`design_requirement_linkage`、`lifetime_estimate`、`measured_evidence`を独立に評価する。
statusの優先順位は`fail > unknown > pass`である。planを宣言しないGD1を含む既存経路は、
このopt-in gateの導入によって変更されない。
