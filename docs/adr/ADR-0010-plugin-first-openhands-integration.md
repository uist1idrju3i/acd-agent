# ADR-0010: plugin-first OpenHands統合

> ステータス: Accepted
> 日付: 2026-08-16

## 決定

ACDのOpenHands統合はpluginを中心に構成する。pluginはSkill、AgentDefinition、
command、SDK ToolDefinition、hooksを配布する。決定論的なACD入口はSDKの
`ToolDefinition`、`Action`、`Observation`、`ToolExecutor`として登録する。

MCP設定とFastMCP serverはACDの公開範囲に含めない。独自の互換層、event、history、
executor基盤も作らない。採否の詳細は[`openhands-sdk-capabilities.md`](../openhands-sdk-capabilities.md)、
OpenHands専用の境界は[`ADR-0024`](ADR-0024-openhands-only-scope.md)を参照する。

## 境界

Skill、agent、reviewerは候補と操舵信号を返すが、合否権限を持たない。hooksはagent経路の
fail-closed境界として既存の決定論的判定を呼び出す。判定・操舵・観測の三層分離は
[`ADR-0023`](ADR-0023-deterministic-gate-authority.md)を正とする。

## 影響

OpenHands SDKの更新では公開APIとACD側の登録を同時に確認する。plugin資材の配置は
`plugins/acd/`に固定し、外部配布では不変refを使用する。過去の決定を保存するために
現行境界と矛盾する互換入口を残してはならない。
