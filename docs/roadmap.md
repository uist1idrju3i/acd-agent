# 実装ロードマップ

> ステータス: 現行実装と近い順の計画

## 現在地

OpenHands plugin、8 Skill、5 AgentDefinition、`/acd:gates`、SDK ToolDefinition、
GD1基板・筐体pipelineを提供する。GD1基板はERC、routing収束、SES import、DRC、
fabrication出力、独立再読込、silkscreen可読性ゲートまで通過する。一方、
[`golden-design-1.md`](golden-design-1.md) §7の設計述語ゲート6件
（USB CC、strapping pin、I2C pull-up、電源デカップリング、電源境界、
ピン・FW整合）は実装済みで、§8のNEG-001〜008も決定論的な注入関数と
ID別negative testで整備済みである。DRC結果のToolEnvelope input hashと
ゲート時点で期待される派生基板の再ハッシュを照合し、対応しない結果をゲート未実行として停止する。
視覚投影のprovenance契約とKiCad SVG renderer（8.1〜8.2）は
実装済みである。現行運用は回路図ビューと層別レイアウトビューを再現可能な観測として
記録し、電気laneではゲート通過後の既定生成配線まで実装済みである。機械laneの
断面・干渉ビューrenderer、AI受け渡しと機械可読電気・機械lane投影との照合、レビュー観点記録まで
実装済みである。
SDK hooksによるfail-closed境界も提供する。筐体pipelineは決定論的ゲートを通過する。
実機Evidenceのschema契約と分類、実機の受領取り込み、FW書き込み・機能測定は実装済みである。
マイルストーン5.4の測定結果反映はproposal生成まで実装済みであるが、proposalから設計入力への
自動逆流は設計上行わない。GD1実機の`measured` Evidenceは未取得で、検証はfixtureベースである。
マイルストーン7は、見積入力契約と保存済みfixtureの読取（7.1）、総発注額の合算（7.2）、
発注前最終ゲート（7.3）、side-effect journal（7.4）、自働発注のdry-runと拒否境界（7.5）
まで実装済みである。ただし、供給者からの価格・在庫・納期・実装可否の自動取得、
実providerへの送信と実発注完了は本範囲外であり、量産対応とともに将来範囲である。
`AcdGateCritic`は決定論的ゲート結果を使うL2操舵として実装済みである。
SDKへ委譲するのは反復制御だけであり、criticはpass evidenceではない。
GD1の独立したwidth positive-control armは固定順で並列集約し、`acd-search`は候補と
provenanceだけを返す。SDK workflowは採用しない。
roadmap 4.4は`sdk.context.prompts`、`sdk.llm.router`、`sdk.io`、
`sdk.logger`／`sdk.observability`、`sdk.settings`／`sdk.credential`／`sdk.profiles`、
`sdk.context.memory`／`sdk.context.view`、`sdk.workspace`まで実装済みである。
hostはSDK `LocalWorkspace`によるprovisional実行に限定し、authoritativeなゲート実行は
digest固定`DockerWorkspace`だけが担う。

決定論的ゲートのauthoritative Evidenceはdigest固定container実行だけが生成する。
runnerとCIは事前build済みdigest固定server imageによる`DockerWorkspace`経路へ移行済みである。
ホスト経路はprovisional専用であり、経路unknownはfail-closedとする。
agent-server package、REST/WebSocket API、server側のresume/forkは
[`ADR-0026`](adr/ADR-0026-openhands-delegation-contract.md)により対象外であり、
[`ADR-0025`](adr/ADR-0025-agent-server-production-adoption.md)はSupersededである。
採用する場合は認証・権限・Evidence境界の受入条件を定義した新規ADRを起票する。
Conversationは現行の`DockerWorkspace`経路で検証し、決定論的gateの代替にはしない。

## 現行実装計画

| 順 | マイルストーン | 達成条件 | 現状 |
|---|---|---|---|
| 1 | 契約と再現可能な投影 | graphをPydanticで検証し、同一入力から投影・provenance・hashを再生成できる | 達成 |
| 2 | 電気レーンの独立検証 | ERC、routing収束、SES import、DRC、Gerber/drill生成、独立再読込、silkscreenゲートを通す | 達成 |
| 2.1 | 設計述語ゲートと負例 | USB CC、strapping pin、I2C pull-up、電源デカップリング、電源境界（`SafetyBoundaryResult`）、ピン・FW整合の6ゲートを実装し、GD1-NEG-001〜008とsilkscreen座標表のpinning testを整備する | 達成 |
| 3 | 機械レーンの決定論的検証 | STEP/3MF生成、CAD再読込、干渉・clearance・肉厚を通す | 達成 |
| 4 | plugin委譲とSDK tool境界 | Skill/agent/command/toolをSDKでloadし、既存gateをfail-closedで公開する | 達成 |
| 4.1 | SDK hooks境界 | 投影保護、Evidence発注ガード、Stop、probe、文書検証を既存判定の呼出しとして実装する | 達成 |
| 4.2 | 決定論的gate critic | Design Graph revision、Evidence、製造manifestだけで二値criticを評価し、SDK反復を操舵する | 達成 |
| 4.3 | 決定論的探索lane | 独立width armを固定順で並列集約し、探索AgentDefinitionは候補とprovenanceだけを返す | 達成 |
| 4.4 | SDK機能移譲 | SDKのcontext、routing、保存、観測、設定、credential、profile、workspaceへ責務を段階移譲する | 達成（hostは`LocalWorkspace`によるprovisional専用、authoritative経路はdigest固定`DockerWorkspace`） |
| 4.5 | 能力カタログ検査の強化 | 採用行の代表APIまたはドメインがACDコード・plugin資材・テストのどこで使われているかを参照検査し、間接利用とテスト利用の参照先を種別付きで宣言してdriftをfail-closedで検出する | 達成 |
| 5 | 実機フィードバック | 製造・組立・測定結果をEvidenceとして取り込み、次の入力へ反映する | 5.1〜5.4実装（GD1実機measured Evidence未取得） |
| 6 | 実行基盤のDockerWorkspace一本化 | 事前build済みdigest固定server imageでゲートを実行し、authoritative Evidence経路を単一化する | 6.1〜6.5完了（tools／server digest記録済み、runnerとCIは`DockerWorkspace`経路へ移行済み） |
| 7 | 発注前最終ゲートと自働発注 | 期限付き見積入力と全ゲート再実行を条件に、side-effect journalへ記録した発注だけを許可する | 7.5 dry-run・拒否境界まで達成（実発注は本範囲外） |
| 8 | 視覚投影レビュー基盤 | 画像生成、画像hash・renderer種別・解像度の記録、機械可読投影との決定論的照合、レビュー観点の記録、`ImageContent`／`inspect_image_with_vision`経路、SSRF境界を実装する | 8.1〜8.6実装済み、8.5はFW lane照合まで実装済み |
| 9 | 生成文書lane | 設計入力、投影、ゲート結果、Evidenceから再現可能な製品・品質・レビュー文書を生成する | 計画 |
| 10 | シミュレーション解析lane | 電気・機械・FWのprovisional解析を追加し、決定論的ゲートを置き換えずに結果を文書へ統合する | 計画 |
| 11 | 機構設計拡張 | 可動機構、干渉、機構向けDFM、部品込み3D統合を機械laneへ追加する | 計画 |
| 12 | 設計ナレッジQA | 設計知識源への出所引用付きQAと公開用FAQ生成を、unknown停止と会話ログ公開除外の規則付きで提供する | 計画 |
| — | agent-server採用判断 | 対象外を維持し、採用する場合だけ新規ADRで認証・権限・Evidence境界を定義する | 対象外 |

各マイルストーンとフェーズの完了条件は、(1)入力と出所、(2)実装、(3)正常系、
(4)negative/fail-closed、(5)再現性の5要素で確認する。SkillやAIの所見だけでは完了としない。
以降のフェーズ表は各要素の確認内容を定義する。

### 2.1 設計述語ゲートと負例

[`golden-design-1.md`](golden-design-1.md) §7の6ゲートと§8の負例を、
電気Evidenceおよび決定論的受入ゲートへ接続する。6ゲート、正常系、負例fixtureを実装し、
8件の停止条件をID別テストで回帰へ含める。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | GD1のDesign Graph、FW pin assignment、部品・ネット宣言、電源境界仕様、silkscreen resolverの最終座標、現行revision |
| 実装 | USB CC、strapping pin、I2C pull-up、電源デカップリング、電源境界（`SafetyBoundaryResult`）、ピン・FW整合の6ゲートを決定論的述語として実装し、結果を電気Evidenceのclaimへ追加する |
| 正常系 | 6ゲートがrevision一致の入力から再現可能に評価され、GD1の電気Evidenceへ各結果が記録される。silkscreen最終配置座標表をfixtureとpinning testで固定する。KiCadライブラリがある`--stage standard`ではtestを実行し、hostに無い場合は既存のskip慣習で前提不足を明示する。`container-gates`では固定image内でKiCad依存の同じ3件を実行する |
| negative/fail-closed | 述語・入力・型の欠落は合格にしないことをunit testで確認し、NEG-001〜008を決定論的な注入関数とID別negative testで検証する。DRCの入力hash不一致・`unknown`、異なる入力集合・ファイル名、基板欠落はゲート未実行として停止する |
| 再現性 | 同一graph、FW入力、fixture、revisionから同一ゲート結果、Evidence claim、座標表を再生成し、NEG-001〜008のnegative testを回帰へ含める。DRC結果はゲート時点の基板bytesを再ハッシュして対応を検証する |

KiCadライブラリを要するNEG-002およびライブラリhash不一致の補助testは、
ライブラリのない`verify` jobでは前提不足としてskipし、KiCad有効な
`container-gates`で実行する。ローカルの`--stage standard`ではライブラリがある場合に
実行し、ない場合は同じ条件でskipする。

## マイルストーン4.4: SDK機能移譲

secret allowlistの`SecretSource`、`EnsembleSecurityAnalyzer`、`ConfirmRisky`、
Skill明示ロード、`StuckDetector`、`ConversationStats`／`Metrics`のL3観測出力、
role別promptの`PromptSection`化と資材manifest drift検査、role別LLM routing policyは
実装済みである。`FileStore`によるL3観測保存と観測の構造化ログ出力、
settings/profile資材のcanonical hash固定とcredential参照名だけの保持、
永続memoryの明示有効化と表示専用event view projectionも実装済みである。
`ToolDefinition`、現行の`DockerWorkspace`、決定論的gateの責務境界は変更しない。
MCP、Canvas、remote API、cloud、agent-serverは採用しない。

- `sdk.context.prompts`: `plugins/acd/agents/*.md`のrole別promptをSDK prompt構造へ寄せ、
  資材hashを固定してpromptとの整合性を確認する。
- `sdk.llm.router`: judge modelと主agent modelを分離する（決定論的な
  `AcdGateCritic`は変更しない）。routing結果は合否へ影響させず、policy hashと
  非Evidence観測を固定する。
- `sdk.io`: `src/acd/openhands/session/bootstrap.py`のmetrics/stats保存を`FileStore`
  抽象へ移譲する。L3観測だけを対象とし、Evidenceと設計入力の保存経路は変更しない。
- `sdk.logger`／`sdk.observability`: 実装済み。metrics/stats/goal_result/
  model_routing_observationの保存経路を`ObservationLogRecord`の構造化ログへ寄せ、
  観測名・field名・canonical hashだけを出力する。値は出力せず、secretは
  `SecretRegistry`のmask経路で検知し、未知の`artifact_kind`、pass authority
  相当のfield、書込み失敗、ログ出力失敗はfail-closedにする。
- `sdk.settings`／`sdk.credential`／`sdk.profiles`: 実装済み。secret allowlistと
  profile driftを`plugins/acd/agent-settings.json`のsettings資材へ移し、
  canonical hashを固定して`OpenHandsAgentProfile`としてsecret-freeに検証する。
  credentialは`SecretRegistry`参照名だけを保持し、値は保存・出力しない。
  hash不一致、routing policyとのprofile drift、allowlist外の参照名、unknown設定は
  `unknown`で停止するfail-closedとし、`scripts/verify_agent_settings.py --check`を
  通常検証へ組み込む。
- `sdk.context.memory`: 実装済み。`.openhands/memory/MEMORY.md`のmemoryを
  `build_acd_conversation(enable_persistent_memory=True)`の明示有効化だけで読み込み、
  作業文脈の補助に限定する。観測は`MemoryContextObservation`のpath・文字数・hashだけとし、
  memory本文をEvidence／pass判定へ流さない。secret混入、読込失敗、index不在は
  fail-closedにする。
- `sdk.context.view`: 実装済み。SDK `View`から`EventViewProjection`を生成し、
  表示する各eventが原EventLogに同一内容で存在することを照合する。canonical hashを固定し、
  hash不一致・EventLog不一致・EventLog外eventはfail-closedにする。projectionと
  memory観測はgate criticのEvidence経路で明示的に拒否し、同一EventLogから同一viewを
  再生成する`scripts/verify_context_view.py --check`を通常検証へ組み込む。
- `sdk.workspace`／`LocalWorkspace`: 実装済み。`--local-provisional`の明示opt-inから
  `LocalWorkspace(working_dir=...)`をcontext managerとして使い、host結果をprovisional型で返す。
  container markerまたはdigest環境変数がある場合は経路を拒否する。
- `workspace.DockerWorkspace`: 実装済み。authoritativeなゲート実行はdigest固定server imageを
  `DockerWorkspace`へ渡す既存経路だけに限定し、host結果をEvidenceのauthoritative passへ昇格しない。

### 4.5 能力カタログ検査の強化

`docs/openhands-sdk-capabilities.md`の採否はドメイン単位の判断であり、SDK内部経路を
含む間接利用と、明示したテスト利用を区別して記録する。代表APIまたはドメインの参照先を
ACDコード・plugin資材・テストへ種別付きで記録し、採用行の未使用・参照先欠落・catalog
driftをfail-closedで検出する。現行catalogは採用46行の参照を宣言し、テスト専用の
`sdk.testing`だけをテスト直接importとして登録する。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `docs/openhands-sdk-capabilities.json`、pinned SDKの代表API一覧、ACDコード、plugin資材、テスト、SDK経路の間接利用宣言 |
| 実装 | `scripts/verify_sdk_capabilities.py`に直接import、SDK内部経路、plugin資材、テスト直接importの4種別を追加し、参照先を宣言する |
| 正常系 | 4種別をroot境界付きで区別して検査し、採用行の根拠とテスト利用をMarkdownへ再生成できる |
| negative/fail-closed | 採用行の参照先欠落、4種別のroot境界違反、直接import・SDK内部経路・plugin token・テスト直接importの不備、catalogと生成Markdownのdriftを検出して停止する。検査ロジックを代表APIの存在確認だけへ弱めない |
| 再現性 | 固定SDK checkout、catalog、ACD/plugin入力から同一Markdownと同一検査結果を再生成する |

## マイルストーン5: 実機フィードバック

製造・組立・測定の結果を実機Evidenceとして取り込み、次の設計入力へ反映する。
実機Evidenceは決定論的ゲートの合否を置き換えず、入力更新の根拠として扱う。
GD1の実機Evidence 4件と分類規則は[`golden-design-1.md`](golden-design-1.md)の
9章を正とする。

### 5.1 実機Evidence契約と分類

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 測定機器名・版、治具、実行条件、測定者、取得時点、対象graph revisionを入力に持つ契約を実装した |
| 実装 | `acd.schema.evidence`に`measured`／`virtual`の分類、測定量・単位・期待範囲・許容差、機器情報、時刻整合性、canonical hashを追加した |
| 正常系 | `measured`分類のvalid recordが必須項目と値域を満たし、`supports_pass(revision)`の判定対象として読み込めることをfixtureとtestで確認した |
| negative/fail-closed | 分類欠落、`unknown`分類、単位欠落、revision不一致、機器版unknown、時刻逆転、値域外、測定量ゼロ件をfixtureとtestに含めた。実機Evidenceのauthoritative合格は常に拒否する |
| 再現性 | フィールド順に依存しないcanonical JSONから同一入力の同一hashを得るtestを追加した |

### 5.2 製造・組立受領の取り込み

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `ReceiptRecord`がfab／assembler、業者名、記録者、出所URI、受領物、検査レポート参照、送付manifest参照、送付・受領・記録時刻を保持する |
| 実装 | `acd.core.receipt`と`scripts/ingest_receipt.py`で受領recordを製造データpackageのmanifestと決定論的に突合し、対応結果を型付きreportへ記録する |
| 正常系 | 送付manifestと受領recordのhash・対象revision・成果物一覧が一致し、`measured`分類のhost実機Evidenceとして残る |
| negative/fail-closed | manifest hash不一致、revision不一致、`status: "fail"`、manifest構造不備、受領物の欠落・余剰・hash不一致、検査レポート欠落、日時逆転を停止条件にする。manifestの`unknowns`自体はsortedキーをreportへ残し、受領物の突合は継続する |
| 再現性 | 受領recordの取り込みをCLIで再実行でき、同一入力から同一report・Evidenceバイト列とcanonical hashになる |

### 5.3 FW書き込みと機能測定

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `FunctionalRunRecord`がESP-IDF版、toolchain版、project commit、`.elf`／`.bin`成果物、`app_flash_offset`、build／flash／LED／serialの生ログ、測定機器、シリアルtag、期待条件、時刻を宣言する |
| 実装 | `acd.core.firmware`と`scripts/ingest_functional_run.py`が宣言hashを実ファイルへ照合した後、build、flash、LED capture、serial logを独立parserで読み直す |
| 正常系 | 固定版の宣言値と成果物hashが一致し、ESP32-C3書き込み検証、LED 1 Hz、温湿度値域・周期を満たす4件の`measured` host実機Evidenceを個別に保存する |
| negative/fail-closed | 成果物・ログhash不一致、成果物欠落、必須ログ行の欠落・形式不正・parse不能は`unknown`、ESP-IDF版不一致、書き込みverify数不足・対象chip不一致、値域外、周波数・duty・周期外れは`fail`として停止する。flashは書き込み行と`Hash of data verified.`行の件数一致、app offset・サイズ一致、`Hard resetting`完了を検査する |
| 再現性 | recordと保存済み生ログから同一report・4件のEvidenceバイト列とcanonical hashを再生成し、各negative fixtureを含める |

### 5.4 測定結果の入力反映ループ

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 5.1〜5.3の実機Evidenceと現行の設計入力ファイル、git revisionを入力する |
| 実装 | 明示的な反映policyに従い、実機Evidenceと設計入力の差分、更新候補、必要なrationaleを型付きproposal documentへ提示する。入力ファイルは書き換えない |
| 正常系 | proposal documentを人または別の明示的工程でレビュー・適用した後、適用後validatorで宣言された属性だけの変更を検査できる |
| negative/fail-closed | 投影や実機Evidenceを入力へ直接逆流させる経路、stale／virtual／invalid Evidence、policy不整合、unclassified属性、rationale欠落をunknownまたは適用不可として扱う |
| 再現性 | 同一のgraph、rationale、policy、実機Evidence集合から同一のproposalとcanonical hashを再生成し、適用後の余分な差分をnegative testに含める |

5.4では`propose_input_feedback.py`が入力を読み取り、`set_value`または`reconfirm`の
明示的な反映policyに基づく提案だけを出力する。`rationale_required`が残る提案は
適用可とは扱わず、proposalから入力への自動逆流は実装しない。stale Evidence、
unclassified属性、policy不整合はfail-closedでstatusを`unknown`とする。

## マイルストーン6: 実行基盤のDockerWorkspace一本化

6.1ではACD toolsのpublish済みdigestを`docker/image-digests.json`へ記録した。
6.2では、そのlock済みtools digestをbaseにするagent-serverのbuild／publish workflowを追加した。
6.3ではrunnerを事前build済みserver imageの`DockerWorkspace(server_image=...)`へ切り替え、
6.4ではCIをlock解決とpullへ移行し、6.5では旧dev workspace経路を撤去した。
derived server digestはpublish実行後にlockへ記録済みである。base tools digest
`sha256:daf2908f4742e5a0d29ad3bcef187b9b11832701bf6b38fd2e2150b94bf1e301`と、それから
deriveしたserver digest
`sha256:cc605baff68b8d2648d208fe6c29dee57bd418b3e3da7c5f3837708a14792f3b`は
独立した値として保持する。受入条件は
[`ADR-0026`](adr/ADR-0026-openhands-delegation-contract.md)の入口と実行形、
[`ADR-0028`](adr/ADR-0028-execution-provenance.md)の実行provenanceを正とする。
フェーズは6.1から順に依存する。

agent-server packageの直接API、REST/WebSocket経路、server側のresume/forkは本
マイルストーンに含めない。conversation persistenceは`LocalConversation`の
`persistence_dir`範囲に限り、再開結果をauthoritative Evidenceへ昇格しない。

### 6.1 ACD tools imageのpublishとdigest記録

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `docker/acd-tools.Dockerfile`、pinned SDK版、`publish-acd-tools.yml`のjob summaryのGHCR digest |
| 実装 | publish済みdigestと外部ツール版を運用記録へ転記し、参照refとdigestを対応付ける |
| 正常系 | 記録したdigestをpullして`probe_tools.py`が既知の外部ツール版を報告する |
| negative/fail-closed | placeholder digest、未publish状態でのlock作成、digest未解決のpullを禁止する |
| 再現性 | 同一Dockerfileとpinned SDK版から同一の外部ツール版一覧が得られることを記録する |

### 6.2 事前build済みagent-server imageの整備

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 6.1のACD tools image digestとpinned SDK v1.42.1のagent-server構成 |
| 実装 | server実行資材を含むimageを事前buildしてpublishし、derived digestを独立に記録する |
| 正常系 | publish済みserver imageのdigestを指定してworkspaceが起動し、command実行が成功する |
| negative/fail-closed | base imageとderived imageのdigestを同一と主張する記述、digest不明起動を拒否する |
| 再現性 | 同一入力から再buildしたimageのtool版とentrypointが一致することを記録する |

### 6.3 runnerの`DockerWorkspace`切替

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 6.2のserver image digest、`src/acd/openhands/workspace.py`の現行runner契約 |
| 実装 | `DockerWorkspace(server_image=...)`へ切り替え、digestとcontainer markerをforwardする |
| 正常系 | resolver、GD1基板pipeline、GD1筐体pipelineがcontainer内で実行され、Evidenceが`container`＋digestを持つ |
| negative/fail-closed | digest未解決、`server_image`未指定、command失敗、file download失敗で非ゼロ終了する |
| 再現性 | 同一digestでの再実行が同一のEvidence hashを生成し、digest欠落のnegative testを含める |

### 6.4 CI authoritative gateの移行

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `.github/workflows/ci.yml`の`container-gates` job、6.1のdigest記録 |
| 実装 | 毎回のbuildxビルドから記録済みdigestのpullへ移行し、`verify_authoritative_evidence.py`の検査を維持する |
| 正常系 | CIが両laneのEvidenceをrevision一致・`status="valid"`・既知provenance・digestで通す |
| negative/fail-closed | digest未記録時の暗黙build fallback、pull失敗時の合格を禁止する |
| 再現性 | 同一commitと同一digestでCIを再実行して同一の検査結果になる |

### 6.5 ホスト経路のprovisional固定と移行完了判定

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | host実行のEvidence、container実行のEvidence、`ADR-0028`の`execution_context`契約 |
| 実装 | 旧SDK dev workspace経路を撤去し、host経路はprovisional専用として文書と実装で明示する |
| 正常系 | authoritative Evidenceの生成経路が`DockerWorkspace`だけになり、文書の記述と一致する |
| negative/fail-closed | host Evidenceの合格側昇格、旧dev workspace残存参照、経路unknownを拒否する |
| 再現性 | 移行後のCIとローカル実行の双方で同一のEvidence provenanceを再生成できる |

## マイルストーン7: 発注前最終ゲートと自働発注

金銭と納期が発生する不可逆点は発注だけである。発注は全ゲート通過と上限額の2条件を
満たす場合に限り許可し、実行はside-effect journalへ記録する。設計要件は
[`SECURITY.md`](../SECURITY.md)の「AIエージェント特有の前提」、
発注ガードの縮約は[`ADR-0008`](adr/ADR-0008-minimal-vibebb-scope.md)、
製造データと`unknown`境界は[`ADR-0005`](adr/ADR-0005-jlcpcb-pcba-preparation-contract.md)を正とする。

### 7.1 期限付き見積入力の取得契約（達成）

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | fab／distributorの価格・在庫・納期・実装可否を、出所URL、取得時点、有効期限付きで入力する |
| 実装 | 期限付き見積入力のPydantic契約と取得記録を追加し、値の一次確認区分を保持する |
| 正常系 | 期限内かつ必須項目を満たす入力から、部品・基板・実装の各費目が確定値として読める |
| negative/fail-closed | 期限切れ、出所欠落、取得時点不明、`unknown`混在を停止条件にする |
| 再現性 | 保存済み取得recordから同一の費目集合とcanonical hashを再生成し、期限切れのnegative testを含める |

`QuoteRecord`はfixtureとして保存したfab／distributorの見積入力を、URL、取得時点、
有効期限、記録時点、対象revisionとともに検証する。金額は通貨コードと最小通貨単位桁数を
持つ整数であり、基板・部品・実装・送料・税の費目を表現する。`read_quote()`は評価時刻と
対象revisionを明示的に受け取り、一次確認（`primary`）の金額だけを確定値として費目集合へ
読み出す。`inference`の金額、期限切れ、出所欠落、必須区分欠落、通貨不一致、
`unknown`混在はfail-closedで停止する。返すのは7.2以降が参照する入力集合とcanonical hash
だけであり、合否権限、発注許可、外部送信は持たない。実発注は行わず、7.5のdry-runまで
別工程として扱う。

### 7.2 総発注額の合算契約（達成）

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 7.1の費目、fab profileの宣言値、筐体・機械部品を含む対象範囲の宣言 |
| 実装 | fab profile一致を確認し、基板、部品、実装、機械部品、送料、税を合算する契約を実装し、内訳と対象revisionを記録する |
| 正常系 | GD1の総発注額が内訳付きで確定し、上限額との比較が決定論的に行える |
| negative/fail-closed | 費目欠落、通貨・税条件不明、内訳と総額の不一致を`unknown`として停止する |
| 再現性 | 同一の見積入力集合から同一の総額と内訳hashを再生成する |

`OrderScope`は対象revision、fab profile、相手方区分、許可供給者、必須費目区分、
送料・税の扱い、機械部品の扱い、通貨・桁数を明示する入力契約である。`QuoteRecord`の
供給者申告総額は費目合計と契約validatorで照合し、`aggregate_order_total()`は7.1の
`read_quote()`を再利用して一次確認済み・期限内の費目だけを区分別に合算する。返却する
小計、総額、各見積のcanonical hash、内訳hashは再現性のための入力結果であり、各recordの
供給者申告総額の合計と内訳から積み上げた総額も突合する。上限額との比較、合否、Evidence、
発注許可は7.3以降の責務としてこの層へ導入しない。

### 7.3 発注前最終ゲート（達成）

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 現行git revisionの設計入力、authoritative Evidence、7.2の総額、宣言された上限額 |
| 実装 | 発注直前に全決定論的ゲートを現revisionで再実行し、上限額とゲート通過の2条件を判定する。order policyの`required_evidence_ids`へ電気laneの`evidence.gd1.electrical`を追加し、両laneのauthoritative Evidence一致を要求する |
| 正常系 | 全ゲートがrevision一致のauthoritative Evidenceで通り、総額が上限内のときだけ許可を返す |
| negative/fail-closed | ゲート未実行、provisional Evidence、revision不一致、dirty入力、上限超過、判定unknownで却下する |
| 再現性 | 同一revisionと同一入力で同一判定になり、各却下条件のnegative testを回帰へ含める |

### 7.4 side-effect journal（達成）

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 7.3の許可record、送信対象の製造データpackage hash、宛先、実行時刻、操作の冪等key |
| 実装 | 不可逆操作の事前予定と事後結果をhash連鎖付きJSON Linesの追記専用journalへ記録し、許可recordと相互参照する。読み出し時に契約、連鎖、冪等性、対応関係を再検証する |
| 正常系 | 発注1件がjournalの事前・事後1組で追跡でき、receiptと成果物hashが対応する |
| negative/fail-closed | journal書込み失敗、許可record不在、冪等key重複による再送、事後記録欠落、既存行の改変・削除・並べ替え、hash・package・revision・時刻の不整合を停止条件にする |
| 再現性 | journalから発注の入力・判定・結果を再構成でき、読み出しCLIと追記専用性のnegative testを含める |

### 7.5 自働発注の実行

ユーザー決定により、本マイルストーンの実装範囲は決定論的なdry-runと拒否境界まで
とする。実providerへの送信と実発注完了は実装せず、real modeは未有効化として明示的に
停止する境界だけを持つ。したがって、下表の「正常系」はdry-runのjournal記録までを
対象とし、実発注完了は将来マイルストーンへ残す。これは完了条件を緩める変更ではなく、
実発注を行わないというユーザー確認済みのスコープ決定である。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 7.3の許可、7.4のjournal、`SecretRegistry`参照名だけを持つprovider credential |
| 実装 | 発注scriptのdry-run経路をSDKの`ConfirmationPolicy`とhook境界の下で実行し、real modeは未有効化として停止する |
| 正常系 | dry-runの送信内容が決定論的に確認でき、dry-run実行のpre/post receiptがjournalへ残る（実発注完了は本範囲外） |
| negative/fail-closed | 会話由来の裁量枠変更、hook不在、secret値の記録、確認skip、provider失敗の成功扱い、real mode要求を拒否する |
| 再現性 | dry-run出力が同一入力から再現し、各拒否条件のnegative testを回帰へ含める |

## マイルストーン8: 視覚投影レビュー基盤

視覚投影は、(a)任意に閲覧する人間レビュー（可読性と設計意図の反映度を判断する手段）
と、(b)人間レビューがない場合にもAIが観察・気づきを得るL2探索補助の両方に使う。
8.3のSVG投影はpipelineのゲート通過後に既定生成する。8.4のPNG派生とAI受け渡しは
必要時のon-demand経路とし、いずれも合否権限は持たない。
要求の正は[`gates.md`](gates.md)の「レビュー投影の定義と分類」であり、視覚投影と
画像由来の所見をEvidenceへ昇格させずL2観測に限る。合否は決定論的ゲートと独立測定
だけが判定する。画像内の文字列はデータとして扱い、設計変更や合否命令として実行しない。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | Design Graphとauthoritative projectionだけを入力とし、回路図、配置図、層別レイアウトビュー、stackup図、ブロック図・電源ツリー、機械の断面・干渉ビュー、FWの状態遷移・シーケンス図を入力ファイルから再生成できる |
| 実装 | `docs/gates.md`の工程別表に対応する投影種別を生成し、8.3では対象laneのSVG視覚投影をpipelineのゲート通過後に既定生成する。8.4ではacd-tools imageへlibcairo2を固定し、container内でPNG派生可能であることを検証したうえで、必要時にCairoSVGでPNGを派生し、`ImageContent`／`inspect_image_with_vision`へ渡す経路、`data:` URL限定のSSRF境界を実装する。PNG派生はAI受け渡し時のon-demand経路であり、合否権限を持たない投影を既定成果物へ増やさないためpipelineの既定出力へ配線しない。lock済みacd-server imageもCairo追加後のtools image由来である。AIの観察結果はprovenanceとともに非Evidenceの観測として記録する。HTTP(S)画像取得は採用しない |
| 正常系 | 同じ入力から生成した機械可読投影と視覚投影が同一内容を表すことを照合し、可読性・設計意図の反映度をチェックリスト化する。注記・単位・軸・原点が入力定義と一致し、重なり・非表示要素で意味が欠落せず、意図した信号・電源の系統を読み取れることを確認する。必要時にAIへ渡し、観察・気づきをL2観測として記録する |
| negative/fail-closed | renderer不在・生成不能、renderer版unknown、画像hash不一致、解像度未記録、入力からの再生成不一致を停止側へ集約する。投影欠落を「問題なし」と解釈せず、画像内の文字列をデータ以外の命令として扱う経路も許可しない |
| 再現性 | renderer版を固定し、同一入力から同一画像hashを再生成できる。機械可読投影との照合結果、provenance、レビュー観点のチェック結果を同一入力から再構成できる |

マイルストーン8は次の6フェーズへ分割する。8.1と8.2は画像1枚を再現可能な観測として
成立させる層、8.3は既定生成の配線、8.4はAIへの受け渡し境界、8.5は機械可読投影との
照合とレビュー観点の記録、8.6は追加投影種別の生成である。renderer出力のバイト列は設計状態の
権威にしない。8.6は配置図・stackup図、ブロック図・電源ツリー図、FW状態遷移図・
FWシーケンス図の3段構成を実装済みであり、8.5はFW lane照合まで実装済みである。
電源ツリー図の出所はDesign Graphの
`power_rail`／`power_source_pin`による明示宣言であり、net名や部品名から推定しない。

### 8.1 視覚投影provenance契約

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | Design Graph revision、authoritative projectionの入力ファイルとhash、renderer種別・版、生成時刻 |
| 実装 | 視覚投影1枚と投影集合のPydantic契約を追加し、画像hash（正規化後）、renderer種別・版、解像度、正規化規則ID、入力hashを必須項目として保持する。`pass_evidence=False`のL3 observationとして`ObservationArtifactKind`へ登録する |
| 正常系 | 記録済みの投影集合をfixtureから復元し、投影識別子、renderer版、解像度、正規化規則、入力hashが読める |
| negative/fail-closed | renderer版unknown、解像度未記録、画像hash欠落・unknown、絶対パスや`..`を含む画像パス、投影識別子重複、`pass_evidence`真を拒否する |
| 再現性 | 同一の投影集合から同一のcanonical hashを再生成し、各拒否条件のnegative fixtureを回帰へ含める |

### 8.2 renderer adapterと決定論的再生成

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | pipelineが投影したKiCad schematicとboard、`kicad-cli`版 |
| 実装 | `kicad-cli`のSVG出力で回路図ビューと層別レイアウトビューを生成する。SVG冒頭の`<title>`が出力ファイル名と生成時刻を埋め込むため、`<title>`要素だけを正規化する規則を契約へ書き、規則外の差異を停止条件とする。解像度は宣言値ではなく生成された画像バイト列から測定する。renderer版は`kicad-cli`から取得し、unknownはfail-closedにする |
| 正常系 | GD1の投影から回路図ビューと層別レイアウトビューを生成し、正規化後の画像hash、renderer版、測定した解像度を持つ投影recordを得る |
| negative/fail-closed | renderer不在、非零終了、出力欠落、renderer版unknown、`<title>`が想定形と一致しない、解像度が測定できない、2回目の生成で正規化後hashが一致しないを停止条件にする |
| 再現性 | 同一入力・同一renderer版から同一の正規化後画像hashを再生成し、正規化規則の適用範囲をunit testで固定する |

### 8.3 ゲート通過後の既定生成配線

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 電気laneおよび機械laneの決定論的ゲート通過後のauthoritative投影成果物、現行revision |
| 実装 | GD1基板pipelineのERC、routing収束、DRC、独立再読込、silkscreen、DFM、設計述語の決定論的ゲート通過後に電気laneの回路図ビューと宣言銅層ごとの層別レイアウトビューを既定生成し、筐体pipelineの機械ゲート通過後にauthoritative assembly STEPから機械laneの断面・干渉ビューを既定生成する。各投影集合をL3 observationとして書き出し、order readinessは視覚投影の前提に含めない。生成失敗はpipelineの停止条件とし、Evidenceへは昇格させない |
| 正常系 | GD1基板・筐体pipelineの完走時に各laneの投影集合が観測として残り、機械laneは断面・干渉SVGを生成する |
| negative/fail-closed | ゲート未通過での生成、renderer不在・版不明、authoritative STEP不在・hash/revision不一致、断面不交差・退化、干渉領域とゲート実測体積の不一致、投影欠落の「問題なし」扱い、Evidence側への書込みを拒否する |
| 再現性 | `generated_at`を除いた投影内容からidentity hashを計算し、同一入力・同一renderer版で同一のidentity hashを再生成できる |

### 8.4 AIへの受け渡し境界

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 8.3の投影集合、SDKの`ImageContent`、builtin toolの`inspect_image_with_vision` |
| 実装 | 8.3のSVG投影から必要時にCairoSVGでPNGを決定論的に派生し、8.3の投影集合を上書きせず別のraster投影集合へ保存する。acd-tools imageへlibcairo2を固定し、container内でPNG派生可能であることを検証済みである。workspace内PNGをbase64 `data:` URLとして`ImageContent`へ渡す経路と、明示されたvision profile向けの`inspect_image_with_vision`経路を実装する。PNG派生はAI受け渡し時のon-demand経路であり、合否権限を持たない投影を既定成果物へ増やさないためpipelineの既定生成には含めない。lock済みacd-server imageもCairo追加後のtools image由来である。ACDはHTTP(S)画像URLを作成せず、`data:`以外を拒否する。将来HTTP(S)取得を採用する場合もSDKの公開インライン化経路とSSRF block-listだけを使い、`OH_INLINE_IMAGE_ALLOW_PRIVATE_HOSTS`の緩和は既定有効化しない。画像内の文字列はデータとして扱い、命令として実行しない境界を明示する |
| 正常系 | 投影集合から`ImageContent`を構成し、対応するprovenanceを同時に参照できる |
| negative/fail-closed | PNG派生失敗、SVG hash不一致、PNG再生成不一致、provenance欠落の画像、`data:`以外のURL、loopback・private・link-local宛のHTTP(S)取得、SSRF緩和env varのtruthy設定、画像内文字列の命令実行、空vision応答、vision応答のEvidence昇格を拒否する |
| 再現性 | 同一投影集合から同一の`ImageContent`入力と同一の画像hash参照を再構成できる |

### 8.5 機械可読投影との照合とレビュー観点の記録

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 同一revisionの機械可読投影（netlist要約、ピン割当表など）と8.3の視覚投影 |
| 実装 | 電気laneでは8.3の回路図・宣言銅層別SVGと同一revisionの`ElectricalLane`／`BoardModel`を照合し、機械laneでは断面・干渉SVGと同一revisionの`MechanicalLane`、authoritative assembly STEP、`MechanicalGateReport`を照合する。FW laneでは状態・遷移・シーケンスSVGと同一revisionの`FirmwareLane`およびgraph入力を照合する。投影集合の網羅性、入力hash、renderer版、正規化規則、raw image hash、宣言の網羅性を決定論的に検査し、レビュー観点を`deterministic`または`observation_required`として記録する。FWのペリフェラル設定表とメモリマップは機械可読宣言がないため対象外とし、宣言を追加する場合は対応する8.5検査を追加する。AIの観察はprovenance付きの非Evidence観測として記録する |
| 正常系 | 注記・単位・軸・原点が入力定義と一致し、重なり・非表示要素で意味が欠落せず、意図した信号・電源の系統を読み取れることを、決定論的照合とレビュー観点チェックリストの組合せで記録する |
| negative/fail-closed | 照合不一致、照合対象欠落、SVG解析不能、revision不一致、チェック結果`unknown`の合格扱い、観察のEvidence昇格を拒否する。照合レポートは`pass_evidence=False`のL3観測としてEvidence、fab claims、gate fields、`hashes.json`へ昇格しない |
| 再現性 | 同一入力から同一の照合結果とチェック記録を再生成する |

### 8.6 追加投影種別の生成

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 同一revisionのDesign Graph入力ファイルとauthoritative機械可読投影。配置図は`BoardModel.placements`、stackup図は`BoardView.layers`・`thickness_mm`・`outer_copper_thickness_um`・`copper_thickness_source`、ブロック図はDesign Graphのnode種別と`depends_on`、電源ツリー図は`NetView.voltage_nominal_v`とpin接続、FW状態遷移・シーケンス図は`firmware.module`へ追加する機械可読宣言を出所とする |
| 実装 | リポジトリ内の決定論的SVG renderer（`acd-svg`）で配置図、stackup図、ブロック図、電源ツリー図、FW状態遷移図、FWシーケンス図を生成し、8.1のprovenance契約へ投影識別子、source revision、入力pathとhash、出力hash、renderer版、生成時刻、再生成判定、正規化規則IDを記録する。renderer版はコード側で固定し、生成時刻や絶対パスをSVGへ埋め込まない。宣言の欠落は推定で埋めずfail-closedとする。全投影は`pass_evidence=False`のL3観測であり、画像とAI所見はDesign Graph、rationale、policy、gate status、Evidence、fabrication claimsへ逆流しない |
| 正常系 | 同一入力から各投影種別を生成し、2回目の生成で同一の画像hashを再現する。生成した投影集合はrevisionと入力hashから出所を追跡できる |
| negative/fail-closed | renderer不在、renderer版unknown、入力ファイル欠落、宣言欠落（基板厚、外層銅厚、銅厚出所、FW状態・遷移）、未対応の層数・実装面、投影識別子重複、SVG解析不能、画像hash不一致、再生成不一致、revision不一致、`pass_evidence`真を拒否する |
| 再現性 | 同一入力・同一renderer版から同一の画像hashとidentity hashを再生成し、各拒否条件のnegative testを回帰へ含める |

8.6は3段で実装する。配置図とstackup図、ブロック図と電源ツリー図、FWの状態遷移・シーケンス図
（機械可読宣言の追加を含む）の順であり、本節の完了条件は3段すべての実装で満たす。

## 改善バックログ（2026-08-20 実行例とレビューからの反映）

実行例で得た改善メモ（[`improvement-notes.md`](../examples/sensor-node-20260820/report/improvement-notes.md)）
とレビュー所見（[`review-notes.md`](../examples/sensor-node-20260820/report/review-notes.md)）から、
実装・運用へ反映する項目を次のバックログとして記録する。いずれも計画・注記であり、
現行の閾値、ゲート挙動、fail-closed境界を変更または緩和するものではない。

| 項目 | 出所 | 対応方針 | 状態 |
|---|---|---|---|
| 視覚投影SVGへのviewBox相対font-size付与（placement / power-tree / system-block / fw-state / fw-sequence） | レビュー | マイルストーン8 rendererを改善し、viewBoxに対して可読な相対font-sizeを付与する | 未着手 |
| KiCad由来SVG（f-cu / b-cu / schematic）のfit-to-board化 | レビュー | 用紙全面プロットで基板が極小表示される問題を解消するrendererまたは後処理を実装する | 未着手 |
| 回路図投影の可読性向上 | レビュー | 機能ブロック配置と主要配線を描画するか、ネットラベル接続方式である旨を投影へ注記する | 未着手 |
| 出力ファイルprefixとevidence subject_nodeのgraph_id由来化 | 改善メモ／レビュー | `gd1`固定を解消し、出力命名とEvidenceの対象nodeを入力graphから導出する | 未着手 |
| ToolEnvelopeの`exit_code`のツール別意味論の文書化 | レビュー | kicad-cli ERC/DRCは違反件数由来で非ゼロになりうることを記録し、statusと混同しない説明を追加する | 未着手 |
| order-readiness `ready`の定義へのCPL実装基準の明示 | レビュー | position/rotation basisについてfab側目視確認を前提とすることをreadyの定義へ明記する | 未着手 |
| fixture複製ヘルパと組立手順のdocs化 | 改善メモ | libraries/overlays込みで新規fixtureを組み立てるヘルパと手順を追加する | 未着手 |
| FW pipelineのhost前提の`/acd:doctor`診断化 | 改善メモ | QEMU PATH、libslirp0、SDL2系ライブラリを診断項目へ追加する | 未着手 |
| 実行時clone不要化（locked imageへのacd本体・scripts・fixture同梱） | セッション分析／ユーザー要望 | authoritative経路はimage内のacd本体・pipeline scripts・fixtureだけで完結させ、DockerWorkspace起動のみで実行可能にする。リポジトリcloneは開発時のみ必要とする | 未着手 |
| ESP-IDF・QEMU実行環境のlocked image同梱 | セッション分析／ユーザー要望 | ESP-IDF v5.3.1、Espressif QEMU 9.2.2、libslirp0、SDL2系ライブラリ、PATH設定を同梱し、FW laneをcontainer経路で実行可能にする | 未着手 |
| Python依存のprebake | セッション分析／ユーザー要望 | cadquery-ocp等の巨大wheelを含む依存を事前解決したvenv／uvキャッシュをimageへ同梱し、起動高速化とネットワーク非依存の再現性を得る | 未着手 |
| fonts-noto-cjkの同梱 | セッション分析／ユーザー要望 | 視覚投影の日本語描画とSVG→PNG派生hashの安定化のためCJKフォントを固定同梱する | 未着手 |
| ccacheの同梱 | セッション分析／ユーザー要望 | ESP-IDF再ビルドを高速化する | 未着手 |
| KiCad 3Dモデルの選択的同梱 | セッション分析／ユーザー要望 | 設計で使用する部品の3Dモデルのみを単一imageへ同梱し、部品込みSTEP表現を可能にする。フル同梱（kicad-packages3d 約6GB）とimage分割はdigest管理・再現性・CI運用の複雑化を伴うため将来判断とする | 未着手 |
| host EDA不在時のdoctor誘導 | 改善メモ | doctor出力へlocked image + DockerWorkspaceの推奨経路への誘導リンクを追加する | 未着手 |
| OpenHands Local GUI APIのトークン発行手順のdocs化 | 改善メモ | トンネル越しcurlがUnauthorizedとなる制約を踏まえ、自動化検証に必要なGUI経由のトークン取得手順を記録する | 未着手 |
| FW出力命名の改善（`acd_gd1_fw`ディレクトリを含む） | 改善メモ | FW成果物の固定名と`acd_gd1_fw`固定ディレクトリ名を解消し、graph_idを出力名へ反映する | 未着手 |
| pipelineログの要約出力（入力トークン削減） | [session-analysis.md](../examples/sensor-node-20260820/report/session-analysis.md) | pipelineログのtail既定化など、再取り込み量を削減する要約出力を実装する | 未着手 |
| SKILL triggerとACD ToolDefinition会話登録条件・doctor診断の見直し | レビュー／[session-analysis.md](../examples/sensor-node-20260820/report/session-analysis.md) | 実運用語彙でacd-qc-seven-tools / acd-reliability-reviewを活性化できるtriggerへ見直し、会話へのACD ToolDefinition登録条件を文書化し、登録有無をdoctorで診断する | 未着手 |
| hook遮断（UserRejectObservation）の要約自動集計 | レビュー／[session-analysis.md](../examples/sensor-node-20260820/report/session-analysis.md) | hookによる遮断理由を実行レポートへ自動集計し、振り返り可能な要約を残す | 未着手 |
| リリース手順のdocs化 | [session-analysis.md](../examples/sensor-node-20260820/report/session-analysis.md) | タグ作成権限・ruleset、GH013時の対応、実行例リンク中心のリリースノート、Release assetsを添付しない方針を運用手順へ記録する | 未着手 |

上記のimage同梱には、imageサイズ増加、publish時間の増加、digestの再lock、
ADR-0028のprovenance更新が伴う。ただし、閾値やゲート挙動の変更ではない。

## マイルストーン9: 生成文書lane（SKILL拡張）

成果物公開・品質保証・レビューに使う文書を、設計入力・投影・ゲート結果・Evidenceから
決定論的に生成する。生成文書はL3観測（提示物）であり、合否権限を持たず、
投影を設計入力へ逆流させない不変条件を維持する。文書はworkspaceの`out/docs/`へ格納し、
入力hash・生成ツール版・テンプレートhashをprovenanceとして記録する。
必要な入力（ゲート結果、Evidence、視覚投影）が欠落する場合は生成をfail-closedで停止し、
「問題なし」とは解釈しない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 9.1 | 製品説明README生成SKILL | 図解入りの製品説明`README.md`を生成する。Design Graphの仕様（MCU、電源、センサ、I/F）、BOMサマリ、視覚投影（回路図・配置・電源ツリー・筐体断面）を埋め込み、公開用にライセンス・帰属注記を自動付与する |
| 9.2 | 取扱説明書生成SKILL | 機能説明・接続手順・LED表示の意味・書き込み手順・安全注意を、graphとFWピン投影（`acd_pins.h`相当）から生成する。値はすべて入力由来とし、推定値を書かない |
| 9.3 | 品質文書生成SKILL | ゲート結果（ERC/DRC/DFM/機械/FW）、rationale coverage、authoritative Evidence、既知の未実装チェック一覧から検査成績書・トレーサビリティレポートを生成する。Evidence欠落・revision不一致は生成失敗として停止する |
| 9.4 | レビュー資料生成SKILL | レビューチェックリスト、視覚投影一式、前revisionとのgraph差分、DRC/DFM所見の要約を1パッケージへまとめ、`acd-reviewer`agentの入力にする |
| 9.5 | 多言語出力 | 9.1〜9.4の文書を日本語・英語で再現可能に生成する（テンプレート分離、値の翻訳はしない） |

## マイルストーン10: シミュレーション解析lane

電気・機械・FWの解析をprovisional検証として追加する。解析結果はL2操舵・L3観測であり、
決定論的ゲートの合否を置き換えない。閾値との比較をゲート化する場合は、
入力・ツール版・メッシュ／刻み幅を固定した再現可能な決定論的判定として個別に定義する。
GPLツール（ngspice、CalculiX等）はsubprocess実行に限定し、ACDへのimport結合をしない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 10.1 | 電気シミュレーション（SPICE） | 同梱済みngspiceで、graphから電源系ネットリスト（LDO・デカップリング・LED電流・I2Cプルアップ）を決定論的に抽出して過渡・動作点解析を実行し、値域チェックを行う |
| 10.2 | 電源系解析（PDN/IR drop） | ガーバ・銅箔形状から電源経路の断面積・電流密度・IR dropを推定し、閾値超過を停止側の所見として報告する |
| 10.3 | 機械解析（質量・熱・構造） | 質量特性・肉厚（実装済み）に加え、熱抵抗の簡易推定と、FEM（CalculiX等のCLI）による落下・応力・熱の解析経路を追加する |
| 10.4 | FW解析 | 静的解析（clang-tidy相当）、スタック使用量解析、QEMU上のペリフェラルスタブ（SHT40応答モデル等）による機能テストを追加し、仮想検証の範囲を広げる |
| 10.5 | 解析結果の文書統合 | 10.1〜10.4の結果を9.3品質文書・9.4レビュー資料へ取り込む |

## マイルストーン11: 機構設計拡張

筐体（静的な箱）から機構（可動・組立）へ機械laneを拡張する。

| 順 | フェーズ | 内容 |
|---|---|---|
| 11.1 | 機構要素ライブラリ | スナップフィット、ヒンジ、ボタン・ライトパイプ、ボス・リブをbuild123dのパラメトリック部品として追加し、寸法根拠をrationale必須にする |
| 11.2 | 可動干渉チェック | 可動範囲のスイープ干渉を決定論的ゲートとして追加する（開閉・押下ストローク） |
| 11.3 | 製造性チェック拡張 | 3Dプリント／射出成形向けのDFM（最小肉厚、抜き勾配、オーバーハング）を機械laneゲートへ追加する |
| 11.4 | 部品込み3D統合 | KiCad 3Dモデルの選択的同梱（バックログ）と連携し、基板＋部品＋筐体の統合干渉チェックと組立図投影を生成する |

## マイルストーン12: 設計ナレッジQA

完成した設計の知識源（design graph、rationale record、ゲート結果、Evidence、生成文書、
git履歴、revision差分、会話ログ）を照会可能なナレッジとしてまとめ、製品仕様、使い方、
トラブルシューティング、設計根拠、歴史的経緯の質問に出所の引用付きで答える。
対象ユーザは設計者・開発チームと、成果物を受け取る第三者（製品ユーザ・レビュア）の両方とする。
回答はL2操舵・L3観測であり、合否権限を持たない。回答は必ず出所（rationale ID、
Evidenceファイル、コミット、文書パス）を引用し、知識源から導出できない質問には
unknownと答え、推測で補完しない。会話ログは内部向けQAの知識源にのみ含め、
公開用FAQの知識源には含めない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 12.1 | ナレッジ索引契約 | graph・rationale・ゲート結果・Evidence・生成文書・git履歴・会話ログを、出所種別と参照パス付きで列挙する索引contractを定義する。欠落した知識源はunknownとして記録する |
| 12.2 | 対話QA SKILL | OpenHands会話内で製品仕様・使い方・トラブルシューティング・設計根拠・歴史的経緯の質問に、索引contractの範囲で出所引用付きの回答を返すSKILL（例: `/acd:ask`）を追加する |
| 12.3 | トラブルシューティング知識の構造化 | 症状→確認手順→期待値（LED表示、I2Cアドレス、期待シリアル出力等）をgraphとFW投影から機械可読に導出し、12.2と公開用FAQの共通知識源にする |
| 12.4 | 公開用FAQ生成 | 成果物と一緒に公開できるFAQ・ナレッジ文書を`out/docs/`へ生成する（マイルストーン9の文書laneと同じprovenance規則）。知識源から会話ログを除外し、除外した旨をprovenanceへ記録する |
| 12.5 | 歴史的経緯QA | git履歴・revision差分・会話ログ（内部のみ）・ECO記録から「いつ・なぜ変わったか」を出所引用付きで回答する経路を追加する |

## 追加SKILL候補（バックログ）

| 項目 | 対応方針 |
|---|---|
| ブリングアップ試験計画の生成 | 実機フィードバック（マイルストーン5）の入力となる測定点・期待値・手順のチェックリストをgraphから生成する |
| BOMコンプライアンス事前チェック | BOM部品属性からRoHS等の申告状況を集計し、不明部品をunknownとして列挙する（適合判定はしない） |
| BOMコスト・代替部品検討 | JLCPCB basic/extended区分や代替候補の整理を、保存済み見積入力（7.1契約）の範囲で支援する |
| 面付け（panelization）対応 | 小基板の面付けガーバ生成とDFM再検査を追加する |
| graph差分投影 | revision間のgraph差分（追加・削除・属性変更）を視覚投影し、レビュー資料へ統合する |
| 製造しやすさ（DFA）レビューSKILL | 組立性・作業性・生産性の観点（部品の向きの統一、片面実装可否、手はんだ部品のアクセス性、コネクタ・ケーブルの組付け順序、筐体組立の工数、治具の要否）をレビュー観点として構造化し、graph・配置・筐体形状からL2所見として報告する |
| 出荷検査文書生成SKILL | 出荷検査の検査項目・実施方法・合否判定基準（外観、導通・電源電圧、書き込み・起動確認、LED・センサ動作、期待シリアル出力）を生成する。判定基準の値はgraph・ゲート閾値・FW投影由来に限定し、出所のない基準を作らない。導出できない項目はunknownとして人手決定欄を残す。生成文書はマイルストーン9のprovenance規則に従い`out/docs/`へ格納する |
| 出荷検査モード付きFW開発機能 | 出荷検査文書と対になる検査モード（自己診断・検査シーケンス）をFWへ組み込む開発機能を追加する。検査モードはUART等の明示操作でのみ起動し、検査項目（LED点灯、I2Cセンサ応答、電源電圧の自己確認等）と結果出力形式を出荷検査文書生成SKILLと同じ知識源（graph・FW投影）から導出する。検査結果の出力はprovisional観測であり、実測Evidenceへの昇格はマイルストーン5の実機フィードバック契約に従う |

## 拡張候補バックログ（2026-08-20 追加調査からの反映）

現行実装計画と将来構想でカバーされていない拡張候補を、追加調査の結果として記録する。
いずれも計画であり、現行の閾値、ゲート挙動、fail-closed境界、L1権限の範囲を
変更または緩和するものではない。

### A. 設計能力の拡張

| 項目 | 対応方針 |
|---|---|
| 4層基板・階層graph対応 | 現行の2層・フラット構造前提を拡張し、stackup宣言、差動ペア・インピーダンス管理配線の契約とゲートを追加する |
| バッテリ駆動製品対応 | 充電IC・残量計・保護回路の設計述語と、電力バジェット（消費電流と容量の収支）を宣言由来の入力から決定論的に検査するゲートを追加する |
| EMC/ESD設計述語 | 外部コネクタへの保護素子の有無、電源ループ面積、リターンパス連続性のチェックを設計述語として追加する（認証適合の判定はしない） |
| テスト容易化設計（DFT） | テストポイントのネットカバレッジをゲート化し、プローブアクセス（最小間隔・径）を検査する |

### B. 部品・サプライチェーン

| 項目 | 対応方針 |
|---|---|
| 部品ライブラリ統治SKILL | footprintのpad寸法・courtyard・原点をライブラリ契約として検査する。今回のDRC警告30件（`lib_footprint_issues`）の類型に対応する |
| EOL・セカンドソース管理契約 | 部品のライフサイクル状態と代替候補を宣言contractとして記録し、未宣言はunknownとして停止側へ集約する（外部APIの自動照会は別途判断） |

### C. FW拡張

| 項目 | 対応方針 |
|---|---|
| secure boot・flash暗号化・OTA設計対応 | パーティション構成・鍵管理境界・OTAスロットを宣言として扱い、ビルド設定との整合をゲート化する。鍵素材は扱わない |
| QEMUコードカバレッジと実機HIL接続 | QEMU実行でのカバレッジ計測を追加し、実機フィードバック（マイルストーン5）のHIL測定Evidenceへ接続する |

### D. プロセス・UX

| 項目 | 対応方針 |
|---|---|
| `acd init`ウィザード | fixture複製ヘルパ（改善バックログ）を一般化し、graph・rationale・libraries・overlaysの新規プロジェクト雛形を対話的に生成する |
| GitHub Actions統合 | 設計変更PRへゲート結果・Evidence要約を自動コメントする。コメントはL3提示であり合否権限を持たない |
| 視覚投影の自動品質検査 | 8.4のvision経路で投影の可読性（文字の重なり、極小表示、コントラスト）をL2所見として検出する。今回のfont-size問題の再発防止に対応する |
| トークン・コスト予算ガード | セッションのトークン消費・実行時間をL2で監視し、予算超過を警告する（実行の強制停止はhook側の判断とする） |

### E. 改訂管理

| 項目 | 対応方針 |
|---|---|
| ECOワークフローとrevisionライフサイクル | 設計変更指示（変更理由・影響範囲・再検証要件）をcontract化し、revision遷移とゲート再実行の対応関係を文書化する |

## 次回実装スコープ（2026-08-20 選定）

ユーザー体験に直結する項目を優先して、次回の実装対象を以下に確定する。
上から依存順であり、いずれも既存の閾値、ゲート挙動、fail-closed境界を変更しない。

1. 視覚投影SVGへのviewBox相対font-size付与とKiCad由来SVGのfit-to-board化（改善バックログ）
2. 回路図投影の可読性向上（改善バックログ）
3. 出力ファイルprefix・Evidence subject_nodeのgraph_id由来化とFW出力命名の改善（改善バックログ）
4. マイルストーン9.1 製品説明README生成SKILL
5. マイルストーン9.2 取扱説明書生成SKILL
6. 実行時clone不要化（locked imageへのacd本体・scripts・fixture同梱）（改善バックログ）
7. ESP-IDF・QEMU実行環境のlocked image同梱（改善バックログ）
8. Python依存のprebake（改善バックログ）
9. fonts-noto-cjkの同梱（改善バックログ）
10. ccacheの同梱（改善バックログ）
11. host EDA不在時のdoctor誘導（改善バックログ）
12. SKILL triggerとACD ToolDefinition会話登録条件・doctor診断の見直し（改善バックログ）
13. hook遮断（UserRejectObservation）の要約自動集計（改善バックログ）
14. マイルストーン12 設計ナレッジQA（12.1〜12.5）
15. 出荷検査文書生成SKILL（追加SKILL候補）
16. 出荷検査モード付きFW開発機能（追加SKILL候補）
17. 視覚投影の自動品質検査（拡張候補バックログD）

## 将来構想

現行実装計画の次に残る機能は、次の構想として保持する。

- routing後のvia mask開口を含む投影・実測・再配置の反復
- 複数fab profileと製造データ契約の拡張
- 長時間運用と予算監視、ローカル製造
- 高密度基板、認証設計、熱・SIなどの拡張
- agent自体のコンテナ化と配布済みACD image
- 複数instanceのshared storage負荷検証

## 検証要件

変更ごとに、契約・投影・独立再読込・決定論的ゲートを実行する。ツール不在、
parse失敗、未実行、unknownはfail-closedとする。Markdownのみの変更は
`verify_docs.py`と`git diff --check`で検証し、それ以外は`AGENTS.md`の全検証を行う。

## フェーズ横断の検証要件

以下は全マイルストーンの完了条件に共通して要求する。固有の達成条件が満たされても、
ここに反する実装は合格にしない。これらは実際の欠陥類型に基づく設計判断であり、
外部リポジトリの記述を権威として引くものではない。

| # | 要件 | 禁止する構造 |
|---|---|---|
| 1 | 判定の両辺は別の出自から取る | 自分が生成した成果物の存在を自分の合格根拠にする（自己証明）。replay結果同士、生成器同士の比較 |
| 2 | 導出できない入力は`unknown`として停止側へ集約する | `continue`・早期return・既定値補完でskipを合格に見せる。宣言の欠如を0や空と同一視する |
| 3 | 実行中のstageを入場時に宣言し、失敗はその宣言から帰属させる | 直前の成功結果や末尾要素を失敗の帰属先にする |
| 4 | CIが読み込む入力・fixture・scriptはtrackedにし、typecheck／lintの対象に含める | 検査対象外の領域を「検査済み」と扱う。gitignore下のデータに依存する回帰 |
| 5 | 外部ツールの保存バイト列を設計状態の権威にしない。非決定な出力は正規化規則を契約に書き、規則外の差異は停止条件とする | 外部ツールの決定論性を説明で仮定する（timestamp、再保存時のセグメント構成差など） |
| 6 | 契約はPydanticモデルから導く | runnerと文書でgate番号・状態を二重管理する |
| 7 | 安全条件・保護対象は書き換わる部分木で判断する | pathの完全一致だけで許可・却下を決める |
| 8 | 予算（token、money、wall-clock、外部process回数）を各ゴールデンタスクで実測して記録する。`ADR-0026`の観測境界に従いSDK `Metrics`／`ConversationStats`と外部ツールの実行記録を使う | 予算を実測せず見積や説明で代替する。`Metrics`／`ConversationStats`出力を合格根拠へ昇格させる |
| 9 | 探索を含む工程では、代理指標スコアを合格根拠にせず、停止理由と実行結果を記録する | 代理指標をL1合否へ混入する。停止理由を記録しない |

## 見直し条件

外部ツールの非決定性が正規化できない、一次情報とライセンス境界が合わない、
negative testなしでしか完了条件を満たせない場合は、その機能を止めてADRと本書を
更新する。閾値・期待値を変更して成功に見せない。
