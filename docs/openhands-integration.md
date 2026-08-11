# OpenHands SDK統合

> ステータス: Draft  
> 対象バージョン: OpenHands Software Agent SDK v1.41.0  
> submodule commit: `ca46719d5e9a0b0af79f7de2da37067a5b94563c`（2026-08-06）  
> ライセンス: MIT、Python 3.12+

本書は、`vendor/software-agent-sdk`のソースと公式ドキュメントを一次情報として調査した
結果の要約であり、OpenHands SDKが担う実行基盤とACDが担う設計グラフ・ゲート・Evidenceの
境界を正とする。工程のFW契約は [`design-flow.md`](design-flow.md)、実装フェーズは
[`roadmap.md`](roadmap.md)を参照する。代表的な根拠は、`openhands-sdk/openhands/sdk/agent/`、
`openhands-sdk/openhands/sdk/conversation/`、`openhands-sdk/openhands/sdk/event/`、
`openhands-sdk/openhands/sdk/tool/`、`openhands-sdk/openhands/sdk/security/`、
`openhands-workspace/openhands/workspace/`のリポジトリ相対パスにある。

## パッケージ構成

| package | 責務 | ACDでの使い方 |
|---|---|---|
| `openhands-sdk` | Agent、Conversation、Event、Tool、LLM、MCP、security、settings | 計画・型付きtool・会話・実行制御 |
| `openhands-tools` | terminal、browser、file/editor、delegate | 必要な汎用toolとサブエージェント |
| `openhands-workspace` | Local、Docker、Apptainer、cloud、remote workspace | CAD/EDA workerの隔離実行 |
| `openhands-agent-server` | FastAPI REST/WebSocket、会話、workspace、MCP | CLI以外のAPI入口、長時間会話の管理 |

## 実行モード

- `LocalWorkspace`: 開発と軽量なローカル検証。ホスト分離は自動保証されないため、
  外部CAD/EDAや製造CLIは専用環境と権限で実行する。
- `DockerWorkspace`: workerと依存ツールをimageへ固定し、CI・再現性を優先する。
- `APIRemoteWorkspace`＋agent-server: 長時間実行、遠隔worker、API入口に使う。

ユーザーとの対話インタフェースはOpenHands（CLIやagent-serverを含むクライアント）が
担う。ACDが提供するのは、OpenHandsへ登録するツール群、設計グラフ、決定論的ゲート、
Evidenceである。

## SDK機能とACD自前実装

| ACD要件 | SDKで使うもの | ACDが自前実装するもの |
|---|---|---|
| 型付きtool | `ToolDefinition`、Pydantic Action/Observation、annotations | 設計グラフschema、artifact contract、CAD/EDA意味論 |
| 決定論的gate | tool hooks、typed result、`readOnly`/`destructive`/`idempotent` annotations | gate policyの版、input/design hash、stale判定、fail-closed |
| 承認 | `ConfirmationPolicy`、`SecurityRisk`、confirmation state | approval IDの一回性、失効、ActionEventとの束縛、不可逆executor |
| 実行履歴 | EventLog、snapshot、resume、fork | 外部副作用journal、署名、idempotency、外部状態snapshot |
| 長時間実行 | condenser、memory、interrupt、max iteration、budget | ACD task ledger、checkpoint方針、予算の製造・機械統合 |
| 分業 | delegate/spawn、子Conversation、権限継承 | 電気・機械レーンのgraph merge、成果物契約、失敗因果 |
| LLM運用 | token/cost metrics、cache、retry | ACD retry budget、同一input hash、外部副作用の再実行防止 |
| 外部tool | MCP client、動的Pydantic schema、timeout、再接続 | adapterの意味検証、tool version固定、Evidence生成 |
| 作業資材の配布 | `Skill`、`KeywordTrigger`／`PathTrigger`／`TaskTrigger`、skill repositoryのpin、`PluginManifest`、marketplace | 工程契約、レビュー観点、Q7/N7手法、ECAD操作手順の内容と版、Evidenceへの記録 |
| サブエージェント定義 | `AgentDefinition`、`AgentDefinitionLevel`、model/tools/skills/hooks/MCP/予算・反復上限、`permission_mode` | 生成・レビューagentの役割境界、別profile、設計グラフへの書込み制約、`RV1`／`RV2`の判定 |
| hook | `PreToolUse`、`PostToolUse`、`UserPromptSubmit`、`SessionStart`、`SessionEnd`、`Stop`、`HookDecision` | 不可逆操作の防護、side-effect journal、決定論的gate、共通executor |
| 反復改善 | `CriticBase`、`CriticResult`、`IterativeRefinementConfig`、`Conversation.run()`の自動retry | PDCAの`ReviewFinding`、処分状態、ラウンド上限、`RV2`の合否 |
| 目標・停滞検出 | `/goal`、`GoalController`、judge、`GoalVerdict`、`StuckDetector` | 収束判定、差し戻し、エスカレーション、決定論的な完了条件 |
| 会話圧縮 | `LLMSummarizingCondenser`、`PipelineCondenser`、`NoOpCondenser` | Evidence、hash、ゲート結果、対象revisionの永続記録 |
| セキュリティ防護 | analyzer、`ConfirmationPolicy`、risk、ensemble、defense-in-depth、policy rails、shell AST/parser | 不可逆操作の多層防護、裁量枠、`SB1`／`SB2`、fail-closedな共通executor |
| agent profile | `AgentProfile`、profile store、resolver、`llm_profile_ref`／`mcp_server_refs` | model・prompt・tool構成の版管理、`ReviewFinding`との対応付け、秘密情報を含まない参照 |
| workflow分業 | `WorkflowTool`／`WorkflowExecutor`、`task`、`task_tracker`、`delegate`、`manager` | 電気・機械・FWレーンのtask ledger、graph merge、成果物契約、決定論的状態 |
| 可観測性 | `observability/laminar.py` | 任意の計測、Evidenceと判定面の分離 |

ACDのtoolは`ToolDefinition`として登録し、Pydantic Action/Observationで入力と結果を
型付けする。annotationsはread-only、destructive、idempotentの宣言に使うが、
宣言だけで安全性は成立しない。共通executorが実際の副作用を分類・検査する。

## SDK機能の活用方針

SDKの機能は実行、配布、反復、分業、防護の基盤として利用する。ただし設計グラフ、
投影、Evidence、決定論的ゲート、合否の正はACDに残す。ストレージとworkspaceの所在境界は
[`architecture.md`](architecture.md)に従い、OpenHands側へ移したファイル実体をACDの正へ
逆流させない。

### skills、plugin、marketplace

工程ごとのレビュー観点チェックリスト、Q7/N7の作業手法、ECAD操作手順をfrontmatter付き
Markdownの`Skill`として配布し、`KeywordTrigger`、`PathTrigger`、`TaskTrigger`で必要な
工程へ載せる。複数のskill、hooks、MCP設定、agent定義、commandをまとめて配布する場合は
`PluginManifest`を用い、marketplaceからGitHubまたはGitのURLでpluginを取得する。
skills repositoryとpluginの参照はpinし、解決した版をEvidenceへ記録する。

Skillの記述、pluginの定義、triggerの発火はプロンプト資材または実行制御であり、設計グラフ
の正でもEvidenceそのものでもなく、合否根拠にもならない。内容の版、対象revision、
入力hash、実行結果はACDの契約で検証する。

### subagentとレビューの独立性

`AgentDefinition`で生成側と`RV1`レビュー側を別のagent定義、別profile、別コンテキスト
として固定する。`AgentDefinition`の`name`、`description`、`model`、`tools`、`skills`、
`max_iteration_per_run`、`max_budget_per_run`、`hooks`、`mcp_config`、`permission_mode`、
`condenser`を役割ごとに明示する。定義のlevelは`project`、`user`、`builtin`、`plugin`、
`programmatic`から選び、設計の再現に必要なものはproject側で版管理する。

レビュー側はtoolsと`permission_mode`を絞り、設計グラフへ書き込めない構成にする。
ただしSDKのagent定義だけを信頼境界とはせず、共通executorとACDの権限検査でも書込みを
拒否する。レビューagentは自分または生成agentの成果物を修正して合格根拠にせず、
`ReviewFinding`を生成する。`RV2`の判定はその処分状態を決定論的ゲートが行う。

### hooksによる前段防護

`PreToolUse`は発注や実機書込みなど不可逆操作の前段確認に、`PostToolUse`は副作用journalと
出力hashの記録点に使う。`UserPromptSubmit`、`SessionStart`、`SessionEnd`、`Stop`は
セッション境界や停止時の記録・後処理に利用する。`HookDecision`の`allow`／`deny`は
多層防御の一層であり、hookが`allow`したことも`deny`されなかったことも合格根拠にしない。
最終的な裁量枠、承認、Evidence、合否はACDの決定論的ゲートと共通executorが担う。

### critic、目標判定、停滞検出

`CriticBase`、`CriticResult`、`IterativeRefinementConfig`の`success_threshold`と
`max_iterations`を、投影レビューPDCAのラウンド上限と自動retryの実行機構として利用する。
`agent_finished`、`empty_patch`、`pass_critic`、API basedのcritic結果は改善のシグナルで
あって、`ReviewFinding`の代替ではない。criticのスコアや閾値超過を`RV2`の合格根拠にしない。

`/goal`の`GoalController`と別LLMのjudge（`judge_goal`／`GoalVerdict`）は、PDCAが目標へ
収束したかを確認し、上限まで再プロンプトする機構として使う。`StuckDetector`は反復する
action-observation／action-error cycle、agentの独白、context window errorを検出し、
差し戻しまたはエスカレーションを起動する。いずれもLLMまたは宣言的な補助機構であり、
judgeの判定や停滞検出結果は`RV2`の判定面ではない。

### condenserとprofile

`LLMSummarizingCondenser`、`PipelineCondenser`、`NoOpCondenser`は長時間会話のcontext
圧縮に使う。圧縮後もEvidence、入力・出力hash、対象revision、ツール版、ゲート結果を
要約で置き換えず、ACDの永続記録から参照する。要約の欠落や誤りは`unknown`として扱い、
必要なEvidenceを再取得してから判定する。

`AgentProfile`は`llm_profile_ref`と`mcp_server_refs`を参照で持つため、at restでsecret-free
なmodel、prompt、tool構成の固定に使う。profile storeとresolverで解決した参照、版、解決
条件を`ReviewFinding`が持つモデル・プロンプト版と対応付ける。secretそのものをprofile、
Evidence、設計グラフへ複製しない。

### securityと分業

analyzer、`ConfirmationPolicy`、risk、ensemble、defense-in-depthのpattern／policy rails、
shell AST／parserを、外部コマンドと不可逆操作の多層防護へ使う。LLMベースのrisk判定は
確率的であるため、`SB1`／`SB2`、発注裁量枠、実機書込みの最終判定を代替しない。防護の
どの層でも不明、矛盾、解析不能はfail-closedとし、ACDの決定論的ゲートへ戻す。

`WorkflowTool`／`WorkflowExecutor`、`task`、`task_tracker`、`delegate`を電気・機械・FW
レーンの分業と反復実行へ使う。SDK側のtask状態、delegateの完了報告、workflowの成功状態は
ACDのtask ledgerの正ではない。ACDは対象revision、成果物hash、依存関係、失敗因果、ゲート
結果をledgerへ記録し、各レーンの成果物を意味的にmergeせず対象revisionから再生成する。

`observability/laminar.py`は任意の計測として導入できるが、導入する場合も、計測値を
Evidenceや合否判定へ自動昇格させない。可観測性は実行の理解を助けるものであり、判定面ではない。

CAD/EDA外部プロセスがファイルを保持している間は、worktreeの切替・復元と外部ツール実行を
排他にする。adapterはプロセス終了とファイルハンドル解放を確認し、隔離した設定ディレクトリ
で実行する。切替・復元後は対象revisionから投影を再生成し、再読込とゲートを再実行する。

## MCP接続

SDKのMCP統合は、外部CAD/EDA、sourcing、simulationを動的schemaで接続する候補である。
MCP toolの入力をPydantic Actionへ変換し、timeout、再接続、secret展開、出力maskingを
利用する。MCP serverが返す成功文字列を合格Evidenceとはせず、生成artifactを再読込し、
決定論的gateを別途実行する。

## ファームウェア開発とOpenHands

OpenHands SDKのソフトウェア開発能力（bash、ファイル編集、テスト実行、MCP client、
delegate）は、FWレーンの実装にそのまま利用できる。ACD側が用意するのは、設計グラフ
から投影する型付きFWパッケージ、ピン・ネット整合ゲート、ビルド・テスト・ログの
Evidence記録である。FW側の決定がピン割当やペリフェラル設定を変える場合は、E1へ
戻す双方向契約として扱う。

実機への書き込み、RTT等のログ取得、Blinkの実行を外部ツールまたはMCPサーバとして
OpenHandsから呼び出す構成は候補である。候補例として`FreeOCD/freeocd-vscode-extension`
（CMSIS-DAP、RTT、MCPサーバ）と`OpenBlink/openblink-vscode-extension`（mruby/c、
BLEによるBuild & Blink、MCPサーバ）がある。ただし、接続方法、提供ツール、ライセンスは
本リポジトリで一次情報による接続検証をしておらず、候補・要検証である。

## SDKが保証しないこと

- 外部副作用を含む決定論的replay。
- LocalWorkspaceでのホスト権限・ファイル・ネットワークの完全分離。
- 承認IDと不可逆操作の暗号学的または因果的な束縛。
- KiCad、FreeCAD、SPICE、slicerの設計意味論や製造妥当性。
- 外部サービスの価格、在庫、発注状態の永続的な正確性。
- FWの機能的正しさ、書き込み・実機ログの再現性、ターゲット固有の意味論。
- critic、`/goal` judge、LLM security analyzer、hookは確率的または宣言的な機構であり、
  決定論的ゲートとEvidenceを代替しない。

したがって、OpenHandsは実行基盤であって、ACDのcanonical graph、gate、Evidence、
approval、side-effect journalを代替しない。

## 公開先行事例

`docs/prior-art.md`の調査では、OpenHands SDKを使った公開のハードウェア/CAD設計先行
事例は確認できなかった。OpenHandsからKiCad、FreeCAD、agentcad、slicerを呼ぶことは
ACDの統合案であり、既存事例の実績ではない。
