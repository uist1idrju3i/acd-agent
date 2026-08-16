# ADR-0003: Phase 0で骨組みを作るSDK機能と後段に送る機能

> ステータス: Accepted
> 日付: 2026-08-11

## コンテキスト

OpenHands SDKの実行・分業・反復・防護機能は再利用し、同等機能をACDで自作しない
（[`docs/openhands-integration.md`](../openhands-integration.md)）。Phase 0では
どの機能の骨組みを作り、どれを後段に送るかを確定する必要がある。

## 決定

SDK標準機能を利用する骨組み:

- `EventLog`: ACD独自eventを定義せず、SDKの`EventLog`と成果物ファイルを履歴とする。
- `TestLLM`: 決定論的AI回帰の唯一の経路とする。レビュー応答の解析
  はTestLLMの固定応答で回帰テストする。
- plugin構成: `plugins/acd/`に`.plugin/plugin.json`、`skills/`、`agents/`、
  の骨格を置く。

Phase 1以降に送る機能:

- `DockerWorkspace`／`RemoteWorkspace`による実行隔離。
- `SecretRegistry`／`SecretSource`によるfab API等の資格情報注入。
- MCP serverの実接続（Phase 0はMCP設定hashの検証点だけを持つ）。
- subagent分業（別コンテキストのレビュー実行）。
- critic／judge／LLM security analyzer（採用しても合否根拠にはしない）。

## 影響

- Phase 0の回帰は実LLMなしで決定論的に実行できる。
- 後段機能の追加はこのADRの改訂として記録する。
