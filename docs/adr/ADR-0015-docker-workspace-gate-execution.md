# ADR-0015: DockerWorkspaceによるゲート実行

> ステータス: Accepted
> 日付: 2026-08-17

## 決定

決定論的ゲートの実行環境を`DockerWorkspace(server_image=...)`へ一本化する。
`server_image`にはDockerが受け付けるdigest参照（`...@sha256:<digest>`）を渡し、digestを
解決できないEvidenceは合否根拠にしない。ホスト実行は参考実行であり、合格側Evidenceを
生成しない。

`DockerDevWorkspace(base_image=...)`はACD tools imageからagent-server imageをbuildする
準備経路に限定し、ゲートの既定経路にしない。imageは配布せず、利用者がbuildしてdigest
を記録する。KiCadとFreeRoutingのGPL頒布義務を回避するためである。

Dockerはdeterminismを保証しない。timestamp、locale、filesystem、CPU、APT repositoryの
差は残るため、ToolEnvelope、入力・出力hash、timestamp正規化、独立再読込、決定論的
期待値とゲートは維持する。

## 現行実装との差分

現行runnerは`DockerDevWorkspace`を使い、CIとホスト実行が既定である。次フェーズで
runnerを`DockerWorkspace`とdigest固定へ移行し、CIのゲート実行をcontainerへ移す。
同時に`docker/acd-tools.Dockerfile`のKiCad pinを9系から10系へ更新し、GD1の期待値は
10.0.5基準とする。受け入れ条件は[`ADR-0025`](ADR-0025-agent-server-production-adoption.md)
を参照する。

## 記録

`execution_env.container`がdigestならEvidence適格性を検討できる。digest不明は
`unknown`、ホスト実行は`none`として記録し、どちらも合格側の根拠にしない。
