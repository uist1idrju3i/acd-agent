# OpenHands統合

> ステータス: 実装済み範囲と未実装範囲を分離して記録
> 対象: OpenHands Software Agent SDK v1.42.1

## 統合方針

ACD pluginをOpenHands側の主成果物とする。OpenHandsはSkill、AgentDefinition、
command、SDK ToolDefinition、任意のworkspace実行を提供し、Python側はPydantic契約、決定論的投影、
ゲート、adapter、evidence契約を保持する。AIやSkillの出力は候補・所見であり、
ACDの合否根拠ではない。

SDKは`vendor/software-agent-sdk`のv1.42.1を参照する。Agent Canvasのsubmoduleは使用せず、
OpenHandsの公開Skills repositoryはsubmoduleにせず外部参照とする:
<https://github.com/OpenHands/extensions>

## 現行LocalConversation経路: SDK Conversation bootstrap

`acd_tools.agent_session.build_acd_conversation()`は、`Agent`へ
`AcdGateCritic`と`LLMSummarizingCondenser`を設定し、`LocalConversation`へ
`plugins/acd`、`plugins/acd/hooks/hooks.json`、workspace、
`persistence_dir`を渡す。登録済みのACD ToolDefinitionは
`register_acd_tools()`で利用可能にする。SDKがloop、history、state/event persistence、
metricsを担当し、ACD側は配線と決定論的ゲートの設定だけを行う。

`acd-evidence-git-check`はSDK gitの変更情報をstale判定の入力にする薄いCLIである。
Evidenceの正は引き続き`Evidence.supports_pass(graph.revision)`だけであり、
`graph.revision`は`rN`であってgit SHAではない。EventLog、state、metrics、
condenser outputはpass evidenceではない。

## 次フェーズ: pinned plugin配布とTestLLM回帰

`acd_tools.plugin_distribution.acd_plugin_source()`は外部配布用の
`PluginSource(source="github:uist1idrju3i/acd-agent", repo_path="plugins/acd",
ref=...)`を作る。refは40桁commit SHAまたは`v<semver>` tagだけを受け付け、
branch名・未指定ref・不正値はfail-closedに拒否する。開発時は
`build_acd_conversation()`のlocal path既定値を使える。

次フェーズのTestLLM回帰はbootstrapからSDK agent stepを通した投影保護hookのDENYと、
Conversationのrunを通したゲート未達時の二値critic、follow-up、反復上限を
カバーする。hookテストはローカルpluginと登録済みテスト用terminal定義を使い、
外部fetchを発生させない。外部plugin fetch、実LLM、Docker、外部terminal実装、
複数stepのtool-call E2Eは未検証であり、合否根拠には使わない。

## agent-server実運用: agent-server運用境界

SDK v1.42.1の`openhands-agent-server`を、conversation、event、workspace、
永続化を運ぶruntime層として文書化した。REST、WebSocket、`/v1` OpenAI互換API、
pause/interrupt/resume/forkとfilesystem保存先の事実は
[`agent-server-runbook.md`](agent-server-runbook.md)に整理している。

agent-serverのevent、conversation state、metrics、agent出力、OpenAI互換応答は
経過であり、合否Evidenceではない。合否はCIまたは`run_in_workspace`側の決定論的
pipelineとgateが決める。ACDではagent-serverを実運用済みとは扱わず、起動、
REST/WebSocket E2E、resume/fork、Docker image buildは未検証である。

## plugin構成

```text
plugins/acd/
├── .plugin/plugin.json
├── commands/gates.md
├── hooks/
│   ├── hooks.json
│   └── scripts/
├── agents/
│   ├── acd-electrical.md
│   ├── acd-mechanical.md
│   ├── acd-firmware.md
│   ├── acd-reviewer.md
│   └── acd-search.md
└── skills/
    ├── acd-contracts
    ├── acd-placement-search
    ├── acd-silkscreen-placement
    ├── acd-firmware-esp32c3
    ├── acd-cad-determinism-probe
    ├── acd-qc-seven-tools
    ├── acd-reliability-review
    └── acd-design-rationale
```

### Skill trigger

8 Skillは`version`、`license`、`triggers`をfrontmatterに持つ。
`triggers`はSDKの`KeywordTrigger`であり、内容に即した英語キーワードを3〜6個指定する。
`paths:`は`disable_model_invocation=True`を強制するため使わない。`inputs:`は
TaskTriggerになるため、現在の自然言語起点の任意利用には適さず使わない。

Skillは作業手法と探索器を提供するが、結果は合否Evidenceではない。配置・シルク探索を
fixture生成で利用する場合も、ACD本体からSkillのPython moduleをimportせず、CLIを
subprocess実行して結果を設計入力へ確定する。scriptのsha256とSkill名をprovenanceへ
記録し、入力不備や実行失敗はfail-closedとする。silkscreen探索では、決定論的ゲートが
Gerber実測の幾何・判定条件・文字寸法上界モデルをcontextとして渡し、Skillは自前の
閾値や文字寸法係数を持たず、受け取った条件だけで候補を生成する。

設計入力の編集後は実装済みの`PostToolUse` hookが`file_editor`に対して
`uv run python scripts/check_rationale.py --if-present --warn-only`を実行し、
rationale不足を警告する。`Stop` hookは
`uv run python scripts/check_rationale.py --if-present`を実行する。exit code 2の不足・
parse失敗・stale・unclassifiedは停止をブロックする。Conversationの永続ログはconversation event
referenceとして参照するだけで、rationaleや合否の権威ではない。

## AgentDefinition

| 定義 | 役割 | Skill | 権限 |
|---|---|---|---|
| `acd-electrical` | 回路レーン投影、配置、ERC/DRC失敗調査 | `acd-contracts`, `acd-placement-search`, `acd-silkscreen-placement` | `confirm_risky` |
| `acd-mechanical` | 筐体投影、機械ゲート、CAD決定性 | `acd-contracts`, `acd-cad-determinism-probe` | `confirm_risky` |
| `acd-firmware` | ESP32-C3のFW開発、ビルド、仮想実行 | `acd-firmware-esp32c3` | `confirm_risky` |
| `acd-reviewer` | 投影レビューと所見整理。合否権限なし | `acd-qc-seven-tools`, `acd-reliability-review` | `never_confirm` |
| `acd-search` | 決定論的探索CLIの実行と候補provenanceの返却。合否権限なし | `acd-placement-search`, `acd-silkscreen-placement` | `confirm_risky` |

各定義は`model: inherit`、反復上限、budget上限を持ち、toolはSDKで確認した
`terminal`、`file_editor`、`grep`、`glob`、`task_tracker`に限定する。reviewerの
自然文所見は合否を決めず、決定論的ゲートへ戻される。

`acd-search`は決定論的探索laneである。既存の探索CLIをterminal経由で実行し、
候補とSkill名・script SHA-256 provenanceだけを返す。候補は合否根拠ではなく、
設計入力へ確定した後に決定論的ゲートで検証する。配置greedy探索とsilkscreen探索は
状態依存のため並列化しない。SDK workflowはLLM subagent専用で、scriptからの
shell・file操作が禁止されるためACD探索には使用しない。

## `/acd:gates`

`.plugin/plugin.json`の`entry_command: "gates"`により、`/acd:gates`を提供する。
command本文は既存の決定論的電気・機械ゲートを実行するようagentへ指示し、閾値・
期待値・evidence規則を変更しない。ツール不在、未知状態、parse失敗、未検証は
fail-closedとする。

## SDK ToolDefinition境界

`packages/acd-tools/src/acd_tools/sdk_tools.py`はSDKの`ToolDefinition`、
`Action`、`Observation`、`ToolAnnotations`、`ToolExecutor`を使い、明示的な
`register_acd_tools()`から次の4つの決定論的入口を登録する。これはSDK標準toolとは
別のACD toolであり、MCP client互換層は提供しない。

| tool | 内容 |
|---|---|
| `acd_probe_tools` | 外部ツールの有無と版を返す |
| `acd_validate_design_graph` | Pydantic契約でgraphを検証する |
| `acd_run_board_pipeline` | 既存GD1基板pipelineを実行する |
| `acd_run_enclosure_pipeline` | 既存GD1筐体pipelineを実行する |

返り値は`ok`、`operation`、`failure_reason`、`fail_closed`、summary、出力パス、
ToolEnvelope由来のtool名・版・hashを含む構造化JSONである。入力不備、ファイル不在、
JSON/Pydantic parse失敗、pipeline例外は成功に見せずfail-closedで返す。

一方、`terminal`、`file_editor`、`grep`、`glob`、`task_tracker`は
`plugins/acd/agents/*.md`のAgentDefinitionが使用するOpenHands SDK標準toolであり、
`register_acd_tools()`が登録する4つのACD toolとは区別する。

## 決定論的ゲートcritic

現行では`AcdGateCritic`をagentのcriticへ接続できる。

```python
from acd_tools.gate_critic import AcdEvidenceRequirement, AcdGateCritic
from openhands.sdk import Agent

critic = AcdGateCritic(
    requirements=[
        AcdEvidenceRequirement(
            path="out/gd1-enclosure/evidence-mechanical.json",
            evidence_id="evidence.gd1.mechanical",
        ),
    ],
)
agent = Agent(llm=llm, tools=tools, critic=critic)
```

criticはDesign Graphの`graph.revision`を現revisionとし、設計入力がgitで
cleanな場合だけEvidenceの`supports_pass()`を評価する。git SHAを
`target_revision`へ変換しない。eventsと`git_patch`は評価対象外で、スコアは
全要件充足時の`1.0`またはそれ以外の`0.0`だけである。critic出力は反復の
操舵信号であり、pass evidenceではない。

hookのDesign Graph revision解決は`acd-design-revision` console scriptへ委譲する。
CLIはpathを`DesignGraph`として検証し、単一pathが有効な場合だけrevisionをstdoutへ
出力する。hookは別途gitによる設計入力のdirty判定とpath数の検査を行う。

## Docker workspace実行

決定論的pipelineとゲートは`DockerWorkspace(server_image="...@sha256:<digest>")`で
実行する。`DockerDevWorkspace`は`base_image`からagent-server imageをbuildする準備
経路に限定する。現行runnerのホスト実行とDockerDevWorkspace経路は移行中であり、
ホスト実行は合格側Evidenceを生成しない。

`scripts/run_in_workspace.py`は`docker image inspect`でRepoDigestsを優先し、
ローカルbuildではimage IDへフォールバックする。sha256 digestを解決できない場合は
workspaceを起動しない。repoを`volumes`でmountし、`ACD_CONTAINER_IMAGE_DIGEST`を
`forward_env`で渡す。Dockerはdeterminismを保証しないため、既存のhash、
timestamp正規化、独立再読込、決定論的ゲートは維持する。

## hook境界

`plugins/acd/hooks/`はSDK command hookとして実装済みである。投影保護はpathフィールド
だけを部分木解決して判定し、本文中の文字列は対象にしない。orderガードはtransmission
commandかつ製造成果物への言及、または明示的order commandの場合だけ作動し、
`required_evidence_ids`ごとに現revisionの`supports_pass()`を要求する。通常のsource push
や文書取得は対象外である。

Stopガードはorderガードより弱い。dirtyな設計入力すべてより新しいmtimeのvalidかつ
unknownなしEvidenceがある場合だけ終了を許可するが、mtimeはpassの根拠ではない。
`supports_pass()`はcommit済みrevision一致を要求し続ける。基板fabrication側は現状
Evidenceを生成しないため、該当成果物の送信はdenyされる。

## 未実装・将来

以下はSDKに存在する概念を調査したが、本リポジトリの採用済み実行経路ではない。

- SecretRegistry連携とprovider secretの注入
- agentごとのDocker実行と配布済みACD image
- agent-serverの実運用とstaging E2E
- Conversationを使ったACD実行経路、fork、長時間resume
- SDKのcritic、goal、workflow、memoryを使う自動修復ループ
- browser経由のsourcingと自働発注

これらは将来検討であり、現行の合否・Evidence・発注契約には使わない。

## 外部参照

OpenHandsが公開する追加Skillsの参照先は
<https://github.com/OpenHands/extensions> である。クローン重量と更新負債を避けるため、
このrepositoryはこれをsubmoduleとしてvendorしない。ACD pluginのSkillとは別の外部資材
として扱う。
