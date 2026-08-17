# OpenHands統合

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.42.1

境界の規範は[`architecture.md`](architecture.md)を正とし、この文書はplugin資材と具体的な
登録内容だけを記録する。SDK全機能の採否は[`openhands-sdk-capabilities.md`](openhands-sdk-capabilities.md)を参照する。

## plugin構成

```text
plugins/acd/
├── .plugin/plugin.json
├── skills/
├── agents/
├── commands/
└── hooks/
```

Skillは探索、FW作業、レビューなどの手法を提供し、AgentDefinitionは電気、機械、FW、
レビューの役割を分ける。`/acd:gates`は既存の決定論的入口を呼び出す。いずれも合否権限を持たない。

## SDK tool

`register_acd_tools()`からACDのToolDefinitionを明示登録する。Toolはterminal、file editor、
grep、glob、task trackerなどに限定し、payloadはACD Observation契約として返す。登録、
confirmation、risk annotationはSDK APIへ委譲する。

## hooks

`plugins/acd/hooks/hooks.json`からcommand hookを読み込む。policy欠落、unknown、Evidence
不一致は停止側へ集約する。agent-serverのhooks APIはworkspace設定の読み込みを担うが、
server直接APIの全経路へhookが自動適用されるとは記載しない。受け入れ条件V7は
[`ADR-0025`](adr/ADR-0025-agent-server-production-adoption.md)を参照する。

## Conversationとserver

`LocalConversation`、persistence、condenser、criticはSDKの実行経路として使用する。
agent-serverはREST/WebSocketとConversationを運ぶ。event、metrics、agent出力は観測であり、
決定論的ゲートの代替ではない。運用手順は[`agent-server-runbook.md`](agent-server-runbook.md)を参照する。
