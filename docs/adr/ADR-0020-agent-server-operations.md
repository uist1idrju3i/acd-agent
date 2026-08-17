# ADR-0020: agent-serverの運用境界

> ステータス: Accepted
> 日付: 2026-08-17

## 決定

`openhands-agent-server`はACDの会話、agent実行、event、workspace、永続化を運ぶruntime
層として扱う。ACD独自のserver、history、event、metrics基盤は追加しない。実運用前提の
採用と検証条件は[`ADR-0025`](ADR-0025-agent-server-production-adoption.md)に定める。

REST、WebSocket、conversation state、event、metrics、agent出力、OpenAI互換応答はL3観測
であり合否Evidenceではない。CIまたはDockerWorkspace内の決定論的pipelineが判定する。

## 運用境界

単一instanceとDockerWorkspaceを基本単位とする。pause、interrupt、resume、fork、delete
はserver APIの手順に従う。session keyを設定しないserverをnetworkへ公開しない。
`OH_SECRET_KEY`なしではsecretを含む永続stateを再起動後に完全復元できない。

`hooks_router`と`hooks_service`は`POST /api/hooks`でworkspaceの`.openhands/hooks.json`を
読み込む設定APIである。serverのfile、git、bash、OpenAI互換直接経路へ同じhookが自動適用
されることは、確認したソースからは断定しない。V7で実測する。

## 検証状態

vendor source inspectionは完了しているが、server起動、REST/WebSocket E2E、resume/fork、
Docker build、registry pullは未実施である。未実施を検証済みと表現せず、V1〜V8を
受け入れ条件として追跡する。
