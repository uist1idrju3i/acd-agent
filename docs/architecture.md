# アーキテクチャ

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.42.1

この文書はACDの境界説明の単一の正である。SDK機能の採否は
[`openhands-sdk-capabilities.md`](openhands-sdk-capabilities.md)、実行手順は
[`agent-server-runbook.md`](agent-server-runbook.md)を参照する。

## 正規データと責務

入力ファイル、Design Graph、git履歴を設計の正とする。Python packageはPydantic契約、
決定論的投影、外部ツールadapter、ゲートを担当する。AI、Skill、agent、reviewerは候補と
修正案を返すが、設計入力と合否を直接決めない。

```text
acd-schema → acd-core → acd-pipeline → adapters/*
                                      └→ acd-tools
plugins/acd/ → Skill / AgentDefinition / command / hooks
vendor/software-agent-sdk → OpenHands runtime
```

## OpenHands境界

pluginはSkill、AgentDefinition、`/acd:gates`、SDK ToolDefinition、hooksを配布する。
ACD入口は`ToolDefinition`、`Action`、`Observation`、`ToolExecutor`であり、MCP互換層や
FastMCP serverは提供しない。ACDのObservation payloadはMCP互換ではなく、ACD固有契約である。
詳細は[`ADR-0024`](adr/ADR-0024-openhands-only-scope.md)を参照する。

hooksはagent経路のfail-closed境界である。agent-serverの`POST /api/hooks`はworkspaceの
`.openhands/hooks.json`を読み込む設定APIだが、server直接APIへの自動適用は未確認である。

## 判定、操舵、観測

判定・操舵・観測を分離する。L1は決定論的ゲートと
`Evidence.supports_pass(graph.revision)`だけをauthorityとする。L2はcritic、condenser、
Skill、agentの操舵、L3はevent、metrics、telemetryの観測である。L2とL3は停止側にだけ
作用でき、合格側へ作用できない。詳細は[`ADR-0023`](adr/ADR-0023-deterministic-gate-authority.md)を参照する。

## Workspaceとserver

決定論的ゲートの正は、digest固定の`DockerWorkspace(server_image=...)`である。
`DockerDevWorkspace(base_image=...)`はimage build準備経路に限定する。現行runnerは移行中で
DockerDevWorkspaceとホスト実行を使用するため、実装済みの境界と目標を混同しない。
Dockerはdeterminismを保証せず、digest不明またはホスト実行のEvidenceは合格側に使わない。

agent-serverとLocal/Remote Conversationは実運用前提の運搬層である。event、state、metrics、
agent応答は観測であり、合否はDockerWorkspace内の決定論的ゲートを再実行して決める。
