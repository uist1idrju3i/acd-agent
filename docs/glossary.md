# 用語集

> ステータス: Draft

| 用語 | 定義 |
|---|---|
| Pydantic契約 | `packages/acd-schema`のPydanticモデルで表現する入力・出力の契約 |
| 投影 | 入力ファイルから生成される派生成果物。正へ逆流させない |
| 機械可読投影 | netlist、寸法、干渉結果、ピン割当、ゲート結果など、機械的に再読込できる投影 |
| 視覚投影 | 回路図、配置図、レイアウト、3Dビュー、断面など、人またはvisionが観察する投影 |
| 代理指標 | HPWL、混雑度、余裕などの安価な評価量。候補の順位付けだけに使い、合格根拠にしない |
| 整合化（legalization） | 配置候補から重なり、keepout侵入、外形逸脱、回転制約違反などを除去する処理 |
| fab profile | 製造者の能力、形式、材料、出所、確認日時を宣言する版管理データ |
| adapter | 外部ツールや製造サービスの入出力を扱う境界 |
| Skill | OpenHands SDKへ工程手順や観点を配布するMarkdown資材 |
| plugin | Skill、`AgentDefinition`、MCP設定などをまとめるOpenHands SDKの配布単位 |
| AgentDefinition | OpenHands SDKのサブエージェント役割定義 |
| ImageContent | 画像をLLM入力へ渡すSDKの型 |
| inspect_image_with_vision | SDKの画像レビューtool |
| EventLog | OpenHands SDKが提供する会話履歴の保存機構 |
| ConfirmationPolicy | OpenHands SDKの不可逆操作確認ポリシー |
| workspace | agentがファイルと外部ツールを扱うSDKの実行環境 |
| fail-closed | 判定不能、unknown、版不明などを許可側へ倒さず停止する性質 |
| ゲート | 成果物を次へ進めるか決定論的に判定する境界 |
| Evidence | ツール名、版、入力hash、出力hash、収束状態、実行時刻などを含む検証根拠 |
| fixture | 再現可能な入力、環境、期待結果を固定した検証データ |
| golden task | fixtureから成果物とゲート結果を再現する基準作業 |
| negative test | 禁止や失敗を入力し、合格へ進まず停止することを確認する試験 |
| VibeBB | 対話から実機試作まで進めるACDの体験価値 |
| 安全境界 | 禁止領域を定め、設定を`profiles/`のcommitで管理する規則 |
| `RV1`／`RV2` | 旧ADRで使われるレビュー段階ID。現在の合否判定には使用しない |
| 工程ID | `S`（共通）、`E`（電気）、`M`（機械）と番号で表す工程識別子 |

## 工程ID体系

| ID | 工程 |
|---|---|
| `S1` | 要件対話 |
| `E1` | 部品選定と回路設計 |
| `E2` | アートワーク |
| `M1` | 筐体コンセプト |
| `M2` | 筐体詳細 |
| `S2` | 製造出力 |
| `S3` | 製造・加工フィードバック |
| `S4` | 試作立ち上げ |
