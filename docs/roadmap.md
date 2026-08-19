# 実装ロードマップ

> ステータス: 現行実装と近い順の計画

## 現在地

OpenHands plugin、8 Skill、5 AgentDefinition、`/acd:gates`、SDK ToolDefinition、
GD1基板・筐体pipelineを提供する。GD1基板はERC、routing収束、SES import、DRC、
fabrication出力、独立再読込、silkscreen可読性ゲートまで通過する。一方、
[`golden-design-1.md`](golden-design-1.md) §7の設計述語ゲート6件
（USB CC、strapping pin、I2C pull-up、電源デカップリング、電源境界、
ピン・FW整合）は実装済みで、§8のNEG-001〜006・008も決定論的な注入関数と
ID別negative testで整備済みである。NEG-007は派生状態とDRC結果の対応検査が未実装で、
未検出の残件である。視覚投影レビューも未実装であり、
現行運用は機械可読投影と独立測定だけを使用する。
SDK hooksによるfail-closed境界も提供する。筐体pipelineは決定論的ゲートを通過する。
実機Evidenceのschema契約と分類、実機の受領取り込み、FW書き込み・機能測定は実装済みである。
マイルストーン5.4の測定結果反映はproposal生成まで実装済みであるが、proposalから設計入力への
自動逆流は設計上行わない。GD1実機の`measured` Evidenceは未取得で、検証はfixtureベースである。
価格・在庫・納期取得、発注は未実装である。
`AcdGateCritic`は決定論的ゲート結果を使うL2操舵として実装済みである。
SDKへ委譲するのは反復制御だけであり、criticはpass evidenceではない。
GD1の独立したwidth positive-control armは固定順で並列集約し、`acd-search`は候補と
provenanceだけを返す。SDK workflowは採用しない。
roadmap 4.4は`sdk.context.prompts`、`sdk.llm.router`、`sdk.io`、
`sdk.logger`／`sdk.observability`、`sdk.settings`／`sdk.credential`／`sdk.profiles`、
`sdk.context.memory`／`sdk.context.view`まで実装済みで、残るのは`sdk.workspace`の
authoritative経路化だけである。

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
| 2.1 | 設計述語ゲートと負例 | USB CC、strapping pin、I2C pull-up、電源デカップリング、電源境界（`SafetyBoundaryResult`）、ピン・FW整合の6ゲートを実装し、GD1-NEG-001〜008とsilkscreen座標表のpinning testを整備する | 一部達成（6ゲート、Evidence claim、正常系、述語のfail/unknown unit test、NEG-001〜006・008の注入fixtureとID別negative test、resolver実出力を検証するsilkscreen座標pinningを実装。NEG-007は派生状態とDRC結果の対応を検出する経路が未実装のため残件） |
| 3 | 機械レーンの決定論的検証 | STEP/3MF生成、CAD再読込、干渉・clearance・肉厚を通す | 達成 |
| 4 | plugin委譲とSDK tool境界 | Skill/agent/command/toolをSDKでloadし、既存gateをfail-closedで公開する | 達成 |
| 4.1 | SDK hooks境界 | 投影保護、Evidence発注ガード、Stop、probe、文書検証を既存判定の呼出しとして実装する | 達成 |
| 4.2 | 決定論的gate critic | Design Graph revision、Evidence、製造manifestだけで二値criticを評価し、SDK反復を操舵する | 達成 |
| 4.3 | 決定論的探索lane | 独立width armを固定順で並列集約し、探索AgentDefinitionは候補とprovenanceだけを返す | 達成 |
| 4.4 | SDK機能移譲 | SDKのcontext、routing、保存、観測、設定、credential、profile、workspaceへ責務を段階移譲する | 一部実装（`sdk.context.prompts`、`sdk.llm.router`、`sdk.io`、`sdk.logger`／`sdk.observability`、`sdk.settings`／`sdk.credential`／`sdk.profiles`、`sdk.context.memory`／`sdk.context.view`実装済み。`sdk.workspace`はマイルストーン6依存） |
| 4.5 | 能力カタログ検査の強化 | 採用行の代表APIまたはドメインがACDコード・plugin資材・テストのどこで使われているかを参照検査し、間接利用とテスト利用の参照先を種別付きで宣言してdriftをfail-closedで検出する | 達成 |
| 5 | 実機フィードバック | 製造・組立・測定結果をEvidenceとして取り込み、次の入力へ反映する | 5.1〜5.4実装（GD1実機measured Evidence未取得） |
| 6 | 実行基盤のDockerWorkspace一本化 | 事前build済みdigest固定server imageでゲートを実行し、authoritative Evidence経路を単一化する | 6.1〜6.5完了（tools／server digest記録済み、runnerとCIは`DockerWorkspace`経路へ移行済み） |
| 7 | 発注前最終ゲートと自働発注 | 期限付き見積入力と全ゲート再実行を条件に、side-effect journalへ記録した発注だけを許可する | 未着手 |
| 8 | 視覚投影レビュー基盤 | 画像生成、画像hash・renderer種別・解像度の記録、`ImageContent`／`inspect_image_with_vision`経路、SSRF境界を実装する | 未着手 |
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
| negative/fail-closed | 述語・入力・型の欠落は合格にしないことをunit testで確認し、NEG-001〜006・008を決定論的な注入関数とID別negative testで検証する。NEG-007は、現行pipelineに派生状態とDRC結果の対応を検査する経路がなく、未検出の残件である |
| 再現性 | 同一graph、FW入力、fixture、revisionから同一ゲート結果、Evidence claim、座標表を再生成し、実装済みnegative testを回帰へ含める。NEG-007の検出経路追加後に8件全体へ拡張する |

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
- `sdk.workspace`／`workspace.DockerWorkspace`: host workspaceはprovisionalに限定し、
  マイルストーン6の完了後にauthoritative経路化する。

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
derived server digestは初回publish実行後にlockへ記録済みである。base tools digest
`sha256:e64405a15e69991063c688a80b4f215bdc3dbfb8b4fb480b3ef3484f017e1395`とderived server
digest `sha256:a18a56564b7c713b45052ab8c296b59ffcd7fc221f4ed1d0564f4c934b853def`は独立した値
として保持する。受入条件は
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

### 7.1 期限付き見積入力の取得契約

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | fab／distributorの価格・在庫・納期・実装可否を、出所URL、取得時点、有効期限付きで入力する |
| 実装 | 期限付き見積入力のPydantic契約と取得記録を追加し、値の一次確認区分を保持する |
| 正常系 | 期限内かつ必須項目を満たす入力から、部品・基板・実装の各費目が確定値として読める |
| negative/fail-closed | 期限切れ、出所欠落、取得時点不明、`unknown`混在を停止条件にする |
| 再現性 | 保存済み取得recordから同一の費目集合を再生成し、期限切れのnegative testを含める |

### 7.2 総発注額の合算契約

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 7.1の費目、fab profileの宣言値、筐体・機械部品を含む対象範囲の宣言 |
| 実装 | 基板、部品、実装、送料、税を合算する契約を実装し、内訳と対象revisionを記録する |
| 正常系 | GD1の総発注額が内訳付きで確定し、上限額との比較が決定論的に行える |
| negative/fail-closed | 費目欠落、通貨・税条件不明、内訳と総額の不一致を`unknown`として停止する |
| 再現性 | 同一の見積入力集合から同一の総額と内訳hashを再生成する |

### 7.3 発注前最終ゲート

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 現行git revisionの設計入力、authoritative Evidence、7.2の総額、宣言された上限額 |
| 実装 | 発注直前に全決定論的ゲートを現revisionで再実行し、上限額とゲート通過の2条件を判定する。order policyの`required_evidence_ids`へ電気laneの`evidence.gd1.electrical`を追加し、両laneのauthoritative Evidence一致を要求する |
| 正常系 | 全ゲートがrevision一致のauthoritative Evidenceで通り、総額が上限内のときだけ許可を返す |
| negative/fail-closed | ゲート未実行、provisional Evidence、revision不一致、dirty入力、上限超過、判定unknownで却下する |
| 再現性 | 同一revisionと同一入力で同一判定になり、各却下条件のnegative testを回帰へ含める |

### 7.4 side-effect journal

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 7.3の許可record、送信対象の製造データpackage hash、宛先、実行時刻、操作の冪等key |
| 実装 | 不可逆操作の事前予定と事後結果を追記専用journalへ記録し、許可recordと相互参照する |
| 正常系 | 発注1件がjournalの事前・事後1組で追跡でき、receiptと成果物hashが対応する |
| negative/fail-closed | journal書込み失敗、許可record不在、冪等key重複による再送、事後記録欠落を停止条件にする |
| 再現性 | journalから発注の入力・判定・結果を再構成でき、追記専用性のnegative testを含める |

### 7.5 自働発注の実行

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 7.3の許可、7.4のjournal、`SecretRegistry`参照名だけを持つprovider credential |
| 実装 | 発注scriptをSDKの`ConfirmationPolicy`配下でsubprocess実行し、dry-runと実発注を分離する |
| 正常系 | dry-runで送信内容を確認した後、許可済みの実発注が完了しreceiptがjournalへ残る |
| negative/fail-closed | 会話由来の裁量枠変更、hook不在、secret値の記録、確認skip、provider失敗の成功扱いを拒否する |
| 再現性 | dry-run出力が同一入力から再現し、各拒否条件のnegative testを回帰へ含める |

## マイルストーン8: 視覚投影レビュー基盤

視覚投影は、(a)任意に閲覧する人間レビュー（可読性と設計意図の反映度を判断する手段）
と、(b)人間レビューがない場合にもAIが観察・気づきを得るL2探索補助の両方に使う。
可能な工程ではpipelineのゲート通過後に既定生成してAIへ渡すが、合否権限は持たない。
要求の正は[`gates.md`](gates.md)の「レビュー投影の定義と分類」であり、視覚投影と
画像由来の所見をEvidenceへ昇格させずL2観測に限る。合否は決定論的ゲートと独立測定
だけが判定する。画像内の文字列はデータとして扱い、設計変更や合否命令として実行しない。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | Design Graphとauthoritative projectionだけを入力とし、回路図、配置図、層別レイアウトビュー、stackup図、ブロック図・電源ツリー、機械の断面・干渉ビュー、FWの状態遷移・シーケンス図を入力ファイルから再生成できる |
| 実装 | `docs/gates.md`の工程別表に対応する投影種別を生成し、pipelineのゲート通過後に対象laneの視覚投影を既定生成してAIへ渡す配線を実装する。各画像の画像hash・renderer種別・版・解像度を記録するprovenance契約、`ImageContent`／`inspect_image_with_vision`経路、HTTP(S)画像のbase64インライン化とSSRF block-list境界を実装する。AIの観察結果はprovenanceとともに非Evidenceの観測として記録する |
| 正常系 | 同じ入力から生成した機械可読投影と視覚投影が同一内容を表すことを照合し、可読性・設計意図の反映度をチェックリスト化する。注記・単位・軸・原点が入力定義と一致し、重なり・非表示要素で意味が欠落せず、意図した信号・電源の系統を読み取れることを確認する。人間レビューがなくてもAIへ既定配線し、観察・気づきをL2観測として記録する |
| negative/fail-closed | renderer不在・生成不能、renderer版unknown、画像hash不一致、解像度未記録、入力からの再生成不一致を停止側へ集約する。投影欠落を「問題なし」と解釈せず、画像内の文字列をデータ以外の命令として扱う経路も許可しない |
| 再現性 | renderer版を固定し、同一入力から同一画像hashを再生成できる。機械可読投影との照合結果、provenance、レビュー観点のチェック結果を同一入力から再構成できる |

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
