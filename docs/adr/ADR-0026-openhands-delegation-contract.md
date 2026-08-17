# ADR-0026: OpenHands委譲契約

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.42.1

## コンテキスト

ACDはOpenHands Software Agent SDK v1.42.1（pinned checkout）に固有契約を追加する。
SDKの実行・対話・配布・観測を活用し、ACDの設計契約と決定論的合否を重複実装しない。

## 責務分割

**SDKが「実行・対話・配布・観測」を持ち、ACDが「契約・投影・合否」を持つ。**

## SDKへ委譲する領域

Conversation、persistence、hooks、Skill/plugin資材、Tool登録、secret管理とredaction、
security analyzer、agent lane並列化、telemetry、LLM routing、GoalControllerによる
反復制御をSDKへ委譲または採用予定とする。詳細は能力カタログを正とする。

## ACDが保持する領域

`ToolEnvelope`、Design Graph、Pydantic契約、投影、EDA/CAD adapter、fabrication制約、
決定論的ゲート、`Evidence.supports_pass(revision)`、決定論的探索、rationale契約を保持する。

## L1/L2/L3

L1は決定論的ゲートとrevision一致Evidenceだけがpass authorityである。L2のcritic、Skill、
agent、GoalController、analyzerは停止・修正を操舵し、L3のevent・metrics・telemetryは
観測する。L2/L3は停止側にだけ作用し、合格を生成しない。

## 入口と実行形

エージェント入口はSDK `ToolDefinition`だけとし、`scripts/*` CLIは人間とCIの入口とする。
現行の実行形は`LocalConversation` + `DockerWorkspace`である。Docker imageはdigest固定し、
CI/Docker経路でのみ合格側Evidenceを昇格する。

## 将来構想

agent-serverはv1.42.1のrouter、REST、WebSocket、persistenceを含む将来構想だが、
本ADRでは実装・実測・本番採用を行わない。`browser_use`も後段採用予定であり、現時点では
未実装・未検証である。

## 不採用

MCP、marketplace、extensions、Canvas、VSCode、desktop、Apptainer、remote API、cloud、
Gemini、Tom Consult、Apply Patch、ACP agent、agent-serverは、現行のOpenHands-only scope、
provenance境界、DockerWorkspace承認形と合わないため不採用とする。

## 統合したADR

ADR-0003、0009、0010、0013、0014、0015、0016、0017、0018、0019、0020、0024、0025。
