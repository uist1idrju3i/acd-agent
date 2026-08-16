# OpenHands SDK統合

> ステータス: Draft  > 対象バージョン: OpenHands Software Agent SDK v1.42.1（submodule commit
> `167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497`、2026-08-12）、ライセンス: MIT、Python 3.12+

本書は、`vendor/software-agent-sdk`のソースと公式ドキュメントを一次情報として調査した
結果の要約であり、OpenHands SDKが担う実行基盤とACDが担う入力ファイル・ゲート・投影の
境界を正とする。工程のFW契約は [`design-flow.md`](design-flow.md)、実装フェーズは
[`roadmap.md`](roadmap.md)を参照する。代表的な根拠は、`openhands-sdk/openhands/sdk/agent/`、
`openhands-sdk/openhands/sdk/conversation/`、`openhands-sdk/openhands/sdk/event/`、
`openhands-sdk/openhands/sdk/tool/`、`openhands-sdk/openhands/sdk/security/`、
`openhands-workspace/openhands/workspace/`のリポジトリ相対パスにある。

## v1.41.0からv1.42.1への変更点記録

確認日: 2026-08-16。一次情報は[SDK v1.42.0リリースノート](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.42.0)、
[SDK v1.42.1リリースノート](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.42.1)、
[v1.41.0からv1.42.1のcommit差分](https://github.com/OpenHands/software-agent-sdk/compare/v1.41.0...v1.42.1)、
およびsubmoduleのcommit
`ca46719d5e9a0b0af79f7de2da37067a5b94563c`→
`167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497`である。

### ACDが使用するAPIの確認

ACDが実際にimportする次のAPIについて、両commitのtreeとsourceを比較した。

- `openhands.sdk.event.base.Event`
- `openhands.sdk.hooks.types.HookDecision`
- `openhands.sdk.llm`
- `openhands.sdk.testing.TestLLM`
- `openhands.sdk.extensions.installation.info.InstallationInfo`
- `openhands.sdk.extensions.installation.metadata.InstallationMetadata`

上記のmodule pathと対象symbolは両commitに存在した。`event/base.py`、
`hooks/types.py`、`testing/test_llm.py`、installationの`info.py`／`metadata.py`には
この範囲の変更を確認せず、関連領域で差分があった`llm.py`にも上記import pathを
壊す変更は確認しなかった。したがって、今回の差分におけるACDの使用APIへの破壊的変更は
確認されていない。ただし、未使用APIやagent-server全体の互換性まで保証するものではない。

### 主な変更とACDでの評価

| 変更 | 一次情報で確認した内容 | ACDでの評価 |
|---|---|---|
| structured output | v1.42.0でstructured output機能と実行例が追加された | ACDのJSON Schema／決定論的gateとの接続方法、schemaの正、失敗時のEvidenceが未評価。勝手に採用せず、継続調査とする |
| PluginFormat抽出 | plugin loaderのformat戦略を抽出し、Agent Plugins対応の準備を行った | ACDは`.plugin/plugin.json`、skills、hooks、MCP設定を既存契約として固定している。新formatは未採用で、移行要否を継続調査とする |
| prompt-based hooks evaluation | hookにprompt-based evaluationを追加 | ACDの`SessionStart` denyと決定論的gateは維持し、prompt評価やhookのallowを合否根拠にしない。補助的採用は継続調査とする |
| LLM global config serialization修正 | v1.42.1でglobal config経由の呼び出し直列化を停止する修正が入った | ACDが使うLLM呼び出しの同時実行挙動に関係する。直列化修正は利用側のAPI採用ではなくSDK更新の挙動として受け入れ、並行実行と回帰を継続確認する |
| agent-serverのworktree／初期化／observability変更 | v1.42.0〜v1.42.1でworktree root設定、deferred init、event／telemetry等の変更を確認 | ACDのserver実行契約に影響しうるが、今回のsource import確認だけでは相互運用を保証できない。継続調査とする |
| goal／STUCK処理 | STUCK時にgoal loopを停止しない修正をv1.42.1で確認 | ACDの決定論的gateを置き換えないため、ACD側での採用はしていない。SDK挙動として回帰対象にする |

ACDの方針は、SDKのcritic、judge、hookを合否の正にしないことである。structured output、
prompt-based evaluation、goal判定を採用する場合は、Pydantic契約、最小記録、
fail-closed境界を含む設計判断が必要であり、今回の依存更新だけでは採用決定を行わない。
この採否判断は [`ADR-0003`](adr/ADR-0003-sdk-feature-adoption.md) と整合させる。

## パッケージ構成

| package | 責務 | ACDでの使い方 |
|---|---|---|
| `openhands-sdk` | Agent、Conversation、Event、Tool、LLM、MCP、security、settings | 計画・型付きtool・会話・実行制御 |
| `openhands-tools` | terminal、browser、file editor（apply_patch／planning_file_editor）、glob／grep、task／task_tracker、workflow、delegate、preset | 必要な汎用tool、preset agent、サブエージェント |
| `openhands-workspace` | Docker、Apptainer、cloud、remote workspace | CAD/EDA workerの隔離実行 |
| `openhands-agent-server` | FastAPI REST/WebSocket、会話、workspace、MCP | CLI以外のAPI入口、長時間会話の管理 |

## 実行モード

実行基盤は`DockerWorkspace`または`RemoteWorkspace`（agent-server）に限定する。
Docker workerは外部CAD/EDA、製造CLI、依存ライブラリをimage digestへ固定し、RemoteWorkspaceは
agent-serverの長時間実行、会話ごとのworktree、API入口を利用する。`LocalWorkspace`による
Dockerなしの手元単体実行は採用しない。これにより、VS Code、noVNC、Canvas、OpenAI互換
gateway、Webhook、conversation leaseを条件分岐なしにagent-server前提で扱い、外部ツール版の
固定をimage digestでも担保する。LocalWorkspaceでのホスト権限・ファイル・ネットワークの
完全分離をSDKに期待する契約も対象外とする。

ユーザーとの対話インタフェースはOpenHands（CLIやagent-serverを含むクライアント）が
担う。ACDが提供するのは、OpenHandsへ登録するツール群、設計グラフ、決定論的ゲート、
Evidenceである。

### 人間の観察・手修正経路

agent-serverのVS Code経路（`enable_vscode`、`GET /vscode/url`）とnoVNC desktop経路
（`enable_vnc`、`GET /desktop/url`）を、AIが生成した候補を人間が観察・手修正する経路として
使う。GUI操作自体はEvidenceにならず、操作ログが取得できない状態は`unknown`である。
desktopまたはVS Codeを開けた事実は、時刻、conversation ID、git commitだけを記録し、
合格根拠にはしない。

人間の手修正はworktreeの変更として現れるため、commit、commit receipt、対象ゲートの再実行を
経て初めて下流の根拠になる。手修正後にゲートを再実行していない状態はfail-closedとする。
この経路はK1のAI視覚投影レビューを置き換えず、人間の観察・手修正と別コンテキストの
`ImageContent`／`inspect_image_with_vision`レビューを併用する。

### Canvas extension

投影ビューはCanvas extensionとしてagent-serverの
認証境界内へ配布し、ACD独自Webアプリの配信・認証・版管理を増やさない。extensionは解決済み
SHAで固定する。ただしCanvasのフロントエンド本体がSDK repository外である点は未確認であり、
載せる先の可用性を確認するまで採用可否は未確定とする。

## SDK機能とACD自前実装

| ACD要件 | SDKで使うもの | ACDが自前実装するもの |
|---|---|---|
| 型付きtool | `ToolDefinition`、Pydantic Action/Observation、annotations | 設計グラフschema、artifact contract、CAD/EDA意味論 |
| 決定論的gate | tool hooks、typed result、`readOnly`/`destructive` annotations、`CriticBase`／`IterativeRefinementConfig`（反復実行機構） | gate policyの版、input hash、fail-closed、合否の正 |
| 承認 | `ConfirmationPolicy`、`SecurityRisk`、confirmation state | approval IDの一回性、失効、ActionEventとの束縛、不可逆executor |
| 実行履歴 | SDK `EventLog`の追記・lock・branch／resume／fork・conversation state永続化 | SDKの会話履歴とworkspaceを利用し、ACD独自event層を作らない |
| 長時間実行 | condenser、memory、interrupt、max iteration、budget | ACD task ledger、checkpoint方針、予算の製造・機械統合 |
| 分業 | delegate/spawn、子Conversation、権限継承 | 電気・機械レーンのgraph merge、成果物契約、失敗因果 |
| LLM運用 | `Metrics`／`MetricsSnapshot`、`ConversationStats`、token/cost、latency、cache、retry | 外部process回数・外部tool時間の実測。SDKのretry・予算会計へ委譲 |
| 予算上限 | `AgentDefinition.max_budget_per_run`／`max_iteration_per_run`、SDK `Metrics`、`get_metrics_for_usage(usage_id)` | token／money／LLM latencyの実行記録。外部process回数・外部tool wall-clockも最小記録へ含める |
| 外部tool | MCP client、動的Pydantic schema、timeout、再接続 | adapterの意味検証、tool version固定、Evidence生成 |
| 視覚レビュー | `ImageContent`、`inspect_image_with_vision`、画像inline化 | 視覚投影の分類、画像hash、rendererの記録 |
| 実行分岐 | `Conversation.fork(from_event_id=...)`（local／remote） | trade studyの比較と会話履歴の保持 |
| 作業資材の配布 | `Skill`、`KeywordTrigger`／`PathTrigger`／`TaskTrigger`、skill repositoryのpin、`PluginManifest`、marketplace | 工程チェックリスト、Q7/N7の作業手法、レビュー観点、ECAD操作手順 |
| サブエージェント定義 | `AgentDefinition`、`AgentDefinitionLevel`、model/tools/skills/hooks/MCP/予算・反復上限、`permission_mode` | 生成・レビューagentの役割境界、入力ファイルへの書込み制約 |
| hook | `PreToolUse`、`PostToolUse`、`UserPromptSubmit`、`SessionStart`、`SessionEnd`、`Stop`、`HookDecision` | 不可逆操作の防護、commit側receipt参照、決定論的gate、共通executor |
| 反復改善 | `CriticBase`、`CriticResult`、`IterativeRefinementConfig`、`Conversation.run()`の自動retry | 自然文の所見を修正ループへ渡す。合否は決定論的ゲート |
| 目標・停滞検出 | `/goal`、`GoalController`、judge、`GoalVerdict`、`StuckDetector` | 停止・差し戻し・エスカレーション。決定論的な完了条件 |
| 多観点レビュー | `WorkflowTool`／`WorkflowExecutor`のmap/reduce、`max_concurrency` | 自然文の所見を束ね、レビュー観点を分業する。投影の意味的mergeはACDが禁止 |
| 人間UI | agent-server VS Code／noVNC、Canvas extension | 観察・手修正・承認待ちの表示。GUIやUI状態は合否の正ではない |
| 外部連携 | agent-server OpenAI互換gateway | 照会・起票・状態取得。合否・承認・不可逆操作はACD経路でのみ実行 |
| 会話圧縮 | `LLMSummarizingCondenser`、`PipelineCondenser`、`NoOpCondenser` | hash、ゲート結果、実行時刻の最小記録 |
| セキュリティ防護 | analyzer、`ConfirmationPolicy`、risk、ensemble、defense-in-depth、policy rails、shell AST/parser。LLM analyzerはLLM由来riskの伝達層 | 安全境界、発注直前の全ゲート、fail-closed、独立した決定論的検査 |
| agent profile | `AgentProfile`、profile store、resolver、`llm_profile_ref`／`mcp_server_refs` | model・prompt・tool構成の選択。レビューの合否根拠にはしない |
| workflow分業 | `WorkflowTool`／`WorkflowExecutor`、`task`、`task_tracker`、`delegate`、`manager` | 電気・機械・FWレーンのtask ledger、graph merge、成果物契約、決定論的状態 |
| ledger取り込み | agent-server `WebhookSpec`（buffer／flush timer／POST） | task状態の低遅延取り込み。正はEventLog replayとcommit済みartifact |
| secrets | `SecretRegistry`、`StaticSecret`／`LookupSecret`、`conversation.update_secrets()` | `SecretSource`参照名、at rest secret-freeなgraph／Evidence／profile |
| LLM可用性 | `LLMRegistry`（usage ID別インスタンスと独立metrics）、`FallbackStrategy`（transient error時のprofile fallback） | fallback発生の記録、実体model版のEvidence束ね、レビュー中fallbackの`unknown`扱い |
| 作業メモリ | 二層persistent memory（`MEMORY.md` loader、user／project tier） | `KnowledgeItem`の正、配布内容のhash記録。memoryはプロンプト資材であり合否根拠にしない |
| sourcing | `browser_use` toolset（navigate、click、type、get_state、get_content、screenshot、tabs） | API一次・browser二次の期限付きEvidence、Phase 11での利用禁止 |
| 起動契約 | `SessionStart` hook、`HookDecision` | ACD import、外部tool版、解決SHA／MCP設定hashの検証と失敗時deny |
| 可観測性 | `observability/laminar.py` | 任意の計測、Evidenceと判定面の分離 |

ACDのtoolは`ToolDefinition`として登録し、Pydantic Action/Observationで入力と結果を
型付けする。annotationsはread-only、destructive、idempotentの宣言に使うが、
宣言だけで安全性は成立しない。共通executorが実際の副作用を分類・検査する。

## ACDの提供形態

ACDは、OpenHandsとの結合を次の三層に分けて提供する。

- **core:** 設計グラフ、決定論的ゲート、共通executorを含むPythonパッケージ。
  permissiveな依存はimport結合し、ACDの`ToolDefinition`としてOpenHandsへ登録する。
- **外部ツール:** KiCad、FreeCAD、slicer、simulation等のadapter。プロセス境界と
  ライセンス境界を兼ねるMCP serverとして提供する。
- **plugin:** Skill、`AgentDefinition`、hooks、MCP設定、commandの配布単位。
  pluginはPython packageをimportせず、`ToolDefinition`も登録しない。ACD本体の
  配布経路ではなく、OpenHandsへ作業資材と設定を配布する経路である。

SDKのplugin loader（`openhands/sdk/plugin/plugin.py`）が読み込むのは、
`.plugin/plugin.json`または`.claude-plugin/plugin.json`、`skills/`、`commands/`、
`agents/`、`hooks/hooks.json`、`.mcp.json`等のファイル資材である。Python packageの
importや任意の`ToolDefinition`登録経路はない。`entry_command`も実行可能なPython
entry pointではなく、`/<plugin-name>:<entry_command>`というslash command名を返す
ためのmanifest値である。

Git由来のplugin、Skill、Canvas extensionの解決済みcommit SHAは、SDKの
`InstallationInfo.resolved_ref`とインストール先の`.installed.json`だけを出所とする。
`requested_ref`しかなく`resolved_ref`が無い資材はfail-closedとし、ACDはそのメタデータを
読み取ってsource、resolved SHA、内容hashをEvidenceへ束ねる。Skill／hook／MCP設定の実行
条件を固定するため、別の推測値やmanifest記載値をresolved SHAの代わりに使わない。

## SDK機能の活用方針

SDKの機能は実行、配布、反復、分業、防護の基盤として利用する。ただし設計グラフ、
投影、Evidence、決定論的ゲート、合否の正はACDに残す。ストレージとworkspaceの所在境界は
[`architecture.md`](architecture.md)に従い、OpenHands側へ移したファイル実体をACDの正へ
逆流させない。

### skills、plugin、marketplace

工程ごとのレビュー観点チェックリスト、ECAD操作手順をfrontmatter付き
Markdownの`Skill`として配布し、`KeywordTrigger`、`PathTrigger`、`TaskTrigger`で必要な
工程へ載せる。複数のskill、hooks、MCP設定、agent定義、commandをまとめて配布する場合は
`PluginManifest`を用い、marketplaceからGitHubまたはGitのURLでpluginを取得する。
skills repositoryとpluginの参照は信頼済みsourceに限定する。

Skillの記述、pluginの定義、triggerの発火はプロンプト資材または実行制御であり、設計グラフ
の正でも合否根拠にもならない。入力hashと実行結果は最小限の記録として残す。

### subagentとレビューの独立性

`AgentDefinition`で生成側とレビュー側を別のagent定義、別profile、別コンテキスト
として固定する。`AgentDefinition`の`name`、`description`、`model`、`tools`、`skills`、
`max_iteration_per_run`、`max_budget_per_run`、`hooks`、`mcp_config`、`permission_mode`、
`condenser`を役割ごとに明示する。定義のlevelは`project`、`user`、`builtin`、`plugin`、
`programmatic`から選び、設計の再現に必要なものはproject側で版管理する。

SDKのpresetは`default_tools()`、`get_default_agent()`、`get_planning_agent()`等のtool束・agent構成と、
builtinサブエージェント（`general-purpose`、`code-explorer`、`bash-runner`、`web-researcher`）を提供する。
FWレーンの実装・調査タスクやリポジトリ探索にはこれらを再利用し、同等のサブエージェントを自作しない。
ACDの工程agent（生成・レビュー・視覚レビュー）は役割境界と権限が異なるため、presetの流用ではなく
project levelの`AgentDefinition`として別途版管理する。

### 探索ループでのSDK機能割り当て

探索仕様の生成agentとレビューagentは`AgentDefinition`で分離する。観点別レビューは
`WorkflowTool`のmap/reduce、trade studyの枝は`Conversation.fork`で実行する。停止条件は
`run_goal`／`GoalController`と`StuckDetector`を実行機構としてのみ利用し、停止結果を合否根拠にしない。
予算は`ConversationStats`／`LLMRegistry`のusage別metricsで実測する。決定論的AI回帰は`TestLLM`、
視覚投影は`ImageContent`／`inspect_image_with_vision`を使う。L2探索層はSDKのagent反復ではなく、
外部プロセスまたは決定論コードとして実行する。

レビュー側はtoolsと`permission_mode`を絞り、設計グラフへ書き込めない構成にする。
ただしSDKのagent定義だけを信頼境界とはせず、共通executorとACDの権限検査でも書込みを
拒否する。レビューagentは自分または生成agentの成果物を修正して合格根拠にせず、
自然文の所見を生成する。合否は決定論的ゲートが行う。

### 視覚レビュー投影

レビュー投影は、表・netlist要約・マトリクス等の機械可読投影と、図・3Dビュー・
レイアウトビュー等の視覚投影に分ける。視覚投影はSDKの`ImageContent`へ画像を
`data:` URLとして渡すか、builtin tool `inspect_image_with_vision`で画像と質問を
vision対応の別LLM profileへ渡す。HTTP(S)画像はSDKのbase64インライン化とSSRF
block-listを通す。

画像hash、renderer種別、解像度、取得時刻を最小限の実行記録と
レビュー記録へ残す。visionの応答はAIレビューの観察であり、合否権限を持たない。
既定ゲートは描画非依存のままとし、視覚投影をゲートの合格根拠にしない。

### hooksによる前段防護

`PreToolUse`は発注や実機書込みなど不可逆操作の前段確認に、`PostToolUse`は副作用journalと
出力hashの記録点に使う。`UserPromptSubmit`、`SessionStart`、`SessionEnd`、`Stop`は
セッション境界や停止時の記録・後処理に利用する。`HookDecision`の`allow`／`deny`は
多層防御の一層であり、hookが`allow`したことも`deny`されなかったことも合格根拠にしない。
最終的な上限額、全ゲート、合否はACDの決定論的ゲートとパイプラインが担う。

`SessionStart` hookを起動時契約の強制点として使い、ACD packageのimport、外部ツール版
プローブ、Skill／plugin／Canvas extensionの`InstallationInfo.resolved_ref`と
`.installed.json`、MCP設定hashの記録を実行する。ACD独自Eventは最小限のgate結果、承認、
副作用receiptへの参照だけを扱うため、その型登録を必要とする経路に限定してimportを強制する。
未登録、版不明、`requested_ref`しかなく`resolved_ref`が無い、設定hash不一致などは
`HookDecision`でdenyし、セッションをfail-closedで開始しない。plugin導入だけではEvent型
登録にならないため、このhookを運用契約の検証点とする。

### critic、目標判定、停滞検出

ACDの決定論的ゲートをACD側で実行し、その結果を`CriticResult`へ写像してSDKの反復機構
だけを利用する。ゲート合格は`score=1.0`、不合格または例外は`score=0.0`とし、
確率的scoreを閾値判定へ使わない。`CriticResult`は`score`（0.0〜1.0）、`message`、
`metadata`を持つ。

`CriticBase`はソース上`EXPERIMENTAL`である。`AgentBase.critic`は単数であり、複数critic
を登録できないため、複数ゲートはACD側で合成する。`evaluate()`へ渡るのは会話イベントで
あり、現行経路の`git_patch`は常に`None`である。対象のgit commitはACD側で解決する。
criticの例外はSDK側で捕捉され、評価が無かった扱いになるため、ACDはゲート例外を自前で
捕捉して`score=0.0`へ写像し、fail-closedを保つ。

critic結果はEvidenceでも合否の正でもない。合否の正はACDゲートそのものである。
`agent_finished`、`empty_patch`、`pass_critic`、API basedのcritic結果も改善シグナルに
とどまり、決定論的ゲートの合格根拠にはならない。

`/goal`の`GoalController`と別LLMのjudge（`judge_goal`／`GoalVerdict`）は、PDCAが目標へ
収束したかを確認し、停止条件として上限まで再プロンプトする機構として使う。`GoalVerdict`
はEvidenceにせず、合否はゲートで判定する。`StuckDetector`はaction／observationの反復、
error連続、agentのmonologue、交互パターンなどの閾値を検出し、差し戻しまたは
エスカレーションを起動する。いずれもLLMまたは宣言的な補助機構であり、judgeの判定や
停滞検出結果は合否の判定面ではない。

### LLM可用性とmodel実体の記録

`LLMRegistry`はusage ID別にLLMインスタンスを管理し、metricsをインスタンス間で共有させない。
生成、機械可読レビュー、視覚レビューのprofile分離と`get_metrics_for_usage(usage_id)`による
コスト分解の実装基盤として使う。

`FallbackStrategy`は、接続断、rate limit、timeout、5xx等のtransient errorでretryが尽きた場合に、
`LLMProfileStore`のprofile列を順に試すper-callのfallback機構である。可用性のために採用できるが、
fallbackが起きると実際に応答したmodelが指名profileと異なるため、`log_completions` callbackで
実体model・prompt内容hashを必ず記録し、fallback先は同等能力のprofileに限定する。レビュー実行中に
fallbackで実体modelが変わった場合、そのレビュー結果のmodel版は`unknown`として記録する。
レビューは合否権限を持たないため、合否は決定論的ゲートで判定する。

`RouterLLM`（`MultimodalRouter`等）は、画像の有無やtoken量に応じてmodelを暗黙に選択する。
呼び出しごとにmodel実体が変わり、レビューのmodel／profile版固定と両立しないため採用しない。
vision対応modelへの切替は次項の`switch_llm`と別profileの明示指定で行う。LLMのtoken streaming
callbackはUI表示のみに使い、判定・記録の経路にしない。

`switch_llm`は工程境界でACDが明示的に呼び出す。生成、機械可読レビュー、視覚レビューの
profileを切り替えられるが、同一レビュー途中のAI起点の切替は禁止する。切替後の実体を
最小限の実行記録へ残し、レビュー途中の所見を合否根拠にしない。

### condenserとprofile

`LLMSummarizingCondenser`、`PipelineCondenser`、`NoOpCondenser`は長時間会話のcontext
圧縮に使う。圧縮後も入力・出力hash、ツール版、ゲート結果を
要約で置き換えず、ACDの永続記録から参照する。要約の欠落や誤りは`unknown`として扱い、
必要なEvidenceを再取得してから判定する。

`AgentProfile`は`llm_profile_ref`と`mcp_server_refs`を参照で持つため、at restでsecret-free
なmodel、prompt、tool構成の固定に使う。profile storeとresolverで解決した参照、版、解決
条件を最小限の実行記録へ残す。secretそのものをprofileや設計データへ複製しない。

SDKの二層persistent memory（`~/.openhands/memory/`と`<workspace>/.openhands/memory/`の
`MEMORY.md`）は、初回`run()`時に文字数上限付きでプロンプトへ読み込まれる作業メモリである。
位置づけはSkillと同じプロンプト資材であり、`KnowledgeItem`の正・Evidence・合否根拠にはならない。
project tierの`MEMORY.md`へ「現時点の標準」の要約を`KnowledgeItem`から投影・配布することは
できるが、その場合も内容hashと生成元revisionを記録し、memoryの記述から設計判断の正へ
逆流させない。

fab APIやprovider tokenはSDKの`SecretSource`として`SecretRegistry`へ登録し、ACDは
参照名だけを保持する。`StaticSecret`／`LookupSecret`、`conversation.update_secrets()`
の注入・masking・lookup back-offを利用し、graph、Evidence、log、commit、profileへ
secretを保存しない。`AgentProfile`の`llm_profile_ref`／`mcp_server_refs`と組み合わせ、
at rest secret-freeを維持する。

### 予算と外部計測

token、money、LLM latencyはSDKの`Metrics`／`MetricsSnapshot`、per-callの
`TokenUsage`／`ResponseLatency`、`accumulated_cost`を出所とする。`ConversationStats`の
`get_metrics_for_usage(usage_id)`でagent／profile単位へ分解し、生成者、レビュア、視覚レビュー
のコストを分離してEvidenceへ束ねる。外部process回数と外部toolのwall-clockはACD tool
最小限の実行記録へ残し、両者を混同しない。実行上限とretryは
`AgentDefinition.max_budget_per_run`／`max_iteration_per_run`、SDKのMetrics／LLM retryへ
委譲し、実測値と`unknown`境界をEvidenceへ記録する。ACDが持つのは外部tool実測と
独自のretry・予算会計は持たない。

### task ledgerと実行分岐

agent-serverの`WebhookSpec`はtask ledgerと実行状態の低遅延取り込み経路に限る。webhookは
task状態・実行状態の正でも、副作用journal・ドメイン記録の正でもない。
buffer、flush timer、リクエストサイズ上限付きのPOSTを利用し、ACD側でpollingを自作しない。
agent-serverの`/sockets` WebSocket購読も同じ位置づけの低遅延取り込み経路として使えるが、
接続断・欠落を前提とし、正はwebhookと同様にEventLog replayへ置く。
配信保証は未確認なので、task状態・実行状態の取り込みの正はEventLog replayに置く。副作用
journalとドメイン記録の正はcommit済みEvidence artifactに置き、webhookは重複・欠落を前提に
idempotentに処理する。
trade studyやPhase 6の協調修復では`Conversation.fork(from_event_id=...)`で子conversation
を作る。採用した修正は入力ファイルへ反映し、非採用枝は会話履歴として残す。
低遅延journalの利便性を諦め、commit側へ寄せることで可搬性とrevision結合を優先する。

agent-serverのOpenAI互換gatewayは、PLM、ERP、チャットツール、社内ポータルからの照会、
起票、状態取得に限定して使う。gatewayから合否、承認、発注や実機書込みなどの不可逆操作を
駆動せず、ACD共通executorのtyped契約と決定論的ゲートを必ず経由する。gatewayの認証や
session key相当だけでは決定論的ゲートを代替できないためである。

### securityと分業

analyzer、`ConfirmationPolicy`、risk、ensemble、defense-in-depthのpattern／policy rails、
shell AST／parserを、外部コマンドと不可逆操作の多層防護へ使う。SDKの
`LLMSecurityAnalyzer.security_risk()`は`ActionEvent`に付いているLLM由来のrisk値を
そのまま返すだけで、独立した検証を行わない。したがってLLM analyzerは補助であり、
安全境界、発注、実機書込みの最終判定を代替しない。

ACDの`SB1`／`SB2`判定は`SecurityAnalyzerBase`の実装として追加し、
`EnsembleSecurityAnalyzer`へ組み込む。ensembleはriskの最大値を採り、unknownを伝播し、
analyzer例外をHIGH扱いにできる。防護のどの層でも不明、矛盾、解析不能はfail-closedとし、
ACDの決定論的ゲートへ戻す。

confirmation policyは`ConfirmRisky(threshold=HIGH, confirm_unknown=True)`を既定とする。
`NeverConfirm`は不可逆操作を含む構成で採用しない。確認待ち状態と承認画面はSDKの
`ConfirmationPolicy`とCanvas extensionへ寄せ、発注は上限額と発注直前の全ゲートで制御する。

`WorkflowTool`／`WorkflowExecutor`、`task`、`task_tracker`、`delegate`を電気・機械・FW
レーンの分業と反復実行へ使う。`map/reduce`のreduceが束ねるのは自然文の所見であり、
投影そのものではない。SDK側のtask状態、delegateの完了報告、workflowの成功状態は
ACD独自のtask ledgerを正としない。成果物は入力ファイルから再生成し、各レーンの成果物を
意味的にmergeしない。
workflow scriptはLLMが書くPythonであるため、その実行結果を合否根拠にしない。

`ACPAgent`は採用しない。ACP側がLLM、tool、実行を保持するため、実prompt内容hash、model実体版、
tool schema、`log_completions`をACD側で確実に取得できないためである。

`observability/laminar.py`は任意の計測として導入できるが、導入する場合も、計測値を
Evidenceや合否判定へ自動昇格させない。可観測性は実行の理解を助けるものであり、判定面ではない。

CAD/EDA外部プロセスがファイルを保持している間は、worktreeの切替・復元と外部ツール実行を
排他にする。adapterはプロセス終了とファイルハンドル解放を確認し、隔離した設定ディレクトリ
で実行する。切替・復元後は入力ファイルから投影を再生成し、再読込とゲートを再実行する。

### ワークツリーとリソース排他

`DeclaredResources(keys=..., declared=...)`と`ResourceLockManager`／
`ParallelToolExecutor`によるresource lockを、ワークツリー操作と外部ツール実行の
排他の一次機構として使う。ACDが関係toolを自前で包み、共通キー（例：worktreeパス）
を宣言する。既定のterminal toolは`terminal:session`を使い、MCP toolはresource宣言が
なく`tool:<name>`へフォールバックするため、ACDのworktreeキーを共有しない。

ロックは`ParallelToolExecutor`インスタンス単位であり、conversation、executor、プロセスを
またぐグローバル排他ではない。プロセス終了とファイルハンドル解放の確認はACD側の責務として
残る。agent-serverの`conversation_service.py`の`_create_conversation_worktree()`は、
会話ごとに`git fetch origin`、`git worktree add -b`、`git worktree remove --force`、
`git worktree prune`、`git branch -D`を内部実行する。1 conversation = 1 worktreeを
作業revisionの隔離単位に利用できるが、これはagent-server内部処理であり公開typed APIではない。

## MCP接続

外部ツールadapter（KiCad、FreeCAD、slicer、simulation等）はMCP serverとして提供し、
プロセス境界とライセンス境界を兼ねる。SDKのMCP統合が提供するのは、接続、
`list_tools()`による動的discovery、runtime JSON SchemaからのPydantic Action生成、
`MCP_TOOL_TIMEOUT_SECONDS = 300`、reconnect、error observation、secret展開、maskingである。
SDKが提供しないのはserver版の固定、tool semantic version、runtime schema変更の承認、
artifact hashと最小実行記録であり、ACDは決定論的ゲートを担う。
MCP serverが返す成功文字列を合格Evidenceとはせず、生成artifactを再読込し、
決定論的gateを別途実行する。

agent-serverはMCP OAuth資格情報をsettingsの暗号化・redaction経路へ保存する
token store（`mcp_oauth_store.py`）を持つ。OAuth認証が必要なsourcing系MCP serverでは
この経路を一次候補とし、tokenをACD側のgraph、Evidence、profileへ複製しない。動作条件は
Phase 9で一次確認する。

### sourcingとbrowser経路

Phase 9のsourcingはAPI経路を一次とし、型付きAPIがない場合だけSDKの`browser_use`
toolset（navigate、click、type、get_state、get_content、screenshot、tabs）を二次経路
として使う。browser取得値はURL、取得時刻、screenshot hash、git commit、期限を持つ
Evidenceとして記録し、DOM取得の非決定性を`unknown`境界に含める。browser経路はPhase 11
の発注実行には使わず、期限切れまたはscreenshot hash不一致の値を合格根拠にしない。

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

## 採用しない・継続調査のSDK機能

- `RouterLLM`／`MultimodalRouter`: 暗黙のmodel選択がmodel版固定と両立しないため採用しない（前述）。
- `ACPAgent`: Evidence契約を満たせないため採用しない（前述）。
- `TomConsultTool`／`SleeptimeComputeTool`（tom_consult）: 外部Tom agent（tom-swe package）へ
  会話履歴を渡してユーザー意図・好みの理解を得るtoolである。S1要件対話の意図理解の補助候補と
  するが、外部package依存と会話履歴の外部送信範囲が未検証であり、継続調査とする。採用する場合も
  応答は観察データであり、要求の正は設計グラフの`Requirement`とユーザー確認に置く。

## SDKが保証しないこと

- typedなgit commit／push／branch作成／mergeのAPI。
- Skill／pluginのsourceの安全性。Skillはshellを実行できるため、信頼済みsourceに限定する。
- prompt内容やmodel実体の版をEvidenceへ自動的に束ねること。実プロンプトと応答は
  `LLM.log_completions`／`log_completions_folder`または
  `telemetry.set_log_completions_callback()`で取得できるため、ACDはcallbackで内容hashを
算出し、SDKの会話履歴と最小実行記録へ残す。
- 外部定義Eventを、ACD packageのimportなしで読み戻すこと。
- 外部副作用を含む決定論的replay。
- LocalWorkspaceでのホスト権限・ファイル・ネットワークの完全分離。LocalWorkspace自体を
  実行基盤の対象外としたため、これはSDKの不足を補う契約ではなくACDが採用しない経路の整理である。
- SDKの`FileStore`（`LocalFileStore`／`InMemoryFileStore`）に対応しないremote FileStore実装。
  ACD側で保存が必要な場合も独自I/Fを作らずSDK抽象へ合わせる。
- SDKの確認機構だけで決定論的な発注判定を代替すること。
- KiCad、FreeCAD、SPICE、slicerの設計意味論や製造妥当性。
- 外部サービスの価格、在庫、発注状態の永続的な正確性。
- FWの機能的正しさ、書き込み・実機ログの再現性、ターゲット固有の意味論。
- critic、`/goal` judge、LLM security analyzer、hookは確率的または宣言的な機構であり、
  決定論的ゲートとEvidenceを代替しない。
- `ACPAgent`経由でEvidence契約に必要なprompt、model、tool schema、log_completionsを
  自動的に取得すること。

したがって、OpenHandsは実行基盤であって、ACDのcanonical graph、gate、Evidence、
approval、side-effect journalを代替しない。

## 公開先行事例

`docs/prior-art.md`の調査では、OpenHands SDKを使った公開のハードウェア/CAD設計先行
事例は確認できなかった。OpenHandsからKiCad、FreeCAD、agentcad、slicerを呼ぶことは
ACDの統合案であり、既存事例の実績ではない。
