# ADR-0016: 決定論的ゲート結果によるcritic反復

- **状態**: Accepted
- **日付**: 2026-08-18

## 決定

P3aではOpenHands SDK v1.42.1の`CriticBase`と
`IterativeRefinementConfig`を反復制御だけに採用し、`AcdGateCritic`を
`acd-tools`へ追加する。合否はACDの決定論的成果物だけで決まり、events、
`git_patch`、LLMの発言や軌跡はスコアへ影響しない。

criticのスコアは`0.0`または`1.0`だけとする。全要件が満たされた場合だけ
`1.0`、欠落、parse失敗、schema不一致、stale、unknown、status不一致、
revision解決不能のいずれかがあれば`0.0`を返す。中間値は部分合格に見える
数値を生み、SDKの`CriticResult.THRESHOLD=0.5`とも意味が衝突するため採用しない。
既定の反復設定は`success_threshold=1.0`、`max_iterations=3`である。

## revisionとEvidence

ACDの`target_revision`はgit SHAではなく、設定されたDesign Graphの
`graph.revision`（例:`r1`）である。criticとhooksはDesign Graphを
`DesignGraph`として検証し、そのrevisionを`Evidence.supports_pass()`へ渡す。
gitはrevision値への変換には使わず、設計入力がcleanであることの判定だけに使う。
graphを読めない、schema違反、gitが使えない、またはgraph.jsonを含む
`fixtures/**/graph.json`・`profiles/**`の設計入力がdirtyならfail-closedとする。
`out/`とEvidence成果物の差分は設計入力のdirty判定から除外する。

P1のorder hookも同じrevision意味論へ統一し、有効なEvidenceに出口を与える。
ゲート閾値、Evidence契約、保護対象、fail-closed規則は変更しない。

## 要件

`AcdGateCritic`は`Evidence`要件では指定されたpathと`evidence_id`を検証し、
`Evidence.supports_pass(current_revision)`を唯一の判定手段とする。製造packageと
order-readinessのmanifest要件では`status`、全gate、`unknowns`を検査し、
未達要件を決定論的順序でmessageとmetadataへ記録する。

## SDK境界

`CriticBase`は反復の再試行だけを提供し、criticのmessageは修正対象を示す
操舵信号である。`get_followup_prompt()`は未達要件、ゲート・閾値・Evidenceを
書き換えて通してはならないこと、critic出力はpass evidenceではないことを明示する。
critic出力そのものはpass evidenceではなく、最終判定は引き続きEvidenceと
決定論的製造ゲートが担う。
