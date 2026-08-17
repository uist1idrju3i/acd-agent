# ADR-0016: 決定論的ゲート結果によるcritic反復

> ステータス: Accepted
> 日付: 2026-08-17

## 決定

現行ではOpenHands SDK v1.42.1の`CriticBase`と`IterativeRefinementConfig`を反復制御だけに
採用し、`AcdGateCritic`を`acd-tools`へ追加する。criticは[`ADR-0023`](ADR-0023-deterministic-gate-authority.md)
のL2操舵であり、合否を判定しない。合否はACDの決定論的成果物だけで決まる。

criticのスコアは0.0または1.0だけとする。全要件が満たされた場合だけ1.0、欠落、parse
失敗、schema不一致、stale、unknown、status不一致、revision解決不能のいずれかがあれば
0.0を返す。既定の反復設定は`success_threshold=1.0`、`max_iterations=3`である。

## revisionとEvidence

`target_revision`はDesign Graphの`graph.revision`（例:`r1`）であり、git SHAではない。
`Evidence.supports_pass(revision)`を唯一の判定手段とする。graphを読めない、schema違反、
gitが使えない、または設計入力がdirtyならfail-closedとする。

criticのmessageは修正対象を示す操舵信号であり、ゲート、閾値、Evidenceを変更しては
ならない。critic出力そのものはpass evidenceではない。
