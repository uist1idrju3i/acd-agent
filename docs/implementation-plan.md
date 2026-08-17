# 実装計画

> ステータス: Accepted

## 次フェーズ

| 作業 | 完了条件 |
|---|---|
| DockerWorkspace移行 | runnerがdigest固定`server_image`を使い、digest不明を拒否する |
| container CI | gates-containerがGD1を実行し、Docker不可を失敗にする |
| KiCad更新 | image pinを10系、GD1期待値を10.0.5基準へ更新する |
| agent-server検証 | ADR-0025のV1〜V8とnegative testを実装する |
| secret経路 | `SecretSource`候補を評価し、平文転送を避ける |
| 予算観測 | token、money、wall-clock、process回数を記録する |

## 実装済みの前提

ToolDefinition、hooks、critic、Conversation、plugin配布、TestLLM、agent-server接続、
DockerDevWorkspaceによるbuild準備は実装済みである。これらを未実装作業へ戻さない。
