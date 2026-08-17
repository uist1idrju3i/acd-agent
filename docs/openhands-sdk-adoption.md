# ACD × OpenHands Software Agent SDK 活用度の見直し提案

> 調査対象: `uist1idrju3i/acd-agent` @ `d43a14a`、`vendor/software-agent-sdk` (v1.42.1)
> 種別: 提案のみ（コード変更なし）

## 0. 結論（要旨）

現在のSDK活用は**宣言物（Markdown）だけ**で、実行時にSDKのPython APIを使っている箇所は
ゼロである。`pyproject.toml`は`openhands-sdk`をdependencyに持つが、`packages/`と
`scripts/`のどこからも`openhands`をimportしていない（`grep`で0件）。つまり現状の統合は
「plugin資材をSDKが読む」までで、SDKの**実行基盤**（Conversation、hooks、critic、
subagent、workspace、secret、persistence、budget計測）は一切使っていない。

一方でACD側には、SDKが標準で持つ機構と重なる自作物がすでにある。

| ACDの自作物 | SDKの該当機構 | 重複度 |
|---|---|---|
| `acd_tools.mcp_server`（FastMCP自作server + 手書きの`ok/failure_reason`規約） | `sdk.tool.register_tool` / `ToolDefinition` / `ToolExecutor`、`sdk.mcp` | 高 |
| `gd1_board.run_pipeline`内の反復・停止・再実行判断（`max_passes`、収束判定の司会） | `sdk.critic`（`CriticBase` + `IterativeRefinementConfig`）、`sdk.conversation.goal` | 中 |
| `plugins/acd/skills/acd-placement-search`の単一プロセス総当り探索 | `openhands.tools.workflow`（並列subagent）、`sdk.subagent`、`openhands.tools.delegate` | 中 |
| `AGENTS.md`の「fail-closed規約」を人手・レビューで守る運用 | `sdk.hooks`（`PreToolUse`/`Stop`で`HookDecision.DENY`）、`security.confirmation_policy`、`security.defense_in_depth.policy_rails` | 高（機構が無い＝規約のみ） |
| `ToolEnvelope.execution_env` / `tool_version`をprobeで自己申告 | `openhands-workspace`（`docker` / `apptainer` / `remote_api`）でツール版を固定 | 中 |
| `scripts/fetch_lcsc_footprint_orientation.py`の資格情報なし直叩き | `sdk.secret`（`SecretSource` / `StaticSecret` / `LookupSecret`） | 低〜中（将来のfab/価格API） |
| 実行履歴・provenanceをACDの出力ファイルだけで持つ | `sdk.event`（EventLog）、`sdk.io`（FileStore: local/memory/cache）、conversation persistence / fork | 中 |
| plugin配布がlocal path前提（`.mcp.json`が`${SKILL_ROOT}/../..`でuv run） | `sdk.plugin`（`github:owner/repo` + `repo_path` + `ref`でpinned fetch）、`sdk.marketplace` | 高 |

**逆に、SDKでは絶対に代替できないのが物理設計の「判定」側**である（§3に列挙）。
提案の骨子は、**「司会・実行・分業・防護・配布はSDKへ全面的に寄せ、ACDは契約・投影・
独立測定・ゲート・発注ガードだけを持つ」**という現在のADR-0010の方針を、
*宣言レベルからランタイムレベルへ引き上げる*ことである。

---

## 1. 現状のSDK活用マップ

使っている（宣言のみ）:

- `plugins/acd/.plugin/plugin.json`（plugin manifest）
- `skills/*/SKILL.md` 7件（`KeywordTrigger`）
- `agents/*.md` 4件（`AgentDefinition`: model/tools/skills/permission_mode）
- `commands/gates.md`（`/acd:gates`）
- `.mcp.json`（stdio MCP server 1件）

使っていない（SDKに存在するのに未接続）:

`Conversation`（実行経路・fork・resume）、`EventLog`、`sdk.hooks`（6種のhook event）、
`sdk.critic`、`sdk.conversation.goal`（controller/judge/runner）、`sdk.subagent` +
`tools.delegate` + `tools.workflow`、`openhands-workspace`（Docker/Apptainer/Remote）、
`sdk.secret`、`sdk.io`（FileStore）、`sdk.context.condenser`、`sdk.profiles`、
`sdk.marketplace`、`sdk.observability`（laminar）、`sdk.testing.TestLLM`、
`sdk.git`（git_changes/git_diff/git_commits）、`sdk.llm.router`、`openhands-agent-server`。

ADR-0003ではこのうち`EventLog`と`TestLLM`を「Phase 0で骨組みを作る」としたが、
実装は入っていない（docsに言及があるだけ）。ここは記述と実態の乖離である。

---

## 2. 提案（優先度順）

### P1: fail-closed境界をhookとして機構化する（最も費用対効果が高い）

現在ACDのfail-closedは「pipelineの内側」にしか無い。pipelineを通さずにagentが
`out/`のGerberを直接書き換える、evidenceのJSONを手で書く、gate未通過のzipを
発注扱いにする、といった経路は`AGENTS.md`の文章だけが止めている。

SDKは`plugins/<name>/hooks/hooks.json`を読み、`PreToolUse` / `PostToolUse` /
`UserPromptSubmit` / `SessionStart` / `SessionEnd` / `Stop`で
`HookDecision.DENY`を返せる（`sdk/hooks/types.py`、`sdk/plugin/plugin.py`）。
hook種別は`command`（subprocess）/ `prompt` / `agent`の3種。

提案する`plugins/acd/hooks/hooks.json`:

| hook | 目的 | 判定主体 |
|---|---|---|
| `PreToolUse` | 投影生成物（`out/**`、Gerber/drill/zip/STEP）とevidence配下への直接編集をDENY。設計入力（`graph.json`、`profiles/**`）の編集はALLOW | 決定論的script（LLMなし） |
| `PreToolUse` | 発注・外部送信に相当するコマンドを、対応revisionのgate通過evidenceが無ければDENY | `Evidence.supports_pass(revision)`をそのまま使う |
| `SessionStart` | `probe_tools`を実行し、外部ツール版をcontextへ注入。ツール不在は最初に露出させる | 既存`acd_tools.probe` |
| `Stop` | 設計入力を変更したまま該当ゲート未実行の終了をDENY（`sdk.git.git_changes`で差分検出） | 決定論的script |
| `PostToolUse` | Markdown変更後に`scripts/verify_docs.py`を自動実行 | 既存script |

これはACDの新しい閾値を作らず、既存の判定を**呼ぶ場所を増やすだけ**なので、
「Skill/AIの出力は合否根拠ではない」という原則と衝突しない。
`permission_mode`（`ConfirmRisky`等）と`security.defense_in_depth.policy_rails`も
併用でき、SB1/SB2の危険操作に`AlwaysConfirm`を割り当てられる。

### P2: MCP自作serverをSDK `ToolDefinition`に寄せ、MCPは互換層に降格

現状`acd_tools/mcp_server.py`はFastMCPで4 toolを公開し、`ok` / `failure_reason` /
`fail_closed`という**独自の返却規約**を手書きしている。SDKは
`register_tool(name, ToolDefinition subclass)`、`Action` / `Observation`（Pydantic）、
`ToolExecutor`、`ToolAnnotations`を持ち、observationの型付け・可視化・
confirmation・risk annotationがすべて標準経路に乗る。

提案:

1. `acd-tools`に`ToolDefinition`実装（`ValidateDesignGraph`、`RunBoardPipeline`、
   `RunEnclosurePipeline`、`ProbeTools`）を置き、`register_tool`で登録する。
   `Observation`にACDの`ToolEnvelope`をそのまま埋める（契約はACD所有のまま）。
2. `agents/*.md`の`tools:`からこれらを名前参照する。
3. FastMCP serverはユーザー決定により廃止し、P2で`acd-mcp`と`plugins/acd/.mcp.json`を削除してToolDefinitionに一本化する。
   実装は1.のexecutorを薄く包むだけにし、返却規約の二重管理をやめる。

これで`failure_reason`/`fail_closed`の手書きJSON規約が1箇所に減る。

### P3: 反復ループ（silkscreen未解決課題）の司会をSDKへ渡す

READMEの既知課題「投影→実測→再配置の反復ループが未実装」は、実装すべきものが
**ループ制御**である。SDKには2つの既製機構がある。

- `sdk.critic`: `CriticBase`を実装し、`IterativeRefinementConfig(success_threshold, max_iterations)`
  を付けると`Conversation.run()`が閾値未満で自動的に再試行する。
  → **ACDは`AcdGateCritic`を実装し、決定論的ゲート結果（合否と違反geometry）を
  `CriticResult`として返すだけでよい。**スコアはLLM由来でなく実測値なので、
  「合否は決定論的ゲート」という原則を崩さない。
- `sdk.conversation.goal`: `judge_goal`（LLM judge）+ `GoalController`で
  「継続 or 停止（`complete` / `capped`）」を判断する。こちらはLLM判定なので
  **合否には使わず**、探索の打ち切り判断（budget/反復上限）にだけ使う。

推奨は`AcdGateCritic`（P3a）が主、goal loopは補助（P3b）。ACD側に新しい
ループ実装を書かない。

P3aの`AcdGateCritic`はDesign Graphの`graph.revision`をEvidenceの
`target_revision`と比較する。git SHAはtarget revisionではなく、設計入力の
clean判定だけに使う。criticのスコアは二値であり、全要件充足時だけ1.0、
それ以外は0.0である。

### P4: ACD側の決定論的並列化と探索lane

GD1基板pipelineの独立したwidth positive-control armだけを`ThreadPoolExecutor`
で並列化する。arm-a、arm-bの結果は固定順で集約する。worker数1と4では、出力パスと
KiCad DRC日時を除いたarm summaryの正規化比較が一致した。`hashes.json`は既存pipeline
のKiCad UUIDとDRC日時による非決定性のため一致せず、この是正はP4の範囲外である。
greedy配置探索とsilkscreen探索は状態依存のため並列化しない。

`acd-search` AgentDefinitionは既存の決定論的探索CLIを実行し、候補とSkill名・
script SHA-256 provenanceだけを返す。候補は合否権限を持たず、設計入力へ確定した
後に決定論的ゲートで判定する。SDK workflowはLLM subagent用でshell・file操作が
禁止されるため採用しない。

### P5: 外部ツール版の固定を`openhands-workspace`へ

`ToolEnvelope.execution_env` / `tool_version`は現在probeの自己申告で、
ホスト環境が変われば再現しない。`openhands-workspace`は`DockerWorkspace`
（+ `apptainer`、`remote_api`、`cloud`）を持つ。KiCad 9 / FreeRouting / FreeCAD /
ngspiceを固定したimageをworkspaceとして宣言すれば、**`ToolEnvelope`の再現性主張が
初めて検証可能になる**（roadmap「フェーズ横断の検証要件#5」の実効化）。
ACDはimage digestをenvelopeへ記録するだけでよい。

### P6: 履歴・provenance・再開をSDKの永続化に載せる（実装済み）

`EventLog`（`sdk.event`）+ `sdk.io`のFileStore（`local` / `memory` / `cache`）+
conversation persistence / fork を採用すると、(a) 設計判断の履歴、(b) 長時間セッションの
resume、(c) 設計案の分岐（fork）が標準機構になる。ACDの正は引き続き
「入力ファイル + git commit + evidence」であり、EventLogは**根拠ではなく経過**として扱う
（ADR-0008の記述と一致）。あわせて`sdk.git`の`git_changes` / `git_diff` / `git_commits`で
stale evidence判定の入力（revision差分）を取る。
`acd_tools.agent_session`が`LocalConversation`へplugin、hooks、workspace、
`persistence_dir`、`AcdGateCritic`を接続する。loop、history、state/event persistenceは
SDKへ委譲し、EventLogとconversation stateは経過であって合否Evidenceではない。

### P7: 予算とcontextの標準機構（実装済み）

`ConversationStats.get_combined_metrics()`を
`acd_tools.agent_session.write_conversation_metrics()`でJSONへ出力できる。
出力は`pass_evidence: false`を持つ経過情報であり、実LLM測定はP8のTestLLMで検証する。
長い反復ループには`context.condenser.LLMSummarizingCondenser`を接続する。

### P8: 配布とテスト

- plugin配布: `acd_tools.plugin_distribution.acd_plugin_source()`で
  `github:uist1idrju3i/acd-agent`の`plugins/acd`を40桁commit SHAまたは
  `v<semver>` tagへpinしてfetchできる。branch名や未指定refはfail-closedで拒否する。
  開発時のlocal pathは既定値として維持する。`sdk.marketplace`はrepo部分木の
  pinned fetchだけでは不要なため採用しない。
- 回帰テスト: `sdk.testing.TestLLM`でbootstrapからSDK agent stepを通した投影保護hookの
  DENYと、Conversationのrunを通した二値criticの未達、follow-up、反復上限をLLMなしで
  決定論的に検証する。外部plugin fetch、実LLM、Docker、外部terminal実装、
  複数stepのtool-call E2Eは未検証。
- `sdk.profiles`（`AgentProfile` / `agent_profile_store`）はsecret-freeな参照モデルだが、
  ACDの電気・機械・FW・reviewer設定への採用は見送る。解決済みLLMやAPI keyを宣言へ
  埋め込まず、将来のprofile契約が固まった段階で再評価する。
- `sdk.observability.laminar`はトレース可視化の選択肢（合否には無関係）。

### P9（将来）: `openhands-agent-server`でVibeBBの運用面を得る

`openhands-agent-server`はREST/WebSocket、persistence、OpenAI互換API、
canvas extensions、VSCode extensionsを持つ。VibeBB（人間が要件オーナー）のUIを
ACDが自作せずに済む。ただし合否・evidence契約はACD側に残す。

---

## 3. SDKでは実現できない部分（ACD独自実装として残すもの）

SDKは「agentを動かす基盤」であり、**物理設計が正しいかを判断する機能は一切持たない**。
以下はSDKに置き換え先が存在せず、ACDが所有し続ける。

### 3.1 契約とセマンティクス

1. `DesignGraph` / `FabProfile`（設計入力の型と不変条件）
2. `ToolEnvelope`（tool版・format版・config/input/output hash・収束状態・測定条件・
   idempotency・`has_unknown()`）
3. `Evidence` / `EvidenceClaim`と`supports_pass(revision)`の意味論
   （valid / stale / invalidated / unknown、revision一致要求）
4. stale evidence（graph変更でどの検証結果が無効になるか）の伝播規則
5. 「unknownは停止側へ集約」「判定の両辺は別出自」「自己証明の禁止」という判定原則
   — SDKのcritic/judgeはLLMスコアであり、これらの代替にならない

### 3.2 決定論的投影（生成）

6. KiCad schematic / board / netclass / BOMの生成（`acd-adapter-kicad`、約2,800行）
7. 決定論的配置と`Placement`、net幅導出、stitch via注入、routing注入
8. Specctra DSN export / SES parse（`acd-adapter-freerouting`）
9. 筐体投影（build123d/FreeCAD経路、`acd-core.mechanical` + `acd-adapter-cad`）
10. 外部ツールの保存バイト列の**正規化規則**（timestamp、セグメント構成差、
    `deterministic_zip`、normalized hash manifest）

### 3.3 独立測定と決定論的ゲート

11. 独立再読込（生成経路と別parser: sexpdata / gerbonara）による board / schematic /
    Gerber / drill の再検証
12. ERC / DRC ゲートと違反分類（width violation帰属、positive control付き）
13. Gerber実測系: silkscreen可読性、SMD pad中心の存在、ground plane被覆、
    uncovered stitch via、drill測定、net path抵抗、track幅実測
14. DFM（`fab/dfm.py`、618行）とfab profile適合
15. BOM / CPLのcross validation、CPL回転契約（`cpl_orientation.py`、490行 +
    LCSC provenance evidence 20件）
16. 機械ゲート: 干渉、clearance、肉厚、部品高さ、CAD決定性
17. routing収束判定（`assert_converged`）
18. 発注ガード（全ゲート通過evidenceのみが発注可能条件）と
    Safety Boundary SB1/SB2のドメイン判断
19. 実機測定Evidenceの取り込み（roadmap milestone 5、未着手）

### 3.4 ドメイン知識・運用契約

20. 部品カタログのprovenance契約（ADR-0004）、JLCPCB PCBA準備契約（ADR-0005）
21. 外部ツールprobe（kicad-cli等の存在と版の検出）
    — workspace固定で再現性は上がるが、「どのツールのどの版が必要か」はACDの知識
22. 文書検証契約（`scripts/verify_docs.py`: 相対リンク、GitHub互換anchor、Mermaid、
    見出し階層、用語集整合）
23. Golden Design #1 fixture一式（設計そのもの）

**要点**: SDKへ寄せられるのは *司会・実行・分業・防護の配線・配布・観測* であり、
*何をもって合格とするか* は1件もSDKへ移せない。逆に言えば、現在ACDが持っている
「pipelineの`max_passes`ループ、MCPの返却規約、探索の並列化、fail-closedの人手運用、
plugin配布の手組み」は全部SDK側の既製機構で置き換えられる。

---

## 4. 段階的な適用順（推奨）

| 段 | 内容 | 規模感 | 効果 |
|---|---|---|---|
| 1 | `plugins/acd/hooks/hooks.json` + 決定論的hook script（P1） | 小 | fail-closedが規約から機構になる。ADR新規1本 |
| 2 | `ToolDefinition`化 + MCPを互換層へ（P2） | 中 | 独自返却規約の一本化。`architecture.md`のMCP境界を改訂 |
| 3 | `AcdGateCritic` + `IterativeRefinementConfig`（P3a） | 中 | silkscreen既知課題の反復ループをACDに書かずに得る |
| 4 | `DockerWorkspace`宣言 + envelopeへのimage digest記録（P5） | 中 | `ToolEnvelope`再現性主張の実効化 |
| 5 | workflow/subagentでの探索並列化（P4） | 中 | 探索時間と主context汚染の削減 |
| 6 | EventLog / FileStore / git差分、Metrics、condenser（P6・P7） | 中 | 履歴・resume・予算実測（roadmap要件#8）を満たす |
| 7 | plugin配布のpinned source化 + `TestLLM`回帰（P8） | 小 | 外部利用可能な配布物になる |
| 8 | agent-server運用（P9） | 大 | VibeBBの運用面。将来 |

各段でADRを1本追加し、ADR-0003（SDK機能採否）とADR-0010（plugin-first境界）、
`docs/openhands-integration.md`の「未実装・将来」節を実態に合わせて更新する。

## 5. リスクと注意点

- **critic/judgeを合否に使わない境界**を明文化しないと、`CriticResult.score`が
  ゲート合否と混同される。`AcdGateCritic`は決定論的ゲート結果の**転写**に限る。
- hookのDENYはagent経路だけに効き、人間の直接編集やCIは止めない。CI側の検証と
  二重に置く必要がある（hookを唯一の防壁にしない）。
- `DockerWorkspace`はKiCad/FreeCADのimage維持コストとライセンス確認が発生する。
- SDK v1.42.1へのランタイム依存が増えるため、vendor submoduleの更新負債が上がる
  （ADR-0006のvendor方針の再検討が必要）。
- workflow並列化は探索の再現性を落としうる。seed・順序・打ち切り条件を
  provenanceへ記録しないと、同一入力で同一候補にならない。
## DockerWorkspace を ACD に入れると具体的にどうなるか

> 根拠: `vendor/software-agent-sdk` v1.42.1 の
> `openhands-workspace/openhands/workspace/docker/{workspace,dev_workspace}.py`、
> `openhands-sdk/openhands/sdk/workspace/{base,remote}`、
> `openhands-agent-server/openhands/agent_server/docker/{build.py,Dockerfile}`、
> `examples/02_remote_agent_server/02_convo_with_docker_sandboxed_server.py`
> および ACD 側 `acd_core/process.py`、`acd_tools/probe.py`、`plugins/acd/.mcp.json`

## 1. DockerWorkspace の実体（読んだ通りの動作）

`DockerWorkspace` は `RemoteWorkspace` のサブクラスで、**agent-server が入った
Docker image を1つ起動し、以後の作業をそのコンテナ内で行う**ための仕組み。

初期化（`model_post_init`）で起きること:

1. `host_port` を自動選択（30000-39999、指定も可）
2. `docker version` で daemon 確認（無ければ即 `RuntimeError`）
3. `docker run -d --rm --platform linux/amd64 --ulimit nofile=65536:65536
   --name agent-server-<uuid> -p <host_port>:8000 [-v ...] [-e ...] <image>
   --host 0.0.0.0 --port 8000`
4. `http://127.0.0.1:<host_port>/health` を `health_check_timeout`（既定120秒）まで poll
5. `RemoteWorkspace` として初期化。以後の操作は HTTP API 経由

主なフィールド: `server_image`、`base_image`（Dev版のみ）、`volumes`（`-v` 相当）、
`forward_env`（既定 `DEBUG` / `SESSION_API_KEY` / `OH_SESSION_API_KEYS_0` のみ）、
`working_dir`（既定 `/workspace`）、`extra_ports`（VSCode 8001 / VNC 8002 を公開）、
`enable_gpu`、`network`、`platform`、`cleanup_image`、`detach_logs`。
`mount_dir` は削除済みで、指定すると validator が例外を投げる（`volumes` を使う）。

使える操作（`BaseWorkspace` / `RemoteWorkspace`）:
`execute_command`、`file_upload`、`file_download`、`git_changes`、`git_diff`、
`clone_repos`、`get_secrets`、`get_mcp_config`、`pause` / `resume`、`get_server_info`。
`with` を抜けるとコンテナは停止・`--rm` で破棄される（`cleanup_image=True` なら image も削除）。

**重要な制約**: image は「agent-server が入っている image」でなければならない。
既製の `ghcr.io/openhands/agent-server:latest-python` に KiCad は入っていないので、
ACD はどちらかを選ぶ必要がある。

| 方式 | API | 特徴 |
|---|---|---|
| A. 実行時ビルド | `DockerDevWorkspace(base_image="<ACD tool image>", target="source")` | 内部で `openhands.agent_server.docker.build.build(BuildOptions(base_image=...))` を呼び、SDK の sdist を含めて agent-server 層を base image の上に構築する。`base_image` に prebuilt agent-server を渡すのは禁止（validator）。SDK ソースが手元に必要 → ACD は vendor しているので条件を満たす |
| B. 事前ビルド + 固定 | 自前で上記 build を1回実行し `ghcr.io/uist1idrju3i/acd-agent-server:<sha>-kicad9` を publish → `DockerWorkspace(server_image="...@sha256:<digest>")` | 起動が速く、**digest で固定できる**。ACDの再現性主張と相性が良い。CI でも同じ digest を使える |

**推奨は B**（digest 固定が ToolEnvelope の主張と直結する）。A は image を作る前の実験用。

## 2. ACD ではどういう構成になるか

### 2.1 image の中身（ACD が用意する base image）

`probe_tools` が見る外部ツール一式を base image に固定する。

```dockerfile
# 例: acd-tools base image（agent-server 層は SDK の build が上に載せる）
FROM ubuntu:24.04
# kicad-cli 9.x（KiCad 公式 PPA / apt pin で版固定）
# openjdk-17-jre + freerouting.jar（版とjar sha256を固定）
# ngspice
# python3.12（build123d / cadquery-ocp は uv 側で wheel 固定）
```

ACD 本体は次のどちらかで持ち込む:

- `volumes=["/host/acd-agent:/workspace"]` でホストの repo を mount（開発時。
  `out/` と `evidence/` がホスト側に残るので後片付けが不要）
- image に `uv sync --frozen` 済みの repo を焼き込む（CI・再現性重視。
  ただし設計入力ごとに repo は変わるので、実際は「依存だけ焼く + repo は mount」が現実的）

`--rm` で起動するため、**mount も `file_download` もしなければ生成物とevidenceは消える**。
ここは必ず設計に含める必要がある。

### 2.2 実行モデルの3択

| モデル | 構成 | 導入コスト | 得られる再現性 |
|---|---|---|---|
| **B1: gateだけコンテナ内**（推奨・第一段） | agent と LLM はホスト。`workspace.execute_command("uv run python scripts/run_gd1_pipeline.py ...")` で pipeline をコンテナ内実行 | 小。ACD の Python 側はほぼ無改造 | 外部ツール版・OS・libが固定。envelope の再現性主張が検証可能になる |
| B2: agent も gate もコンテナ内 | `RemoteConversation` + `DockerWorkspace`。terminal / file_editor / MCP すべてコンテナ内 | 中。`.mcp.json` の `cwd` をコンテナpath に合わせる必要あり | 上記 + agent の副作用がホストに漏れない（fail-closed境界の物理化） |
| B3: CI も同じ image | GitHub Actions で同じ digest を使い pipeline を実行 | 小（B1の後） | 「同一入力 → 同一 output_hash」をホスト差をまたいで回帰テストできる |

段階は B1 → B3 → B2 が安全。

### 2.3 ACD 側で必要になる具体的な改造

1. **`acd_core.process.execution_env()`（現状 `f"{system}-{machine}; container=none"` の
   ハードコード）を、コンテナ実行時に image digest を含む文字列にする。**
   SDK は image digest を公開しない（`_container_id` / `_image_name` は private、
   `get_server_info()` はサーバ情報のみ）。したがって ACD が
   `docker inspect --format '{{index .RepoDigests 0}}' <image>` 相当で取得し、
   `ACD_EXECUTION_ENV=container=ghcr.io/...@sha256:...` として
   `forward_env` に追加して注入する形になる。**digest が取れない場合は
   `unknown` として fail-closed 側に寄せる**（既存 `has_unknown()` の意味論に合わせる）。
2. `ToolEnvelope` の `execution_env` / `config_hash` の意味を ADR で確定する
   （image digest はどちらに属するか。推奨は `execution_env` に digest、
   `config_hash` は現状通りコマンド列 hash のまま）。
3. `plugins/acd/.mcp.json` の `cwd: "${SKILL_ROOT}/../.."` + `uv run acd-mcp` が
   コンテナ内 path（`/workspace`）で成立するか確認・修正（B2 で必須）。
4. `docs/installation.md` に image の取得・digest 確認手順を追加。
   probe は「ホストに kicad-cli がある」前提を捨て、コンテナ内 probe を正とする。
5. negative test を足す: (a) ツール不在 image で fail-closed になる、
   (b) digest 取得失敗で `unknown` 停止、(c) 別ホスト/別アーキで同一 output_hash。

## 3. 何が良くなるか

- **roadmap「フェーズ横断の検証要件#5」（外部ツールの保存バイト列を権威にしない、
  非決定性は正規化規則に書く）が実効化する。** 今は `container=none` の自己申告なので、
  ホストの KiCad が上がれば envelope の意味が静かに変わる。digest 固定なら
  「同一 digest + 同一入力 → 同一 output_hash」を回帰にできる。
- ホスト環境差による GD1 pipeline の非再現（KiCad 9.x のマイナー差、
  freerouting の JVM 差、OCP の版差）が消える。
- B2 なら fail-closed 境界が**物理境界**になる（agent がホストの `out/` を触れない）。
- `extra_ports=True` で VNC(8002)/VSCode(8001) が開くので、KiCad/FreeCAD の GUI 確認や
  人間のレビューを同じコンテナ内で行える。

## 4. 何が良くならないか / 注意点

- **Docker は決定論を与えない。** digest を固定しても KiCad の timestamp や再保存時の
  セグメント差は残るので、ACD の正規化規則（`deterministic_zip`、normalized hash）は
  そのまま必要。「コンテナ化したから再現する」とは書けない。
- image が重い（KiCad + FreeCAD/OCP で数GB）。初回 build は分単位。
  Apple Silicon では `linux/amd64` エミュレーションで大幅に遅くなる
  （`platform="linux/arm64"` にすると KiCad の arm64 パッケージ可用性の確認が必要）。
- **ライセンス**: KiCad は GPLv3、freerouting も GPL 系（版により要確認）。
  image を配布すると GPL の頒布義務（対応ソースの提供）が発生しうる。
  安全側は「Dockerfile と pin 情報を repo に公開し、image は各自でローカル build」。
  publish するなら義務の確認が先。
- CI で使うには docker daemon が必要（GitHub Actions ならホストの docker で可、
  dind 構成なら追加設定）。`health_check_timeout` 既定120秒は KiCad 入り image では
  余裕を見て延ばす。
- secret は `forward_env` 既定に含まれないので、LLM key や将来の fab API key は
  `sdk.secret`（`SecretSource` / `LookupSecret`）または agent-server 設定経由で渡す。
  `-e` で素通しするとコンテナ環境に平文で残る。
- SDK への**ランタイム依存**が増える（現在は import 0件）。vendor submodule の
  更新負債が上がるので ADR-0006（vendor方針）の再検討が必要。
- 代替として `openhands-workspace` には `apptainer`（rootless / HPC）、
  `remote_api`、`cloud` もある。Docker が使えない環境向けの逃げ道はある。

## 5. 最小の第一歩（B1）

1. `docker/acd-tools.Dockerfile` を追加（kicad-cli 9.x / java+freerouting / ngspice を版固定）
2. 1回だけ `BuildOptions(base_image="acd-tools:<tag>", target="source", push=False)` で
   agent-server 層を載せて `acd-agent-server:<tag>` を作る（digest を記録）
3. `scripts/run_in_workspace.py`（新規）で
   `DockerWorkspace(server_image="...@sha256:...", volumes=[f"{repo}:/workspace"])` を開き、
   `execute_command("uv run python scripts/run_gd1_pipeline.py --out out/gd1")` を実行
4. `execution_env()` を `ACD_EXECUTION_ENV` 尊重に変更（未設定時は現状の文字列、
   コンテナ実行時は digest 入り。digest 不明は `unknown`）
5. GD1 の output_hash が host 実行と一致するか比較し、差が出たら
   「正規化規則の不足」として記録する（ここが一番価値のある観測点）

この段までで ACD 本体の変更は `execution_env()` 1関数 + 新規 script + Dockerfile + ADR 1本。
ゲート・閾値・期待値は一切変更しない。
