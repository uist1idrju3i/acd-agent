# ADR-0026: OpenHands委譲契約

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.43.1

## コンテキスト

ACDはOpenHands Software Agent SDK v1.43.1（pinned checkout）に固有契約を追加する。
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
実行形は`LocalConversation` + `DockerWorkspace(server_image=...)`である。
以前のSDKのdev workspace経路（on-the-fly build）は移行前の開発・テスト経路として
歴史的に記録し、現在のauthoritative実行経路には含めない。CI/Docker経路でのみ
合格側Evidenceを昇格する。host経路はprovisional専用である。

6.3〜6.5でrunnerとCIの移行を完了し、事前build済みdigest固定server imageを
`DockerWorkspace`で実行する。server digestがlockへ記録されるまで、lock解決は
fail-closedで停止する。

## Agent安全境界

ACDのagent経路に必要な確認、secret注入、Skill資材配布、停滞検知は、独自基盤を追加せず
pinned OpenHands SDK v1.43.1のL2機能へ委譲する。`AcdSecurityAnalyzer`とSDKの
`PatternSecurityAnalyzer`を`EnsembleSecurityAnalyzer`へ渡し、`LLMSecurityAnalyzer`、
`ToolShieldLLMSecurityAnalyzer`、`GraySwanAnalyzer`は採用しない。Conversationには
`ConfirmRisky(threshold=SecurityRisk.MEDIUM)`を設定し、HIGHとMEDIUMは確認し、LOWは
通過させる。

明示allowlistの環境変数だけをlazy `SecretSource`として`LocalConversation(secrets=...)`
へ渡し、`SecretRegistry.mask_secrets_in_output()`を出力maskingの権威とする。secret値は
ログ、`ToolEnvelope`、Evidenceへ入れない。`load_skills_from_dir()`で
`plugins/acd/skills`だけを読み、壊れた資材はwrapperの事前検証とロード数照合で
fail-closedにする。`LocalConversation(stuck_detection=True)`と
`StuckDetectionThresholds`は停止・修正の操舵に限定する。

## Goal loopと中断・観測境界

SDKの`GoalController`をACD固有driverから再利用し、SDKの`run_goal()`は使わない。
ACD driverは各run後の`execution_status`を観測し、`PAUSED`ならjudgeを呼ばず
`interrupted`で終了する。judgeの`GoalVerdict`は反復制御だけに使い、
`gate_passed`と`authoritative`はACDの決定論的判定からのみ導出する。判定未指定または
例外時は`False`へ倒す。

SIGINTは`LocalConversation.interrupt()`へ結線し、handlerはcontext manager終了時に元へ
戻す。`goal_result`と`conversation_stats`は`pass_evidence=false`の観測成果物とし、
`ConversationStats`はcombined metricsとusage別snapshotを記録する。

## lane並列とsub-agent境界

ACDは`tool_concurrency_limit`の既定値1を維持し、2以上は呼び出し側の明示指定に限る。
`acd_*` toolは入力graphと出力directoryを`DeclaredResources`へ明示し、path解決不能時は
`declared=False`としてSDKのmutexによる直列化へ倒す。

5つのACD `AgentDefinition`へhooks.jsonの必須hookを明記し、検査はfrontmatter文字列
ではなく`AgentDefinition.load()`後の`HookConfig`を対象にする。task/delegateはL2の
実行・操舵経路とし、sub-agentの結果をEvidenceへ昇格しない。sub-agentへ親hookが
自動継承されないため、必須hookを各定義へ明記する。workflowは任意Python script実行の
安全境界を含めて別途判断する。

## 統合後の権限境界

critic、security analyzer、Skill、GoalController、cancellation、parallel executor、
task、delegate、sub-agentはいずれもL2の操舵・停止層であり、Evidenceを生成・昇格しない。
ConversationStats、event、metrics、telemetryはL3観測層である。L1の合否は、digest固定
containerで実行されたrevision一致の決定論的gateとauthoritative Evidenceだけが担う。
中断、judge評決、hook drift、資源宣言不能、path解決失敗を合格へ倒さず、fail-closedとする。

## agent-server境界

agent-serverはACDの対象外とする。将来採用する場合は、認証・権限・Evidence境界の受入
条件を定義した新規ADRを起票してから検討する。現行の実行経路をagent-serverへ置き換えない。

## 不採用

MCP、marketplace、extensions、Canvas、VSCode、desktop、Apptainer、remote API、cloud、
Gemini、Tom Consult、Apply Patch、ACP agentは、現行のOpenHands-only scopeとprovenance
境界に合わないため不採用とする。agent-serverは非対象として別途管理する。
installed pluginの自動読み込みによるインストール経路はADR-0036で採用へ変更した。
MarketplaceRegistryは引き続き不採用とする。

## 統合したADR

ADR-0003、0009、0010、0013、0014、0015、0016、0017、0018、0019、0020、0024、0025、
0029、0030、0031。
