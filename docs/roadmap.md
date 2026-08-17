# ロードマップ

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.42.1

## 現在地

| 項目 | 状態 |
|---|---|
| ACD契約、投影、決定論的ゲート | 実装済み |
| OpenHands plugin、ToolDefinition、hooks | 実装済み |
| Conversation、session persistence、critic操舵 | 実装済み |
| agent-server運搬経路 | 実装済み（受け入れ条件は検証中） |
| DockerDevWorkspaceによるimage build準備 | 実装済み |
| DockerWorkspace digest固定をゲートの正にする移行 | 次フェーズ |

## 次フェーズ

1. runnerを`DockerWorkspace(server_image=...@sha256:<digest>)`へ移行する。
2. CIのゲート実行をcontainerへ移し、Docker不可を失敗として扱う。
3. `docker/acd-tools.Dockerfile`のKiCad pinを9系から10系へ移し、GD1期待値を10.0.5基準にする。
4. agent-server受け入れ条件V1〜V8を実測し、各項目のnegative testを追加する。
5. secret経路、予算計測、単一instanceの運用手順を確定する。

## 検証原則

L1の合否は決定論的ゲートだけが担う。critic、Skill、agent、metrics、telemetryはL2/L3
として停止・操舵・観測に使うが、合格を作らない。詳細は[`ADR-0023`](adr/ADR-0023-deterministic-gate-authority.md)を参照する。
