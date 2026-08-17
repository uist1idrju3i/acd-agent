# ADR-0014: SDK ToolDefinitionによるACD入口の一本化

> ステータス: Accepted
> 日付: 2026-08-17

## 決定

ACDの決定論的入口はOpenHands SDK v1.42.1の`ToolDefinition`、`Action`、`Observation`、
`ToolExecutor`、`ToolAnnotations`、`register_tool`で公開する。実装は
`packages/acd-tools/src/acd_tools/sdk_tools.py`に置き、明示的な登録関数から登録する。

MCP client互換層とFastMCP serverは提供しない。MCPをSDK側の機構で再導入するという
留保も置かない。これは本リポジトリをOpenHands専用拡張とする
[`ADR-0024`](ADR-0024-openhands-only-scope.md)による。

## 境界

ObservationのpayloadはACD契約として`ok`、`operation`、`failure_reason`、`fail_closed`
およびToolEnvelopeを返す。これはMCP互換規約ではない。ToolAnnotationsはconfirmationと
risk情報をSDKへ渡すが、Observationは合否Evidenceではない。

## 関連

SDK機能の全採否は[`openhands-sdk-capabilities.md`](../openhands-sdk-capabilities.md)、
合否権限の境界は[`ADR-0023`](ADR-0023-deterministic-gate-authority.md)を参照する。
