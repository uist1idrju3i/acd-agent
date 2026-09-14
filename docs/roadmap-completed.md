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


### 11.4a 統合3Dモデル投影（glTF＋HTMLビューア）（達成）

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | Design Graphの`MechanicalLane`（outline・component_bodies・enclosure）、authoritative STEP（shell・lid・assembly）、`MechanicalGateReport`、電気laneのrefdes対応 |
| 実装 | `acd.adapters.cad.assembly_3d`がboard（外形・厚さ・取付穴）、非`none`部品の直方体近似（`approximated`、refdes名）、import_step由来のshell/lid（`step`）、実測干渉node（`computed`）を固定node順の`AssemblyMesh`へまとめ、canonical化した三角形列をglTF 2.0 binary `out/<lane>/3d/assembly.glb`（mm→m、右手Y-up）へ書き出す。writerと独立した`read_glb_format_check`（`struct`/`json`のみ）が結果を`assembly-3d.json`の`format_check`へ記録し、`assembly_viewer.py`がvendored three.js 0.186.0（MIT）をimport mapで埋め込んだ単独HTMLビューア`assembly.html`を生成する。PBR材質のみで`KHR_materials_*`等のextensionは使わない |
| 正常系 | GD1筐体pipelineの機械visual cross-check通過後・Evidence生成前に3成果物を既定生成し、node名（`board`・各refdes・`enclosure-shell`・`enclosure-lid`）とprovenance extrasをmanifestへ記録する |
| negative/fail-closed | STEP不在・import失敗、tessellation失敗、干渉体積とゲート実測の不一致、GLB format checkのいずれかの失敗をpipeline停止条件とし、HTML生成より前に停止する。投影欠落を「問題なし」と解釈しない |
| 再現性 | 頂点を6桁丸め・退化三角形除去・最小頂点先頭化・三角形lexicographic sortにより、逐次（worker=1）と並列（worker=N）で同一GLB sha256とmanifestを再生成する。時刻・worker数をhash入力へ含めない |

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

### 9.4 レビュー資料生成の実装記録

`plugins/acd/skills/acd-product-docs/scripts/generate_review_package.py`が
design graph、記録済み視覚投影、design-predicates、DFM report、および明示的に
宣言された前revisionから、`review-package.md`、`review-package.json`、
`graph-diff.json`を決定論的に生成する。graph差分はノードの追加・削除・`kind`／
`attrs`単位の変更と、`depends_on`から導出した辺の追加・削除をID順に整理し、
前revisionを宣言しない場合はunknownとして記録する。
レビュー項目には設計述語、DFM所見、未実装・unknown、視覚投影、graph差分を入力由来の
itemとして収録し、`authority: "none"`、`record_class: "L3"`、
`pass_evidence: false`を固定する。

`run_projection_docs`はこのscriptを5番目のgeneratorとして実行し、3文書と
provenance、`hashes.json`への収録を要求する。`run_design_loop`とCLIの
`--previous-graph`は前revisionを任意入力として伝搬し、省略時は
`--no-previous-revision`を明示する。graph ID／revision、投影再生成状態、画像、
述語・DFM revisionの不一致や入力欠落はfail-closedで停止し、JSON本体には
timestampを含めない。

### 9.5 多言語出力の実装記録

`acd-product-docs`の5 generatorに`templates/ja.json`と`templates/en.json`を
導入し、`--lang ja|en`で日本語・英語の文書を決定論的に生成する。日本語は既存の
`out-dir`直下、英語は`out-dir/en/`へ出力し、ラベルだけをテンプレートで切り替える。
graph由来の値、識別子、単位、revision、hash、投影metadataは翻訳せず、そのまま記録する。
テンプレートのpath・hash・languageを各文書のprovenanceと入力hashへ含め、同一入力の
再生成結果を固定する。`projection-docs`と`run_design_loop`は複数言語を受け付け、
言語ごとの文書集合と`hashes.json`を検証する。

### 20.2 graph差分投影の実装記録

`acd.schema.graph_diff`の契約と`acd.core.graph_diff`の決定論的builderを追加し、
ノードの追加・削除・`kind`／`attrs`単位の変更、および`depends_on`から導出した辺の
追加・削除をrevision間で比較する。`graph-diff-projection` stageは前revisionが宣言
された場合だけ`acd-svg`のSVG投影を生成し、前revisionがない場合はL3のskip記録を
残す。投影はnode kindごとの列とnode ID順の行で配置し、追加・削除・変更・不変を
色と凡例で示す。`visual-review-manifest`の前段で生成するため、PNG派生とレビュー
manifestへ自動的に取り込まれる。

レビュー資料には`graph_diff_projection_id`を記録し、graph差分と視覚投影の対応を
追跡できるようにした。投影、資料、stage結果はいずれもL3観測であり、合否権限や
authoritative pass evidenceを生成しない。

### 20.1 ECOワークフローとrevisionライフサイクルの実装記録

`EcoRecord`、`EcoDocument`、`EcoCheckResult`を追加し、変更理由、impact node、
影響lane、再検証要件、水平展開処置、ワークアラウンド廃止hookを契約化した。
`check_eco.py`はfrom/to graphのrevisionとgraph ID、graph diff、lane別最低限ゲート、
revision一致evidence、13.1水平展開の処置を決定論的に検査し、未宣言・欠落・unknown・
不一致をfail-closedでclose不可とする。salvage gateとECO gateの外部evidence読込は
共通`external_gate_run()`へ抽出した。

ECOの恒久変更は`rN+1` graphへ反映し、`rN+WA-001`のワークアラウンドrevisionは
恒久revisionへ昇格させない。運用ライフサイクルとlane別evidence名は
[`eco-workflow.md`](eco-workflow.md)に記録する。ワークアラウンド廃止判定そのものは
マイルストーン13.6で定義する。

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
| （達成）O-12残項 `OrderScope`の決定論的導出とquote request宣言 | 14.14 |
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
| ACD imageのコンテナ化と配布 | 6・14.9（達成、[`docker/README.md`](../docker/README.md)） |
| routing後のvia mask開口を含む再解決 | 14.25（2026-09-13） |
| 長時間runの予算・中断・再開契約 | 15.20（2026-09-13） |
| 代替routerの単独実測 | 15.21（2026-09-13） |
| 機器I/F契約投影 | 9.6（2026-09-13） |
| 品質文書生成 | 9.3（2026-09-13） |
| レビュー資料生成 | 9.4 |
| 多言語出力 | 9.5 |
| graph差分投影 | 20.2 |
| ハーネス契約と結線検査 | 16.6（2026-09-13） |
| 想定実使用環境の宣言contract | 16.3（2026-09-13） |
| （実機組み付け）筐体アンテナ干渉（`board_edge_overhang`ノード未消費） | 3.1 |
| （実機組み付け）筐体ネジ穴欠落（スタンドオフが固体円柱・リッドが平板） | 3.1 |

## マイルストーン12の達成済みフェーズ

完成した設計の知識源（design graph、rationale record、ゲート結果、Evidence、生成文書、
git履歴、revision差分、会話ログ）を照会可能なナレッジとしてまとめ、製品仕様、使い方、
トラブルシューティング、設計根拠、歴史的経緯の質問に出所の引用付きで答える。回答はL2操舵・
L3観測であり、合否権限を持たない。出所（rationale ID、Evidenceファイル、コミット、文書パス）
を必ず引用し、導出できない質問にはunknownと答える。会話ログは内部向けQAだけに含め、
公開用FAQから除外する。

| 順 | フェーズ | 内容 |
|---|---|---|
| 12.1 | ナレッジ索引契約 | graph・rationale・ゲート結果・Evidence・生成文書・git履歴・会話ログを、出所種別と参照パス付きで列挙する |
| 12.2 | 対話QA SKILL | 索引contractの範囲で出所引用付きの回答を返すSKILL（例: `/acd:ask`）を追加する |
| 12.3 | トラブルシューティング知識の構造化 | 症状・確認手順・期待値をgraphとFW投影から機械可読に導出する |
| 12.4 | 公開用FAQ生成 | 会話ログを除外したFAQ・ナレッジ文書を`out/docs/`へ生成する |
| 12.5 | 歴史的経緯QA | git履歴・revision差分・内部会話ログ・ECO記録から出所付きで回答する |

12.1〜12.5は`acd-design-knowledge` Skillと`/acd:ask` commandとして実装済みであり、
運用手順は[`operations.md`](operations.md)の設計知識laneに記録する。

## マイルストーン14の達成済みフェーズ

### 14.17 復帰経路と新規設計入口の是正（S-1〜S-5）

S-1〜S-5は、候補評価時のrationale更新、残予算での次候補評価、宣言tool不在検出、
library資材宣言の統一、進行表示を扱う。S-1、S-2、S-4、S-5とS-3のdrift guardは実装済みで、
表示・診断は`pass_evidence`を与えない。S-3の配布形態そのものと復帰成立実行の実測記録は未了である。

### 14.18 復帰候補評価からL3観測の混入を除く（T-1〜T-5）

T-1、T-2、T-4、T-5は実装済みである。候補評価は親laneと独立したtiming recorderを使い、
観測失敗を`stopped`として扱う。T-3はpinned SDKの登録面を検出するdrift guardとして扱い、
authoritative Evidenceを生成しない。実機で成功した復帰runのwall-clock記録は未取得である。

### 14.20 Devin不在で新規設計を1周させるための残関門（V-1、V-3、V-5〜V-7、V-9）

V-1、V-3、V-5、V-6、V-7、V-9は達成した。V-1は
`plugins/acd/hooks/scripts/eda_asset_export.py`の`refuse-eda-asset-export` hookを
`PreToolUse`へ登録し、container内EDA資材のhost持ち出しを拒否する。不足宣言、download、
wall-clock、tool登録の記録とhook診断はL3観測であり、合否権限は持たない。V-2はOpenHands側の
課題として記録に留め、V-4・V-8・V-10は15.17〜15.19で扱う。

### 14.21 GD1非依存の達成判定（W-1〜W-4）

W-1〜W-4は達成した。非GD1 fixture `mini-blink-dongle`がdigest固定containerで全laneと
authoritative Evidence検証を通過し、GD1はregression用positive controlとして維持する。

## マイルストーン12の原文記録

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

## マイルストーン14の原文記録

### 14.17 復帰経路と新規設計入口の是正（S-1〜S-5）

14.15の実装後に同じ8コアVPSで実測した結果（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 10節）、
宣言由来のlane復帰planは機能し（`recovery_supported: true`、`recovery_explorer: board`、
`remediation_dimensions: ["component_placement_xy"]`）、生成された候補は`power_decoupling`を
満たす配置へ到達していた。しかし候補の評価がrationale更新前のgraphで行われるため
`rationale coverage failed: missing=18, stale=18`で却下され、`winner_written=false`、
`termination_reason=fail_closed_stop`で復帰が成立しない。さらに新規specからのfixture生成は
部品catalogのlibrary資材宣言と生成fixtureの不一致により最初のstageで停止し、GUI配布形態では
`acd_*` ToolDefinitionが会話へ登録されないためcommandの宣言toolへ到達できない。ゲートは
いずれも正しく閉じており、緩和ではなく経路の是正で解くフェーズである。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `exploration`の候補評価経路、`commit_candidate_graph`と`refresh_rationale_document`、`check_rationale_coverage`、`fixture_builder`の`_normalize_decoupling_placement`、`gd1_fixture/components.py`のlibrary宣言、`resolve_fixture_path`、`register_acd_tools()`と`build_acd_conversation()`、ADR-0036のambient install経路、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のS節 |
| 実装 | 候補評価入力へ確定経路と同一のrationale更新を適用する（S-1）、候補固有の却下では残予算で次候補を評価し予算をL3へ明示する（S-2）、ambient install経路の会話へACD tool入口を登録するか宣言toolの不在をfail-closedに検出する（S-3）、catalogのlibrary資材宣言を生成fixtureへの同梱かcontainer内絶対pathへ統一し宣言と生成の両側を検査する（S-4）、L3 timing recordとexploration reportを会話へ返す進行表示（S-5） |
| 正常系 | GD1を摂動した内部整合fixtureに対し`recover_lanes`が候補を確定し、graph IDとrevisionを保持したまま正規化content hashが変化し、rationaleが同一transactionで更新され、基板laneの再実行がL1ゲートを通過する。新規specからのfixture生成がlibrary資材を解決して基板laneへ到達する。GD1の判定、Evidence、正規化hashは変化しない |
| negative・fail-closed | rationale更新不能、graph ID／revisionの不一致、正規化hashの不変、候補予算・round上限の超過、宣言と生成が食い違うlibrary資材、宣言toolの不在はいずれもfail-closedで停止する。候補report、進行表示、GUI観測はpass authorityを持たず、`pass_evidence`はrevision一致したL1ゲート由来に限る |
| 再現性 | 候補ごとの評価入力hash、rationale更新結果、予算消費、再実行したlaneをL3記録として保存し、同一入力での再実行で判定と正規化hashが一致することを回帰テストで固定する。復帰が成立した実行のwall-clockと資源使用を[`operations.md`](operations.md)へ追記する |

S-1とS-4は単体成立の前提であり先に扱う。S-3は配布・登録経路の定義であり、実装だけでは
閉じない。S-2とS-5は予算と進行の可視化である。

S-1、S-2、S-4、S-5とS-3のdrift guard（`scripts/verify_acd_tool_registration.py --command`）は実装済みで、記録は[`roadmap-completed.md`](roadmap-completed.md)にある。S-3の配布形態そのもの（ambient install経路への登録）と復帰成立実行の実測記録は未了である。

### 14.18 復帰候補評価からL3観測の混入を除く（T-1〜T-5）

14.17の実装後に同じ8コアVPSでplugin（`fb286380…`）とlock済みserver image
（`sha256:d683f14b…`）で実測した結果（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 11節）、
S-1は解消し候補はrationale coverageで却下されず決定論的pipelineへ到達した。しかし候補評価が
親laneと同一の`TimingRecorder`を共有するため、pre-router却下で`finish`されずに残った
`board[1/12]`と衝突し、候補はtiming stageの二重開始（`timing stage already started`）を理由に
`gate_rejected`となる。復帰は基板却下後にしか起動しないため衝突は常に
発生し、`winner_written=false`のまま`candidate_pool_exhausted`で終わる。加えて候補生成が1件
（`generated_candidates=1`）しか返さないため候補上限3・round上限2は行使されない。L3観測の失敗を
L1判定へ持ち込まないための是正フェーズである。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `src/acd/core/runtime_records.py`の`TimingRecorder`、`src/acd/pipeline/design_loop.py`の候補`pipeline_runner`、`src/acd/core/exploration.py`の候補評価と`_refill_pending`、`plugins/acd/skills/acd-placement-search`の候補生成、`scripts/report_progress.py`、`src/acd/openhands/workspace.py`の`_execute_and_download()`、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のT節 |
| 実装 | 候補評価へ親と独立したtiming記録（または候補IDでnamespaceしたstage名）を与える（T-1）、観測起因の例外を`gate_rejected`と区別する（T-1）、remediation次元ごとに複数候補を宣言順で列挙する（T-2）、pinned SDK v1.44.1のplugin形式（`vendor/software-agent-sdk/openhands-sdk/openhands/sdk/plugin/`）にToolDefinition登録面がないため、ambient経路ではcommandが宣言toolの不在をfail-closedに検出し決定論的CLIへ倒すdrift guardをfast段で実行する（T-3）、`failure_reason`と`next_step_action`をL3 digestへ取り込む（T-4）、transport失敗時もcommandのexit code・stdout・stderr・失敗種別を出力してから非ゼロ終了する（T-5） |
| 正常系 | GD1を摂動した内部整合fixtureに対し`recover_lanes`が候補を確定し（`winner_written=true`）、graph IDとrevisionを保持したまま正規化content hashが変化し、rationaleが同一transactionで更新され、基板laneの再実行がL1ゲートを通過する。候補生成は上限まで候補を返し、`consumed_budget`と`remaining_budget`が実行と一致する。GD1の判定、Evidence、正規化hashは変化しない |
| negative・fail-closed | timing記録の破損・欠落、候補評価の例外、graph ID／revisionの不一致、正規化hashの不変、予算・round上限の超過はいずれもfail-closedで停止する。観測層（timing、digest、探索report）の成功はpass authorityを持たず、`pass_evidence`はrevision一致したL1ゲート由来に限る |
| 再現性 | 候補ごとの評価入力hash、timing記録の帰属、予算消費、再実行したlaneをL3記録として保存し、親laneが却下で中断した後に候補評価が成立することを回帰テストで固定する。復帰が成立した実行のwall-clockと資源使用を[`operations.md`](operations.md)へ追記する |

T-1〜T-5は実装済みで、記録は[`roadmap-completed.md`](roadmap-completed.md)にある。実機で成功した復帰runのwall-clock記録は未取得である。

T-1は復帰経路の唯一の停止点であり先に扱う。T-2はT-1解消後に予算を意味あるものにする前提、
T-4は表示の統合、T-3はS-3の未了部分と同一の配布形態の論点、T-5は検証作業の可読性である。
いずれもEvidenceの合否権限とfail-closed境界を変更しない。

### 14.20 Devin不在で新規設計を1周させるための残関門（V-1、V-3、V-5〜V-7、V-9）

第6回実機実測（2026-08-31、新規VPS・新規workspace、
[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 13節）で、GD1は
決定論的経路で端から端まで通過した。残る停止点は新規設計側にある。新規specからのfixture生成は
成功するが、`silkscreen-resolve`が`GraphExtractionError: silkscreen declarations are missing`で
fail-closedし、返る`next_step_action`は「graphを調整して再実行せよ」であって、
specへ何を追記すればよいかを示さない。宣言の受け口自体は
`DesignFixtureSpec.silk_texts`／`silk_graphics`として存在し、必要属性も
`lane_preflight`の`LANE_REQUIREMENTS["silkscreen-resolve"]`に宣言済みだが、loopはこの
preflightを実行しないため、不足は実行の途中でしか判明しない。ゲートは正しく閉じており、
緩和ではなく不足宣言の提示で解くフェーズである。

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | `src/acd/core/silkscreen.py`の`GraphExtractionError`、`src/acd/core/lane_preflight.py`の`LANE_REQUIREMENTS`と`run_lane_preflight`、`src/acd/pipeline/fixture_builder.py`の`silk_texts`／`silk_graphics`投影、`scripts/run_design_loop.py`、`src/acd/openhands/workspace.py`の`_execute_and_download()`、`src/acd/core/runtime_records.py`の`TimingRecorder`、`scripts/verify_acd_tool_registration.py`、`plugins/acd/commands/vibebb-loop.md`、`plugins/acd/hooks`、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のV節、[`examples/golden-design-1-vps-20260901/report/improvement-notes.md`](../examples/golden-design-1-vps-20260901/report/improvement-notes.md)（同メモのD-1〜D-4はV-7〜V-10と読み替える） |
| 実装 | fixture生成とloop入口で実行予定laneの`run_lane_preflight`を評価し、不足するnode kind・node数・属性名を列挙して`next_step_action`へ「specへ追加すべき宣言」を具体名で返す（V-6）。silkscreen laneでは`mechanical.silk_text`の`layer`／`role`／`text`／`stroke_width_mm`／`height_mm`／`placement_basis`／`placement_search_order`／`placement_reference`を名指しする。宣言の自動補完は行わない。containerからhostへEDA資材を取り出す操作をhookで拒否するか、host実行時にcontainer由来資材の混在を検出してprovisional扱いを記録する（V-1）。commandの報告契約へauthoritative Evidence検証の実行と結果提示を必須項目として書き、`report_progress.py`のdigestへEvidence未検証を明示する行を持たせる（V-3）。`_execute_and_download()`が非ゼロ終了時も宣言済みdownloadを試み、判定はcontainerのexit codeで維持する（V-5）。timing recordへstage duration合計と区別できる`wall_clock_seconds`を持たせる（V-7）。`verify_acd_tool_registration.py --command`の結果を機械可読JSONとしてworkspaceへ保存する（V-9） |
| 正常系 | silkscreen宣言を備えた新規specが、fixture生成からsilkscreen barrierを越えて基板laneへ到達する。宣言が欠けたspecは実行前に`declarations_incomplete`で停止し、不足宣言名と追記先を返す。fail-closedで終わったcontainer実行からも成果物を回収でき、runnerのexit codeは非ゼロのままである。GD1の判定、Evidence、正規化hashは変化しない |
| negative・fail-closed | 不足宣言の列挙、進行表示、tool登録記録はいずれもL3観測であり合格側権限を持たない。preflightの`declarations_complete`はlane通過を意味しない。downloadの成功をcommand成功として扱わず、部分downloadを合格へ倒さない。container由来資材が混在したhost実行のEvidenceをauthoritativeへ昇格しない。宣言の自動補完、既定値の暗黙適用、閾値・ゲート条件の緩和は行わない |
| 再現性 | preflight結果、不足宣言名、download結果、wall-clockとstage duration合計、tool登録差分をL3記録として保存し、同一入力での再実行で一致することを回帰テストで固定する。fail-closed runからの成果物回収を、tarとexit 0による回避策なしで再現する |

実装状況: V-6（`lane-preflight` stageと`fixture-generation`のpreflight診断、
`missing_declarations`と`next_step_action`）、V-7（`wall_clock_seconds`と
`stage_duration_sum_seconds`の分離）、V-5（非ゼロ終了時のdownload試行と`download_errors`、
exit code維持）、V-9（`out/tool-availability/<command名>.json`）、V-3（commandの報告契約と
digestの`authoritative_evidence: unverified`）は達成した。詳細は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のV節の実装状況を正とする。V-1は未着手である。

V-6は新規設計入口の唯一の停止点であり最優先で扱う。V-3とV-9は、会話経路がL3記録だけで
合格を述べないための報告契約と一次資料であり同順で扱う。V-5とV-7は検証可能性、
V-1は防御の深さである。V-2（GUIのplugin picker）はOpenHands側の課題であり、本リポジトリの
実装対象外として記録だけを残す。V-4、V-8、V-10は運用・手順の整備として15.17〜15.19で扱う。

### 14.20 元phase table行

| 14.20 | Devin不在で新規設計を1周させるための残関門（V-1、V-3、V-5〜V-7、V-9） | V-1、V-3、V-5、V-6、V-7、V-9を達成。第6回実機実測で残った不足を扱う。新規specの宣言不足をfixture生成段で列挙して具体名で返す（V-6）、container由来資材のhost混入検出（V-1）、L3記録だけで合格を述べさせない報告契約（V-3）、失敗時も判定を変えずに成果物を回収できるdownload経路（V-5）、timing recordへのwall-clock明示（V-7）、宣言tool不在の機械可読記録（V-9） |

### 14.23 14.22反映後の同一要件再検証（第9回）で残った関門（Z-*）の実装記録

背景と観測は[`roadmap.md`](roadmap.md)の14.23節、各項目の詳細は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のZ節を正とする。

| 区分 | 内容 |
|---|---|
| 実装 | source provenanceの`ACD_SOURCE_GIT_SHA`をbootstrap record／installed plugin revision／`--source-revision`と照合し不一致をfail-closedにする（Z-3）。`run_in_workspace.py`の既定downloadを既定command・`--graph`明示時に限定し、任意commandでは`--download`指定分だけを扱う（Z-5）。hookが`acd-server`／`acd-tools` imageの生`docker run`／`docker exec`起動を拒否しrunner経由を案内する（Z-11）。coverage診断の会話向けnext stepから source表名を外し設計入力側の次手だけを示す（Z-2）。deny理由へ判定種別と該当tokenを付ける（Z-4）。inline codeの動的実行token（`exec(`・`eval(`・`base64.b64decode(`等）を拒否し（Z-6）、wrapper command越しの内側commandを同じ規則で再帰評価する（Z-7）。`init.md`の起動例とtimeout手順（Z-1）、最終報告のsource変更節を`git log <bootstrap>..HEAD --stat`の機械出力に固定（Z-8）、宣言側evidence属性の実測record解決検査（Z-9）、`lane-preflight`へmechanical preflight述語の取り込み（Z-10）、SessionStart hookのlock探索（Z-12）。`design_loop.py --fixture-spec`の`spec_dir`伝播（Z-13）は本変更で解消済み |

### 14.24 14.23反映後の同一要件再検証（第10回）で残った関門（AA-*）の実装記録

背景と観測は[`roadmap.md`](roadmap.md)の14.24節、各項目の詳細は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のAA節を正とする。
14.24の進捗は33件達成、未了0件である。

| 区分 | 内容 |
|---|---|
| 実装 | `--allow-dirty`の許容範囲を設計入力path（`fixtures/`・`evidence/`・`out/`）に限り、`src/`・`contracts/`・`scripts/`・`plugins/`のdirtyはfail-closedのまま（AA-5）。graphの`parts_catalog_sha256`・registry hashをcheckout上の契約と照合し不一致を`contract.hash_mismatch`で止める（AA-8）。`vibebb-loop.md`でbootstrap recordの所在確認を必須にし、stop policyがrecord不在を`bootstrap_record_missing`として停止報告へ載せる（AA-3）。`PartSelectionError`へ要求内容と次手を含める（AA-4）。未知functional blockの診断へ登録名一覧を添え、要件文書がLED・I2C pull-upを含むのにblock未宣言なら`requirement.block_missing`で止める（AA-6）。firmware pin roleをgraphのI2C接続から導出する宣言経路（AA-7）。`estimated` evidenceの他fixture転記をL3警告で列挙（AA-9）。報告契約でworktree各entryへ変更actionの引用を必須にする（AA-10）。SessionStart hookがworkspace registryのlockを探索（AA-2）。W-1 fixtureの宣言を実測へ揃える（AA-1、別PR）。修正後run（[`examples/dual-beacon-tag-vps-20260908/fixed-run/`](../examples/dual-beacon-tag-vps-20260908/fixed-run/README.md)、AA-11〜AA-14の実測根拠）で観測した宣言〜出力の乖離も同フェーズで扱う: `_copper_zone`が`min_island_area`をemitせず宣言値が充填後検証専用である点を区別する（AA-11）。CPL basis段でrecordの`Manufacturer Part`／packageと宣言`mpn`の整合を検査する（AA-12）。`part_request`無し部品へも`cpl_rotation_evidence_revision`を補完または欠如属性を診断へ示す（AA-13）。silkscreen resolverが`measured_pass`でも未配置テキストの配置探索を行う（AA-14）。修正後runでDevinが人手で越えた境界（17.12、AA-15〜AA-22）も同フェーズで扱う: CPL rotation診断へ宣言／有効／実測offsetとbasisを併記（AA-15）、LCSC番号無し部品の`FabOutputError`へ`not_fitted`の次手（AA-16）、`vibebb-loop.md`でgraph直接編集を禁止しspec→`--fixture-spec --fixture-overwrite`再生成を必須化（AA-17）、DFM pad-to-edge診断へ最小移動量（AA-18）、GND島・DRC診断へ囲みfootprintと候補レバーを列挙し`acd-placement-search`へ島解消手順（AA-19）、silkscreen診断へ短縮／探索範囲の次手（AA-20）、catalog entry追加の宣言経路とcontainer内hash算出（AA-21）、宣言直後のLCSC record取得とmpn照合手順（AA-22）。投影段の直後にwriterと独立したreader（SMF parser、STEP header/footer、3MF zip CRC・model XML、RS-274X／Excellon終端）による形式検査を置き、結果を`hashes.json`の各entryへ`format_check`として記録、parse失敗はその投影を欠落としてfail-closedにする（AA-23。利用者報告の`theme-song.mid`破損は修正後runの全投影を事後検査して再現せず、生成物側から判別できない点を閉じる）。acd-agentが持つ投影のうちloopが呼ばない3種（`acd-product-docs`の製品説明README・取扱説明書、`verify_manufacturing_submission.py`の製造提出verdict、`derive_png_visual_projections`のPNG raster）を`run_design_loop.py`の投影段へ組み込み、3 lane完了後に同一out root配下（`docs/`・`manufacturing-submission.json`・`visual/png/`）へ生成して`hashes.json`とloop-summaryへ登録する（AA-24。`--design-only`でも実行し、order lane入力は要求しない。PNG rasterは`visual-review-manifest`段として実装済みで、エージェントによるmanifest全entryの`inspect_image_with_vision`検査と`verify_visual_review.py`のfail-closed検証を必須化した。文書laneと製造提出verdictのloop組み込みは未実装のまま残る）。`generate_instruction_manual.py`がGD1固有のmacro集合（`ACD_PIN_UART_*`・`ACD_PIN_USB_*`・`ACD_SHT40_I2C_ADDRESS`・`ACD_LOG_PERIOD_MS`）を必須とする点を、graphのfirmware capability・pin role宣言から必要節を導出する構成へ改め、宣言に無い節は書かずに省略理由を文書へ記す（AA-25。推定値は書かず、宣言もmacroも無い項目はfail-closedのまま）。theme-songの投影にMML（Music Macro Language、テキスト楽譜）を追加し、`render_midi`と同じ`Score`（tempo・拍子・track別note/rest・drum）から`theme-song.mml`を決定論的にrenderして`theme-song.mid`と並べて`hashes.json`・provenance（同一proposal hash）へ登録する。MMLはtrack別channel・`t`（tempo）・`o`/`l`/音長・`r`（rest）・タイの表記を持つ方言を1つ固定し、MML→note列の独立parserで再読込してMIDIのnote数・総tick・pitch列と一致することを検査する（AA-26。不一致はMML投影をfail-closedで欠落にし、MIDI側の合否や3 lane判定へ作用させない。Evidence・fab packageには含めない）。実機regen run（2026-09-09、[`examples/dual-beacon-tag-vps-20260908/regen-run/`](../examples/dual-beacon-tag-vps-20260908/regen-run/README.md)）で判明した視覚レビュー契約の穴と人間向け投影の残課題（AA-27〜AA-33）も同フェーズで扱う: Local GUI会話に`VisionInspectTool`が無い場合は`visual-review-manifest`直後に`vision_tool_unavailable`でfail-closedにし、GUI会話へvision toolを届ける登録経路を用意する（AA-27）。observation recordへvision toolのObservationEvent idと応答hashを必須にし、会話event logと照合できない記録を`unverified`として`verify_visual_review.py`がfail-closedにする。file_editorによる`visual-observations/`直接書き込みは`write_target`拒否へ加える（AA-28。observationはL3のままで合否に作用しない）。KiCad回路図の用紙選択を配置後の実extentに基づかせ、net labelの衝突を検査する（AA-29）。CAD SVGへ題名・断面位置・寸法・基板断面・干渉体強調（無ければ注記）を付ける（AA-30）。placementへ取付穴・keepout・外形外はみ出し注記（AA-31）。KiCad層SVGのtitle・層名・寸法包み、sequence lifelineのrefdes＋value、state遷移線のy段分離、power-treeの電圧降順（AA-32）。最終報告のEvidence表4列を`verify_authoritative_evidence.py`の機械出力から引用させる（AA-33） |
実装状況（AA-23）: `projection-format-check.json`をL3 recordとして生成し、既存のflatな`hashes.json`を維持したまま形式検査record自体をhash manifestへ登録する。ThemeSongProjectionへ形式検査fieldは追加せず、MIDIのSMF検査はpipeline内でfail-closedに実行する。

実装状況（AA-22・AA-12）: LCSC fetch scriptへ`--expect-mpn`／`--expect-package`とidentity・照合結果を追加し、宣言直後に取得recordの`Manufacturer Part`・package・Supplier Partを確認できるようにした。confirmed CPL recordの内容不一致は`evidence.cpl_rotation.mpn_mismatch`としてlane preflightの停止側へ渡し、catalog-less partsの探索はL2の宣言＋取得recordとして残す。

実装状況（AA-24）: `run_design_loop`へ`projection-docs`と
`manufacturing-submission`を追加し、`--design-only`でも3 lane後に
`out/docs/`（README、取扱説明書、provenance、flatな`hashes.json`）と
`out/manufacturing-submission.json`（`require_authoritative=false`のhost
provisional verdict）を生成する。PNG rasterは既存の
`visual-review-manifest`段で生成済みであり、文書とverdictはいずれもL3観測で
authoritative EvidenceやL1判定を置き換えない。

実装状況（AA-25）: `generate_instruction_manual.py`の必須macroを
`ACD_TARGET_REVISION`だけにし、firmware action、pin assignment、
`mechanical.connector_opening`のgraph宣言から取扱説明書の節を決定論的に導出する。
宣言済みの機能に対応するmacroがpin projectionに無い場合は矛盾としてfail-closedにし、
graphに無い機能・経路は推定せず、文書末の`省略した項目`へ日本語の理由を記録する。
GD1実headerとDBT graph、複数connector、LED2、button操作、revision mismatch、
macro欠落、byte一致を回帰テストで固定した。旧`instruction-manual.fail-closed.log`は
当時の観測記録として保持する。

実装状況（AA-26）: `acd-theme-song`が同一`Score`から`theme-song.mml`を生成し、
`acd-mml 0.1`の独立parserでtempo・voice総tick・note列を照合する。照合不一致時は
MMLだけを省略し、`mml_check`へ理由を記録する。MMLはprovenanceと`hashes.json`へ
登録するが、MIDI、3 laneのgate、Evidence、fab packageの判定は変更しない。

実装状況（AA-27）: SessionStart hookがSDKの`OH_PERSISTENCE_DIR/profiles`（既定は
`~/.openhands/profiles`）を標準libraryだけで読み、保存済みLLM profileの件数と
modelを追加contextへ報告する。visual reviewで`inspect_image_with_vision`が無い
場合は代替画像読み取りを禁止し、`vision_tool_unavailable`とprofile登録・会話再起動を
次手にしたfail-closed stopとする。

実装状況（AA-28）: `inspect_image_with_vision`のPostToolUse hookが応答hash・profile・
modelを含むevent logをhook専用経路で記録し、observationはeventへ一度だけbindする。
eventの欠落・改変・不一致は`unverified`としてvisual reviewをfail-closedにし、
observationとevent logの直接書き込みを拒否する。observationとverdictはL3のままで、
合否やEvidenceへ作用させない。

実装状況（AA-30）: build123dのraw ExportSVGを`svg#cad-view`へbyte-exactに埋め込んだacd-svg文書として出力し、
title、断面位置、寸法、基板外形、legend、干渉領域またはゲート測定注記を付与する。
ネストしたviewBoxと注釈IDを決定論的にcrosscheckし、recordのゲート値やEvidence authorityは変更しない。
実装状況（AA-31）: placement SVGへ取付穴、keepout、部品の外形外はみ出し注記を決定論的に描画し、
宣言済みと未宣言の注記を区別する。これらの注記はL3観測であり、ゲート判定を変更しない。
アンテナ部が板端外へ出て板上の深さが0となるアンテナkeepoutは、板上矩形が存在しないため
placement SVGの描画対象にもGerber検証のkeepout宣言必須条件にも含めない。

実装状況（AA-29）: KiCad回路図の列・行ピッチをsymbol extentとnet labelから決定し、
Reference/Valueをbody外へ配置する。labelとproperty・bodyの衝突は一度だけ外側へ
解消し、残る衝突をfail-closedで拒否し、用紙を実extentから選択する。

実装状況（AA-2）: init workspaceがbootstrap record生成後にworkspace registryへ登録し、
SessionStart hookが登録済みworkspaceのlockを新しい順に探索して解決pathをcontextへ記載する。
registryはL3 discovery aidであり、書き込み・読み取り失敗でもbootstrap recordとfail-closed
探索の権限境界を維持する。

実装状況（AA-9）: estimated CPL rotation evidenceについて、他fixture名への言及と
他fixtureの`at/method/note`三つ組の一致を`evidence.cpl_rotation.structural_copy`の
L3 warningとしてlane preflightへ列挙する。warningは停止statusへ影響せず、estimatedの
不確実性と既存のCPL gate authorityを維持する。

実装状況（AA-10）: file_editor／apply_patch／terminalのPostToolUse hookが変更actionを
`file-change-events.jsonl`へ記録し、最終報告basisがworktree entryごとの時刻・tool・action
とterminal actionを引用可能な表として出力する。

実装状況（AA-33）: `verify_authoritative_evidence.py`がstatus・target revision・container
image digest・source revisionのcitation行と任意のJSON recordを出力し、欠落値をJSON pointer
付きで明示する。既存のauthoritative判定は変更しない。

実装状況（AA-13）: `part_request`無しのcomponentにもCPL orientation evidenceを
`cpl_rotation_*`へ投影し、`<graph_id>-<revision>`のevidence revisionを付与する。
assemblyのunknown rotation reportには欠落・不正属性名を診断として記録する。

実装状況（AA-11）: `_copper_zone`はKiCad zone fillへ`island_removal_mode 0`を出力し、
孤立島を常に除去する。`island_area_min`は出力しない。`island_removal_mode 2`が保持する島は
GND接続点を持たない浮き銅として`NonConductor`で出力され、Gerber gateがfail-closedで拒否する
ため採用しない。宣言値`ground_plane_min_island_area_mm2`は塗り後Gerber検証の最小面積として残し、
Gerber gateの判定は緩めない。

実装状況（AA-14）: silkscreen resolverは`measured_pass`後も未配置textを検出し、
node IDと強制探索をiterationへ記録してSkillへ戻す。探索上限と未解決時のfail-closedは維持する。

### 14.25 routed board上のsilkscreen再解決の実装記録

背景と観測は[`roadmap.md`](roadmap.md)の14.25節を正とする。

| 区分 | 内容 |
|---|---|
| 実装 | `SilkscreenGateError`へ`__reduce__`を追加し、`ProcessPoolExecutor`経由のpickleでも`message`と`context`が保持されるようにした。`measure_silkscreen`へ`routed_board`引数を追加し、routed `.kicad_pcb`指定時は`write_project`を呼ばず同じ5層をkicad-cliでexportし、`parse_routed_board`のviaとmask開口を保持したままdrill項目だけを従来どおり0化する（`measurement_source: "routed"`）。`reresolve_routed_silkscreen`を`ROUTED_SILKSCREEN_MAX_ROUNDS = 1`の宣言上限で実装し、recordを`routed-silkscreen-reresolve.json`へ`record_class: "L3"`・`pass_evidence: false`で書く。入力hash（routed board・Skill・graph revision・fab profile）が一致するrecordがある場合はcache hitとしてgerber exportとSkill subprocessを省略し、記録済み候補を同じapply経路で冪等に再適用する。`resolve_silkscreen`本体は`_run_placement_skill`・`_split_candidates`・`_apply_accepted_candidates`へ分解し、出力とstatus文字列は変更しない。design loopのboard段は`SilkscreenGateError`を捕捉して再解決を1回行い、`candidates_written`の場合だけpipelineを1回再評価する。再解決の失敗・候補なし・再評価のゲート拒否はいずれもfail-closedで停止する。合否権限は既存のrouted silkscreen L1ゲートに留まる |

### 15.17 例示commandとfixture有効期間の整合検査（V-4）の実装記録

`docs/operations.md`のGD1発注集計例7件について、`--evaluated-at`を
`2025-01-14T00:00:00Z`へ揃え、`fixtures/contracts/valid/quote-order-golden-design-1.json`
の`fetched_at`（2025-01-10）から`valid_until`（2025-01-17）までの範囲内にした。
`scripts/verify_docs.py`へbash fence内の`--evaluated-at`と`--quote-record`を読み取り、
明示quoteまたはGD1既定quoteの`fetched_at <= evaluated_at <= valid_until`を検査する
`check_evaluated_at`を追加した。欠落・不在・不正なtimestamp・期限外はfail-closedで停止する。
quote検証コード、期限、ゲート閾値、Evidence意味論は変更していない。

### 14.16 R-2 配置テストの環境非依存化の実装記録

`tests/core/test_decoupling_placement.py`は従来、GD1が参照する
`/usr/share/kicad/footprints/`の存在を前提にmodule全体をskipしていた。
固定fixture `fixtures/decoupling-placement-minimal/`（`graph.json`、
`footprints/C_0603.kicad_mod`、`footprints/REG_SOT223.kicad_mod`、
`symbols/minimal.kicad_sym`）を追加し、既存6テストを同fixtureへ移植した。
fixtureはpad座標を宣言した最小graphで、pinned library非依存のhostで
`solve_decoupling_placements`の初期解と距離判定を回帰する。

固定値として記録したpad座標と期待距離: C_0603 pad 1 = (-0.775, 0.0)、
pad 2 = (+0.775, 0.0)、REG_SOT223 pad 3 = (2.3, -3.0)。U1を(20.0, 20.0)、
C2を(25.075, 17.0)に配置し、C2 pad 1とU1 pad 3の距離は2.0 mm、
limitは3.0 mm（100 nFの小容量閾値）である。退避ケースは(30.0, 30.0)へ
移動してからsolverが(25.475, 17.0)、距離2.4 mmへ戻すことを確認する。

実libraryを要するGD1 caseはskipで隠さず、`pinned_footprint_library`
marker付きの2テストとして残し、`tests/conftest.py`の
`pytest_runtest_setup`でlibrary不在時にfail-closedとする契約を固定した。
hostではskip、CIの`container-gates` jobでは
`ACD_REQUIRE_PINNED_LIBRARY=1`を付けてdigest固定image内で
`-m pinned_footprint_library`を実行し、library欠落はskipではなく
失敗として検出する。判定・閾値・Evidence意味論は変更していない。

### 14.16 R-1 FW lane専用候補生成の実装記録

`explore_firmware_candidates`は従来`explore_board_candidates`へ委譲しており、
基板側の配置・回転次元の候補がFW復帰へ混入しうる構造だった。
`src/acd/core/firmware_exploration.py`を新設し、FW lane専用の候補生成器へ分離した。

- 探索ループとreport組立は`exploration._run_candidate_search`へ抽出して共用化し、
  `explore_board_candidates`のreportは同一入力でbyte一致を維持する
  （既存テストがガード）。`termination_override`で候補ゼロ時の終端を上書きできる。
- `FIRMWARE_SEARCHABLE_DIMENSIONS = frozenset({"gpio_assignment"})`は
  `contracts/lane-recovery-declaration.json`のFW lane
  `recovery_dimensions`との一致をテストでfail-closedに固定する。
- remediationの要求次元は`gpio_assignment`のみ候補化し、
  `component_placement_xy`等は`excluded_dimensions`へ記録して候補にしない。
  基板側の配置・decoupling生成器は呼ばない。
- `firmware-coverage.json`のfinding（未登録action等）は候補生成ではなく
  `status="stopped"`／`termination_reason="declaration_required"`へ倒し、
  `required_declarations`にcode・node_id・declaration_targetをL3提示する。
  declaration_targetは`contracts/firmware-capability-registry.json`の
  capabilities actions／emits_triggersかgraph.jsonのfirmware属性を指す。
- `load_firmware_coverage_findings`はmissing・malformed・未知codeを
  `ExplorationError`でfail-closedにする。
- `design_loop._run_firmware_exploration`はFW lane却下を
  `gate-evidence/design-predicates.json`（存在時）と`firmware-coverage.json`
  （存在時）から受理し、両方不在ならfail-closedで停止する。
  exploration段recordへ`required_declarations`をL3情報として載せる。
  pass authority・Evidence意味論・閾値は変更していない。

### 15.19 成果物の最小収録集合の実装記録

`contracts/lane-artifact-retention.json`（`acd-lane-artifact-retention-v1`）を
新設し、lane runnerの出力dirを持つ全stage（silkscreen-resolve、
board-pipeline、enclosure-pipeline、firmware-pipeline）ごとに
`minimal_artifacts`（glob＋required＋理由）と`regenerable`を宣言した。
FW laneでは`summary.json`・`evidence-firmware.json`・`firmware-coverage.json`・
`firmware-config-report.json`・`flash.bin`・`qemu-serial.log`・`*_fw/`の
投影入力を最小集合とし、`*_fw/build/**/*`等のESP-IDF buildツリーを
regenerableとして区別した。

- `acd.schema.lane_artifact_retention`で契約をPydantic検証する
  （extra禁止・相対glob限定・`..`拒否・lane_id一意）。
- `acd.core.lane_artifact_retention.resolve_lane_retention`がlane出力dirへ
  決定論的にglobを適用し、matchした相対パス・size・sha256と
  `missing_required`、regenerable件数・総bytesを`LaneRetentionReport`
  （`record_class: "L3"`、`pass_evidence: false`、authority文言付き）として返す。
  未宣言laneや契約読込失敗は`LaneArtifactRetentionError`でfail-closedにする。
- `scripts/run_design_lanes.py`のsummaryへ`artifact_retention`を追加し、
  lane plan宣言順で各laneのreport（出力dir不在は`output_missing`）を載せる。
  契約読込失敗はfailure entry＋`ok: false`とする。
- `scripts/collect_lane_artifacts.py`が最小集合のみを
  `dest/<lane_id>/<relative path>`へcopy2で収集し、
  `retention-manifest.json`（declaration_hash、record_class L3、
  pass_evidence false）を書く。required不足やlane出力不在は
  manifestを残してexit 1とする。
- U-5の必須成果物判定（manufacturing_submission）、ゲート、Evidence規則は
  変更していない。本契約は観測・運用のL3記録である。

### 15.15 doctor出力のauthoritative／provisional分離と次手順提示の実装記録

`plugins/acd/skills/acd-install-doctor/scripts/install_doctor.py`の各checkに
`path`（`authoritative-path`、`provisional-path`、`plugin`）と`next_step`を追加した。
lock済みserver imageを`--no-pull`で取得しない場合、またはpull失敗・timeoutの場合だけ、
実行しない`docker pull <image@digest>`を`next_step`へ記録する。Docker CLI不在や
imageが既に存在する場合にはnext stepを設定しない。

workspace指定時、hostの`IDF_PATH/export.sh`、`qemu-system-riscv32`、`cmake`を
`host firmware toolchain`として`provisional-path`で観測する。欠落は`unavailable`であり、
既存のrequired/optional status集計（`fail`／`unknown`のみ失敗扱い）を変更しない。
container内ではhost toolchain checkを追加しない。

diagnoseのtop-level `paths`は3 pathごとのstatusと宣言順check名をまとめ、
`authority`へprovisional観測がauthoritative pathを代替しない旨を明記した。
既存のcheck集合（workspace追加時のhost観測を除く）、判定閾値、fail-closed範囲、exit code、
Evidence権限は変更していない。SKILLとoperationsへJSON fieldsと運用手順を追記した。

### 15.14 長時間laneのbackground実行手順とlog契約の実装記録

`scripts/run_in_workspace.py --log PATH`が`acd-lane-log 0.1`のplain-text契約で
lane logを書く。headerは実行前にimage参照、revision（`--source-revision`または
bootstrap record、なければ`git rev-parse HEAD`、解決不能は`unknown`）、
コマンド行、`started_at`を記録し、stdout／stderrをそのままfileへteeする。
footerは`finally`で`exit_code`、解決済み`image_digest`（startup・transport失敗と
host provisionalでは`unknown`）、`execution_context`、`failure_kind`（例外の
`failure_kind`または`classify_execution_failure`結果）、`finished_at`を追記する。
`src/acd/core/lane_log.py`の`write_lane_log_header`・`append_lane_log_footer`・
`parse_lane_log`を提供し、`--log`未指定時の挙動は従来どおり。

### 15.16 収集入口へのlane log取り込みの実装記録

`LaneLogRecord.to_execution_record()`が`log_type: lane_log`のrecordを返し、
`scripts/export_execution_records.py`が`.log`入力とdirectory内の`*.log`を
`*.json`と名前順に混在して取り込む。生image参照はexportへ残さずdigestだけを
記録し、allowlistへ`command`・`failure_kind`を追加した。既存のredactionと
leak refusalをそのまま適用し、footer欠落の中断logはexit 2で拒否する。
lane logはL3観測であり、合否権限と既存の判定・閾値は変更しない。
リモートworkspaceからのrsync取得とexport手順を`docs/operations.md`へ記録した。

### 15.18 資源計測ラッパのscript化の実装記録

`scripts/measure_lane_resources.py`をrepository内へ追加し、使い捨てshell scriptによる
資源計測を置き換えた。checkout path（`--repo`）、digest固定image（`--image`）、
download対象（`--download`／`--download-root`）、計測間隔（`--interval`）を引数で受け、
`run_in_workspace.py`をsubprocessでwrapして`--log`・`--memory-limit`・`--jvm-max-heap`を
そのまま転送する。実行中は`/proc/stat`のbusy deltaから使用中CPUコア、`/proc/meminfo`から
memory・swap使用量、`docker stats --no-stream`からcontainer memory合計をintervalごとに
採取し、peak／minをrecordへ記録する。docker stats失敗は`stats_available: false`として
記録を継続し、wrapperのexit codeはwrapped runのexit codeを維持する。
`host_resources._read_meminfo`を`read_meminfo`へ公開名変更し共用した。
recordは`record_class: L3`、`pass_evidence: false`であり合否権限を持たない。

### 15.20 長時間runの予算・stage境界checkpoint・resume契約の実装記録

`run_design_loop`と`DesignLoopConfig`へ`wall_clock_budget_seconds`と`token_budget`を
追加した。wall-clock予算は各stage runner呼び出し直前だけで確認し、超過時はstageを
起動せず`budget_exhausted: true`のfail-closed結果を返す。実行中stageは中断せず、
既存gateの判定と閾値には作用しない。token budgetはこのloopではLLM tokenを計数しない
宣言値であり、OpenHands conversationのL2 stop側がenforcementを担う。

各stage完了後、`out_root/design-loop-checkpoint.json`をL3／`pass_evidence: false`で
更新する。stage順、ok、fail_closed、timing name、budget、elapsed、resume、cache dirを
記録し、書き込み失敗はstageの`checkpoint_error`へ記録する。checkpointは人間と
`report_progress`向けで、resumeはcheckpointを参照せず、StageArtifactCacheだけを再利用
してgate stageを再実行する。

### 14.14 O-12残項 `OrderScope`の決定論的導出の実装記録

`OrderScope`を`src/acd/core/order_scope_derivation.py`の`derive_order_scope()`で
設計fixtureから決定論的に導出する。graphの`fab.order_intent`ノードから
fab profile IDを取得してregistry存在を検査し、`rationale.json`のrevisionを
target revisionとし、`mechanical.enclosure`ノードの有無からmechanical treatmentと
必須categoryを決める。設計が保持しない発注条件（通貨、minor unit digits、
shipping／tax treatment、exclusion理由、supplier上書き）は新規schema
`OrderTermsDeclaration`（fixtureの`order-terms.json`）へ宣言する。enclosureが無い
設計で理由未宣言、不明fab profile、欠落入力は`OrderScopeDerivationError`で
fail-closedに停止する。`scripts/derive_order_scope.py`が`order-scope.json`と
`quote-request.json`を出力し、GD1では既存contract fixtureとフィールド完全一致を
回帰testで固定した。`QuoteRecord`はsupplier実見積の金額を要するため合成せず、
L3の`quote-request.json`が`fetch_quote.py`への次段を宣言する。design loopへの
配線は行わず、`--order-scope`明示入力を維持する。

### 9.6 機器I/F契約投影の実装記録

`plugins/acd/skills/acd-product-docs/scripts/generate_interface_spec.py`が
design graph、`acd_pins.h`、`firmware-config-report.json`から機器I/F契約を
決定論的に投影し、`interface-spec.md`（template `acd-interface-spec-ja-v1`）と
`interface-spec.json`（`record_class: "L3"`、`pass_evidence: false`）を
それぞれ`write_document`経由で生成する。graph ID・revision・pin・I2Cアドレスの
3入力不一致、I2Cアドレス重複、report欠落・不正は`DocumentGenerationError`で
fail-closedに停止し、UART transportとコマンド一覧は宣言が無いため
`unknown_fields`へ記録する。`run_projection_docs`はfirmware出力から
`firmware-config-report.json`を一意に特定して本scriptを実行し、
`interface_spec`／`interface_spec_json`の両documentをprovenance付きで要求する。
JSON本体にtimestampを含めず2回実行でbyte一致を回帰testで固定した。

### 9.3 品質文書生成の実装記録

`plugins/acd/skills/acd-product-docs/scripts/generate_quality_report.py`が
3 laneのauthoritative Evidence、board・enclosureのrationale coverage、
design-predicates観測、DFM report、fixture rationaleを入力に、検査成績書
（`inspection-report.md`、template `acd-quality-report-ja-v1`）、
トレーサビリティ報告書（`traceability-report.md`）、機械可読な
`quality-report.json`（`record_class: "L3"`、`pass_evidence: false`）を
`write_document`経由で生成する。必須lane Evidenceの欠落、status `valid`
以外、`supports_authoritative_pass`を満たさないprovisional／host Evidence、
coverage・rationale・predicates・DFMのgraph ID／revision不一致、graphに無い
`subject_node`・`driving_requirements`参照は`DocumentGenerationError`で
fail-closedに停止する。`run_projection_docs`は`enclosure_out`を新規入力として
受け、3 laneのEvidenceと2つのcoverage等を決定論的に特定して本scriptを
4番目のgeneratorとして実行し、`inspection_report`・`traceability_report`・
`quality_report_json`をprovenance付きで要求する。

### 21.1〜21.8 構想ブラッシュアップと分野横断の責務割当の実装記録

`ADR-0049`がアイデアrecordと責務割当のcontract境界を定義する。21.1・21.3は
`src/acd/schema/idea.py`（`IdeaRecord`・`IdeaDialogueHistory`・`IdeaProgress`）と
`src/acd/core/idea_dialogue.py`（`apply_turn`／`progress_summary`）、
`scripts/idea_progress.py`を追加した（PR #448）。21.2・21.4・21.5は
`acd-ideate` Skill（question bank付き）、`src/acd/schema/idea_estimate.py`・
`idea_promotion.py`・`idea_question_bank.py`、`estimate_idea`（stop／risk／within／
not_comparableの範囲比較）と`promote_idea`（open残存でfail-closed、確定ごとに
rationale record必須）、4本のCLIを追加した（PR #450）。21.6・21.7は
`design.responsibility` node kind（`domain`をrationale必須属性、
`function_id`・`criteria`を免除属性として分類）、`responsibility_assignment`
decision kind、`src/acd/schema/responsibility.py`の宣言contract、
`check_responsibility`決定論的gate（11種のfinding codeでfail-closed）、
`scripts/check_responsibility_assignment.py`を追加した（PR #452）。gateは
gate evidenceのみを生成し、authoritative Evidenceは生成しない。

### 13.1 不具合record契約と水平展開検査の実装記録

`src/acd/schema/defect_record.py`へ、不具合の症状、再現条件、発生率、影響機能、
影響個体範囲、根本原因候補、5基準（同一部品MPN・同一node kind・同一rule・
同一fixture・同一profile）の水平展開宣言を追加した。unknown、未探索、重複ID、
水平基準の欠落はPydantic contractでfail-closedに停止する。

`src/acd/core/defect_records.py`の`compute_horizontal_scope`は、identifiedな根本原因
候補のnodeをアンカーとしてgraphを機械的に検索し、node ID順の結果を返す。
`same_rule`は`rule_ids`／`applied_rules`属性だけを検索し、属性が無いgraphでは
「探索済み・該当なし」とする。`check_defect_records`はgraph ID・revision、未知node、
unknown根本原因、未探索・不足・余分な水平展開、unknown個体範囲を検査し、
findingの無いrecordだけを`workaround_eligible`へ分類する。結果はgate evidenceであり、
authoritative Evidenceや合否権限を生成しない。

`scripts/check_defect_record.py`は`defect-record-check.json`と
`gate-evidence/defect-record.json`を生成する。`fixtures/defect/sample/defects.json`を
GD1 graphへ照合し、全5基準をsearchedとして機械的に列挙する正常系と、schema・core・
CLIのnegative testを追加した。未探索、unknown、未知node、水平展開不一致、
revision不一致は停止側へ分類される。

### 13.2 追加工差分contractと派生graph導出の実装記録

`src/acd/schema/rework_diff.py`へ、`cut`・`add`・`remove`・`replace`・
`mechanical`の判別可能な追加工差分contractを追加した。workaround ID、対象graphと
base revision、関連する不具合record、空でない操作列、safety boundary影響宣言を
型付きで保持し、replace属性の許可集合と追加node kindをcontractで制限する。

`src/acd/core/rework_diff.py`の`apply_rework_diff`は、入力graphを変更せず宣言順に
操作を適用し、pin切断、node追加、component除去、部品属性変更、機械寸法変更を
fail-closedに検査する。未知参照、重複追加、dangling dependency、既存値と同じreplace、
未宣言のsafety boundary接触、base graphとのgraph ID／revision不一致は停止する。
結果は`rN+WA-NNN`形式（base revisionにworkaround IDを付加し、派生値を再度baseに
しない）の派生revisionを持つL3投影として扱い、
`derived-graph.json`とhash付きprovenanceを別出力へ書き込む。

`scripts/derive_rework_graph.py`はGD1の`fixtures/rework/sample/rework.json`を
決定論的に適用し、派生graphとprovenanceの出力概要を表示する。base graphの親
directory内への書き戻しは禁止し、schema・core・CLI・決定論性・安全境界のnegative
testを追加した。派生graphは設計入力やfixtureを上書きせず、既存gateの再実行へ渡す
観測投影に限定する。

### 13.3 救済可能性ゲートの実装記録

`src/acd/schema/rework_diff.py`へFW修正だけのワークアラウンドを表す
`FirmwareChange`、`firmware_changes`、`degraded_functions`を追加した。操作が空でも
FW変更があれば派生graphを導出でき、完全に空の差分、重複ID、縮退機能との不整合は
fail-closedに停止する。

`src/acd/schema/salvage.py`と`src/acd/core/salvage_gate.py`は、派生graph上の
電気lane抽出、設計述語、機械preflight、revision一致を要求するERC／DRC Evidence、
DFA、safety approvalを決定論的に評価する。欠落・unknown・revision不一致・実施不能な
DFAは救済不可とし、FW機能の縮退・無効化を伴う場合は`constrained_salvage`として
記録する。制約付き救済は合格を意味せず、CLIのgate Evidenceも`fail`となる。

`scripts/check_salvageability.py`は派生graph、provenance、salvage gate結果、観測用gate
Evidenceを出力する。GD1の追加工サンプルとFW-onlyサンプル、DFA・承認・ERC／DRC
Evidenceをfixturesへ追加し、schema・core・CLIの正常系とfail-closed回帰を固定した。
派生graphで属性を置換するとrationale coverageが失敗するため、正常系fixtureは
rationale coverageを壊さない`jlcpcb_class`置換を使い、`fixture-dir`側のrationaleも
派生revisionへ更新して再実行する契約を維持した。`rationale_refs`は追加していない。

### 13.4 ワークアラウンドSkillの実装記録

`acd-workaround` Skillは13.1の不具合recordをfreshに検査し、identified root-cause
anchorから`firmware_only`・`rework_only`・`combined`の候補を決定論的に立案する。
適用不能な戦略も`not_applicable`として候補setへ残し、候補templateの
`WA-000`、graph、revision、anchor、strategyを契約検査する。候補setと評価は
L2／`pass_evidence=false`であり、合否権限を持たない。

agentはcandidate setにあるtemplateだけを完成し、anchorを発明できない。
`check_workaround.py`は完成diffとDFA、approval、revision一致Evidenceを検査した後、
既存の`evaluate_salvage()`と`write_derived_graph()`を呼び出す。結果JSONは観測として
報告し、`salvageable`だけを終了code 0、`constrained_salvage`を合格ではない終了code
1として扱う。graph・defects・script hashとACD versionをprovenanceへ記録する。

21.8は`plugins/acd/skills/acd-product-docs/scripts/generate_idea_allocation_docs.py`
を追加した。graph、アイデアrecord、見積catalog、責務割当宣言から
`idea-record.md`・`rough-estimate.md`／`.json`（`IdeaRoughEstimate`本体）・
`responsibility-allocation.md`／`.json`（`ResponsibilityGateResult`本体）・
`cross-domain-block-diagram.svg`の6 documentを`write_document`経由で生成する。
対話履歴（`idea-dialogue.json`）は内部資産として読まず、出力へ混入しないことを
testで固定した。宣言のgraph ID／revision不一致、idea recordに無いfunction idの
参照は`DocumentGenerationError`でfail-closedに停止する。gate失敗時も文書は
観測として描画し、statusを冒頭へ明示する。`run_projection_docs`はfixtureの
`idea/idea.json`・`idea/estimate-catalog.json`・`responsibility.json`を探索し、
3つ揃った場合のみ本generatorを5番目に実行して6種をprovenance付きで要求する。
一部だけ存在する場合は欠落pathを列挙してfail-closedに停止し、無い場合は
`idea_allocation_docs: "not_declared"`をstage summaryへ記録する。

### 13.5 作業指示書・検査手順生成の実装記録

`acd-product-docs` Skillへ`generate_work_instruction.py`を追加し、13.1の不具合記録、
13.2のrework差分、13.3のDFA・救済gate結果・派生graphをfail-closedに検証する。
対象個体、交換部品、DFA評価、宣言順の作業手順、firmware変更、graph-diff SVGを
`work-instruction.md`／`work-instruction.json`とprovenanceへ記録する。検査項目は
18.4の出荷検査builderを派生graphへ再利用し、変更対象と電源項目だけを残す。
firmware投影がbase revisionの場合はunknownとして理由を記録し、制約付き救済では
全機能を復元しない旨を明示する。文書はL3観測であり、承認権限を持たない。

### 13.6 個体トレーサビリティとWA廃止条件の実装記録

`WorkaroundLedger`、個体単位の適用record、作業後検査状態、廃棄・解決revisionへの
更新recordを追加した。ロットとシリアルを区別し、シリアルが列挙された場合にロット
recordで代替しないこと、未検証・失敗・未適用個体をopenとして残すことをschemaと
決定論的gateで固定した。

`check_workaround_retirement.py`は、13.1の不具合範囲、13.2のrework、ECO record、
closableな`eco-check.json`のsha256、解決graph、個体台帳を照合する。ECOが同じ不具合を
理由として覆い、すべての対象個体が検証済み適用または妥当な廃棄・解決revision更新で
閉じている場合だけ`retired`とする。unknown scope、欠落・破損・revision不一致・
sha256不一致・誤った更新revisionはfail-closedで停止する。

### 18.1 ブリングアップ試験計画の生成の実装記録

`acd-product-docs` Skillへ`generate_bringup_plan.py`を追加し、18.4の出荷検査
contractを同じ知識源として、無通電、電源投入、書込み・起動、周辺機能、自己検査の
順に実機チェックリストへ再投影する。数値基準は`MeasuredQuantity`へ転記できる
`MeasurementTemplate`として出力し、計測器、probe point、失敗時停止、出荷検査項目の
sourceを記録する。入力current limitがgraphに無い場合は値を推測せずunknownとし、
feedback policyの未被覆ruleも明示する。

`bringup-test-plan.md`／`.json`とprovenanceをja/enで生成し、任意の18.5検査sequence
とfeedback policyのgraph・revision一致をfail-closedで検証する。projection-docs stage
からも出力し、計画はL3観測として実機PhysicalEvidenceの代用にはしない。

### 18.4 出荷検査文書生成SKILLの実装記録

`acd-product-docs` Skillへ`generate_shipping_inspection.py`を追加し、graph、
`acd_pins.h`、firmware config reportから外観、導通、電源、書込み・起動、LED、
センサ、シリアルの7カテゴリを決定論的に導出するようにした。期待値と閾値は
graph属性、gate threshold、firmware projectionのいずれかを出所として記録し、
出所を持たない項目は`unknown`として人手決定を要求する。出力はL3観測であり、
出荷承認のauthoritative Evidenceには昇格しない。

出荷検査契約を`acd.schema.shipping_inspection`へ追加し、未知基準、item ID、
manual decision、unknown count、L3属性を検証する。既存interface specの
firmware config report loaderとrevision／pin／device guardは共有入力モジュールへ
移動し、interface specのfail-closed挙動を維持した。日本語・英語のsemantic template、
Markdown／JSONと`write_document`によるprovenanceを生成し、`projection_docs`から
interface specと同じ入力で両言語を実行してhash登録する。

### 18.5 出荷検査モード付きFW開発機能の実装記録

`firmware.module`へ任意の`inspection_entry_command`を追加し、宣言された場合だけ
FW Skillがgraph・lane pin・capability plan・解決済みdeviceから検査sequenceを導出する。
sequenceはLED、I2C probe、serial echoを決定論的に記録し、graphに自己測定sourceが無い
電源検査はunknownとして保持する。UART commandの明示入力なしでは開始せず、QEMUの
virtual logへ検査開始行が自動出力されないことも検査する。

生成FWは`acd_inspection.c/.h`、UART polling、CMake登録、sequence JSON、設定reportの
commandとhashを出力する。18.4の出荷検査generatorはsequenceを任意入力として受け、
self-test項目・entry command・sequenceのsourceをja/en文書へ追加する。検査出力はL3
観測であり、実機測定EvidenceやL1 gateへ昇格しない。GD1既存graphはinspection modeを
有効化せず、opt-in境界を維持する。
