# OpenHands SDK v1.42.1機能採否

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.42.1

この文書は、SDK v1.42.1の公開機能をACDの境界へ写像する単一の正である。
状態は「採用済み」「採用候補」「不採用」の三語だけを使用する。
合否の権限は決定論的ゲートに限り、詳細は[`ADR-0023`](adr/ADR-0023-deterministic-gate-authority.md)を参照する。

## 機能網羅表

| 機能 | 主なSDK API | 状態 | ACD側の実装ファイルまたは理由 |
|---|---|---|---|
| tool | `ToolDefinition`、`Action`、`Observation`、`ToolAnnotations`、`ToolExecutor`、`register_tool` | 採用済み | `packages/acd-tools/src/acd_tools/sdk_tools.py` |
| hooks | `HookConfig`、`HookMatcher`、command hook | 採用済み | `plugins/acd/hooks/` |
| critic | `CriticBase`、`CriticResult`、`IterativeRefinementConfig` | 採用済み | `acd_tools/gate_critic.py`。L2操舵のみ |
| conversation | `LocalConversation`、`EventLog`、`ConversationStats`、persistence | 採用済み | `acd_tools/agent_session.py` |
| context.condenser | `LLMSummarizingCondenser` | 採用済み | `acd_tools/agent_session.py` |
| plugin | `PluginSource` pinned fetch | 採用済み | `acd_tools/plugin_distribution.py` |
| subagent | `AgentDefinition` | 採用済み | `plugins/acd/agents/` |
| testing | `TestLLM` | 採用済み | `packages/acd-tools/tests/` |
| git | `get_git_changes`等 | 採用済み | `acd-evidence-git-check`。stale判定の入力のみ |
| security | `ConfirmRisky`、`NeverConfirm`、`permission_mode` | 採用済み | `plugins/acd/agents/` |
| event | SDK event、`EventLog` | 採用済み | `acd_tools/agent_session.py`。観測情報であり合否根拠ではない |
| llm | `LLM`、`LLMResponse`等 | 採用済み | Conversation経路。合否判定は行わない |
| workspace DockerWorkspace | `DockerWorkspace(server_image=...)` | 採用済み扱い | 決定論的ゲート実行の正。実装移行は次フェーズ |
| workspace DockerDevWorkspace | `DockerDevWorkspace(base_image=...)` | 採用済み | `scripts/run_in_workspace.py`。image build準備経路に限定 |
| secret | `SecretSource`、`StaticSecret`、`LookupSecret` | 採用候補 | LLM keyと将来の外部API key。平文環境変数を避ける経路を設計する |
| security解析器 | `LLMSecurityAnalyzer`、`PolicyRailSecurityAnalyzer`、`PatternSecurityAnalyzer`、`EnsembleSecurityAnalyzer`、`ToolShield`、`GraySwan` | 採用候補 | agent経路の停止側防御。合否権限は与えない |
| conversation停止検出 | `StuckDetector` | 採用候補 | 停止側の操舵に限定する |
| agent-server hooks | `hooks_router`、`hooks_service` | 採用候補 | `/api/hooks`はworkspace設定の読み込みAPI。直接APIへの自動適用は未確認 |
| observability | `maybe_init_laminar`、`observe` | 採用候補 | L3観測。既定無効、staging限定で再評価する |
| io | `FileStore`、`LocalFileStore`、`InMemoryFileStore` | 採用候補 | session成果物の保存抽象。Evidenceの正はgitとfilesystem |
| delegate | `TaskToolSet`、`DelegateExecutor` | 採用候補 | sub-agentオーケストレーション。合否権限なし |
| profiles | `AgentProfile`、`AgentProfileStore`、profiles router | 採用候補 | agent-server設定配布経路として再評価する |
| resource lock | `ResourceLockManager`、conversation lease | 採用候補 | 複数instance時の所有権。単一instanceでは不要 |
| event補助 | `error_classification`、`resume_transcript` | 採用候補 | L3観測とresume可読化 |
| llm.router | `RouterLLM`、`RandomRouter`、`MultimodalRouter` | 採用候補 | コスト最適化のみ。合否に無関係 |
| agent-server telemetry | HTTP/PostHog exporter、policy、sanitizer | 採用候補 | 送信先とサニタイズ方針の確定が前提 |
| browser | `browser_use` | 採用候補 | 将来のsourcing。発注・外部送信ガードが前提 |
| marketplace | marketplace API | 不採用 | pinned `PluginSource`で要件を満たす |
| MCP | `MCPClient`、`MCPToolDefinition`、`create_mcp_tools`、MCP router | 不採用 | OpenHands専用化により互換層を提供しない |
| workflow | `WorkflowContext`、`WorkflowToolSet` | 不採用 | sub-agent調整用であり、shell/file操作を行う決定論的探索には使えない |
| 追加tool | `apply_patch`、`planning_file_editor`、gemini系、`tom_consult` | 不採用 | ACDのtool集合はterminal、file editor、grep、glob、task trackerに限定 |
| workspace追加 | Apptainer、`APIRemote`、`OpenHandsCloud` | 不採用 | DockerWorkspace一本化 |
| ACP | `agent.acp_*` | 不採用 | 外部client互換は範囲外 |
| Agent Canvas | `canvas_extensions`、`extensions.installation` | 不採用 | Agent Canvas互換は範囲外 |
| llm.auth | OpenAI資格情報経路 | 不採用 | secret経路へ寄せる |
| goal loop | `conversation.goal`、`judge_goal`、`GoalController`、goal endpoint | 不採用 | criticと反復上限で足り、LLM judgeを増やさない |

## SDKへ委譲しないACD固有責務

物理設計の合否、DesignGraph、FabProfile、ToolEnvelope、Evidenceの意味論、独立測定、
決定論的投影、ドメイン知識、発注ガードはSDKへ委譲しない。SDKのevent、metrics、
critic、Skill、agent、LLM出力は合格側Evidenceにならない。
