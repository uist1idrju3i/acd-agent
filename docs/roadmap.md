# 実装ロードマップ

> ステータス: 現行実装と近い順の計画

## 現在地

OpenHands plugin、8 Skill、5 AgentDefinition、`/acd:gates`、SDK ToolDefinition、
GD1基板・筐体pipelineを提供する。GD1基板はERC、routing収束、SES import、DRC、
fabrication出力、独立再読込、silkscreen可読性ゲートまで通過する。
SDK hooksによるfail-closed境界も提供する。筐体pipelineは決定論的ゲートを通過する。
実機Evidenceのschema契約と分類、実機の受領取り込み、FW書き込み・機能測定は実装済みである。
測定結果の入力反映、価格・在庫・納期取得、発注は未実装である。
`AcdGateCritic`は決定論的ゲート結果を使うL2操舵として実装済みである。
SDKへ委譲するのは反復制御だけであり、criticはpass evidenceではない。
GD1の独立したwidth positive-control armは固定順で並列集約し、`acd-search`は候補と
provenanceだけを返す。SDK workflowは採用しない。

決定論的ゲートのauthoritative Evidenceはdigest固定container実行だけが生成する。
現行runnerの`DockerDevWorkspace`、CI、ホスト経路は移行中の参考実行であり、
事前build済みdigest固定server imageによる`DockerWorkspace`一本化はマイルストーン6で扱う。
agent-server package、REST/WebSocket API、server側のresume/forkは
[`ADR-0026`](adr/ADR-0026-openhands-delegation-contract.md)により対象外であり、
[`ADR-0025`](adr/ADR-0025-agent-server-production-adoption.md)はSupersededである。
採用する場合は認証・権限・Evidence境界の受入条件を定義した新規ADRを起票する。
Conversationは現行の`DockerDevWorkspace`経路で検証し、決定論的gateの代替にはしない。

## 現行実装計画

| 順 | マイルストーン | 達成条件 | 現状 |
|---|---|---|---|
| 1 | 契約と再現可能な投影 | graphをPydanticで検証し、同一入力から投影・provenance・hashを再生成できる | 達成 |
| 2 | 電気レーンの独立検証 | ERC、routing収束、SES import、DRC、Gerber/drill生成、独立再読込、silkscreenゲートを通す | 達成 |
| 3 | 機械レーンの決定論的検証 | STEP/3MF生成、CAD再読込、干渉・clearance・肉厚を通す | 達成 |
| 4 | plugin委譲とSDK tool境界 | Skill/agent/command/toolをSDKでloadし、既存gateをfail-closedで公開する | 達成 |
| 4.1 | SDK hooks境界 | 投影保護、Evidence発注ガード、Stop、probe、文書検証を既存判定の呼出しとして実装する | 達成 |
| 4.2 | 決定論的gate critic | Design Graph revision、Evidence、製造manifestだけで二値criticを評価し、SDK反復を操舵する | 達成 |
| 4.3 | 決定論的探索lane | 独立width armを固定順で並列集約し、探索AgentDefinitionは候補とprovenanceだけを返す | 達成 |
| 4.4 | SDK機能移譲 | SDKのcontext、routing、保存、観測、設定、credential、profile、workspaceへ責務を段階移譲する | 一部実装 |
| 5 | 実機フィードバック | 製造・組立・測定結果をEvidenceとして取り込み、次の入力へ反映する | 5.1〜5.3実装、5.4未着手 |
| 6 | 実行基盤のDockerWorkspace一本化 | 事前build済みdigest固定server imageでゲートを実行し、authoritative Evidence経路を単一化する | 一部実装 |
| 7 | 発注前最終ゲートと自働発注 | 期限付き見積入力と全ゲート再実行を条件に、side-effect journalへ記録した発注だけを許可する | 未着手 |
| — | agent-server採用判断 | 対象外を維持し、採用する場合だけ新規ADRで認証・権限・Evidence境界を定義する | 対象外 |

各マイルストーンとフェーズの完了条件は、(1)入力と出所、(2)実装、(3)正常系、
(4)negative/fail-closed、(5)再現性の5要素で確認する。SkillやAIの所見だけでは完了としない。
以降のフェーズ表は各要素の確認内容を定義する。

## マイルストーン4.4: SDK機能移譲

secret allowlistの`SecretSource`、`EnsembleSecurityAnalyzer`、`ConfirmRisky`、
Skill明示ロード、`StuckDetector`、`ConversationStats`／`Metrics`のL3観測出力は実装済みである。
prompt資材、LLM routing、`FileStore`保存、observability、settings／profile driftは未着手である。
`ToolDefinition`、現行の`DockerDevWorkspace`、将来の`DockerWorkspace`、決定論的gateの
責務境界は変更しない。MCP、Canvas、remote API、cloud、agent-serverは採用しない。

- `sdk.context.prompts`: `plugins/acd/agents/*.md`のrole別promptをSDK prompt構造へ寄せ、
  資材hashを固定してpromptとの整合性を確認する。
- `sdk.llm.router`: critic/judge modelと主agent modelを分離する。routing結果は合否へ
  影響させない。
- `sdk.io`: `src/acd/openhands/session/bootstrap.py`のmetrics/stats保存を`FileStore`
  抽象へ移譲する。
- `sdk.logger`／`sdk.observability`: L3観測のad-hoc JSONを構造化ログ・observabilityへ
  移し、secretとEvidenceを混入させない。
- `sdk.settings`／`sdk.credential`／`sdk.profiles`: secret allowlistとprofile driftを
  SDK経路へ移し、unknownはfail-closedにする。
- `sdk.context.memory`: 作業文脈の補助だけに使い、契約・合否の正にしない。
- `sdk.context.view`: 原EventLogと照合する表示だけに使う。
- `sdk.workspace`／`workspace.DockerWorkspace`: host workspaceはprovisionalに限定し、
  マイルストーン6の完了後にauthoritative経路化する。

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
| 入力と出所 | `FunctionalRunRecord`がESP-IDF版、toolchain版、project commit、`.elf`／`.bin`成果物、build／flash／LED／serialの生ログ、測定機器、期待条件、時刻を宣言する |
| 実装 | `acd.core.firmware`と`scripts/ingest_functional_run.py`が宣言hashを実ファイルへ照合した後、build、flash、LED capture、serial logを独立parserで読み直す |
| 正常系 | 固定版の宣言値と成果物hashが一致し、ESP32-C3書き込み検証、LED 1 Hz、温湿度値域・周期を満たす4件の`measured` host実機Evidenceを個別に保存する |
| negative/fail-closed | 成果物・ログhash不一致、成果物欠落、ESP-IDF版不一致、書き込みverify欠落、対象chip不一致、capture／serial parse失敗、値域外、周期外れ、時刻逆転を停止条件にする |
| 再現性 | recordと保存済み生ログから同一report・4件のEvidenceバイト列とcanonical hashを再生成し、各negative fixtureを含める |

### 5.4 測定結果の入力反映ループ

| 要素 | 完了条件 |
|---|---|
| 入力と出所 | 5.1〜5.3の実機Evidenceと現行の設計入力ファイル、git revisionを入力する |
| 実装 | 実機Evidenceと設計入力の差分を検出し、更新すべき入力属性とrationale recordを提示する |
| 正常系 | 実機Evidenceに基づく入力更新後、決定論的ゲートを再実行してauthoritative Evidenceを更新できる |
| negative/fail-closed | 投影や実機Evidenceを入力へ直接逆流させる経路、stale Evidenceでの合格、rationale欠落を拒否する |
| 再現性 | 同一の実機Evidence集合から同一の差分提示を再生成し、staleケースのnegative testを含める |

## マイルストーン6: 実行基盤のDockerWorkspace一本化

現行は`DockerDevWorkspace(base_image=...)`でagent-server imageをon-the-fly buildする
移行中経路である。事前build済みdigest固定server imageへ移行し、
`DockerWorkspace(server_image=...)`へ一本化する。受入条件は
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
| 実装 | `DockerDevWorkspace`経路を撤去し、host経路はprovisional専用として文書と実装で明示する |
| 正常系 | authoritative Evidenceの生成経路が`DockerWorkspace`だけになり、文書の記述と一致する |
| negative/fail-closed | host Evidenceの合格側昇格、`DockerDevWorkspace`残存参照、経路unknownを拒否する |
| 再現性 | 移行後のCIとローカル実行の双方で同一のEvidence provenanceを再生成できる |

## マイルストーン7: 発注前最終ゲートと自働発注

金銭と納期が発生する不可逆点は発注だけである。発注は全ゲート通過と上限額の2条件を
満たす場合に限り許可し、実行はside-effect journalへ記録する。設計要件は
[`SECURITY.md`](../SECURITY.md)の「AIエージェント特有の前提」、
発注ガードの縮約は[`ADR-0008`](adr/ADR-0008-minimal-vibebb-scope.md)、
製造データと`unknown`境界は[`ADR-0005`](adr/ADR-0005-jlcpcb-pcba-preparation-contract.md)を正とする。
旧文書のPhase 10／Phase 11は本マイルストーンを指す。

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
| 実装 | 発注直前に全決定論的ゲートを現revisionで再実行し、上限額とゲート通過の2条件を判定する |
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
