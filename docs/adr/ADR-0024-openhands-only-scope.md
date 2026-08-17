# ADR-0024: OpenHands専用拡張としての範囲

> ステータス: Accepted
> 日付: 2026-08-19

## 決定

本リポジトリはOpenHands Software Agent SDK専用のACD拡張とする。他のagent framework
や外部clientとの互換入口は提供しない。MCP client互換層、ACP互換、Agent Canvas
extensions、Apptainer、remote_api、cloud workspaceも提供しない。

ACDの`ok`、`operation`、`failure_reason`、`fail_closed`およびToolEnvelopeは、MCP互換
規約ではなくACD Observationのpayload契約である。型付け、可視化、confirmation、risk
annotationはSDKの`Observation`と`ToolAnnotations`へ委譲する。

SDK機能の採否は[`openhands-sdk-capabilities.md`](../openhands-sdk-capabilities.md)を
単一の正とする。SDKのMCP機構を将来再導入するという留保は置かない。

## 影響

pluginはSkill、AgentDefinition、command、SDK ToolDefinition、hooksを配布する。
ACD独自の互換serverやevent、history、executor基盤は追加しない。物理設計の契約と
決定論的ゲートはACD側に残す。
