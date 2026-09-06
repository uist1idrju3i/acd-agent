# 実装ロードマップ 達成記録

> ステータス: 達成済みフェーズの完了条件と実装記録

本書は[`roadmap.md`](roadmap.md)から分離した達成済みマイルストーン・フェーズの完了条件、
実装記録、不足項目の割当経緯、バックログからの移行履歴を保持する。現在地と未了の計画は
[`roadmap.md`](roadmap.md)を正とする。本書の記録は履歴であり、閾値・fail-closed境界・
L1権限の定義を変更しない。

## 達成済みマイルストーンの詳細

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

### 3.1 筐体pipelineのアンテナ干渉・ネジ穴欠落修正

**状態: 実装済み（2026-08-30）**

実機組み付け（2026-08-30、[`examples/sensor-node-20260820/`](../examples/sensor-node-20260820/)）
で、筐体シェルがESP32-C3-MINI-1のアンテナ突出部と物理干渉し、スタンドオフにネジ穴が
ないためリッドを締結できないことが判明した。決定論的干渉ゲートが0.0mm³でpassしていた
にもかかわらず実機で物理干渉が発生した事例であり、ゲートの信頼性に関わる修正である。

根因は次の2点である。

1. **アンテナ干渉**: `fixture/graph.json`に`mechanical.board_edge_overhang`ノード
   （edge="top", overhang_mm=5.4）が定義されているが、`extract_mechanical_lane()`
   （`src/acd/core/mechanical.py`）がこのノードを抽出しない。`_build_shapes()`
   （`src/acd/adapters/cad/project.py`）は単純箱型シェルを生成し、アンテナ突出部を
   考慮しない。`run_mechanical_gates()`（`src/acd/adapters/cad/mechanical.py`）の
   干渉検査はcomponent_bodyのみ対象で、overhangを3D固体としてモデル化しないため、
   干渉ゲートが0.0mm³でpassしてしまう。`enclosure/rationale.md`にはoverhang設計判断が
   記録されているのに、コードがそれを実装していない。

2. **ネジ穴欠落**: `_build_shapes()`がスタンドオフを固体円柱（`Cylinder`）として生成し、
   貫通穴を開けない。リッドも平板（`Box`）でネジ穴がない。`outline.mount_holes`の座標は
   スタンドオフ位置決めに使われるが、穴として消費されない。

締結方式は**M2セルフタッピングねじ**とし、筐体材質は発注可能な**PA12-HP nylon**へ
変更する。スタンドオフにはφ1.6 mmのパイロット穴を高さ分だけ設け、リッドにはφ2.2 mm
のクリアランス穴を`outline.mount_holes`ごとに設ける。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `mechanical.board_edge_overhang`ノードを持つgraph（GD1 fixture）、`outline.mount_holes`、`enclosure/rationale.md`のoverhang設計判断、実機組み付け記録（[`examples/sensor-node-20260820/README.md`](../examples/sensor-node-20260820/README.md)の筐体設計上の既知の問題節。凍結済み`examples/sensor-node-20260820/`は変更せず、修正版成果物は新設する別の`examples/`ディレクトリへ保存） |
| 実装 | `extract_mechanical_lane()`へ`board_edge_overhang`ノードの抽出を追加し、`_build_shapes()`へアンテナ突出領域のシェル切欠きを実装した。`run_mechanical_gates()`の干渉検査へoverhang由来の3D固体を含めた。スタンドオフへφ1.6 mmパイロット穴、リッドへφ2.2 mm M2通し穴を追加し、`MechanicalLane`へoverhang viewを追加、`EnclosureView`へfastener方式と穴径宣言を追加した。 |
| 正常系 | GD1 fixtureから生成した筐体STEPがアンテナ突出部と干渉せず、スタンドオフとリッドにネジ穴がある。干渉ゲートがoverhang固体を含めて0.0mm³でpassし、実機組み付けが可能になる。既存の筐体artifact測定（volume・bbox・normalized hash）は形状変更に伴って更新される |
| negative/fail-closed | `board_edge_overhang`ノード欠落時の単純箱型生成、overhang宣言とシェル形状の不一致、ネジ穴位置と`mount_holes`座標の不一致、干渉ゲートがoverhang固体を無視してpassする従来挙動をnegative testで検出する。overhangノード未宣言はunknownとして停止し、推定で切欠き寸法を補完しない |
| 再現性 | 同一graphから同一のシェル切欠き形状・ネジ穴位置を再生成し、干渉ゲート結果とartifact hashを固定する。`--jobs 1`と並列で正規化hashと判定が一致することを回帰テストで固定する |

本フェーズは既存の閾値、ゲート挙動、fail-closed境界を緩めず、決定論的ゲートが実機の
物理干渉を見逃した事例の修正である。`board_edge_overhang`ノードの未消費はgraph入力へ
逆流させる変更ではなく、graph入力に既に存在する宣言をpipelineコードが正しく消費する
ようにする修正である。生成物（STEP/3MF）の形状が変わるため、`examples/`配下の凍結
スナップショットは変更せず、修正版成果物は新設する別の`examples/`ディレクトリへ配置する。

なお、既存のboard plane高さの不整合（top-mounted bodyを
`wall_thickness + internal_clearance`へ置き、スタンドオフ頂部と一致しない問題）は、
形状寸法と成果物測定値を変更するため本項では修正しない。別PRでboard planeと
`shell_height`を一括して是正する。


### マイルストーン4.4: SDK機能移譲

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

#### 4.5 能力カタログ検査の強化

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


### マイルストーン5: 実機フィードバック

製造・組立・測定の結果を実機Evidenceとして取り込み、次の設計入力へ反映する。
実機Evidenceは決定論的ゲートの合否を置き換えず、入力更新の根拠として扱う。
GD1の実機Evidence 4件と分類規則は[`golden-design-1.md`](golden-design-1.md)の
9章を正とする。

#### scope（2026-08-31）

実機測定は将来機能・非対象とし、実機書き込み・機能測定を含む既存コードは残置するが、
決定論的loopの必須段には含めない。GD1の実機measured Evidence未取得は不足として扱わず、
仮想FW実行（QEMU）はvalidation laneとして維持するが、物理Evidenceへ昇格させない。

#### 5.1 実機Evidence契約と分類

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 測定機器名・版、治具、実行条件、測定者、取得時点、対象graph revisionを入力に持つ契約を実装した |
| 実装 | `acd.schema.evidence`に`measured`／`virtual`の分類、測定量・単位・期待範囲・許容差、機器情報、時刻整合性、canonical hashを追加した |
| 正常系 | `measured`分類のvalid recordが必須項目と値域を満たし、`supports_pass(revision)`の判定対象として読み込めることをfixtureとtestで確認した |
| negative/fail-closed | 分類欠落、`unknown`分類、単位欠落、revision不一致、機器版unknown、時刻逆転、値域外、測定量ゼロ件をfixtureとtestに含めた。実機Evidenceのauthoritative合格は常に拒否する |
| 再現性 | フィールド順に依存しないcanonical JSONから同一入力の同一hashを得るtestを追加した |

#### 5.2 製造・組立受領の取り込み

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `ReceiptRecord`がfab／assembler、業者名、記録者、出所URI、受領物、検査レポート参照、送付manifest参照、送付・受領・記録時刻を保持する |
| 実装 | `acd.core.receipt`と`scripts/ingest_receipt.py`で受領recordを製造データpackageのmanifestと決定論的に突合し、対応結果を型付きreportへ記録する |
| 正常系 | 送付manifestと受領recordのhash・対象revision・成果物一覧が一致し、`measured`分類のhost実機Evidenceとして残る |
| negative/fail-closed | manifest hash不一致、revision不一致、`status: "fail"`、manifest構造不備、受領物の欠落・余剰・hash不一致、検査レポート欠落、日時逆転を停止条件にする。manifestの`unknowns`自体はsortedキーをreportへ残し、受領物の突合は継続する |
| 再現性 | 受領recordの取り込みをCLIで再実行でき、同一入力から同一report・Evidenceバイト列とcanonical hashになる |

#### 5.3 FW書き込みと機能測定

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `FunctionalRunRecord`がESP-IDF版、toolchain版、project commit、`.elf`／`.bin`成果物、`app_flash_offset`、build／flash／LED／serialの生ログ、測定機器、シリアルtag、期待条件、時刻を宣言する |
| 実装 | `acd.core.firmware`と`scripts/ingest_functional_run.py`が宣言hashを実ファイルへ照合した後、build、flash、LED capture、serial logを独立parserで読み直す |
| 正常系 | 固定版の宣言値と成果物hashが一致し、ESP32-C3書き込み検証、LED 1 Hz、温湿度値域・周期を満たす4件の`measured` host実機Evidenceを個別に保存する |
| negative/fail-closed | 成果物・ログhash不一致、成果物欠落、必須ログ行の欠落・形式不正・parse不能は`unknown`、ESP-IDF版不一致、書き込みverify数不足・対象chip不一致、値域外、周波数・duty・周期外れは`fail`として停止する。flashは書き込み行と`Hash of data verified.`行の件数一致、app offset・サイズ一致、`Hard resetting`完了を検査する |
| 再現性 | recordと保存済み生ログから同一report・4件のEvidenceバイト列とcanonical hashを再生成し、各negative fixtureを含める |

#### 5.4 測定結果の入力反映ループ

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


### マイルストーン6: 実行基盤のDockerWorkspace一本化

6.1ではACD toolsのpublish済みdigestを`docker/image-digests.json`へ記録した。
6.2では、そのlock済みtools digestをbaseにするagent-serverのbuild／publish workflowを追加した。
6.3ではrunnerを事前build済みserver imageの`DockerWorkspace(server_image=...)`へ切り替え、
6.4ではCIをlock解決とpullへ移行し、6.5では旧dev workspace経路を撤去した。
derived server digestはpublish実行後にlockへ記録済みである。base tools digest
`sha256:901ffd495c4876d3c02ff9c3303c67a6ee0d2c54b39460bb370a2c8260bb602c`と、
そこからderiveしたserver digest
`sha256:b5afc5daadf801f62d7bcb3f8229fe417e0e658b7ab1a660bf737f105f18c968`は
独立した値として保持する。受入条件は
[`ADR-0026`](adr/ADR-0026-openhands-delegation-contract.md)の入口と実行形、
[`ADR-0028`](adr/ADR-0028-execution-provenance.md)の実行provenanceを正とする。
フェーズは6.1から順に依存する。

6.6は、pull入口とcontainer起動・実行のtimeout境界を決定論的に扱うフェーズであり、
6.3〜6.5の経路を前提に追加した。

agent-server packageの直接API、REST/WebSocket経路、server側のresume/forkは本
マイルストーンに含めない。conversation persistenceは`LocalConversation`の
`persistence_dir`範囲に限り、再開結果をauthoritative Evidenceへ昇格しない。

#### 6.1 ACD tools imageのpublishとdigest記録

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `docker/acd-tools.Dockerfile`、pinned SDK版、`publish-acd-images.yml`のjob summaryのGHCR digest |
| 実装 | publish済みdigestと外部ツール版を運用記録へ転記し、参照refとdigestを対応付ける |
| 正常系 | 記録したdigestをpullして`probe_tools.py`が既知の外部ツール版を報告する |
| negative/fail-closed | placeholder digest、未publish状態でのlock作成、digest未解決のpullを禁止する |
| 再現性 | 同一Dockerfileとpinned SDK版から同一の外部ツール版一覧が得られることを記録する |

#### 6.2 事前build済みagent-server imageの整備

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 6.1のACD tools image digestとpinned SDK v1.44.1のagent-server構成 |
| 実装 | server実行資材を含むimageを事前buildしてpublishし、derived digestを独立に記録する |
| 正常系 | publish済みserver imageのdigestを指定してworkspaceが起動し、command実行が成功する |
| negative/fail-closed | base imageとderived imageのdigestを同一と主張する記述、digest不明起動を拒否する |
| 再現性 | 同一入力から再buildしたimageのtool版とentrypointが一致することを記録する |

#### 6.3 runnerの`DockerWorkspace`切替

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 6.2のserver image digest、`src/acd/openhands/workspace.py`の現行runner契約 |
| 実装 | `DockerWorkspace(server_image=...)`へ切り替え、digestとcontainer markerをforwardする |
| 正常系 | resolver、GD1基板pipeline、GD1筐体pipelineがcontainer内で実行され、Evidenceが`container`＋digestを持つ |
| negative/fail-closed | digest未解決、`server_image`未指定、command失敗、file download失敗で非ゼロ終了する |
| 再現性 | 同一digestでの再実行が同一のEvidence hashを生成し、digest欠落のnegative testを含める |

#### 6.4 CI authoritative gateの移行

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `.github/workflows/ci.yml`の`container-gates` job、6.1のdigest記録 |
| 実装 | 毎回のbuildxビルドから記録済みdigestのpullへ移行し、`verify_authoritative_evidence.py`の検査を維持する |
| 正常系 | CIが両laneのEvidenceをrevision一致・`status="valid"`・既知provenance・digestで通す |
| negative/fail-closed | digest未記録時の暗黙build fallback、pull失敗時の合格を禁止する |
| 再現性 | 同一commitと同一digestでCIを再実行して同一の検査結果になる |

#### 6.5 ホスト経路のprovisional固定と移行完了判定

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | host実行のEvidence、container実行のEvidence、`ADR-0028`の`execution_context`契約 |
| 実装 | 旧SDK dev workspace経路を撤去し、host経路はprovisional専用として文書と実装で明示する |
| 正常系 | authoritative Evidenceの生成経路が`DockerWorkspace`だけになり、文書の記述と一致する |
| negative/fail-closed | host Evidenceの合格側昇格、旧dev workspace残存参照、経路unknownを拒否する |
| 再現性 | 移行後のCIとローカル実行の双方で同一のEvidence provenanceを再生成できる |

#### 6.6 container実行のtimeout境界とpull入口（達成）

pinned SDK v1.44.1の`DockerWorkspace`は`execute_command()`へtimeoutを渡さないため、
`docker version`、image不在時の暗黙pullを含む`docker run`、`docker inspect`、
`docker logs`、`cleanup()`の`docker stop`が無期限にブロックしうる。ACD側の
`resolve_image_digest()`の`docker image inspect`も同様である。lock済みdigestをpullする
決定論的入口は`.github/workflows/ci.yml`と[`operations.md`](operations.md)の手順にしかなく、
standalone実行ではpullがtimeout・retry・provenanceの管理外になる。あわせて、
`health_check_timeout`は既定120sのまま、`platform`は`linux/amd64`固定、
`detach_logs`は既定有効、remote commandのpollingは0.1s間隔である。実機検証では
locked image pull完了後に会話が無応答となった（原因はOOM未確認）。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `docker/image-digests.json`のlock entry、`src/acd/openhands/workspace.py`、pinned SDKの`DockerWorkspace`と`execute_command()`実装、[`ADR-0028`](adr/ADR-0028-execution-provenance.md)の実行provenance契約 |
| 実装 | lock entry指定でimageをpullする決定論的入口を追加し、全体timeout、有限回backoff retry、pull後のdigest一致確認、provenance記録を持たせる。ACD側のdocker CLI呼出しへ明示timeoutを与え、`workspace_factory`経由で`health_check_timeout`、`platform`、`detach_logs`、memory上限、docker CLI timeoutを明示した`DockerWorkspace`構成を渡す。`WorkspaceResult`へ失敗種別（timeout、通信失敗、command非ゼロ）を保持し、起動失敗時のcontainer後始末を明示する |
| 正常系 | image不在の状態からpull入口を実行してlock digestと一致するimageがlocalへ入り、`run_in_workspace.py`がcontainer経路でゲートを実行してauthoritative Evidenceを生成する |
| negative/fail-closed | pull失敗、retry上限到達、digest不一致、health timeout、docker CLI timeoutをいずれも非ゼロ終了かつEvidence非生成とする。retryはdigest固定pullとfile downloadに限り、gate実行とEvidence生成の再試行で合格側へ昇格しない |
| 再現性 | 同一lockと同一digestの再実行で同一Evidence hashになること、timeout値とretry上限が文書と実装で一致することを検査する |

実装は`src/acd/openhands/image_pull.py`と`scripts/pull_locked_image.py`をpull入口の正とし、
`src/acd/openhands/container_runtime.py`が`DockerWorkspace`のlifecycleが呼ぶdocker CLIへ
timeoutとmemory上限を与える。既定値は`--health-check-timeout 300`、
`--command-timeout 3600`、`--docker-cli-timeout 300`、`--memory-limit 8g`、
`--platform linux/amd64`、pull timeout 900s、pull retry 3回であり、
[`operations.md`](operations.md)の運用手順と一致させる。`WorkspaceResult`は失敗種別
（`timeout`、`transport`、`command`）を保持し、起動失敗時は観測したcontainerを停止する。
retryはdigest固定pullとfile downloadに限り、gate実行とEvidence生成は再試行しない。


### マイルストーン7: 発注前最終ゲートと自働発注

金銭と納期が発生する不可逆点は発注だけである。発注は全ゲート通過と上限額の2条件を
満たす場合に限り許可し、実行はside-effect journalへ記録する。設計要件は
[`SECURITY.md`](../SECURITY.md)の「AIエージェント特有の前提」、
発注ガードの縮約は[`ADR-0008`](adr/ADR-0008-minimal-vibebb-scope.md)、
製造データと`unknown`境界は[`ADR-0005`](adr/ADR-0005-jlcpcb-pcba-preparation-contract.md)を正とする。
C-4（CPL orientation期待値のfixture非依存化）は、部品catalog宣言と設計fixture側の
placement確認宣言、graph_id由来のEvidence pathを使う実装として本マイルストーンの
範囲で達成した。設計確認の無い場合はCPL属性を補わず、既存gateでfail-closedとする。

#### scope（2026-08-31）

自動発注は将来機能・非対象とし、dry-run／real送信経路のコードは残置するが、
決定論的loopの必須段から外す。order-total集計とpre-order gateはquote／order scope入力が
与えられた場合のみの任意段として維持し、外部への発注副作用を持たない「ユーザーが発注判断に
使う決定論的成果物」と位置付ける。

現行必須scopeは、Gerber一式・drill・gbrjob・gerbers.zip・BOM・CPL・fab-package manifest・
筐体STEP／3MF／STLの製造提出データと、それらの独立reload・hash・DFM・幾何検査である。
実発注を行わないことはこれらのファイル品質要件を下げない。

#### 7.1 期限付き見積入力の取得契約（達成）

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

#### 7.2 総発注額の合算契約（達成）

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

#### 7.3 発注前最終ゲート（達成）

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 現行git revisionの設計入力、authoritative Evidence、7.2の総額、宣言された上限額 |
| 実装 | 発注直前に全決定論的ゲートを現revisionで再実行し、上限額とゲート通過の2条件を判定する。対象graph pathを検証し、order policyのEvidence lane宣言とgraph IDから両laneのEvidence IDを導出してauthoritative Evidence一致を要求する |
| 正常系 | 全ゲートがrevision一致のauthoritative Evidenceで通り、総額が上限内のときだけ許可を返す |
| negative/fail-closed | ゲート未実行、provisional Evidence、revision不一致、dirty入力、上限超過、判定unknownで却下する |
| 再現性 | 同一revisionと同一入力で同一判定になり、各却下条件のnegative testを回帰へ含める |

#### 7.4 side-effect journal（達成）

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 7.3の許可record、送信対象の製造データpackage hash、宛先、実行時刻、操作の冪等key |
| 実装 | 不可逆操作の事前予定と事後結果をhash連鎖付きJSON Linesの追記専用journalへ記録し、許可recordと相互参照する。読み出し時に契約、連鎖、冪等性、対応関係を再検証する |
| 正常系 | 発注1件がjournalの事前・事後1組で追跡でき、receiptと成果物hashが対応する |
| negative/fail-closed | journal書込み失敗、許可record不在、冪等key重複による再送、事後記録欠落、既存行の改変・削除・並べ替え、hash・package・revision・時刻の不整合を停止条件にする |
| 再現性 | journalから発注の入力・判定・結果を再構成でき、読み出しCLIと追記専用性のnegative testを含める |

#### 7.5 自働発注の実行

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


### マイルストーン8: 視覚投影レビュー基盤

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

#### 8.1 視覚投影provenance契約

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | Design Graph revision、authoritative projectionの入力ファイルとhash、renderer種別・版、生成時刻 |
| 実装 | 視覚投影1枚と投影集合のPydantic契約を追加し、画像hash（正規化後）、renderer種別・版、解像度、正規化規則ID、入力hashを必須項目として保持する。`pass_evidence=False`のL3 observationとして`ObservationArtifactKind`へ登録する |
| 正常系 | 記録済みの投影集合をfixtureから復元し、投影識別子、renderer版、解像度、正規化規則、入力hashが読める |
| negative/fail-closed | renderer版unknown、解像度未記録、画像hash欠落・unknown、絶対パスや`..`を含む画像パス、投影識別子重複、`pass_evidence`真を拒否する |
| 再現性 | 同一の投影集合から同一のcanonical hashを再生成し、各拒否条件のnegative fixtureを回帰へ含める |

#### 8.2 renderer adapterと決定論的再生成

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | pipelineが投影したKiCad schematicとboard、`kicad-cli`版 |
| 実装 | `kicad-cli`のSVG出力で回路図ビューと層別レイアウトビューを生成する。SVG冒頭の`<title>`が出力ファイル名と生成時刻を埋め込むため、`<title>`要素だけを正規化する規則を契約へ書き、規則外の差異を停止条件とする。解像度は宣言値ではなく生成された画像バイト列から測定する。renderer版は`kicad-cli`から取得し、unknownはfail-closedにする |
| 正常系 | GD1の投影から回路図ビューと層別レイアウトビューを生成し、正規化後の画像hash、renderer版、測定した解像度を持つ投影recordを得る |
| negative/fail-closed | renderer不在、非零終了、出力欠落、renderer版unknown、`<title>`が想定形と一致しない、解像度が測定できない、2回目の生成で正規化後hashが一致しないを停止条件にする |
| 再現性 | 同一入力・同一renderer版から同一の正規化後画像hashを再生成し、正規化規則の適用範囲をunit testで固定する |

#### 8.3 ゲート通過後の既定生成配線

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 電気laneおよび機械laneの決定論的ゲート通過後のauthoritative投影成果物、現行revision |
| 実装 | GD1基板pipelineのERC、routing収束、DRC、独立再読込、silkscreen、DFM、設計述語の決定論的ゲート通過後に電気laneの回路図ビューと宣言銅層ごとの層別レイアウトビューを既定生成し、筐体pipelineの機械ゲート通過後にauthoritative assembly STEPから機械laneの断面・干渉ビューを既定生成する。各投影集合をL3 observationとして書き出し、order readinessは視覚投影の前提に含めない。生成失敗はpipelineの停止条件とし、Evidenceへは昇格させない |
| 正常系 | GD1基板・筐体pipelineの完走時に各laneの投影集合が観測として残り、機械laneは断面・干渉SVGを生成する |
| negative/fail-closed | ゲート未通過での生成、renderer不在・版不明、authoritative STEP不在・hash/revision不一致、断面不交差・退化、干渉領域とゲート実測体積の不一致、投影欠落の「問題なし」扱い、Evidence側への書込みを拒否する |
| 再現性 | `generated_at`を除いた投影内容からidentity hashを計算し、同一入力・同一renderer版で同一のidentity hashを再生成できる |

#### 8.4 AIへの受け渡し境界

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 8.3の投影集合、SDKの`ImageContent`、builtin toolの`inspect_image_with_vision` |
| 実装 | 8.3のSVG投影から必要時にCairoSVGでPNGを決定論的に派生し、8.3の投影集合を上書きせず別のraster投影集合へ保存する。acd-tools imageへlibcairo2を固定し、container内でPNG派生可能であることを検証済みである。workspace内PNGをbase64 `data:` URLとして`ImageContent`へ渡す経路と、明示されたvision profile向けの`inspect_image_with_vision`経路を実装する。PNG派生はAI受け渡し時のon-demand経路であり、合否権限を持たない投影を既定成果物へ増やさないためpipelineの既定生成には含めない。lock済みacd-server imageもCairo追加後のtools image由来である。ACDはHTTP(S)画像URLを作成せず、`data:`以外を拒否する。将来HTTP(S)取得を採用する場合もSDKの公開インライン化経路とSSRF block-listだけを使い、`OH_INLINE_IMAGE_ALLOW_PRIVATE_HOSTS`の緩和は既定有効化しない。画像内の文字列はデータとして扱い、命令として実行しない境界を明示する |
| 正常系 | 投影集合から`ImageContent`を構成し、対応するprovenanceを同時に参照できる |
| negative/fail-closed | PNG派生失敗、SVG hash不一致、PNG再生成不一致、provenance欠落の画像、`data:`以外のURL、loopback・private・link-local宛のHTTP(S)取得、SSRF緩和env varのtruthy設定、画像内文字列の命令実行、空vision応答、vision応答のEvidence昇格を拒否する |
| 再現性 | 同一投影集合から同一の`ImageContent`入力と同一の画像hash参照を再構成できる |

#### 8.5 機械可読投影との照合とレビュー観点の記録

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 同一revisionの機械可読投影（netlist要約、ピン割当表など）と8.3の視覚投影 |
| 実装 | 電気laneでは8.3の回路図・宣言銅層別SVGと同一revisionの`ElectricalLane`／`BoardModel`を照合し、機械laneでは断面・干渉SVGと同一revisionの`MechanicalLane`、authoritative assembly STEP、`MechanicalGateReport`を照合する。FW laneでは状態・遷移・シーケンスSVGと同一revisionの`FirmwareLane`およびgraph入力を照合する。投影集合の網羅性、入力hash、renderer版、正規化規則、raw image hash、宣言の網羅性を決定論的に検査し、レビュー観点を`deterministic`または`observation_required`として記録する。FWのペリフェラル設定表とメモリマップは機械可読宣言がないため対象外とし、宣言を追加する場合は対応する8.5検査を追加する。AIの観察はprovenance付きの非Evidence観測として記録する |
| 正常系 | 注記・単位・軸・原点が入力定義と一致し、重なり・非表示要素で意味が欠落せず、意図した信号・電源の系統を読み取れることを、決定論的照合とレビュー観点チェックリストの組合せで記録する |
| negative/fail-closed | 照合不一致、照合対象欠落、SVG解析不能、revision不一致、チェック結果`unknown`の合格扱い、観察のEvidence昇格を拒否する。照合レポートは`pass_evidence=False`のL3観測としてEvidence、fab claims、gate fields、`hashes.json`へ昇格しない |
| 再現性 | 同一入力から同一の照合結果とチェック記録を再生成する |

#### 8.6 追加投影種別の生成

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 同一revisionのDesign Graph入力ファイルとauthoritative機械可読投影。配置図は`BoardModel.placements`、stackup図は`BoardView.layers`・`thickness_mm`・`outer_copper_thickness_um`・`copper_thickness_source`、ブロック図はDesign Graphのnode種別と`depends_on`、電源ツリー図は`NetView.voltage_nominal_v`とpin接続、FW状態遷移・シーケンス図は`firmware.module`へ追加する機械可読宣言を出所とする |
| 実装 | リポジトリ内の決定論的SVG renderer（`acd-svg`）で配置図、stackup図、ブロック図、電源ツリー図、FW状態遷移図、FWシーケンス図を生成し、8.1のprovenance契約へ投影識別子、source revision、入力pathとhash、出力hash、renderer版、生成時刻、再生成判定、正規化規則IDを記録する。renderer版はコード側で固定し、生成時刻や絶対パスをSVGへ埋め込まない。宣言の欠落は推定で埋めずfail-closedとする。全投影は`pass_evidence=False`のL3観測であり、画像とAI所見はDesign Graph、rationale、policy、gate status、Evidence、fabrication claimsへ逆流しない |
| 正常系 | 同一入力から各投影種別を生成し、2回目の生成で同一の画像hashを再現する。生成した投影集合はrevisionと入力hashから出所を追跡できる |
| negative/fail-closed | renderer不在、renderer版unknown、入力ファイル欠落、宣言欠落（基板厚、外層銅厚、銅厚出所、FW状態・遷移）、未対応の層数・実装面、投影識別子重複、SVG解析不能、画像hash不一致、再生成不一致、revision不一致、`pass_evidence`真を拒否する |
| 再現性 | 同一入力・同一renderer版から同一の画像hashとidentity hashを再生成し、各拒否条件のnegative testを回帰へ含める |

8.6は3段で実装する。配置図とstackup図、ブロック図と電源ツリー図、FWの状態遷移・シーケンス図
（機械可読宣言の追加を含む）の順であり、本節の完了条件は3段すべての実装で満たす。


## マイルストーン14の達成済みフェーズ

C-1（筐体の干渉解決探索）とD-1〜D-3（測定結果の入力反映、見積自動取得、実発注）は既存
マイルストーン11・5・7の範囲で扱う。
マイルストーン14.10後の会話駆動loopの残存不足は、L-1〜L-7として14.11で扱う。
14.11後の再監査（L-7）で残ったM-1・M-2は14.12で扱い、M-3はマイルストーン7のprovider境界、
M-4は16.2・16.3、M-5はマイルストーン5の実機Evidenceへ割り当てる。M-6は境界の維持であり
追加実装を要しない。
実機OpenHands環境での新規設計実測（[`vibebb-onpremise-verification.md`](vibebb-onpremise-verification.md)、
[`examples/mini-blink-dongle-20260825/`](../examples/mini-blink-dongle-20260825/)）で残った
N-1〜N-12のうち、acd-agent内で閉じるN-1〜N-7とN-11は14.13で扱い、運用・手順側のN-8〜N-10と
N-12はマイルストーン15.10〜15.13へ割り当てる。
N-1・N-5の解消後の実機実測（[`examples/pulse-check-tag-20260825/`](../examples/pulse-check-tag-20260825/)）で
残ったO-1〜O-13のうち、acd-agent内で閉じるO-1・O-2・O-4・O-5・O-9〜O-13は14.14で扱い、
運用・手順側のO-3・O-6〜O-8はマイルストーン15.14〜15.16へ割り当てる。
多コアVPS（CPU 8コア／MemTotal 15.0 GiB）での実測（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md)）と、
その実測を受けた復帰・反復経路のコード監査で残ったP-2〜P-4とQ-1〜Q-10は14.15で扱う。
P-1（install doctorのESP-IDF判定）は解消済みで、実機VPSのGUIから`/acd:init`がdoctorを
通過し`bootstrap-record.json`が生成されることを確認した。資源要件の実測値と最低・推奨
スペックは[`operations.md`](operations.md)を正とする。
第6回実機実測（2026-08-31、新規VPS・新規workspace）で残ったV-1〜V-10のうち、
acd-agent内で閉じるV-1、V-3、V-5〜V-7、V-9は14.20で扱い、運用・手順側のV-4、V-8、V-10は
マイルストーン15.17〜15.19へ割り当てる。V-2はOpenHands GUIのplugin picker側の課題であり、
本リポジトリの実装対象外として記録だけを残す。GD1非依存の達成条件はW-1〜W-4として14.21で扱う。
第5回実機実測（2026-08-31）で残ったU-1〜U-5は14.19で扱う。自動発注と実機測定は
将来機能・非対象として必須段から外すが、製造提出データの生成・独立検査・品質判定は
現行必須scopeとして維持する。

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


### 14.13 実機実測で残った新規設計の不足（N-1〜N-7、N-11）

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `DesignFixtureSpec`、`fixture_builder`、`design_predicates`の`PREDICATE_CATALOG`、rationale coverage、parts catalog、`plugins/acd/hooks`のstop policy、実機実測記録（[`vibebb-onpremise-verification.md`](vibebb-onpremise-verification.md)、[`examples/mini-blink-dongle-20260825/`](../examples/mini-blink-dongle-20260825/)） |
| 実装 | mechanical・silkscreen・firmware moduleの宣言追加（N-1）、lane別必須宣言の一括preflight（N-3）、parts catalog由来のpin function展開（N-5）、fail-closed停止報告によるstop許可とdeny連続時のエスカレーション（N-2）、rationale provenanceの生成主体必須化と定型レコード検出（N-4）、要件↔topologyの直列素子述語（N-6）、設計反復のみのmodeとダミーorder-total拒否（N-7）、生成器による既存入力上書きの停止（N-11） |
| 正常系 | 宣言を備えた新規設計がsilkscreen barrierを越え、基板・筐体・FW laneをdigest固定containerで実行してrevision一致のauthoritative Evidenceを生成する。GD1の判定、Evidence、正規化hashは変化しない |
| negative・fail-closed | 宣言不足・preflight不足・pin function未解決はunknownで停止する。定型rationaleと`deterministic_tool`の自称、ダミーorder-total、要件と不一致なtopology、既存入力の暗黙上書きを不合格にする。停止報告は合格側権限を持たず、laneのskipを合格として扱わない |
| 再現性 | 宣言・catalog・preflight結果の正規化hashとprovenance（Skill名、script SHA-256）を記録し、`--jobs 1`と並列で収集件数・判定・正規化hashを一致させる |


### 14.15 Devinなしで新規設計を1周させるための残タスク（P-2〜P-4、Q-1〜Q-10）（達成）

汎用エージェント（Devin）が不在でも、OpenHands（L2）とacd-agentの決定論的経路だけで
新規設計を要件から発注可否まで1周させることを目的とするフェーズである。今回の実測では
新規設計`vibebb-sensor-node`が基板laneのpre-router段で`power_decoupling`（C4-U1のpad距離
15.838 mm > 3.0 mm）とrationale coverage不足によりfail-closedし、そこから先へ進む復帰経路が
起動しなかった。さらに同じfixtureへ`--explore-board`を明示したdigest固定container実行
（9.7節のRun B）では探索段が起動したものの、`evaluated_candidates=1`、`status='stopped'`、
`diagnostic_dimensions=[]`、`winner_written=false`で終わり、基板laneは復帰しなかった。
すなわち不足は「探索の起動」だけでなく「却下理由に基づく候補生成と、候補確定時の
rationale整合」である。ゲートは正しく閉じており、緩和ではなく復帰経路の実装で解く。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `run_design_loop`（復帰判定`board_rejection`と探索round）、`explore_board_candidates`、`explore_enclosure_candidates`、`compile_requirement_change`の`_refresh_rationale`、`build_design_fixture`と手編集ガード、`check_rationale_coverage`の必須属性、`diagnose_gate_failure`、`run_acd_goal`、`plugins/acd/commands/vibebb-loop.md`、多コアVPS実測記録（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md)）と[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のP節・Q節 |
| 実装 | 探索が設計入力を確定する際のrationale決定論的更新（Q-4）、宣言された上書きによるfixture再生成経路（Q-5）、却下時に機械可読な再実行引数を返し設計反復modeで探索を起動する経路（Q-2）、却下predicateのremediationを入力とする候補生成（Q-3）、laneごとの復帰可能な変更次元の宣言と筐体・silkscreen・FWへの連結（Q-1、Q-8、M-1の後続）、要件の追加・削除とgraph差分の同一transaction反映（Q-6）、bounded反復harnessの会話経路への接続（Q-7）、診断入力へのrationale coverageとlane preflightの取り込み（Q-9）、firmware capability registryへのaction／capability fragment宣言追加経路（Q-10）、初期配置のdecoupling距離制約（P-2）、QEMU打ち切りの正常終了明示（P-3）、FW laneのauthoritative Evidence生成（P-4） |
| 正常系 | 会話由来のspecから生成した新規設計が、pre-router却下を含む1回以上の却下から探索・修正・再実行を経て基板・筐体・FW laneを通過し、digest固定containerでrevision一致のauthoritative Evidenceを生成して発注可否判定へ到達する。GD1の判定、Evidence、正規化hashは変化しない |
| negative・fail-closed | 候補予算・round上限の超過、graph ID／revisionの不一致、正規化content hashの不変、rationale更新不能、宣言されていない上書き、復帰次元が宣言されていないlaneの却下、remediationを持たない却下はいずれもfail-closedで停止する。探索report、診断、goal評決、L2の合意はpass authorityを持たず、`pass_evidence`はL1ゲート由来に限る |
| 再現性 | 探索round、候補ID、変更subject、rationale更新結果、再実行したlaneをL3記録として保存し、同一入力での再実行で判定と正規化hashが一致することを回帰テストで固定する。復帰経路を含む実行のwall-clockと資源使用を[`operations.md`](operations.md)の実測へ追記する |

14.15では、宣言由来のlane復帰plan（`contracts/lane-recovery-declaration.json`）、却下応答の
機械可読な再実行引数、却下predicateのremediationに限定した候補生成、候補確定時の
rationale決定論的更新と原子的commit、宣言された`fixture_overwrite`、要件の追加・削除、
診断の拡張（失敗subject、変更次元、rationale coverage、lane preflight、必要宣言）、
firmware capability registryへの原子的な宣言追記、初期配置のdecoupling距離解決、QEMU打ち切りの
正常終了明示、FW laneのrevision一致Evidence（virtual実行明示）を追加した。会話経路の入口は
`/acd:vibebb-loop`の`recover_lanes`・`fixture_overwrite`と`/acd:vibebb-recover`であり、
bounded反復harnessは`scripts/run_acd_goal.py`である。探索report、診断、goal評決は
pass authorityを持たず、`pass_evidence`はrevision一致したL1ゲート由来に限る。

14.1〜14.3、14.4、14.5、14.6、14.7、14.8および14.9は達成済みである。14.4では、
配置・回転、GPIO割当、placement coupling、単一datum、stitch via fallbackを含むbounded
探索loopへ接続した。14.5では、要件から任意fixture、部品選定、トポロジ合成、決定論的
tool入口、機能ブロック契約registry宣言入口までを接続した。14.6では、GD1依存の命名、
FW設定、feedback適用、quote/order provider境界をgraph・policy駆動へ一般化した。14.7では、
単一orchestrator、入力hashに基づくDSN／SES生成物cache、cacheだけを利用するresume、
各laneのL3 timing recordを追加した。14.8では、`/acd:init`と`acd_bootstrap_workspace`を
単一のfail-closed初期化経路として追加し、workspace健全性doctorとL3 bootstrap recordを
提供した。cache hitでもL1ゲートとEvidenceは再実行され、resumeは判定を保存・復元しない。
生成物、compiler、Skill結果はpass authorityを持たず、14.9では単一publish workflowによる
tools/serverの直列publish、digest lock更新PR、registry manifest照合、配布文書の整合を追加した。L1決定論的ゲートとrevision一致した
authoritative Evidenceが唯一の合否根拠である。実測値と運用上の注意事項は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)と[`operations.md`](operations.md)を正とする。


### 14.19 製造提出データの完備とscope改定後の残タスク（U-1〜U-5）

第5回実機実測（2026-08-31）で残ったU-1〜U-5を、製造提出データの品質を現行必須として
扱うフェーズである。自動発注と実機測定は将来機能・非対象であり、既存コードを削除せず、
決定論的loopの必須段にも含めない。L1権限、既存の閾値、ゲート条件、fail-closed境界は
変更しない。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 第5回実機実測のRun F／H／I／J／K、生成されたGerber・drill・gbrjob・gerbers.zip・BOM・CPL・fab-package manifest・筐体STEP／3MF／STL、`vibebb-gap-analysis.md`のU節 |
| 実装 | 生成物のUTF-8明示読書きと非UTF-8 locale回帰（U-1、解消済み）、筐体STL出力とSTEP／3MF同等の検査（U-2）、quote／order例のrevision整合（U-3、GD1整合fixtureと回帰testで解消済み）、decoupling制約を含む決定論的な配置順序・回転探索（U-4、解消済み）、製造提出データの必須成果物・独立reload・正規化hash・DFM・幾何・profile整合・revision整合・Evidence妥当性をまとめた単一の独立L1判定（U-5、解消済み）を追加する。U-4では電気laneに宣言されたside／layer次元がないため、面配置は実装せず利用不可として記録する |
| 正常系 | 同一の生成物がlocaleに依存せず独立reloadを通過し、筐体STEP／3MF／STLを含む必須成果物を生成する。decoupling配置は既存探索、宣言rotation、決定論的配置順序の順に再試行し、宣言limitとcourtyard clearanceを維持する。quote／order scopeを与えた場合だけ整合した任意段を実行し、製造提出データの品質判定を発注実行から独立して読める |
| negative・fail-closed | UTF-8でない生成物、欠落・破損した必須成果物、独立reload・hash・DFM・幾何・profile整合の失敗、revision不一致、decoupling制約を満たせない配置、order scopeの不整合はfail-closedとする。自動発注や実機測定の未実行を合格へ倒さず、QEMUのvirtual Evidenceをphysical Evidenceへ昇格させない |
| 再現性 | 同一digest・同一入力から同一成果物hash、独立検査結果、U-1〜U-5の診断を再生成し、locale・revision・欠落成果物・配置制約のnegative caseを固定する。decouplingの不足量、blocking refdes、探索次元、面配置 unavailable、変更可能次元はL3 reportとして決定論的に記録する |

U-1は、`src/acd/**/*.py`、`scripts/**/*.py`（`scripts/tests/**`を除く）、
`plugins/**/scripts/**/*.py`をASTで走査し、text modeの`open`、`read_text`／`write_text`、
`subprocess`、`io.TextIOWrapper`に`encoding="utf-8"`、`"utf-8-sig"`、または厳格な
`"ascii"`が明示されていることを
検査するguardをfast段へ追加したことで解消済みである。非literal mode／encodingもfail-closedで
扱い、例外は呼出し行の`# encoding-exempt: <英語の理由>`だけ（空理由は違反）とする。
reloadに加え、fabのBOM／CPL・fab-package・gbrjob／ZIP、筐体のSTEP／3MF／STL・manifest、
FWのsummary／serial log／Evidenceの非UTF-8 locale回帰を共有child-process helperで固定した。

U-2は筐体projectionへASCII STL出力を追加し、STLを正規化、provenance／manifestへ登録し、
正規化hashをEvidenceへ含め、3MFとともに独立reloadして部品数、bbox、三角形数、体積を検査したことで
解消済みである。既存のSTEP部品・組立検査は維持している。

U-5は、Gerber一式、drill、gbrjob、ZIP、BOM／CPL、fab-package manifest、
筐体STEP／3MF／STLを必須成果物として列挙し、独立reload、正規化hash、DFM、幾何、
fab profile、revision、Evidence妥当性を単一のL1 verdictへ統合したことで解消済みである。
`order-readiness.json`は状態を記録するだけで、quote集計・発注実行は判定scopeから除外する。
U-1〜U-5の残作業は解消済みである。U-4は、既存のorigin探索を維持したうえでrotationと配置順序を追加し、
不足量と変更可能次元をL3 reportへ記録したことで解消済みである。面配置（side）は電気laneの宣言に
存在しないため実装せず、利用不可の次元として記録する。


### 14.17 実装済みの是正の記録

実装済みの是正は次のとおりである。S-1は`exploration`と`enclosure_exploration`の候補評価が
確定経路と同一の`refresh_rationale_document`を一時fixtureへ適用する。元のgraphとrationaleは
却下候補で変更されず、rationaleの欠落・破損はfail-closedである。S-2は候補固有の却下を
`gate_rejected`として扱い、残予算がある限り宣言順で次候補を評価し、`max_candidates`、
`generated_candidates`、`evaluated_candidates`、`consumed_budget`、`remaining_budget`、
`termination_reason`をreportへ記録する。fail-closedの停止は従来どおり即時に打ち切る。
S-3は`scripts/verify_acd_tool_registration.py --command`で、commandが宣言する`acd_*`と
会話が露出するtoolの差分を検出し、不足toolごとに決定論的CLI入口またはCLI入口が無い理由を
返す。S-4は`src/acd/core/library_assets.py`をcatalogと生成fixtureの共通契約とし、相対宣言の
資材を生成fixtureへ同梱してhashを両側で検査し、`scripts/verify_library_assets.py`をfast段へ
追加する。S-5は`scripts/report_progress.py`がrun出力のtiming recordと探索reportをL3 digestと
して会話へ返し、読めないrecordを`unknown`として非零終了する。いずれの表示・診断も
`pass_evidence`を与えない。S-3の配布形態そのもの（ambient install経路への登録）と、
復帰成立実行の実測記録は引き続き未了である。

S-4の初回実装では、Espressif資材を`libraries/`（canonical store）へ移した一方で、
基板・回路図・project・CPL経路の相対library宣言はfixture dir基準でしか解決しなかったため、
commit済みGD1 fixtureに対する探索とcontainerのゲート実行が
`pinned library file missing: fixtures/golden-design-1/libraries/...`でfail-closed停止し、
`scripts/verify_library_assets.py --check`だけが同じ宣言を`store_verified`として通す非対称が
生じていた。解決は`acd.core.library_assets.resolve_fixture_library_path()`に統一し、
fixture同梱copyを優先してcanonical storeへfallbackする。生成fixtureは従来どおり資材を同梱し、
storeの外を指す相対宣言はfail-closedのままである。

ただし本体の修正だけでは出荷経路に届かなかった。Skill scriptはPEP723で
`acd @ git+…@<pinned sha>`を宣言するため、`plugins/acd/skills/acd-package-ref.txt`と
`acd-package-contract.json`を更新するまでsubprocessは旧コードで動き、GD1既定fixtureの探索は
同じ`pinned library file missing`で停止しexploration reportも書かれない。さらに隔離環境では
`repository_root()`がinstalled packageのpathをrootとみなしmarker検証で落ちるため、
store fallbackには`ACD_REPOSITORY_ROOT`が必要である。よってpinned refを修正commitへ上げ、
library資材を解決するSkill script（placement search、vision proposal、vision route proposal、
silkscreen search）を`acd-firmware-esp32c3`と同じ規約で自身のrepository rootを設定する形へ
統一した。repository checkoutを伴わないpackaged plugin単体ではcanonical storeが存在せず
fail-closedになる。この配布形態の扱いはS-3の未了項目と同じ論点として残る。


### 14.18 実装済みの是正の記録

T-1、T-2、T-4、T-5は実装済みである。候補評価は親laneと独立したtiming recorderを使い、
観測失敗を`stopped`として扱う。各design loopはcanonical hash付きの
`loop-summary.json`をL3へ保存し、`report_progress.py`が失敗lane・理由・次の手順を表示する。
workspaceのdownloadが失敗した場合もcommandのexit code・stdout・stderr・部分downloadを出力したうえで
fail-closedに終了する。T-2ではremediation次元ごとにspacing preferenceの候補を宣言順で生成し、
候補予算まで評価できるようにした。T-3は、pinned SDK v1.44.1のplugin形式に
ToolDefinition登録面が無い（根拠: `vendor/software-agent-sdk/openhands-sdk/openhands/sdk/plugin/`）ため、
ambient経路でのtool登録を主張せず、commandが宣言toolの不在をfail-closedに検出して
決定論的CLIへ倒す経路とdrift guardを実装した。CLI入口を持たない3 toolの段は実行せず不成立として報告し、
この判定はL3観測でauthoritative Evidenceを生成しない。
実機で成功した復帰runのwall-clock記録も未取得である。


## マイルストーン15の達成済みフェーズ

15.1〜15.13は達成済みであり、15.14〜15.19は未着手である。15.1〜15.4と15.12は運用手順・設計文書側の明記で完了し、
15.5はlane runnerのログ要約（既定tailと完全ログの別途保存）、15.10は
container出力の`out/container/`分離と権限・環境起因失敗の分類、15.11は`--fixture`＋
`--out`へ統一したlane CLI（旧引数は明示エラー）、15.13は
`scripts/export_execution_records.py`のallowlist抽出・秘匿化・漏洩検出で完了した。
いずれも合否権限を変更せず、fail-closed境界を維持する。15.10〜15.13は
実機OpenHands環境での新規設計実測（N-8〜N-10、N-12）を出所とする。15.6〜15.9は
[`improvement-notes.md`](../examples/sensor-node-20260820/report/improvement-notes.md)と
[`review-notes.md`](../examples/sensor-node-20260820/report/review-notes.md)の運用改善項目を
出所とし、いずれも既存の閾値、ゲート挙動、fail-closed境界を変更していない。15.17〜15.19は
第6回実機実測と成果物回収（V-4、V-8、V-10）を出所とし、例示・計測・収録の手順側だけを
整備する項目であり、判定と閾値には触れない。


## バックログからマイルストーンへの移行

旧3バックログ節の全項目を、次のマイルストーンへ移した。実行例・レビュー由来の
改善バックログは[`improvement-notes.md`](../examples/sensor-node-20260820/report/improvement-notes.md)
と[`review-notes.md`](../examples/sensor-node-20260820/report/review-notes.md)、および実機実測の
[`improvement-notes.md`](../examples/mini-blink-dongle-20260825/report/improvement-notes.md)を
出所として保持し、
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
| （実機実測）N-1 `DesignFixtureSpec`のmechanical・silkscreen・firmware module宣言 | 14.13 |
| （実機実測）N-2 Stop hookのfail-closed停止経路 | 14.13 |
| （実機実測）N-3 必須宣言のpreflight | 14.13 |
| （実機実測）N-4 rationale coverageの生成主体検査 | 14.13 |
| （実機実測）N-5 parts catalog由来のpin function展開 | 14.13 |
| （実機実測）N-6 要件↔topologyの直列素子述語 | 14.13（16.2・16.3の述語拡張と同じ契約registryを使う） |
| （実機実測）N-7 設計反復のみのmodeとダミーorder-total拒否 | 14.13 |
| （実機実測）N-8 out-rootのhost／container分離と権限起因失敗の区別 | 15.10 |
| （実機実測）N-9 lane scriptのCLI引数統一 | 15.11 |
| （実機実測）N-10 graph単体検証入口の明確化 | 15.12 |
| （実機実測）N-11 生成器による既存入力上書きの防止 | 14.13 |
| （実機実測）N-12 実機実行記録の持ち出し経路と秘匿化 | 15.13 |
| （実機実測）O-1 `run_tool`のtimeout引数化とtimeout収束状態の区別 | 14.14 |
| （実機実測）O-2 container起動前のホスト資源検査 | 14.14 |
| （実機実測）O-3 長時間laneのbackground実行手順とlog契約 | 15.14 |
| （達成）O-4 preflight語彙と診断限定の表明 | 14.14 |
| （達成）O-5 lane別必須宣言の一括preflight | 14.14 |
| （実機実測）O-6 doctor出力のauthoritative／provisional分離 | 15.15 |
| （実機実測）O-7 lock済みimage未取得時のpullコマンド提示 | 15.15 |
| （実機実測）O-8 収集入口へのlane log取り込み | 15.16 |
| （実機実測）O-9 router pass予算既定の単一定数化 | 14.14 |
| （達成）O-10 FW laneの必要netと生成codeのGD1固定解消 | 14.14 |
| （達成）O-11 projection guardの判定を書き込み対象で行いlane起動とstop reportを許可 | 14.14 |
| （実機実測）O-12 筐体lane entrypointと発注policyのGD1固定解消 | 14.14 |
| （達成）O-13 rationale被覆検査の対象解決 | 14.14 |
| （達成）P-1 install doctorのESP-IDF判定の読み取り可能性統一 | 14.14 |
| （多コアVPS実測）P-2 初期配置のdecoupling距離制約 | 14.15 |
| （多コアVPS実測）P-3 QEMU打ち切りの正常終了明示 | 14.15 |
| （多コアVPS実測）P-4 FW laneのauthoritative Evidence生成 | 14.15 |
| （コード監査）Q-1 却下後の自動復帰の全laneへの連結 | 14.15 |
| （多コアVPS実測）Q-2 会話経路からの復帰起動 | 14.15 |
| （多コアVPS実測）Q-3 remediation由来の候補生成 | 14.15 |
| （コード監査）Q-4 探索確定時のrationale決定論的更新 | 14.15 |
| （コード監査）Q-5 宣言された上書きによるfixture再生成 | 14.15 |
| （コード監査）Q-6 要件の追加・削除とgraph差分の同一transaction反映 | 14.15 |
| （コード監査）Q-7 bounded反復harnessの会話経路への接続 | 14.15 |
| （コード監査）Q-8 lane別の復帰次元宣言（silkscreen・FW） | 14.15 |
| （コード監査）Q-9 診断入力へのrationale coverageとlane preflight取り込み | 14.15 |
| （多コアVPS実測）Q-10 firmware capability registryへの宣言追加経路 | 14.15 |
| （多コアVPS実測）T-1 候補評価と親laneのTimingRecorder分離 | 14.18 |
| （多コアVPS実測）T-2 remediation次元ごとの複数候補生成 | 14.18 |
| （多コアVPS実測）T-3 ambient install経路へのACD tool登録 | 14.18 |
| （多コアVPS実測）T-4 失敗理由と進行のL3 digest統合 | 14.18 |
| （多コアVPS実測）T-5 transport失敗時のcommand出力保持 | 14.18 |
| （多コアVPS実測・達成）U-1 生成物の読み書きのUTF-8明示と非UTF-8 locale回帰 | 14.19 |
| （多コアVPS実測・達成）U-2 筐体STL出力とSTEP／3MF同等の検査 | 14.19 |
| （多コアVPS実測・達成）U-3 例示commandのquote／order入力のrevision整合 | 14.19 |
| （多コアVPS実測）U-4 decoupling制約を満たすfixture配置探索 | 14.19 |
| （多コアVPS実測）U-5 製造提出データの独立L1品質判定 | 14.19 |
| （実機組み付け）筐体アンテナ干渉（`board_edge_overhang`ノード未消費） | 3.1 |
| （実機組み付け）筐体ネジ穴欠落（スタンドオフが固体円柱・リッドが平板） | 3.1 |
