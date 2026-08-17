# ADR-0010: plugin-first OpenHands統合

> ステータス: Accepted
> 日付: 2026-08-16
> 関連: [`ADR-0008-minimal-vibebb-scope.md`](ADR-0008-minimal-vibebb-scope.md)、[`ADR-0009-openhands-delegation-and-skills.md`](ADR-0009-openhands-delegation-and-skills.md)

## コンテキスト

ACDには、探索・FW開発・レビューなどOpenHandsの標準実行能力と重なる処理がある。
一方、設計契約、投影、独立測定、決定論的ゲート、fail-closed境界はACDの設計権威
として保持する必要がある。

## 決定

ACDの主成果物をOpenHands pluginとし、次の資材を配布する。

- Skill: 工程手法、候補探索、FW作業、レビュー観点
- AgentDefinition: 電気、機械、FW、レビューの役割と権限
- command: `/acd:gates`
- MCP設定: 既存の契約検証・probe・決定論的pipeline入口

Python側は`acd-schema`、`acd-core`、`acd-pipeline`、`acd-tools`、adaptersに絞る。
独自のtool、event、history、task、executor基盤は追加せず、SDKへ委譲する。

Skill triggerは`KeywordTrigger`とする。`paths:`はmodel invocationを無効化し、
`inputs:`はTaskTriggerになるため、現在の任意利用と合わず採用しない。

MCPの公開範囲は読み取り、Pydantic検証、既存の決定論的ゲート実行だけとする。
MCP、Skill、agentは設計権威を持たず、未知・不備・未検証を成功に変換しない。
FastMCP 3.4.7のtool登録とstdio APIだけを採用する。

Agent CanvasのsubmoduleはACDの実行基盤ではなく参照価値もないため削除する。
OpenHandsの公開Skillsは<https://github.com/OpenHands/extensions>を外部参照とし、
submoduleには追加しない。clone重量と更新負債を増やさないためである。

## 影響

plugin loadとPython packageの責務が分離され、Skillの実行結果を合否根拠にしない
境界が明確になる。SDKの未採用機能（SecretRegistry、DockerWorkspace、agent-server、
Conversation実行経路など）は将来検討として記録し、現行実装と混同しない。

## 既存ADRとの整合

ADR-0003、ADR-0006、ADR-0008、ADR-0009の記述は本ADRおよびADR-0011で更新する。
過去の決定を削除せず、現在の採用範囲は本ADRを優先する。
