# OpenHands SDK能力カタログ

> 対象: v1.42.1 / submodule commit `167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497`
>
> v1.42.1より新しい上流release tagはない。pinned checkoutをAST traversalして機械抽出した。
> 「採用」は現行コードまたはplugin資材で使用中、「採用予定」は未使用だが採用を決定済み、
> 「不採用」は採用しないと決定した能力を表す。未確認の挙動は「未検証」とする。

| 能力ドメイン（パッケージ） | 代表API | ACDでの用途 | 採否 | 根拠 | 検証手段 |
|---|---|---|---|---|---|
| sdk.agent | `Agent`, `AgentDefinition` | pluginの役割別agent | 採用 | `plugins/acd/agents/`がAgentDefinitionを参照 | plugin資材検査、agent起動 |
| sdk.conversation | `LocalConversation`, `ConversationState` | 現行agent session | 採用 | `src/acd/openhands/agent_session.py`で使用 | session回帰 |
| sdk.critic | `CriticBase`, `CriticResult`, `IterativeRefinementConfig` | gate結果によるL2操舵 | 採用 | `gate_critic.py`で使用し、pass authorityにしない | critic回帰、negative |
| sdk.context.condenser | `LLMSummarizingCondenser` | 長い対話の圧縮 | 採用 | `agent_session.py`で使用し、Evidenceを置換しない | resume/fork回帰 |
| sdk.hooks | `HookConfig`, `HookEventType`, `HookExecutionEvent` | agent経路の停止側境界 | 採用 | `plugins/acd/hooks/`がSDK hook契約を使用 | DENY/allow試験 |
| sdk.git | `get_git_changes`, `GitError` | stale判定へのgit入力 | 採用 | `src/acd/openhands/evidence_git.py`で使用 | dirty/stale fixture |
| sdk.plugin | `PluginSource` | pinned plugin配布 | 採用 | `src/acd/openhands/plugin_distribution.py`でSHA/tagを固定 | ref検証、拒否試験 |
| sdk.tool | `ToolDefinition`, `Tool`, `register_tool`, `list_registered_tools` | ACD toolのagent入口 | 採用 | `register_acd_tools()`とSDK登録を使用 | schema/実行試験 |
| sdk.llm | `LLM`, `Message`, `TextContent` | Conversation/LLM入出力 | 採用 | 現行session配線で使用 | prompt回帰 |
| sdk.llm.utils.metrics | `Metrics` | 使用量・予算の観測 | 採用 | 現行SDK wiringでmetricsを扱う | metrics回帰 |
| sdk.testing | `TestLLM` | SDK wiringの回帰 | 採用 | test fixtureとbootstrap回帰で使用 | pytest |
| sdk.event | `Event`, `MessageEvent`, `EventLog` | session経過の記録 | 採用 | Conversationのイベント経路で使用 | event/resume回帰 |
| sdk.security | `ConfirmRisky`, `NeverConfirm`, `permission_mode` | agent操作の安全境界 | 採用 | 現行conversationへMEDIUM以上の確認方針を設定 | risky/deny試験 |
| sdk.subagent | agent loader/factory | 役割別sub-agent | 採用 | `plugins/acd/agents/`で参照 | agent資材検査 |
| sdk.skills | `load_skills_from_dir(skill_dir: str | Path) -> tuple[dict[str, Skill], dict[str, Skill], dict[str, Skill]]` | ローカルACD Skillの配布・prompt提供 | 採用 | `build_acd_conversation()`が`plugins/acd/skills`を明示ロードし、壊れた資材はfail-closed | Skill loader回帰 |
| sdk.profiles | `AgentProfile`, `AgentProfileStore` | secret-free profile配布 | 採用予定 | profile driftを管理する採用方針 | 未検証 |
| sdk.secret | `SecretSource`, `StaticSecret`, `LookupSecret` | secretを平文から分離 | 採用 | allowlist環境変数をlazy sourceとしてConversation registryへ渡す | registry masking回帰 |
| sdk.security.analyzer | `SecurityAnalyzerBase`, `PatternSecurityAnalyzer`, `EnsembleSecurityAnalyzer`, `SecurityRisk` | agent操作の決定論的追加監視 | 採用 | ACD analyzerとPattern analyzerをSDK ensembleへ合成し、LLM/GraySwanは使わない | risk/ensemble回帰 |
| sdk.context.memory | `MEMORY.md` memory | 作業文脈の補助 | 採用予定 | 契約・合否の正にしない前提で採用 | 未検証 |
| sdk.context.prompts | `Prompt`, `PromptSection`, preset/registry/section、static/dynamic/planning | role別prompt構造化 | 採用予定 | prompt hashと資材固定を条件に採用 | 未検証 |
| sdk.context.view | context/event view properties | 長時間sessionの表示 | 採用予定 | 原EventLogと照合し、Evidenceを置換しない | 未検証 |
| sdk.agent.parallel_executor | `ParallelToolExecutor` | agent lane並列化 | 採用予定 | 固定順集約と共有resource宣言を条件に採用 | 未検証 |
| sdk.tools.task | `TaskToolSet` | task分離 | 採用予定 | 主会話の汚染を減らすが合否権限なし | 未検証 |
| sdk.tools.delegate | `DelegateExecutor`, `delegate`, `spawn` | sub-agent調整 | 採用予定 | resource lockと停止側権限を条件に採用 | 未検証 |
| sdk.tools.workflow | `WorkflowToolSet`, `map_agents`, `reduce_agent`, `pipeline` | lane並列化のmap/reduce | 採用予定 | 電気・機械・FW laneの並列化に限り、決定論的探索と投影の意味的mergeは委譲しない | 未検証 |
| sdk.conversation.goal | `GoalController`, `GoalVerdict` | 反復停止の補助 | 採用 | L2停止側に限り、L1合否を置換しない | `tests/openhands/test_goal_loop.py` |
| sdk.conversation.stuck_detector | `StuckDetector`, `StuckDetectionThresholds` | 停滞時の差し戻し | 採用 | `LocalConversation(stuck_detection=True)`へ既定値・閾値を渡す | conversation wiring回帰 |
| sdk.conversation.cancellation | `CancellationToken`, `LocalConversation.interrupt()`, `pause()` | 対話中断 | 採用 | SIGINTからinterruptへ結線し、L2停止側に限定 | `tests/openhands/test_goal_loop.py` |
| sdk.conversation.secrets_manager | `SecretsManager` | secret注入・漏洩防止 | 採用 | pinned registryのmaskingとlazy secret注入を現行Conversationで使用 | registry回帰 |
| sdk.conversation.conversation_stats | `ConversationStats` | session別使用量観測 | 採用 | L3観測として採用し合否に混入しない | `tests/openhands/test_goal_loop.py` |
| sdk.llm.router | `RouterLLM`, `RandomRouter`, `MultimodalRouter` | 将来のprofile routing | 採用予定 | 固定profileと予算記録を条件に採用 | 未検証 |
| sdk.observability | `observe`, Laminar初期化 | L3 telemetry | 採用予定 | 送信先・sanitizer・既定無効を固定する | 未検証 |
| sdk.io | `FileStore`, `LocalFileStore`, `InMemoryFileStore` | session保存抽象 | 採用予定 | git/inputを正とし二重の合否状態を持たない | 未検証 |
| sdk.logger | structured logger | 運用診断 | 採用予定 | secretとEvidenceをログへ混入させない条件付き | 未検証 |
| sdk.settings | `settings` | SDK設定解決 | 採用予定 | 設定の明示固定を行う | 未検証 |
| sdk.credential | `credential.py` | secret参照 | 採用予定 | 未使用でありsecret manager導入時に採用 | 未検証 |
| sdk.utils | `utils` | SDK内部補助 | 不採用 | 内部補助をACDが直接依存しない | 未検証 |
| sdk.tools.utils | `tools.utils` | SDK内部補助 | 不採用 | 内部補助をACDが直接依存しない | 未検証 |
| sdk.agent.response_dispatch | `response_dispatch` | SDK内部応答配信 | 不採用 | ACDが直接依存する責務ではない | 未検証 |
| sdk.marketplace | marketplace catalog/installer | 外部資材取得 | 不採用 | pinned PluginSourceでprovenanceを固定する | 未検証 |
| sdk.mcp | `MCPClient`, `MCPToolDefinition` | MCP連携 | 不採用 | OpenHands-only extensionにMCP互換層を追加しない | 未検証 |
| sdk.extensions | extension registry | 外部拡張 | 不採用 | Canvas等の別UI・拡張境界を持ち込まない | 未検証 |
| tools.terminal | `TerminalTool` | agentのCLI実行 | 採用 | AgentDefinitionの標準toolとして参照 | agent実行試験 |
| tools.file_editor | `FileEditorTool` | agentのファイル編集 | 採用 | AgentDefinitionとhook保護経路で参照 | hook/編集試験 |
| tools.grep | `GrepTool` | agent検索 | 採用 | AgentDefinitionの標準toolとして参照 | agent実行試験 |
| tools.glob | `GlobTool` | agent検索 | 採用 | AgentDefinitionの標準toolとして参照 | agent実行試験 |
| tools.task_tracker | `TaskTrackerTool` | agent作業追跡 | 採用 | AgentDefinitionの標準toolとして参照 | agent実行試験 |
| tools.apply_patch | `ApplyPatchTool` | patch編集 | 不採用 | ACDの明示的tool集合と保護hookを単一化する | 未検証 |
| tools.planning_file_editor | planning file editor | 計画ファイル編集 | 不採用 | file_editorと保護hookの単一経路を維持する | 未検証 |
| tools.browser_use | browser toolset | 後段の二次sourcing | 採用予定 | 発注・SSRF・価格Evidenceを別途固定する | 未検証 |
| tools.gemini | Gemini tools | 外部provider | 不採用 | ACDの固定provider境界外 | 未検証 |
| tools.tom_consult | `TomConsultTool` | 外部相談 | 不採用 | 合否に関与しない経路を増やさない | 未検証 |
| tools.preset | tool preset loader | 暗黙tool束 | 不採用 | tool集合を明示固定する | 未検証 |
| tools.preset.standard | standard presets | 汎用tool束 | 不採用 | ACD固有ToolDefinitionで登録する | 未検証 |
| workspace.LocalWorkspace | `LocalWorkspace` | agent作業workspace | 採用予定 | 現行の承認実行形はdigest固定containerへ限定し、hostは参考実行とする | 未検証 |
| workspace.DockerWorkspace | `DockerWorkspace` | 事前build済みdigest固定server imageの実行 | 採用予定 | 現行runnerはbase imageから準備するため未使用。配布済みserver imageへ移行後に採用 | vendor実装のconstructorとdocstringを確認 |
| workspace.DockerDevWorkspace | `DockerDevWorkspace` | 現行runnerのbase imageからagent-server imageを準備 | 採用 | `src/acd/openhands/workspace.py`が`base_image`で実行 | vendor実装、runner回帰 |
| workspace.apptainer | `ApptainerWorkspace` | Apptainer実行 | 不採用 | DockerWorkspace一本化 | 未検証 |
| workspace.remote_api | `APIRemoteWorkspace` | remote API実行 | 不採用 | remote APIを範囲外とする | 未検証 |
| workspace.cloud | OpenHands Cloud workspace | cloud実行 | 不採用 | 再現性と運用境界を固定できない | 未検証 |
| agent-server.conversation_router | conversation endpoints | server対話 | 採用予定（agent-server着手時） | 現行経路外で、将来受入条件に限定 | 未検証 |
| agent-server.event_router | event endpoints | server event取得 | 採用予定（agent-server着手時） | L3観測に限定しEvidence化しない | 未検証 |
| agent-server.tool_router | `tool_router` | server tool routing | 採用予定（agent-server着手時） | 現行agent入口ではなく将来構想 | 未検証 |
| agent-server.tool_preload_service | `tool_preload_service` | server tool preload | 不採用 | 現行実行形に直接依存しない | 未検証 |
| agent-server.settings_router | `settings_router` | server設定API | 採用予定（agent-server着手時） | server着手時の設定境界 | 未検証 |
| agent-server.llm_router | `llm_router` | server LLM routing | 不採用 | 暗黙routingはmodel固定と非両立 | 未検証 |
| agent-server.init_router | `init_router` | server初期化 | 採用予定（agent-server着手時） | 将来server起動契約の一部 | 未検証 |
| agent-server.server_details_router | `server_details_router` | server情報 | 採用予定（agent-server着手時） | 将来運用診断の一部 | 未検証 |
| agent-server.workspace_router/workspaces_router | workspace routers | server workspace管理 | 採用予定（agent-server着手時） | DockerWorkspace受入時に検証 | 未検証 |
| agent-server.profiles_router/agent_profiles_router | profile routers | profile配布 | 採用予定（agent-server着手時） | secret-free profileを条件にする | 未検証 |
| agent-server.credential_binding | `credential_binding` | server credential binding | 採用予定（agent-server着手時） | SDK secret経路と分離して検証 | 未検証 |
| agent-server.middleware | middleware | server認証・境界 | 採用予定（agent-server着手時） | 直接APIへの適用範囲を確認する | 未検証 |
| agent-server.pub_sub | `pub_sub` | server event配信 | 不採用 | SDK Conversation/eventを正とし直接依存しない | 未検証 |
| agent-server.openapi | OpenAPI schemas | server API投影 | 採用予定（agent-server着手時） | API利用時のみ契約投影として使う | 未検証 |
| agent-server.env_parser | `env_parser` | server環境解析 | 不採用 | SDK内部補助をACDが直接依存しない | 未検証 |
| agent-server.mcp_oauth_store | `mcp_oauth_store` | MCP OAuth | 不採用 | MCPを採用しない | 未検証 |
| agent-server._secret_redaction/_secrets_exposure | secret redaction | server secret漏洩防止 | 採用予定（agent-server着手時） | server採用時の停止境界に限定 | 未検証 |
| agent-server.canvas_extensions/vscode_extensions | extension APIs | GUI拡張 | 不採用 | Canvas/VSCode/desktopを採用しない | 未検証 |
| agent-server.bash_service | `bash_service` | server bash | 不採用 | ToolDefinitionとWorkspace境界を使う | 未検証 |
| agent-server.sockets | socket APIs | server transport | 採用予定（agent-server着手時） | server着手時の通信境界 | 未検証 |
| agent-server.telemetry | telemetry exporters | server L3観測 | 採用予定（agent-server着手時） | SDK observabilityと混同せずserver時のみ | 未検証 |
| agent-server.persistence | persistence APIs | server Conversation保存 | 採用予定（agent-server着手時） | SDK conversation保存と別のserver機能 | 未検証 |
| agent-server.conversation_lease | `conversation_lease` | server所有権 | 採用予定（agent-server着手時） | 複数instance受入時に検証 | 未検証 |
| agent-server.docker | server Docker build | server image build | 採用予定（agent-server着手時） | digest記録を条件にする | 未検証 |

ACD固有のDesign Graph、Pydantic契約、投影、EDA/CAD adapter、fabrication制約、
決定論的ゲート、`Evidence.supports_pass(revision)`、決定論的探索、rationale契約は
SDKへ委譲しない。L1のpass authorityはこれらの決定論的責務だけであり、L2のcritic・Skill・
agent・GoalController・security analyzerとL3のevent・metrics・telemetryは合格を生成しない。
