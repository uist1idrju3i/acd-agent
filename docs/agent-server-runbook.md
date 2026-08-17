# agent-server運用手順

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.42.1

このrunbookは単一instanceのagent-serverとConversationを運用する手順である。境界は
[`architecture.md`](architecture.md)、受け入れ条件は[`ADR-0025`](adr/ADR-0025-agent-server-production-adoption.md)を参照する。

## 起動

```bash
uv run python -m openhands.agent_server --host 127.0.0.1 --port 8000
```

session keyを設定しないserverをnetworkへ公開しない。`OH_SECRET_KEY`はsecretを含む永続
stateの復元に必要であり、API key、token、secretを文書やログへ記録しない。

## Conversation操作

RESTでconversationを作成し、message送信、run、event取得を行う。WebSocketではイベントを
購読する。pause、interrupt、resume、fork、deleteはserver APIの応答を確認しながら行う。
resumeやfork後は必ず決定論的ゲートを再実行する。

## hooks

`POST /api/hooks`は指定workspaceの`.openhands/hooks.json`を読み込み、`HookConfig`を返す。
これは設定ロードAPIであり、file、git、bash routerやOpenAI互換gatewayへの自動適用を本書で
保証しない。適用範囲はV7の実測結果で更新する。

## 判定と障害

serverのevent、state、metrics、agent応答は観測であり、合否Evidenceではない。DockerWorkspace
のdigestが解決できない、ゲートが未実行、入力がunknownの場合はfail-closedで停止する。
実測未完了を検証済みとして扱わない。
