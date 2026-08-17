# OpenHands SDK v1.42.1機能採否

> ステータス: Accepted
> 日付: 2026-08-17
> 対象: OpenHands Software Agent SDK v1.42.1

## 一次情報と状態語彙

一次情報は`vendor/software-agent-sdk`のv1.42.1 checkoutと、そこから機械生成した
`/home/ubuntu/sdk-inventory.md`である。主な参照先は
`openhands-sdk/openhands/sdk`、`openhands-tools/openhands/tools`、
`openhands-workspace/openhands/workspace`、
`openhands-agent-server/openhands/agent_server`である。

状態は次の三語だけを使う。

- **採用済み**: ACDの現行実行経路で使用する。
- **採用候補**: 未使用だが価値があり、次フェーズの条件を満たせば採用する。
- **不採用**: ACDの境界・決定論・OpenHands専用方針により採用しない。

合否はL1の決定論的ゲートだけが判定する。L2の操舵とL3の観測は合格側Evidenceに
ならない。SDK機能の採否は本書を単一の正とする。

## `openhands-sdk`

| 機能 | 主なAPI・実装事実 | 状態 | 優先度／価値・前提・リスク | ACD側の根拠または理由 |
|---|---|---|---|---|
| agent | `Agent`、`AgentBase`、`AgentDefinition` | 採用済み | — | `plugins/acd/agents/`。役割別AgentDefinitionを使用 |
| conversation | `LocalConversation`、`RemoteConversation`、`EventLog`、`ConversationStats`、persistence | 採用済み | — | `packages/acd-tools/src/acd_tools/agent_session.py` |
| critic | `CriticBase`、`CriticResult`、`IterativeRefinementConfig` | 採用済み | — | `packages/acd-tools/src/acd_tools/gate_critic.py`。L2操舵のみ |
| event | `Event`、`MessageEvent`、`EventLog`、resume transcript | 採用済み | — | sessionの経過観測。合否Evidenceではない |
| hooks | `HookConfig`、`HookMatcher`、command hook | 採用済み | — | `plugins/acd/hooks/`。agent経路の停止側境界 |
| io | `FileStore`、`LocalFileStore`、`InMemoryFileStore` | 採用候補 | 中。session保存抽象として有用。Evidenceの正との二重化に注意 | gitとfilesystemを正とするため、採否は保存契約の検証後 |
| git | `LocalWorkspace.git_changes()`等 | 採用済み | — | `scripts/acd_evidence_git_check.py`。stale判定の入力のみ |
| llm | `LLM`、`LLMResponse`、`LLMStreamChunk`、`TokenUsage` | 採用済み | — | ConversationとTestLLMの配線。合否判定は行わない |
| llm.router | `RouterLLM`、`RandomRouter`、`MultimodalRouter` | 採用候補 | 低。コスト・可用性を改善する。モデル選択が再現性を損なう | 固定profile、予算計測、L1非依存を満たせば再評価 |
| llm.auth | OpenAI資格情報・auth helper | 不採用 | — | secret経路へ寄せ、資格情報を宣言へ持ち込まない |
| llm.metrics | `Metrics`、`MetricsSnapshot`、token/money/wall-clock集計 | 採用候補 | 中。ADR-0025 V8の予算実測に必要。合否混入を禁止 | V8で外部process記録と併せて保存できれば採用 |
| context | `AgentContext`、memory、prompt registry | 採用済み | — | Conversation bootstrapのcontext経路 |
| context.condenser | `LLMSummarizingCondenser`、`CondenserSettings` | 採用済み | — | `agent_session.py`。L2操舵・要約でありEvidenceではない |
| context.view | context view、event view | 採用候補 | 低。長時間sessionの表示を軽量化する。要約欠落を監視する必要 | resume/forkと原EventLogの照合を満たせば再評価 |
| context.prompts | `Prompt`、`PromptSection`、preset registry | 採用候補 | 低。役割別指示を構造化できる。prompt差分のprovenanceが必要 | prompt hashとagent定義の固定を満たせば採用 |
| plugin | `Plugin`、`PluginSource`、plugin loader | 採用済み | — | `packages/acd-tools/src/acd_tools/plugin_distribution.py`。SHA/tag固定 |
| profiles | `AgentProfile`、`AgentProfileStore` | 採用候補 | 中。agent-serverの設定配布に有用。API key保存とprofile driftがリスク | secret-free profileとleaseをV1〜V8で検証 |
| marketplace | marketplace catalog、plugin installer | 不採用 | — | pinned `PluginSource`で要件を満たし、marketplace依存を増やさない |
| mcp | `MCPClient`、`MCPToolDefinition`、`create_mcp_tools` | 不採用 | — | OpenHands専用拡張としてMCP互換層を提供しない |
| observability | `observe`、Laminar初期化 | 採用候補 | 中。L3観測を増やせる。送信先・秘密情報・既定無効が前提 | stagingでsanitizerと送信ポリシーを確認後に採用 |
| secret | `SecretSource`、`StaticSecret`、`LookupSecret` | 採用候補 | 高。LLM・外部API keyの平文回避に直結。secret復元とDocker境界がリスク | `OH_SECRET_KEY`、forward_env、secret managerのV1/V8条件を満たす |
| security | `ConfirmRisky`、`NeverConfirm`、`permission_mode` | 採用済み | — | `plugins/acd/agents/*.md`の`confirm_risky`、reviewerの`never_confirm` |
| security解析器 | `LLMSecurityAnalyzer`、`PolicyRailSecurityAnalyzer`、`PatternSecurityAnalyzer`、`EnsembleSecurityAnalyzer`、`ToolShield`、`GraySwan` | 採用候補 | 高。agent経路を多重防御できる。L2停止側のみでL1判定へ混入させない | negative testと停止理由の記録を満たせば採用 |
| subagent | sub-agent登録・factory・agent loader | 採用済み | — | `plugins/acd/agents/`。合否権限は持たせない |
| testing | `TestLLM`、test helpers | 採用済み | — | bootstrap、hook DENY、critic反復の回帰テスト |
| tool | `ToolDefinition`、`Action`、`Observation`、`ToolAnnotations`、`ToolExecutor`、`register_tool` | 採用済み | — | `register_acd_tools()`から4入口を登録 |
| workspace | `Workspace`、`LocalWorkspace`、`RemoteWorkspace` | 採用候補 | 中。SDK実行境界を抽象化する。ACDのDocker一本化と競合しうる | DockerWorkspaceの受け入れ後、非Docker経路は採用しない |
| logger | SDK logger、structured logging | 採用候補 | 低。運用診断に有用。secret・Evidence混入がリスク | sanitizerと保存先をV1〜V8で固定 |
| extensions | SDK extension registry | 不採用 | — | Agent Canvas等の他環境拡張は範囲外 |
| goal loop | `GoalController`、`judge_goal`、goal endpoint | 不採用 | — | LLM judgeでL1ゲートを省略しない。criticのL2操舵で足りる |

## `openhands-tools`

| 機能 | 主なAPI | 状態 | ACD側の根拠または理由 |
|---|---|---|---|
| terminal | `TerminalTool`、terminal toolset | 採用済み | `plugins/acd/agents/*.md`の標準SDK tool |
| file_editor | `FileEditorTool` | 採用済み | AgentDefinitionが使用。hookの対象経路 |
| grep | `GrepTool` | 採用済み | AgentDefinitionの標準検索tool |
| glob | `GlobTool` | 採用済み | AgentDefinitionの標準検索tool |
| task_tracker | `TaskTrackerTool` | 採用済み | AgentDefinitionの作業追跡tool |
| task | `TaskToolSet` | 採用候補 | 中。主contextの汚染を減らす。合否権限なし | delegateの運用受け入れ後に採用 |
| delegate | `DelegateExecutor`、`spawn`、`delegate` | 採用候補 | 中。sub-agent調整に有用。blockingとmax_children=5が前提 | resource lock、停止側のみの権限を検証 |
| workflow | `WorkflowContext`、`WorkflowToolSet`、`run_agent`、`map_agents`、`reduce_agent`、`pipeline`、`flatten` | 不採用 | shell/file操作を行う決定論的探索には使えず、L1判定へ委譲しない |
| browser_use | Browser toolset | 採用候補 | 低。将来のsourcing。外部送信・発注ガードが前提 | order guard、認証、価格・在庫のEvidence契約を実装 |
| apply_patch | `ApplyPatchTool` | 不採用 | ACDのAgentDefinition tool集合を増やさない |
| planning_file_editor | planning file editor | 不採用 | file_editorと保護hookの単一経路を維持 |
| gemini系 | Gemini tools | 不採用 | OpenHands専用の標準tool境界外 |
| tom_consult | `TomConsultTool` | 不採用 | 合否に関与しない外部相談経路を増やさない |
| preset | tool preset loader | 不採用 | tool集合を明示固定する |

## `openhands-workspace`

| 機能 | 主なAPI | 状態 | 優先度／価値・前提・リスク | ACD側の根拠または理由 |
|---|---|---|---|---|
| LocalWorkspace | `LocalWorkspace` | 不採用 | — | ゲートのホスト実行は参考実行で、合格側Evidenceを生成しない |
| DockerWorkspace | `DockerWorkspace(server_image=...)` | 採用済み | — | digest固定agent-server imageを決定論的ゲート実行の正とする。次フェーズ移行 |
| DockerDevWorkspace | `DockerDevWorkspace(base_image=...)` | 採用済み | — | ACD tools imageからagent-server imageをbuildする準備経路に限定 |
| Apptainer | `ApptainerWorkspace` | 不採用 | — | Docker一本化 |
| APIRemote | `APIRemoteWorkspace` | 不採用 | — | remote API互換は範囲外 |
| OpenHandsCloud | cloud workspace | 不採用 | — | OpenHands専用拡張の境界外、再現性と外部運用を持ち込まない |

## `openhands-agent-server`

| 機能 | 主なAPI・router | 状態 | 優先度／価値・前提・リスク | ACD側の根拠または理由 |
|---|---|---|---|---|
| conversation router | conversation create/run/pause/interrupt/fork/delete | 採用候補 | 高。実運用経路の中心。永続化とleaseが前提 | ADR-0025 V1/V2/V6で受け入れ |
| event router | event list/search/count/get/message | 採用候補 | 中。経過観測をRESTで取得できる。Evidenceと混同しない | V2とfail-closed negative testで受け入れ |
| bash/file/git router | workspace操作API | 採用候補 | 高。直接APIのhook境界を検証する必要。認証・network分離が前提 | ADR-0025 V7で適用可否を実測 |
| vscode/desktop router | UI・desktop操作 | 不採用 | — | ACDの決定論的ゲート経路に不要 |
| skills/plugins/sub_agents router | skill、plugin、sub-agent管理 | 採用候補 | 中。server運用時の資材配布に有用。source/ref固定が前提 | pinned refと安全境界をV1〜V4で検証 |
| agent_profiles router | profile list/save/rename | 採用候補 | 中。設定配布に有用。secret漏えいがリスク | secret-free responseとleaseを検証 |
| auth router | session key、secret認証 | 採用候補 | 高。ネットワーク公開の前提。誤設定はfail-closed | `SESSION_API_KEY`、`OH_SECRET_KEY`をV1で検証 |
| hooks router/service | `POST /api/hooks`、`load_hooks_from_workspace` | 採用候補 | 高。直接APIへの自動適用可否が未確認。過信を禁止 | V7でrouter適用を実測し、未適用なら権限境界で閉じる |
| MCP router | MCP test/OAuth endpoints | 不採用 | — | MCP互換層を提供しない |
| WebSocket | conversation event subscription | 採用候補 | 高。実運用観測に必要。認証と切断復旧が前提 | ADR-0025 V3で受け入れ |
| `/v1` OpenAI互換 | `/v1/models`、`/v1/chat/completions` | 採用候補 | 中。既存client接続に有用。`stream=true`未対応を明示 | V2とauth、stream negative testで受け入れ |
| telemetry | HTTP/PostHog exporter、policy、sanitizer | 採用候補 | 低。L3観測。送信先と秘密情報の方針が前提 | staging限定でサニタイズを検証 |
| conversation lease | lease manager、resource lock | 採用候補 | 中。複数instanceの所有権を保つ。単一instanceでは不要 | shared storage負荷試験後に採用 |
| Docker build | agent-server Dockerfile、`openhands.agent_server.docker.build` | 採用候補 | 高。digest記録の起点。Docker daemonとsource固定が前提 | ADR-0025 V4/V5でbuildとdigestを受け入れ |

## 採用候補の優先順位

- **高**: `secret`はsecret manager、`OH_SECRET_KEY`、Docker forwardの平文回避を実装する。
  `security解析器`は停止側negative testを追加する。agent-serverのconversation、auth、hooks、
  WebSocket、Docker buildはADR-0025 V1〜V7を完了する。
- **中**: `io`、`delegate`、`profiles`、resource lock、event補助、llm.metricsは、
  session保存、所有権、予算実測、resume/forkの契約とnegative testを満たす。
- **低**: router、observability、telemetry、browserは、送信先・再現性・発注ガードを
  固定し、L1合否へ影響しないことを検証する。

## SDKへ委譲しないACD固有責務

物理設計の合否、DesignGraph、FabProfile、ToolEnvelope、Evidenceの意味論、
`Evidence.supports_pass(graph.revision)`、独立測定、決定論的投影、GD1の電気・機械・
製造ドメイン知識、rationale coverage、発注ガードはSDKへ委譲しない。SDKのevent、metrics、
critic、Skill、agent、reviewer、LLM出力は合格側Evidenceにならない。
