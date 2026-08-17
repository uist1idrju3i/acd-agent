# ADR-0013: OpenHands SDKランタイム機能の段階採用

> ステータス: Accepted
> 日付: 2026-08-17

## 決定

SDK v1.42.1のACD側採用範囲を次の通り整理する。

現行の採用対象は次のとおりである。

- hooksによるagent経路のfail-closed境界
- SDK ToolDefinitionによるACD入口
- Docker workspaceでの決定論的ゲート実行準備とcritic反復
- 決定論的探索lane
- Conversationとagent session persistence
- agent-serverとの運搬経路
- pinned plugin配布とTestLLM回帰
- agent-server／Conversation実運用化の検証要件
- DockerWorkspaceをゲート実行の正とする移行

SDK配線の多くは現行実装に存在する。ただしagent-server／Conversationの受け入れ条件と
DockerWorkspace一本化は次フェーズの実装対象である。各機能の採否は
[`openhands-sdk-capabilities.md`](../openhands-sdk-capabilities.md)を参照する。

## 境界

SDKのConversation、event、metrics、criticはACDの実行と操舵を支えるが、合否Evidence
にはならない。agent-serverの運用要件は[`ADR-0025`](ADR-0025-agent-server-production-adoption.md)、
workspaceの境界は[`ADR-0015`](ADR-0015-docker-workspace-gate-execution.md)を参照する。
