# OpenHands SDK能力カタログ

> 対象: v1.42.1 / submodule commit `167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497`
>
> v1.42.1より新しい上流release tagはない。pinned checkoutをAST traversalして機械抽出した。
> 本表にない挙動は未検証であり、生成物やローカル生成パスは根拠にしない。

| 能力ドメイン | 代表API | ACDでの用途 | 採否 | 根拠 | 検証手段 |
|---|---|---|---|---|---|
| sdk.skills | `skills` | Skill資材の配布・起動 | 採用予定 | checkoutに存在 | AST/単体 |
| sdk.settings | `settings` | SDK設定の解決 | 採用予定 | checkoutに存在 | 設定試験 |
| sdk.credential | `credential.py` | secret参照の解決 | 採用 | checkoutに存在 | redaction試験 |
| sdk.utils | `utils` | SDK共通補助 | 採用予定 | checkoutに存在 | AST/単体 |
| sdk.banner | `banner.py` | 起動情報表示 | 不採用 | ACD合否に不要 | 未検証 |
| agent.parallel_executor | `ParallelToolExecutor` | agent lane並列化 | 採用予定 | checkoutに存在 | 固定順fixture |
| agent.response_dispatch | `response_dispatch` | 応答配信 | 採用予定 | checkoutに存在 | event回帰 |
| conversation | `LocalConversation`, `ConversationState` | 対話・履歴・保存 | 採用 | checkoutに存在 | resume/fork |
| conversation.stuck_detector | `StuckDetector` | 停滞時差し戻し | 採用予定 | checkoutに存在 | stuck fixture |
| conversation.cancellation | cancellation APIs | 中断・停止 | 採用 | checkoutに存在 | cancellation試験 |
| conversation.secrets_manager | `SecretsManager` | secret注入・漏洩防止 | 採用 | checkoutに存在 | redaction試験 |
| context.prompts.sections.planning | `planning` | 計画文脈の供給 | 採用予定 | checkoutに存在 | prompt snapshot |
| context.view.properties | view properties | 観測文脈の制御 | 採用予定 | checkoutに存在 | context回帰 |
| tools.utils | `tools.utils` | tool補助 | 採用予定 | checkoutに存在 | AST/単体 |
| ToolDefinition | `ToolDefinition`, `Action`, `Observation` | 唯一のagent入口 | 採用 | checkoutに存在 | schema/negative |
| tools.preset | `preset` | 汎用tool束 | 不採用 | ACD契約と競合 | 未検証 |
| browser_use | browser toolset | 後段の二次sourcing | 採用予定 | inventory確認 | SSRF/fixture |
| Canvas/VSCode/desktop | canvas/vscode extensions | GUI経路 | 不採用 | ACDの正に不要 | 未検証 |
| Tool/ToolSet | tool classes and sets | tool登録 | 採用 | checkoutに存在 | import/実行 |
| agent-server tool_router | `tool_router` | server routing | 不採用 | 現行承認経路外 | 未検証 |
| tool_preload_service | `tool_preload_service` | tool preload | 不採用 | 現行承認経路外 | 未検証 |
| settings_router | `settings_router` | server設定API | 不採用 | agent-server不採用 | 未検証 |
| llm_router | `llm_router` | 暗黙LLM routing | 不採用 | model固定と非両立 | 未検証 |
| init_router | `init_router` | server初期化API | 不採用 | agent-server不採用 | 未検証 |
| server_details_router | `server_details_router` | server情報API | 不採用 | agent-server不採用 | 未検証 |
| workspace_router/workspaces_router | router APIs | workspace管理 | 不採用 | 現行形を限定 | 未検証 |
| profiles_router/agent_profiles_router | router APIs | profile管理 | 不採用 | agent-server不採用 | 未検証 |
| credential_binding | `credential_binding` | credential binding | 採用予定 | checkoutに存在 | secret試験 |
| middleware | server middleware | 認証・境界 | 不採用 | agent-server不採用 | 未検証 |
| pub_sub | `pub_sub` | event配信 | 採用予定 | checkoutに存在 | event回帰 |
| openapi | OpenAPI schemas | API契約投影 | 不採用 | server API不採用 | 未検証 |
| env_parser | `env_parser` | 環境設定解析 | 採用予定 | checkoutに存在 | 設定試験 |
| mcp_oauth_store | `mcp_oauth_store` | MCP OAuth | 不採用 | OpenHands-only scope | 未検証 |
| _secret_redaction/_secrets_exposure | secret redaction | secret漏洩防止 | 採用 | checkoutに存在 | redaction試験 |
| canvas_extensions/vscode_extensions | extension APIs | GUI拡張 | 不採用 | GUIを採用しない | 未検証 |
| bash_service | `bash_service` | server bash実行 | 不採用 | Workspace境界を使用 | 未検証 |
| sockets | socket APIs | server transport | 不採用 | agent-server不採用 | 未検証 |
| telemetry | telemetry APIs | L3観測・metrics | 採用予定 | checkoutに存在 | metrics回帰 |
| persistence | persistence APIs | Conversation保存 | 採用 | checkoutに存在 | resume/fork |
| conversation_lease | `conversation_lease` | lease競合制御 | 採用予定 | checkoutに存在 | 並列fixture |
| docker | `DockerWorkspace` | ゲート実行環境 | 採用 | 承認済み実行形 | digest固定 |
| GoalController | `run_goal`, `GoalVerdict` | 反復停止補助 | 採用予定 | checkoutに存在 | stop-side |
| security analyzer | security analyzers | agent操作監視 | 採用予定 | inventory確認 | deny/allow |
| LLM routing | `LLMRegistry`, `FallbackStrategy` | profile・予算観測 | 採用予定 | checkoutに存在 | metrics回帰 |
| MCP/marketplace/extensions | MCP, marketplace | 外部拡張配布 | 不採用 | provenance境界 | 未検証 |
| Apptainer/remote/cloud | remote workspace APIs | 遠隔実行 | 不採用 | DockerWorkspace限定 | 未検証 |
| Gemini/Tom Consult/Apply Patch | provider/integration APIs | 外部固有経路 | 不採用 | ACD契約に不要 | 未検証 |
| ACP agent | `ACPAgent` | 外部agent実行 | 不採用 | Evidence束ね不可 | 未検証 |

L1の合否は決定論的ゲートと`Evidence.supports_pass(revision)`のみが担う。Skill、critic、
GoalController、agent、analyzer、event、metricsはL2/L3として停止・修正・観測に使えるが、
合格を生成しない。
