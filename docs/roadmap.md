# 実装ロードマップ

> ステータス: 現行実装と近い順の計画

## 現在地

OpenHands plugin、11 Skill、5 AgentDefinition、`/acd:gates`、SDK ToolDefinition、
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

視覚投影はviewBox相対font-sizeまで実装済みで、
出力命名とEvidenceの対象nodeはgraph_id由来である。KiCad由来SVGのfit-to-board化
（用紙余白の除去）は未実装である。8.5の電気視覚照合が図枠のtitle blockをツール生成の
根拠として読むため、`--exclude-drawing-sheet`と`--page-size-mode`を使わない現行exportを
維持しており、極小表示の所見は20.4の可読性検査で扱う。locked tools imageはacd本体、
pipeline scripts、fixture、profile、ESP-IDF v6.0.2、Espressif QEMU 9.2.2、CJKフォント、
ccache、事前解決したPython依存を同梱し、authoritative経路はcloneなしで実行できる。
回路図投影は機能ブロック配置と主要配線またはネットラベル接続方式を注記し、可読性向上を
実装済みである。運用面では、host EDA不在時のdoctor誘導、FW出力命名のgraph_id由来化、
SKILL triggerとToolDefinition登録条件のdoctor診断、hook遮断理由の要約自動集計まで実装済みである。
マイルストーン9は9.1製品説明READMEと9.2取扱説明書の生成SKILLまで実装済みである。
マイルストーン12は知識index、出典付きQA、トラブルシューティング導出、公開FAQ生成、
歴史的経緯QAまで実装済みで、いずれも`pass_evidence=false`のL3観測である。

決定論的ゲートのauthoritative Evidenceはdigest固定container実行だけが生成する。
runnerとCIは事前build済みdigest固定server imageによる`DockerWorkspace`経路へ移行済みである。
ホスト経路はprovisional専用であり、経路unknownはfail-closedとする。
agent-server package、REST/WebSocket API、server側のresume/forkは
[`ADR-0026`](adr/ADR-0026-openhands-delegation-contract.md)により対象外であり、
[`ADR-0025`](adr/ADR-0025-agent-server-production-adoption.md)はSupersededである。
採用する場合は認証・権限・Evidence境界の受入条件を定義した新規ADRを起票する。
Conversationは現行の`DockerWorkspace`経路で検証し、決定論的gateの代替にはしない。

設計述語の契約が特定のnet名・refdesを前提としているため、GD1以外のトポロジは現状の
ゲートに到達できない（14.2）。また、Skill scriptのpinned refが実装より古く、
FW laneはGD1 fixtureでも停止する（14.1）。

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
| 9 | 生成文書lane | 設計入力、投影、ゲート結果、Evidenceから再現可能な製品・品質・レビュー文書を生成する | 9.1〜9.2実装済み（9.3〜9.5は計画） |
| 10 | シミュレーション解析lane | 電気・機械・FWのprovisional解析を追加し、決定論的ゲートを置き換えずに結果を文書へ統合する | 計画 |
| 11 | 機構設計拡張 | 可動機構、干渉、機構向けDFM、部品込み3D統合を機械laneへ追加する | 計画 |
| 12 | 設計ナレッジQA | 設計知識源への出所引用付きQAと公開用FAQ生成を、unknown停止と会話ログ公開除外の規則付きで提供する | 12.1〜12.5達成 |
| 13 | 既存製造品の救済（ワークアラウンドlane） | 既存製造品に対する追加工・FW修正の救済差分を記録し、派生graphへ既存ゲートと実施可能性を再適用する | 計画 |
| 14 | VibeBB単体成立（会話駆動の設計反復） | 汎用エージェントの代行なしで会話から設計反復を回し、候補生成・検証・失敗回復を行う | 計画 |
| 15 | 運用と文書の整備 | 運用・文書側の改善を整備し、ツール意味論、発注判定、取得・リリース手順、ログ要約を記録する | 15.6〜15.9達成（15.1〜15.5は計画） |
| 16 | 設計能力の拡張 | 多層基板、階層graph、バッテリ、EMC/ESD、DFT、構造安全性の設計契約とゲートを拡張する | 計画 |
| 17 | 部品・サプライチェーン統治 | 部品ライブラリ、ライフサイクル、代替、BOMコンプライアンスとコスト検討を統治する | 計画 |
| 18 | 量産・出荷準備lane | ブリングアップ、panelization、DFA、出荷検査文書と検査FWを整備する | 計画 |
| 19 | FWセキュリティと検証拡張 | secure boot、暗号化、OTA、QEMUカバレッジと実機HILを拡張する | 計画 |
| 20 | 改訂管理とレビュー運用 | ECO、graph差分、PR提示、視覚品質、トークン・コスト予算を運用する | 計画 |
| 21 | 構想ブラッシュアップと分野横断の責務割当 | ものづくりアイデアを宣言contractとして受け取り、利用者との対話で洗練して要件へ確定し、機能の配置先を宣言と決定論的検査で割り当てる | 計画 |
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

catalogの更新運用も本フェーズの成果物とする。SDK版更新時は
`docs/openhands-sdk-capabilities.json`を正本として更新し、
`scripts/verify_sdk_capabilities.py`で[`openhands-sdk-capabilities.md`](openhands-sdk-capabilities.md)
を再生成する。生成Markdownを手で編集せず、正本と生成物のdriftはfail-closedで停止する。
版更新時の手順は[`operations.md`](operations.md)の依存・版の記録節を正とする。

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
`sha256:be0d3c30817e482110195a756c088c67c0e2ad98f212612c7af23bbeef2fee49`と、
そこからderiveしたserver digest
`sha256:d055bfc34a205cc618bdd86879ac81e9efd10913161076927c5b951f5035410a`は
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
| 入力と出所 | 6.1のACD tools image digestとpinned SDK v1.43.1のagent-server構成 |
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
C-4（CPL orientation期待値のfixture非依存化）は、部品catalog宣言と設計fixture側の
placement確認宣言、graph_id由来のEvidence pathを使う実装として本マイルストーンの
範囲で達成した。設計確認の無い場合はCPL属性を補わず、既存gateでfail-closedとする。

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

9.1と9.2は`acd-product-docs` Skillとして実装済みで、9.3〜9.5は計画である。

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
| 10.6 | ワーストケース解析（WCA） | 10.1の公称値解析に加え、偏り成分（公差中心のずれ、温度・経時による系統的変化）は決定論的に累積し、独立なばらつき成分はRSSで合成する解析を追加する。使用した公差表・環境条件・変動源の分類と合成方法をEvidenceへ記録し、公差表または環境条件が宣言されていない場合はunknownとして停止側へ集約する。16.2の電力バジェットは平均ではなくピーク需要で評価する |

10.1〜10.6は計画である。

## マイルストーン11: 機構設計拡張

筐体（静的な箱）から機構（可動・組立）へ機械laneを拡張する。設計述語を追加する範囲は
マイルストーン14.2の契約registryを前提とする。

| 順 | フェーズ | 内容 |
|---|---|---|
| 11.1 | 機構要素ライブラリ | スナップフィット、ヒンジ、ボタン・ライトパイプ、ボス・リブをbuild123dのパラメトリック部品として追加し、寸法根拠をrationale必須にする |
| 11.2 | 可動干渉チェック | 可動範囲のスイープ干渉を決定論的ゲートとして追加する（開閉・押下ストローク） |
| 11.3 | 製造性チェック拡張 | 3Dプリント／射出成形向けのDFM（最小肉厚、抜き勾配、オーバーハング）を機械laneゲートへ追加する |
| 11.4 | 部品込み3D統合 | KiCad 3Dモデルの選択的同梱と連携し、基板＋部品＋筐体の統合干渉チェックと組立図投影を生成する。選択的同梱にはimageサイズ増加、publish時間の増加、digestの再lock、ADR-0028のprovenance更新が伴う |
| 11.5 | 筐体の干渉解決探索（C-1） | 達成。宣言された筐体寸法のbounded候補を決定論的に列挙し、候補ごとに筐体pipelineの機械gateを評価してL2 reportへ記録する。探索結果はgraphへ自動確定せず、L1 gateとEvidenceの権限を変更しない |

11.1〜11.4は計画であり、11.5は達成済みである。

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

12.1〜12.5は`acd-design-knowledge` Skillと`/acd:ask` commandとして実装済みである。
運用手順は[`operations.md`](operations.md)の設計知識laneを参照する。

## マイルストーン13: 既存製造品の救済（ワークアラウンドlane）

すでに製造・組立を終えた個体（在庫品・出荷済み品）に生じた不具合を、基板を作り直さずに
救済する経路を追加する。ここでいうワークアラウンドとは、新revisionの製造データを
発注し直す代わりに、**追加工**（ジャンパ線の追加、部品の後付け・除去・定数変更、
パターンカット、手はんだ、筐体の追加切削・穴あけ）と**FW修正**（ピン割当変更、
タイミング・閾値の変更、機能の縮退・無効化）だけで、対象個体を許容可能な動作へ
戻す暫定的な回復手段を指す。設計としての本修正ではなく、個体群に対する
意図的な逸脱の適用であり、[`design-requirement-variation.md`](design-requirement-variation.md)の
要件変更（新規設計・新revision）とは別の経路として扱う。

設計原則は次のとおりとし、既存の閾値、ゲート挙動、fail-closed境界、L1権限を緩めない。

- ワークアラウンドは設計入力の正を書き換えない。graphへの本修正はECO（マイルストーン20.1）
  として別に起票し、ワークアラウンドrecordは適用対象個体に対する逸脱の記録に限る。
- 救済状態は`revision + workaround ID`で識別する（例: `rev1.0+WA-001`）。
  対象個体はロット・シリアル単位で明示し、未適用個体を適用済みと同一視しない。
- 救済可否はSKILLの所見ではなく決定論的ゲートが決める。追加工差分から派生graphを導出し、
  ERC、設計述語ゲート（USB CC、strapping pin、I2C pull-up、デカップリング、電源境界、
  ピン・FW整合）、DRCの影響範囲、機械干渉を再実行する。導出不能・ゲート未実行・unknownは
  「救済不可」として停止し、「問題なし」とは解釈しない。
- FW修正だけで救済する場合も、派生graphに対してピン・FW整合ゲートを再実行する。
- 電源経路、保護素子、安全境界に関わる追加工は承認必須とし、機能の縮退・無効化を伴う救済は
  「制約付き救済」として明記する。制約付き救済は合格を意味しない。
- 追加工の実施可能性（工具アクセス、部品の向き、手はんだ可否、筐体分解の可否）を
  DFA観点として判定に含め、物理的に不可能な追加工を候補にしない。
- 作業後の実測はマイルストーン5の実機Evidence契約に従う個体単位のrecordとし、
  L1のauthoritative合格へ昇格しない。
- 不具合recordのcloseは是正の実施だけで完了としない。同一原因が影響し得る箇所の水平展開の列挙と、再現条件でのゲート再実行または実測Evidenceによる有効性確認をclose条件とする。説明だけでcloseしない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 13.1 | 不具合record契約 | 症状、再現条件、発生率、影響機能、影響個体範囲（ロット・シリアル）、根本原因候補を宣言contractとして定義する。原因が導出できない場合はunknownとして記録し、救済候補の立案へ進めない。併せて水平展開の列挙（同一部品・同一トポロジ・同一ルール適用箇所・同一fixture・同一プロファイルをgraph上で機械的に検索した結果と、対象外にした箇所の理由）を必須項目とし、列挙結果が空の場合は「探索して該当なし」と「未探索」を区別して記録する。未探索はunknownとして停止側へ集約し、救済候補の立案へ進めない |
| 13.2 | 追加工差分contract | 追加工を`cut`（パターンカット）、`add`（部品・配線の追加）、`remove`（部品の除去）、`replace`（定数・型番の変更）、`mechanical`（筐体の追加加工）の型付き差分として宣言し、元graphへ適用した派生graphを決定論的に導出する。差分は投影として扱い、設計入力へ逆流させない |
| 13.3 | 救済可能性ゲート | 派生graphへ既存の電気・機械・FWゲートを再実行し、追加工の実施可能性（DFA）と安全境界の承認要否を合わせて判定する。判定結果は`救済可`／`制約付き救済`／`救済不可`の三値とし、根拠ゲート結果を伴わない判定を出さない |
| 13.4 | ワークアラウンドSKILL | 不具合recordから救済候補（FW修正のみ／追加工のみ／併用）を立案し、13.2の差分contractへ落として13.3の再検証を呼び出すSKILL（例: `/acd:workaround`）を追加する。SKILL自体はL2の操舵であり合否権限を持たず、候補と根拠、代替案、不可理由をprovenance付きで返す |
| 13.5 | 作業指示書・検査手順生成 | 対象個体、必要部品・工具、作業手順、該当箇所を強調した視覚投影、作業後の検査項目と期待値を生成する。検査項目は出荷検査文書生成SKILLと同じ知識源（graph・ゲート閾値・FW投影）から導出し、出所のない基準を作らない。生成文書はマイルストーン9のprovenance規則に従い`out/docs/`へ格納する |
| 13.6 | 個体トレーサビリティとWA廃止条件 | どの個体にどのワークアラウンドを適用したかを追跡可能な記録として残し、次revisionで当該不具合が構造的に解消されたことをゲート結果で確認できた時点をWA廃止条件として定義する。ECOワークフロー（マイルストーン20.1）と対応付ける |

13.1〜13.6は計画である。

## マイルストーン14: VibeBB単体成立（会話駆動の設計反復）

汎用エージェントの代行なしで、会話から設計反復を開始し、候補生成・検証・失敗からの
回復までを回せる状態を目指す。L1権限は決定論的ゲートのままとし、不変条件、
fail-closed境界、L1権限の範囲は変更しない。各項目の観測根拠と詳細は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)を正とする。
マイルストーン14〜20は番号順の優先順位ではなくテーマ別の整理であり、優先順位は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)の優先順位節と各節の依存関係に従う。

| 順 | フェーズ | 内容 |
|---|---|---|
| 14.1 | Skill package refのskew解消（H-1〜H-5） | refの陳腐化をCIと`/acd:doctor`で検出し、pinned `acd`をlocked imageへ事前導入して実行時のgit・ネットワーク依存を除く。CIでSkill scriptをfixtureに対し実行し、pinned `acd`でgraphが読めることを検査する。達成 |
| 14.2 | 設計述語の適用条件宣言と機能ブロック契約registry（J-1〜J-3） | 宣言された機能ブロックに対応する述語だけを必須にし、新トポロジの追加を述語コード改変ではなく契約追加で行えるようにする。fab profileを複数持てるようにする。fail-closed境界は維持し、「検証不能」と「機能を持たない」を区別する |
| 14.3 | 失敗理由の構造化とゲートの前倒し評価（B-3、B-4、K-3） | 未配線netとpad対などの失敗理由を機械可読Evidenceとして返し、配置のみで判定できる述語をrouter実行前に評価する。利用者向けに変更可能な次元と現在の余裕を含む形で提示する。達成 |
| 14.4 | 物理設計の自律探索loop（B-1、B-2、B-5〜B-9） | B-1・B-2・B-5〜B-9を達成。配置・回転とGPIO割当のbounded探索loop、placement coupling、単一mechanical datum、stitch via候補fallback、設計自由度の宣言、`stitch_candidate_report`の常時保存を追加した |
| 14.5 | 要件→graphの変換と任意設計fixture（A-1〜A-5、I-2） | 会話由来の要件レコード化、任意設計向けfixtureビルダー、要件差分からgraph差分（接続・FWピン・テストポイント・シルク・rationale）を同時更新するcompiler、部品選定とlibrary provenance、回路トポロジ合成、agent向けtool（FW pipeline、fixture編集、発注、失敗診断）の網羅。機能ブロック契約registryへの宣言入口も追加した。達成 |
| 14.6 | gd1固定の解消と発注laneの汎用化（I-3〜I-5、E-5、C-2〜C-3、D-1〜D-3） | workspace既定値、生成物名・`part_number`、`order_policy`の必須evidence anchor、FW設定をgraph_id・graph宣言由来にする。測定feedback適用、見積provider境界、実発注provider境界までを追加し、GD1以外の設計も同じlaneで扱えるようにする。達成（実supplier接続は境界の後続作業） |
| 14.7 | 実行時間と再開性（E-1〜E-4、E-6、K-1、K-2、K-4） | stage並列化、run並列、JVM・containerの資源宣言、入力hash単位のstage cache、単一orchestrator、途中失敗からの再開、stageごとの所要時間記録を達成した。検証段階の並列実行（E-6）は既存の`pytest -n auto --dist loadgroup`と`verify_all.py --jobs N`を維持し、`uv sync`とfullの後続pipelineはbarrierとして単独実行する。新しいcacheはDSN／SESの生成物だけを対象とし、ゲートとEvidenceは毎回再実行する |
| 14.8 | workspace初期化とbootstrap（G-1〜G-3） | workspace作成からclone・submodule取得・`uv sync`・plugin読み込み確認・`/acd:doctor`までを1経路にまとめ、doctorへworkspace健全性検査（repository不在、submodule初期化、`uv.lock`同期、lock digestのpull可否、FW実行に必要なhost前提）を追加し、会話開始時のbootstrap経路を用意する。達成 |
| 14.9 | image publishとdigest lock更新の自動化（F-1〜F-4） | main mergeでのtools publish起動と`workflow_run`による`acd-server` publishの連鎖、lock更新PRの自動作成、lock digestとregistry現行manifestの一致検査、`docker/README.md`の配布記述と実運用の整合。達成 |
| 14.10 | VibeBB loopのcommand（I-1） | `/acd:vibebb-loop`とgraph駆動の単一orchestratorを追加し、要件からgraph検証、silkscreen barrier、基板・筐体・FW、発注可否までを固定順序でfail-closed実行する。達成 |
| 14.11 | 会話駆動loopの残存不足（L-1〜L-7） | orchestratorの二重化解消（cache・resume・timing・lane並列を会話経路へ接続）、却下後の候補探索の自動連結、要件→graph段のloop内取り込み、order-total生成経路の追加、gd1既定値の残存解消、契約registry・catalogの被覆整理を扱う。L-1〜L-6のdata/template・catalog追加経路・USB-C非搭載／電池給電fixture到達部分は実装済みだが、電池の充電・保護回路の規範的契約とpredicateは未実装で16.2・16.3に依存するため、L-6を全面完了とは扱わない。C-1（筐体の干渉解決探索）はマイルストーン11.5で達成済み、C-4（CPL orientation期待値のfixture非依存化）はマイルストーン7の範囲で達成済みである。計画 |

C-1（筐体の干渉解決探索）とD-1〜D-3（測定結果の入力反映、見積自動取得、実発注）は既存
マイルストーン11・5・7の範囲で扱う。
マイルストーン14.10後の会話駆動loopの残存不足は、L-1〜L-7として14.11で扱う。

### 14.1 Skill package refのskew解消（H-1〜H-5）（達成）

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `acd-package-ref.txt`、pinned commitのschema/API、`fixtures/**/graph.json`、全acd-importing Skill scriptとGD1 probeのPEP 723 metadata |
| 実装 | canonical package contract、git/API/schema/kind checker、ref updater、offline doctor判定、pinned-acd graph probe、CI auto-PR、image prebakeを追加した |
| 正常系 | current refでcontractが一致し、GD1 graphをpinned `acd`で検証してFW `extract_firmware_lane`が実行できる。image buildでもonline warm後のoffline probeが成功する |
| negative・fail-closed | 非ancestor・未解決・shallow ref、schema/API/kind不一致、contract drift、script hash/symbol drift、contract欠落・parse不能を不合格にする |
| 再現性 | ref、schema tree SHA、AST-derived API/kind、script SHA-256を契約へ固定し、standard CI、doctor、digest固定imageのoffline実行で同一判定を再現する |

### 14.2 設計述語の適用条件宣言と機能ブロック契約registry（J-1〜J-3）（達成）

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `contracts/functional-block-registry.json`、`profiles/fab-profile-registry.json`、graphの`design.functional_block`宣言、fab profile本体 |
| 実装 | 機能ブロックregistryと述語catalogの被覆検査、宣言からの適用述語解決、`unknown`／`not_applicable`分離、profile registryとID選択を追加した |
| 正常系 | GD1の6述語が適用されて合格し、機能ブロックを減らしたgraphでは該当述語だけが`not_applicable`になる。Evidenceとvisual projectionは適用範囲を追跡できる |
| negative・fail-closed | 宣言ゼロ、未知・重複・mandatory欠落、registry被覆不足、適用ブロックのnet欠落、Evidenceの不正status、profile ID・metadata・path不一致を停止する |
| 再現性 | registry IDと正規化hash、ソート済み宣言一覧、profile registryの正規化hashを記録し、固定catalog順で同一判定を再現する |

### 14.3 失敗理由の構造化とゲートの前倒し評価（B-3、B-4、K-3）（達成）

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 設計graph・配置由来の述語結果、routerのSES、機能ブロックregistry |
| 実装 | 述語measurement／subject、net単位のrouting connectivity観測、決定論的Evidence writer、評価段階catalog、registry由来remediationを追加した |
| 正常系 | pass／fail／unknown／not_applicableを同じEvidenceへ保存し、収束時もrouting connectivityを保存する。述語は6件すべて`pre_router`として分類される |
| negative・fail-closed | SES欠落・parse失敗は`unavailable`へ記録して従来gateへ委ねる。Evidence失敗で合格を不合格へ変えず、既存のGateError、閾値、停止位置を変更しない。未知の変更次元とcatalog被覆漏れは停止側へ倒す |
| 再現性 | Evidenceはソート済みキー、固定座標丸め、canonical JSON SHA-256を使い、同一入力から同一バイト列を生成する |

14.1〜14.3、14.4、14.5、14.6、14.7、14.8および14.9は達成済みである。14.4では、
配置・回転、GPIO割当、placement coupling、単一datum、stitch via fallbackを含むbounded
探索loopへ接続した。14.5では、要件から任意fixture、部品選定、トポロジ合成、決定論的
tool入口、機能ブロック契約registry宣言入口までを接続した。14.6では、GD1依存の命名、
FW設定、feedback適用、quote/order provider境界をgraph・policy駆動へ一般化した。14.7では、
単一orchestrator、入力hashに基づくDSN／SES生成物cache、cacheだけを利用するresume、
各laneのL3 timing recordを追加した。14.8では、`/acd:init`と`acd_bootstrap_workspace`を
単一のfail-closed初期化経路として追加し、workspace健全性doctorとL3 bootstrap recordを
提供した。cache hitでもL1ゲートとEvidenceは再実行され、resumeは判定を保存・復元しない。
生成物、compiler、Skill結果はpass authorityを持たず、14.9ではpublish workflowの連鎖、
digest lock更新PR、registry manifest照合、配布文書の整合を追加した。L1決定論的ゲートとrevision一致した
authoritative Evidenceが唯一の合否根拠である。実測値と運用上の注意事項は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)と[`operations.md`](operations.md)を正とする。

## マイルストーン15: 運用と文書の整備

運用・文書側の改善項目を出所とする整備を行う。いずれも契約の緩和ではなく、
現行の閾値、ゲート挙動、fail-closed境界を維持する。他フェーズに依存しない運用整備である。

| 順 | フェーズ | 内容 |
|---|---|---|
| 15.1 | ToolEnvelopeの`exit_code`のツール別意味論の文書化 | kicad-cli ERC/DRCは違反件数由来で非ゼロになりうることを記録し、statusと混同しない説明を追加する |
| 15.2 | order-readiness `ready`の定義へのCPL実装基準の明示 | position/rotation basisについてfab側目視確認を前提とすることをreadyの定義へ明記する |
| 15.3 | OpenHands Local GUI APIのトークン発行手順のdocs化 | トンネル越しcurlがUnauthorizedとなる制約を踏まえ、自動化検証に必要なGUI経由のトークン取得手順を記録する |
| 15.4 | リリース手順のdocs化 | タグ作成権限・ruleset、GH013時の対応、実行例リンク中心のリリースノート、Release assetsを添付しない方針を運用手順へ記録する |
| 15.5 | pipelineログの要約出力（入力トークン削減） | pipelineログのtail既定化など、再取り込み量を削減してトークン消費を下げる要約出力を実装する |
| 15.6 | hook遮断理由の要約自動集計 | `RejectionSummary`契約でhookの遮断理由を集計し、遮断の再発箇所を利用者が追える形で提示する。要約はL3観測であり、遮断そのものの判定を置き換えない |
| 15.7 | SKILL triggerとToolDefinition登録条件のdoctor診断 | `ToolRegistrationManifest`契約と`scripts/verify_acd_tool_registration.py`で登録面を固定し、trigger不一致・未登録tool・登録条件不成立を`/acd:doctor`から診断する |
| 15.8 | host EDA不在時の推奨経路への誘導 | host EDA（kicad-cli等）が無い環境では、digest固定locked imageと`DockerWorkspace`経路をdoctorから提示する。host経路をprovisional専用とする境界は変更しない |
| 15.9 | FW実行のhost前提とlocked image同梱のdocs化 | ESP-IDF、Espressif QEMU、`libslirp0`、SDL2系共有ライブラリ、PATH解決の前提を運用手順へ記録し、locked tools imageへの同梱状況を明記する |

15.1〜15.5は計画であり、15.6〜15.9は達成済みである。15.6〜15.9は
[`improvement-notes.md`](../examples/sensor-node-20260820/report/improvement-notes.md)と
[`review-notes.md`](../examples/sensor-node-20260820/report/review-notes.md)の運用改善項目を
出所とし、いずれも既存の閾値、ゲート挙動、fail-closed境界を変更していない。

## マイルストーン16: 設計能力の拡張

設計拡張候補Aを、設計契約と決定論的ゲートの拡張として扱う。設計述語とgraph拡張は
マイルストーン14.2の契約registryを前提とする。

16.5で残留する単一故障点は、除去せずに受容する場合もクリティカル項目として根拠付きで列挙し、検査対象外にした箇所はその理由を記録する。列挙のない状態を「単一故障点なし」と解釈しない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 16.1 | 4層基板・階層graph対応 | 現行の2層・フラット構造前提を拡張し、stackup宣言、差動ペア・インピーダンス管理配線の契約とゲートを追加する |
| 16.2 | バッテリ駆動製品対応 | 充電IC・残量計・保護回路の設計述語と、電力バジェット（消費電流と容量の収支）を宣言由来の入力から決定論的に検査するゲートを追加する |
| 16.3 | EMC/ESD設計述語 | 外部コネクタへの保護素子の有無、電源ループ面積、リターンパス連続性のチェックを設計述語として追加する（認証適合の判定はしない） |
| 16.4 | テスト容易化設計（DFT） | テストポイントのネットカバレッジをゲート化し、プローブアクセス（最小間隔・径）を検査する |
| 16.5 | 構造安全性述語 | 冗長経路が同一コネクタ・同一ハーネス・同一電源バス・同一IC・同一via・同一熱経路・同一保護素子を共有していないかの単一故障点／共通原因検査、電源ツリー全体での保護の選択性（下流が上流より先に切れるか、短絡の封じ込め範囲、保護素子と被保護機能が同一ICへ集約されていないか）、ネットの信号クラス宣言と非互換な同一コネクタ・隣接配置の検出、クリティカル回路に限定したスニーク解析（意図しない導通経路・タイミング・表示・表記）、導体の台形断面を考慮した許容電流評価を設計述語として追加する。適用条件と有効域は14.2の契約registryで宣言し、宣言のない範囲はunknownとして停止側へ集約する（認証適合の判定はしない） |

16.1〜16.5は計画である。

## マイルストーン17: 部品・サプライチェーン統治

部品・BOM関連の拡張候補Bと統治項目を扱う。部品属性を設計契約へ接続する範囲は
マイルストーン14.2の契約registryを前提とする。

| 順 | フェーズ | 内容 |
|---|---|---|
| 17.1 | 部品ライブラリ統治SKILL | footprintのpad寸法・courtyard・原点をライブラリ契約として検査する。`examples/sensor-node-20260820/`のreportで観測されたDRC警告30件（`lib_footprint_issues`）の類型に対応する |
| 17.2 | EOL・セカンドソース管理契約 | 部品のライフサイクル状態と代替候補を宣言contractとして記録し、未宣言はunknownとして停止側へ集約する（外部APIの自動照会は別途判断） |
| 17.3 | BOMコンプライアンス事前チェック | BOM部品属性からRoHS等の申告状況を集計し、不明部品をunknownとして列挙する（適合判定はしない） |
| 17.4 | BOMコスト・代替部品検討 | JLCPCB basic/extended区分や代替候補の整理を、保存済み見積入力（7.1契約）の範囲で支援する |

17.1〜17.4は計画である。

## マイルストーン18: 量産・出荷準備lane

量産準備、組立性、出荷検査の経路を整備する。graphから検査項目を導出する範囲は
マイルストーン14.2の契約registryを前提とし、18.1はマイルストーン5の実機フィードバックへ接続する。

| 順 | フェーズ | 内容 |
|---|---|---|
| 18.1 | ブリングアップ試験計画の生成 | 実機フィードバック（マイルストーン5）の入力となる測定点・期待値・手順のチェックリストをgraphから生成する |
| 18.2 | 面付け（panelization）対応 | 小基板の面付けガーバ生成とDFM再検査を追加する |
| 18.3 | 製造しやすさ（DFA）レビューSKILL | 組立性・作業性・生産性の観点（部品の向きの統一、片面実装可否、手はんだ部品のアクセス性、コネクタ・ケーブルの組付け順序、筐体組立の工数、治具の要否）をレビュー観点として構造化し、graph・配置・筐体形状からL2所見として報告する |
| 18.4 | 出荷検査文書生成SKILL | 出荷検査の検査項目・実施方法・合否判定基準（外観、導通・電源電圧、書き込み・起動確認、LED・センサ動作、期待シリアル出力）を生成する。判定基準の値はgraph・ゲート閾値・FW投影由来に限定し、出所のない基準を作らない。導出できない項目はunknownとして人手決定欄を残す。生成文書はマイルストーン9のprovenance規則に従い`out/docs/`へ格納する |
| 18.5 | 出荷検査モード付きFW開発機能 | 出荷検査文書と対になる検査モード（自己診断・検査シーケンス）をFWへ組み込む開発機能を追加する。検査モードはUART等の明示操作でのみ起動し、検査項目（LED点灯、I2Cセンサ応答、電源電圧の自己確認等）と結果出力形式を出荷検査文書生成SKILLと同じ知識源（graph・FW投影）から導出する。検査結果の出力はprovisional観測であり、実測Evidenceへの昇格はマイルストーン5の実機フィードバック契約に従う |

18.1〜18.5は計画である。

## マイルストーン19: FWセキュリティと検証拡張

FWセキュリティと検証の拡張候補Cを扱う。FW契約と検証項目の追加は
マイルストーン14.2の契約registryを前提とし、19.2はマイルストーン5の実機HIL測定Evidenceへ接続する。

| 順 | フェーズ | 内容 |
|---|---|---|
| 19.1 | secure boot・flash暗号化・OTA設計対応 | パーティション構成・鍵管理境界・OTAスロットを宣言として扱い、ビルド設定との整合をゲート化する。鍵素材は扱わない |
| 19.2 | QEMUコードカバレッジと実機HIL接続 | QEMU実行でのカバレッジ計測を追加し、実機フィードバック（マイルストーン5）のHIL測定Evidenceへ接続する |

19.1〜19.2は計画である。

## マイルストーン20: 改訂管理とレビュー運用

改訂・レビューに関する拡張候補D・Eと運用項目を扱う。20.1はマイルストーン13.6の
ECO記録と対応し、20.4はマイルストーン8.4のvision経路を前提とする。

| 順 | フェーズ | 内容 |
|---|---|---|
| 20.1 | ECOワークフローとrevisionライフサイクル | 設計変更指示（変更理由・影響範囲・再検証要件）をcontract化し、revision遷移とゲート再実行の対応関係を文書化する。マイルストーン13.6と対応付ける。ECOのclose条件には13.1の水平展開列挙の消化状況を含め、未消化の対象が残るrevisionをclose扱いにしない |
| 20.2 | graph差分投影 | revision間のgraph差分（追加・削除・属性変更）を視覚投影し、レビュー資料へ統合する |
| 20.3 | GitHub Actions統合 | 設計変更PRへゲート結果・Evidence要約を自動コメントする。コメントはL3提示であり合否権限を持たない |
| 20.4 | 視覚投影の自動品質検査 | 8.4のvision経路で投影の可読性（文字の重なり、極小表示、コントラスト）をL2所見として検出する。`examples/sensor-node-20260820/`のreportで観測されたfont-size問題の再発防止に対応する |
| 20.5 | トークン・コスト予算ガード | セッションのトークン消費・実行時間をL2で監視し、予算超過を警告する（実行の強制停止はhook側の判断とする） |

20.1〜20.5は計画である。

## マイルストーン21: 構想ブラッシュアップと分野横断の責務割当

会話で持ち込まれた「ものづくりアイデア」を設計入力へ落とせる水準まで洗練し、洗練後の
機能群を機構・機械・電気・FW・PC側ソフト・サーバ・スマホアプリのどこへ配置するかを
決める上流段階を扱う。要件レコード化とgraph差分への反映はマイルストーン14.5、
生成文書のprovenance規則はマイルストーン9、出所引用はマイルストーン12の索引contractを
前提とする。PC側ソフト・サーバ・スマホアプリ自体の開発は将来構想のままであり、
本マイルストーンは配置先の宣言と検査までを範囲とする。

アイデアのブラッシュアップは一回の生成でなく、OpenHandsの会話上で利用者と往復しながら
進める反復経路として扱う。agentは未決論点を優先度順に少数ずつ問い、利用者の回答と
選択をアイデアrecordへ追記し、残ったunknownを持ち越す。利用者が回答していない項目を
agentが推測で埋めない。

設計原則は次のとおりとし、既存の閾値、ゲート挙動、fail-closed境界、L1権限を緩めない。

- アイデアの洗練とレビューはL2操舵・L3観測であり、合否権限を持たない。SKILLの所見だけで
  アイデアを要件へ昇格させず、確定した内容だけを宣言contractへ記録する。
- 対話の各ターンでは利用者が同意した事項と未決論点を区別して記録し、同意のない提案を
  確定として扱わない。対話の途中状態は保存し、中断・再開で同じ未決論点から続けられる。
- 対話ログは内部向けの知識源にとどめ、公開文書へは含めない（マイルストーン12.4と同じ規則）。
- ブラッシュアップの指摘・代替案は、知識源（設計graph、rationale、ゲート閾値、Evidence、
  過去の設計例、部品・fab profile）を出所として提示する。出所のない断定を出さず、
  導出できない論点はunknownとして残し、人手決定欄を設ける。
- 責務割当の判断は設計入力・制約・rationaleを出所とする決定論的な検討として扱う。
  割当結果はDesign Graph等の設計入力contractへ宣言として記録し、投影を設計入力へ
  逆流させない不変条件を維持する。
- 未割当、根拠のない多重割当、配置先の能力宣言と矛盾する割当、導出不能はfail-closedで
  停止し、「問題なし」とは解釈しない。
- コスト・消費電力・体験の比較値を推定する場合は推定であることを明示し、authoritative
  Evidenceへ昇格しない。

| 順 | フェーズ | 内容 |
|---|---|---|
| 21.1 | アイデアrecord契約 | 目的、想定ユーザ、実現したい体験、想定使用環境、既知の制約（コスト、寸法、電源、通信、法規）、成功条件をアイデアrecordの宣言contractとして定義する。各項目は`confirmed`（利用者が同意済み）と`open`（未決）を区別し、未宣言項目はunknownとして記録して要件確定へ進めない |
| 21.2 | 対話型ブラッシュアップSKILL | 利用者との往復でアイデアを洗練するSKILL（例: `/acd:ideate`）を追加する。一回の応答で結論を出さず、未決論点の優先度順に質問を少数ずつ提示し、各質問には選択肢とトレードオフ、推奨案とその出所を添える。利用者の回答を`confirmed`としてrecordへ追記し、未回答は`open`のまま残す。SKILLはL2操舵であり、推測でrecordを埋めない |
| 21.3 | 対話状態の保存と進捗提示 | ターンごとの質問・回答・決定を追記履歴として保存し、中断した対話を同じ未決論点から再開できるようにする。`confirmed`件数と残り`open`件数、確定を妨げているunknownを毎ターン提示する。提示はL3観測であり進捗率を合格根拠にしない |
| 21.4 | 実現可能性の粗見積 | アイデアrecordから必要機能・主要部品・概算コスト・概算消費電力・想定寸法を粗見積として算出し、成功条件との矛盾を停止側の論点として報告する。見積は推定であり合格根拠にしない |
| 21.5 | アイデアから要件への確定 | 洗練済みアイデアrecordを、マイルストーン14.5の要件レコードへ確定変換する経路を定義する。確定時はrationale recordを必須とし、unknownを残したまま確定できないようにする |
| 21.6 | 責務割当contract | 各機能の配置先候補（機構、機械、電気、FW、PC側ソフト、サーバ、スマホアプリ）と選定基準（応答時間、消費電力、コスト、更新頻度、安全性、通信可用性、保守性）を宣言contractとして定義し、選定根拠をrationale必須属性として分類する。候補の提示と選択は21.2の対話で行い、利用者が合意した割当だけをcontractへ記録する |
| 21.7 | 責務割当ゲート | 21.6の宣言に対し、全機能が配置先を持つこと、配置先の能力宣言（GPIO、通信手段、メモリ、電源、可動要件）と矛盾しないこと、分野境界のinterface（信号、プロトコル、電源）が両側から宣言されていることを決定論的に検査する。未割当・矛盾・unknownは停止させる |
| 21.8 | 構想と割当の投影・文書統合 | アイデアrecord、粗見積、責務割当表、分野横断のブロック図を再現可能な投影として`out/docs/`へ生成し、マイルストーン9の文書laneとマイルストーン8の視覚投影provenance規則へ統合する。投影は提示であり合否権限を持たない |

21.1〜21.8は計画である。採用する場合は、アイデアrecordと責務割当のcontract境界、
対話履歴の保存境界と公開除外規則、各分野のinterface宣言の範囲、責務割当のEvidence境界を
新規ADRで定義し、未定義の項目はunknownとしてfail-closedにする。

## 契約とマイルストーンの対応

契約はPydanticモデルを正本とし（フェーズ横断の検証要件6）、`src/acd/schema/`の
各モジュールは次のマイルストーンで定義した。`__init__.py`は再exportだけを行う。
表に対応先を持たない契約モジュールを追加しない。

| モジュール | 役割 | マイルストーン |
|---|---|---|
| `common.py` | 契約共通の値型 | 1 |
| `design_graph.py` | Design Graph正本 | 1 |
| `rationale.py` | 設計根拠record（`ADR-0021`） | 1・14.5 |
| `evidence.py` | Evidence record と`measured`／`virtual`分類 | 1・5.1・6 |
| `tool_envelope.py` | 外部ツール実行envelope（`exit_code`意味論は15.1） | 1・2・15.1 |
| `fab_profile.py` | 宣言的fab profileとprofile registry | 2・14.2 |
| `functional_block.py` | 機能ブロック述語の適用条件（`ADR-0043`） | 14.2 |
| `visual_projection.py` | 視覚投影の再現可能な観測 | 8.1・8.2・8.3 |
| `visual_crosscheck.py` | 機械可読投影との電気視覚照合（L3観測） | 8.5・20.4 |
| `quote.py` | 期限付き見積入力 | 7.1 |
| `order_scope.py` | 宣言された発注範囲 | 7.1 |
| `order_total.py` | 決定論的な総発注額 | 7.2 |
| `order_policy.py` | 発注policyと発注前最終ゲート結果 | 7.3・14.6 |
| `side_effect_journal.py` | append-onlyのside-effect journal | 7.4 |
| `order_execution.py` | 自働発注のdry-run出力 | 7.5 |
| `receipt.py` | 製造・組立受領の取り込み | 5.2 |
| `functional_run.py` | FW書き込みと機能測定 | 5.3 |
| `feedback.py` | 測定結果からのproposal（入力へ逆流させない） | 5.4 |
| `agent_settings.py` | secret-freeなsettings・profile・credential | 4.4 |
| `context.py` | context memoryとevent viewの非authoritative観測 | 4.4 |
| `prompt_manifest.py` | 役割promptの決定論的manifest | 4.4 |
| `model_routing.py` | 役割別modelルーティングpolicy | 4.4 |
| `observation.py` | 非authoritativeな観測payload | 4.4 |
| `observation_log.py` | secret-freeな構造化観測ログ | 4.4 |
| `knowledge_index.py` | 設計知識indexの契約 | 12.1 |
| `knowledge_answer.py` | 出典付きQA回答（`pass_evidence=false`） | 12.2 |
| `troubleshooting.py` | 症状から確認手順への機械可読知識 | 12.3 |
| `rejection_summary.py` | hook遮断理由の要約（L3観測） | 4.1・15.6 |
| `tool_registration.py` | SDK ToolDefinition登録面の契約 | 4・15.7 |

## ADRとマイルストーンの対応

Accepted ADRの索引は[`README.md`](README.md)を正とし、Superseded ADRは統合先を示す
pointerだけを残す。本書はSuperseded ADRを現行決定として引用しない
（`ADR-0025`は`ADR-0026`により対象外化された履歴として現在地でのみ参照する）。

| ADR | 決定 | マイルストーン |
|---|---|---|
| [`ADR-0005`](adr/ADR-0005-jlcpcb-pcba-preparation-contract.md) | JLCPCB PCBA発注準備の契約と宣言データ | 7.1・7.3・15.2 |
| [`ADR-0006`](adr/ADR-0006-vendor-submodule-policy.md) | SDK vendor submoduleの更新方針 | 4・14.8 |
| [`ADR-0007`](adr/ADR-0007-llm-guided-physical-design.md) | 配置・回転・配線探索へのLLM適用境界 | 4.3・14.4 |
| [`ADR-0008`](adr/ADR-0008-minimal-vibebb-scope.md) | VibeBBの最小構成とSDK優先の実装境界 | 1・4・14 |
| [`ADR-0021`](adr/ADR-0021-design-rationale-records.md) | 設計根拠recordの保持 | 1・14.5・21.5 |
| [`ADR-0023`](adr/ADR-0023-deterministic-gate-authority.md) | 判定・操舵・観測の三層分離 | 全マイルストーン（フェーズ横断の検証要件） |
| [`ADR-0026`](adr/ADR-0026-openhands-delegation-contract.md) | OpenHands委譲契約 | 4・4.1〜4.4・6・agent-server採用判断 |
| [`ADR-0027`](adr/ADR-0027-single-distribution.md) | 単一配布パッケージ | 4・14.9 |
| [`ADR-0028`](adr/ADR-0028-execution-provenance.md) | 実行provenanceとauthoritative Evidence | 6・7.3・検証要件 |
| [`ADR-0033`](adr/ADR-0033-sdk-capability-adoption.md) | SDK能力の採否とbrowser_useの境界 | 4.4・4.5 |
| [`ADR-0034`](adr/ADR-0034-document-governance.md) | 文書統治とSDK能力カタログ | 4.5・9 |
| [`ADR-0035`](adr/ADR-0035-standard-distribution.md) | SDK標準機構による配布とインストール | 4・14.9 |
| [`ADR-0036`](adr/ADR-0036-ambient-plugin-install.md) | installed plugin自動読み込みによるインストール | 4・14.8 |
| [`ADR-0037`](adr/ADR-0037-pep723-skill-scripts.md) | PEP 723によるSkill scriptの依存自己解決 | 14.1 |
| [`ADR-0038`](adr/ADR-0038-acd-install-doctor.md) | ACDインストール自己診断入口 | 14.1・14.8・15.7・15.8 |
| [`ADR-0039`](adr/ADR-0039-subagent-skill-reference.md) | sub-agentのSkill参照方式 | 4・4.3 |
| [`ADR-0040`](adr/ADR-0040-hook-plugin-root-resolution.md) | plugin hookのplugin root解決方式 | 4.1 |
| [`ADR-0041`](adr/ADR-0041-vision-proposals-as-design-candidates.md) | ビジョン出力を宣言層入力として受け入れる境界 | 8.4・8.6・20.4 |
| [`ADR-0042`](adr/ADR-0042-skill-package-ref-skew.md) | Skill package refのskew検出と事前導入 | 14.1 |
| [`ADR-0043`](adr/ADR-0043-functional-block-contract-registry.md) | 機能ブロック契約registryによる設計述語の適用条件 | 14.2・16 |

## Skill・command・scriptとマイルストーンの対応

plugin資材とscriptの成果物対応を示す。SkillとcommandはL2操舵・L3観測であり、
表の対応はマイルストーンの成果物としての帰属を示すものであって合否権限を与えない。

| Skill | マイルストーン |
|---|---|
| `acd-contracts` | 1・4 |
| `acd-design-rationale` | 1 |
| `acd-silkscreen-placement` | 2 |
| `acd-cad-determinism-probe` | 3 |
| `acd-placement-search` | 4.3・14.4 |
| `acd-firmware-esp32c3` | 5.3・8.5・15.9 |
| `acd-install-doctor` | 14.1・14.8・15.7・15.8 |
| `acd-product-docs` | 9.1・9.2 |
| `acd-design-knowledge` | 12.1〜12.5 |
| `acd-qc-seven-tools` | 9.3・9.4のL2前段（所見の整理） |
| `acd-reliability-review` | 7.3・9.4のL2前段（余裕のレビュー） |
| `acd-package-contract.json`／`acd-package-ref.txt` | 14.1 |

| command | マイルストーン |
|---|---|
| `/acd:gates` | 4・4.1 |
| `/acd:ask` | 12.2 |
| `/acd:doctor` | 14.1・14.8・15.7・15.8 |

| script | マイルストーン |
|---|---|
| `verify_all.py` | 検証要件（段階の正）・14.7（E-6） |
| `verify_docs.py` | 検証要件・4.1 |
| `verify_sdk_capabilities.py` | 4.5 |
| `verify_agent_prompts.py` | 4.4 |
| `verify_model_policy.py` | 4.4 |
| `verify_agent_settings.py` | 4.4 |
| `verify_context_view.py` | 4.4 |
| `verify_acd_tool_registration.py` | 4・15.7 |
| `verify_authoritative_evidence.py` | 6 |
| `verify_skill_metadata.py` | 14.1 |
| `verify_skill_package_ref.py` | 14.1 |
| `update_skill_package_ref.py` | 14.1 |
| `probe_pinned_acd_graph.py` | 14.1 |
| `probe_tools.py` | 4.1 |
| `print_locked_image.py` | 6 |
| `run_in_workspace.py` | 6 |
| `resolve_gd1_silkscreen.py` | 2 |
| `silkscreen_search.py` | 2 |
| `run_gd1_pipeline.py` | 2 |
| `run_design_lanes.py` | 2・3 |
| `run_gd1_enclosure_pipeline.py` | 3 |
| `build_gd1_fixture.py` | 14.5 |
| `check_rationale.py` | 1 |
| `fetch_lcsc_footprint_orientation.py` | 7.1・17.1 |
| `ingest_receipt.py` | 5.2 |
| `ingest_functional_run.py` | 5.3 |
| `propose_input_feedback.py` | 5.4 |
| `pre_order_gate.py` | 7.3 |
| `order_execution.py` | 7.5 |
| `side_effect_journal.py` | 7.4 |

## バックログからマイルストーンへの移行

旧3バックログ節の全項目を、次のマイルストーンへ移した。実行例・レビュー由来の
改善バックログは[`improvement-notes.md`](../examples/sensor-node-20260820/report/improvement-notes.md)
と[`review-notes.md`](../examples/sensor-node-20260820/report/review-notes.md)を出所として保持し、
追加SKILL候補8項目と拡張候補A〜Eの13項目を含め、移行漏れがないことを照合している。

| 旧バックログ項目 | 反映先 |
|---|---|
| ブリングアップ試験計画の生成 | 18.1 |
| BOMコンプライアンス事前チェック | 17.3 |
| BOMコスト・代替部品検討 | 17.4 |
| 面付け（panelization）対応 | 18.2 |
| graph差分投影 | 20.2 |
| 製造しやすさ（DFA）レビューSKILL | 18.3 |
| 出荷検査文書生成SKILL | 18.4 |
| 出荷検査モード付きFW開発機能 | 18.5 |
| A. 4層基板・階層graph対応 | 16.1 |
| A. バッテリ駆動製品対応 | 16.2 |
| A. EMC/ESD設計述語 | 16.3 |
| A. テスト容易化設計（DFT） | 16.4 |
| B. 部品ライブラリ統治SKILL | 17.1 |
| B. EOL・セカンドソース管理契約 | 17.2 |
| C. secure boot・flash暗号化・OTA設計対応 | 19.1 |
| C. QEMUコードカバレッジと実機HIL接続 | 19.2 |
| D. `acd init`ウィザード | 14.8 |
| D. GitHub Actions統合 | 20.3 |
| D. 視覚投影の自動品質検査 | 20.4 |
| D. トークン・コスト予算ガード | 20.5 |
| E. ECOワークフローとrevisionライフサイクル | 20.1 |
| （改善バックログ）ToolEnvelopeの`exit_code`のツール別意味論の文書化 | 15.1 |
| （改善バックログ）order-readiness `ready`の定義へのCPL実装基準の明示 | 15.2 |
| （改善バックログ）fixture複製ヘルパと組立手順のdocs化 | 14.5 |
| （改善バックログ）FW pipelineのhost前提の`/acd:doctor`診断化 | 14.8 |
| （改善バックログ）KiCad 3Dモデルの選択的同梱 | 11.4 |
| （改善バックログ）OpenHands Local GUI APIのトークン発行手順のdocs化 | 15.3 |
| （改善バックログ）pipelineログの要約出力（入力トークン削減） | 15.5 |
| （改善バックログ）リリース手順のdocs化 | 15.4 |
| （改善バックログ）GD1と実体が異なる設計での実行例作成 | 14.1・14.2 |
| （ギャップ分析）E-6 検証段階の並列実行 | 14.7（達成） |
| （ギャップ分析）E-5 生成物名・`subject_node`のgraph_id由来化 | 14.6（出力命名は達成、`order_policy`のevidence anchorは計画） |
| （改善バックログ）host EDA不在時の推奨経路への誘導 | 15.8（達成） |
| （改善バックログ）FW実行のhost前提（QEMU・`libslirp0`等）のdocs化とlocked image同梱 | 15.9（達成） |
| （改善バックログ）FW成果物ディレクトリ名のgraph_id由来化 | 14.6（達成） |
| （レビュー）視覚投影SVGのviewBox相対font-size | 8.2（達成）、再発防止は20.4 |
| （レビュー）回路図の可読性（機能ブロック配置とネットラベル接続方式の注記） | 8.2（達成） |
| （レビュー）KiCad由来SVGのfit-to-board化 | 20.4（未採用。8.5が図枠のtitle blockを読むため現行exportを維持する） |
| （レビュー）SKILL triggerとToolDefinition登録条件のdoctor診断 | 15.7（達成） |
| （レビュー）hook遮断理由の要約自動集計 | 15.6（達成） |
| （レビュー）DFMの未実装チェック一覧の明示 | 9.3 |

## 将来構想

現行実装計画の次に残る機能は、次の構想として保持する。既にマイルストーン化した
範囲は各マイルストーンへのpointerとして示し、未着手の構想だけを残す。

- routing後のvia mask開口を含む投影・実測・再配置の反復
- 複数fab profileと製造データ契約の拡張はマイルストーン14.2へ移行済み
- 長時間運用、ローカル製造
- 高密度基板、認証設計は将来構想として残し、多層・EMC/ESD相当はマイルストーン16.1・16.3へ、熱・SIはマイルストーン10.2・10.3へ移行済み
- agent自体のコンテナ化と配布済みACD image
- 複数instanceのshared storage負荷検証
- OpenBlink（mruby/cとBLEによる無線コード差し替え）を用いたFW動作の反復探索
- FPGA（GOWIN等）への対応。FPGAロジック（HDL・ネットリスト）とビットストリーム生成を
  宣言由来の設計contractとして扱い、既存のFW laneやピン割当ゲートと同様の決定論的な
  投影・検証境界を持たせる。合否は決定論的ゲートで判定し、ツールチェーン（GOWIN EDA等）は
  subprocess呼び出しに限定する。導出できない割当・制約はunknownとしてfail-closedにする。
- 組み合わせて使用するPC側のソフト開発（WebGUI等）。完成した基板・製品と組み合わせて
  動作するPC側アプリ・WebGUIの生成
- 組み合わせて使用するサーバ側のソフト開発（バックエンド・フロントエンド）。製品と連携する
  サーバ側ソフトの開発
- 組み合わせて使用するスマホアプリ開発。製品と連携するスマホアプリの開発
- 分野横断の責務割当と、ものづくりアイデアのブラッシュアップはマイルストーン21へ移行済み

上記のPC側ソフト、サーバ側ソフト、スマホアプリは、いずれもVibeBBが設計するハードウェアと
組み合わせて動作する周辺ソフトウェアである。生成物はマイルストーン9の文書lane同様の
provenance規則に従い、authoritative Evidence境界とハードウェア設計の決定論的ゲートを
侵さない。採用する場合は認証・権限・Evidence境界の受入条件を新規ADRで定義し、
未定義の項目はunknownとしてfail-closedにする（agent-serverを対象外とする現行方針と同じ扱いである）。

### OpenBlink

OpenBlinkはmruby/cのVMをBLE経由で差し替えることで、マイコンを再起動せずに
Rubyコードを入れ替える構想である。ACDへ取り込む場合は、ドライバ、BLEスタック、
RTOSを含むC層を宣言由来のFW契約として扱い、無線で差し替えるRuby層はL2の探索・
操舵経路に限定する。差し替えたコードの実行結果はauthoritative Evidenceへ昇格させず、
合否は既存のQEMU実行・実機フィードバックとdigest固定containerの決定論的ゲートで判定する。
採用する場合は、対象ハードウェア（ESP32系を含む）、mruby/cおよびOpenBlink本体の
ライセンス境界、BLE接続・鍵素材の取り扱い境界を新規ADRで定義し、未定義の項目は
unknownとしてfail-closedにする。

## 検証要件

変更ごとに、契約・投影・独立再読込・決定論的ゲートを実行する。ツール不在、
parse失敗、未実行、unknownはfail-closedとする。検証段階の正は
`uv run python scripts/verify_all.py --stage docs`、`--stage standard`、`--stage full`
であり、Markdownのみの変更も該当する段階コマンドで検証する。

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
