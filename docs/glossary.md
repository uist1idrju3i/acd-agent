# 用語集

> ACD文書で使う用語の定義を示す。

| 用語 | 定義 |
|---|---|
| 設計入力 | Pydanticモデルで検証し、gitで履歴管理する入力ファイル。 |
| Design Graph | 電気・機械・製造意図を表すACDの正規設計モデル。 |
| 投影 | 入力から再生成され、入力を置き換えない派生成果物。 |
| レビュー投影 | AIが観察するための機械可読または視覚的な投影。 |
| Evidence | ツール版、入力・出力hash、条件、結果、commitを含む検証根拠。 |
| Rationale | 採用理由、代替案、要求、出所を保持する型付き設計根拠。 |
| rationale coverage | 必須属性が有効なrationale recordで覆われている状態。 |
| ゲート | 成果物を次工程へ進めるか決定する境界。 |
| fail-closed | unknown、未実行、版不明を許可側へ倒さず停止する性質。 |
| ToolEnvelope | ACD toolの入力、出力、provenance、エラーを包む契約。 |
| ToolDefinition | SDKへACDの決定論的入口を登録する定義。 |
| Skill | SDKが配布する工程手順や観点を記述した作業資材。 |
| plugin | Skill、hook、agent定義、commandをまとめる配布単位。 |
| AgentDefinition | agentの役割、model、tool、Skill、権限を定義する資材。 |
| hook | toolやsession境界で防護・記録を行うイベント処理。 |
| critic | 反復改善を操舵する評価機構。合否権限は持たない。 |
| Conversation | SDKが管理する対話、履歴、状態、永続化の単位。 |
| GoalController | 目標達成の反復停止を補助するSDK機構。 |
| DockerWorkspace | digest固定imageでagentやゲートを実行するworkspace。 |
| LocalConversation | 現行ACDが採用するローカルConversation経路。 |
| agent-server | SDKのREST/WebSocket等を提供する将来構想のserver経路。 |
| L1/L2/L3 | L1は判定、L2は操舵、L3は観測を表す責務層。 |
| 自働 | 異常を検知すると人の判断を待たず安全側へ停止する性質。 |
| 代理指標 | 候補順位付けに使う安価な評価量。合否根拠にはしない。 |
| fixture | 入力、環境、期待結果、negative条件を固定した検証データ。 |
| negative test | 禁止・矛盾・unknownが合格へ進まないことを確認する試験。 |
| golden task | 成果物、ゲート、Evidence、予算を回帰検証する代表作業。 |
| 工程ID | `S`、`E`、`M`と番号で表す設計工程の識別子。 |
| SafetyBoundaryResult | 安全境界判定の状態、根拠、commitを記録する結果。 |
| SB1/SB2 | 安全境界の予備判定／確定判定段階。 |
| fab profile | 製造能力、推奨値、出所、確認日時を版管理する宣言データ。 |
| DFM finding | 製造性に関する独立測定結果と分類。 |
| LibraryOverlay | 公式ライブラリを改変せず差分を保持する仕組み。 |
| Canvas | GUIベースのOpenHands拡張経路。ACDでは採用しない。 |
