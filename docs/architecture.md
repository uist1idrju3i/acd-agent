# アーキテクチャ

> ステータス: Draft  
> 対象: ACDコンセプト段階、OpenHands SDK v1.42.1

本書は、設計グラフ、レイヤ境界、投影、ツール契約のアーキテクチャを正とする。
工程の入力・出力・還流は [`design-flow.md`](design-flow.md)、SDKの責務境界は
[`openhands-integration.md`](openhands-integration.md)、ECADの詳細契約は
[`ecad-domain-notes.md`](ecad-domain-notes.md)を参照する。

## 正規データモデル

正規データモデルは、型付き・バージョン付き設計グラフである。少なくとも次の
ドメインを持つ。

- 電気: Requirement、FunctionalBlock、Part、Pin、Net、Footprint、Stackup、Layout。
  `Requirement.intended_use`、`Net.voltage_nominal`、`Net.current_max`、`Part.hazard_class`、
  `Part.certification`を安全境界の判定入力として持つ。
- 機械: BoardEnvelope、ComponentEnvelope、Enclosure、Opening、Fastener、Material、
  Tolerance、AssemblyStep、ThermalPath。
- 製造: FabProfile、ExportFormat、AssemblyClass、MachineProfile、Process、Cost、LeadTime、
  Quantity、DFMReport、FabPackage。
- 発注: OrderEnvelope（金額、納期、月間発注回数、fab指定、地域）、`fab.order_intent`、
  `fab.process_allowance`。
- 根拠: Rationale、Source、Evidence、VerificationResult、Waiver、Approval、Assumption、
  `ReviewFinding`。
  `Assumption`は確度、確定予定アクション、覆った場合の影響先を持つ。
- 安全: `SafetyBoundaryResult`は`SB1`（工程`S1`で実行する予備判定）と
  `SB2`（工程`E1`で実行する確定判定）を区別し、判定根拠、危険区分、状態
  （`pass`／`fail`／`unknown`）を保持する。`SB2`のグラフ述語判定をゲートの正とし、
  `unknown`はfail-closedで停止する。
- ライブラリ: `LibraryOverlay`は公式ライブラリを変更せず、対象ライブラリ・footprint、
  差分、理由、出所Evidenceをプロジェクトローカルに保持する。

製造データ経路は、fab非依存のcore判定、fab profileの宣言データ、出力形式adapterを分離する。
coreは生成物を独立測定し、capabilities（絶対能力）とpreferences（品質・コスト・納期の
ドライバ）を区別して判定する。fab profileは能力値、rule ID、assembly class、export format、
出所・取得時刻・hashを宣言し、adapterはその宣言に従ってBOM/CPL等の形式へ投影する。
特定fabの名称、列名、座標・回転規約、工程区分をcoreの判定ロジックへ埋め込まない。

グラフのnodeとedgeは、revision、schema version、出所、入力hash、状態を持つ。
設計変更はpatchとして表現し、影響するnode、再実行するgate、無効になるEvidenceを導出する。

回路図、KiCad project、Gerber、BOM、STEP/3MF、図面、FW package、監査文書、
Q7/N7図表はすべて派生投影であり、正規データを置き換えない。グラフはテキストとして
シリアライズ可能なJSON形式にし、差分比較、レビュー、gitでの保存を容易にする。
この方針はZener、atopile、tscircuitから得られる教訓である。

投影は意味的にマージしない。分岐、調停、リビジョン復元は設計グラフ上で行い、過去の
生成物を現行Evidenceとして再利用せず、対象revisionから投影を再生成して再検証する。
投影へ写す属性は、ピン電気種別、内部接続ピン、netclass／ルール、variant／DNP、
原点・単位・軸、stackup・基板厚、メタデータ、安定identifierとrefdesを含む。
定義とインスタンスは分離し、共有情報と固有情報の波及範囲をimpact analysisへ渡す。

実行側の代替案探索は`Conversation.fork(from_event_id=...)`へ対応付ける。trade studyや
Phase 6の協調修復では、基準eventから子conversationを作り、各枝を独立した作業revision
として比較する。採用枝だけをcanonical graphへpatchし、非採用枝は対象revision、入力・
出力hash、比較理由を含むEvidence付きtrade study記録として残す。投影を意味的にマージ
せず、採用枝のgraphから投影を再生成する不変条件は維持する。

## レイヤ境界

```text
schema
  ↓
core（graph、rationale、impact、gate、knowledge）
  ↓
adapters（KiCad、FreeCAD/code-CAD、slicer、simulation、sourcing）
  ↓
agent tools（typed Action/Observation、side-effect policy）
  ↓
OpenHands Conversation（計画、実行、delegate、memory、MCP）
```

依存方向は上から下への一方向とする。adapterはcoreの意味論を知らずに設計判断をせず、
typed contractで入出力を返す。agent toolはLLMの自由文を受けても直接ファイルを編集せず、
schema検証済みのActionへ変換する。

## モジュール分割の粒度

パッケージ分割は既存のレイヤ境界（schema、core、adapters、agent tools）を単位とし、
依存は一方向とする。電気・機械・FWの3レーンは工程の軸であってモジュール分割の軸ではない。
3レーンは共通のgraph coreを共有し、レーン固有の事情はadapterとgate policyへ置く。

原則として、1 adapterは1つの外部ツールかつ1つの形式版系列に対応させる。複数ツールを
1つのadapterへ束ねず、ツールを差し替えてもcoreを変更しない構造を維持する。1 schema
ファイルは1契約とし、設計グラフ、tool envelope、gate matrix、error taxonomy、event
payload、`ReviewFinding`はそれぞれ独立した機械可読正本を持つ。文書はこれらの正本から導く。

1 agent toolは1つの副作用クラスに対応させる。readと不可逆操作を同じtoolへ混ぜず、
idempotency keyの単位はtool呼び出し1回とする。coreは外部ツール固有の型、ファイル形式、
座標系変換を持たず、adapterはACDの設計意味論と合否判定を持たない。

生成と判定は別モジュールにする。判定モジュールは生成モジュールへ依存しない。これは
[`projection-review.md`](projection-review.md)のレビュー独立性と
[`reliability-practices.md`](reliability-practices.md)の「生成と判定の分離、独立性」を
コード構造へ落としたものである。

配置・回転・配線探索では、探索器・整合化器・代理指標を生成側モジュールに置き、外部router等の
実測とゲートを判定側モジュールに置く。判定側は生成側へ依存せず、生成側の候補や代理指標を
合格根拠として直接信頼しないことで、生成と判定の分離を具体化する。

分割の判定基準は「版とstale境界」である。独立に版が動くツール版、形式版、ライブラリ
commit、profileは別モジュールへ分ける。モジュール境界と再検証単位（stale伝播の単位）を
一致させ、schema変更で無関係なEvidenceが一斉失効しないようにする。

SDKはSkill／plugin（作業資材）、`AgentDefinition`（役割）、tool（副作用）、workspace
（実行環境）という分割単位を持つ。ACDのモジュール境界はこれらへ写像できるようにするが、
SDKの配布単位に合わせてACDの契約境界を歪めない。詳細な活用方針は
[`openhands-integration.md`](openhands-integration.md)を参照する。本節の原則を
具体的なリポジトリ構成・パッケージ名へ落とした構成正本は
[`implementation-plan.md`](implementation-plan.md)を参照する。

次の状態は粒度が不適切なアンチパターンである。

- adapterがゲート判定を持つ。
- coreが特定ECADの型を参照する。
- 1つのschema変更が無関係な契約を巻き込む。
- 1つのtoolがreadと不可逆操作を兼ねる。
- レーンごとにgraph coreが分裂する。

## 投影

投影は対象revisionから再生成でき、生成時のtool version、input/output hash、Evidence、
時刻を保持する。再読込できない、対象revisionが違う、またはtool versionが不明な投影は
staleである。

レビュー用投影には、別コンテキストのAIレビューと`ReviewFinding`を結び付ける。対象revision、
入力hash、ツール版、ライブラリcommit、profileのいずれかが変われば投影とレビューをstale
とし、staleなレビューを出口ゲートの根拠にしない。詳細なPDCA、RV1／RV2、処分契約は
[`projection-review.md`](projection-review.md)に定める。

レビュー投影は機械可読投影と視覚投影に分ける。視覚投影のメタデータには画像hash、
renderer種別、vision profile／model、解像度を含め、レビュー結果と`ReviewFinding`へ
束ねる。視覚投影は観察入力であり、描画に依存しない決定論的ゲートの入力や合否根拠には
しない。

ゾーン塗りつぶし等の派生状態は、外形・ルール・接続の変更後に再計算してから検証する。
再計算前の結果はstaleとして扱う。図面、3D形状、ブラウザ閲覧形式などのレビュー用投影は
正ではなく、観察の入力に限る。投影側の編集や期待hash不一致は出所不明の派生物として検出し、
設計グラフから再生成する。

## 監査文書の投影

設計グラフから、次の監査文書を生成する。

- 要求トレーサビリティマトリクス
- 設計履歴・レビュー記録
- ECO相当の変更記録
- 検証・試験報告
- 出所付きBOM
- リスク／FMEA風ビュー
- PPAP／PSW相当の量産引き渡し証拠パッケージ

これらは対象revisionとEvidenceから再生成できる派生投影である。

形式はISO 9001の設計記録や医療機器DHFの形式に整合する方向性を持つが、これらの
投影によって認証・法規制適合や顧客承認を自動的に主張しない。

## ツール契約

SDKのPydantic `Action`／`Observation`、JSON Schema、tool call ID、Action↔Observationの
紐付け、`ToolAnnotations`、`DeclaredResources`をtool契約の土台とする。ACDはこれらの
派生型として契約を定義する。`readOnlyHint`、`destructiveHint`、`idempotentHint`は
宣言（hint）であって強制ではない。

ACDはidempotency key、重複副作用防止、side-effect classの強制、ツール版、入力・出力・
artifact hash、実行条件、gate・承認binding、予算、`unknown`の意味論を追加する。副作用は
read、可逆、不可逆に分類する。ECAD adapterは形式版、隔離した設定ディレクトリ、言語、
単位、解決済みライブラリ参照も実行条件として固定する。

- readは再実行可能である。
- 可逆操作はrollbackまたは新revisionで戻せる。
- 不可逆操作は、金額・納期・月間発注回数・fab指定・地域の裁量枠、最終ゲート、
  承認状態を共通executorが確認する。

tool結果には、success/fail/unknown、diagnostics、warnings、Evidence、artifact
hash、収束状態を含める。外部プロセスのstdoutだけをEvidenceにせず、構造化結果と
再読込確認を要求する。

## イベントログとチェックポイント

SDKの`EventLog`を汎用の実行履歴層として利用し、その上にACDドメインpayload層を置く。
SDKは`events/event-{idx:05d}-{event_id}.json`への追記保存、ファイルロック、event ID重複拒否、
parent ID検証、Pydantic型付きevent union（`extra="forbid"`、`frozen=True`）、parent-child
event treeと`path_to_root()`、branch navigation、`fork(from_event_id=...)`、
conversation stateの永続化、異常終了後の未完了tool call検出を提供する。

ACDが定義するのはその上に載せる最小限のドメインイベントpayloadである。payloadはgate結果、
承認、commit側の副作用receiptへの参照を中心とし、ドメイン記録の正はcommit済みEvidence
artifactへ置く。対象revision、projection ID、入力hash、出力hash、ツール版、形式版、
stale状態などの詳細はcommit済みEvidence artifactへ束ねる。ACDはSDKの汎用保存機構を
再実装せず、Evidenceと合否の意味論を所有する。

最小限のACD独自`Event`サブクラスも`DiscriminatedUnionMixin`のsubclass走査で解決される
ため、EventLogを読む前にACD packageがimport済みでなければならない。未知の`kind`は
`ValueError`となり、読み飛ばしやopaque保持はできない。このfail-closed挙動は望ましいため、
例外を握り潰さない。pluginを導入しただけではACDのEvent型は登録されず、起動時importを
gate結果・承認・副作用receipt参照を読む経路の運用契約とする。低遅延の実行journalを諦め、
commit側へ寄せることで可搬性とrevision結合を優先する。

## AIオーケストレーション

計画エージェントは各段階をステップへ分解し、型付きツールを呼び出す。対象には次が含まれる。

- 部品検索
- データシート抽出
- ネットリスト構築
- 配置
- ルーター
- DRC
- シミュレーター
- DFMチェッカー
- CADカーネル
- slicer

AIの出力はすべて決定論的検証を通し、ツール版、入力、出力、測定条件、Evidenceを記録する。

決定論的ゲートの結果は`CriticResult`へ写像できるが、SDKの反復機構は修復ループの実行
機構に限って利用する。`CriticBase`は`EXPERIMENTAL`で、`AgentBase.critic`は単数である。
複数ゲートはACD側で合成し、ゲート合格／不合格をscore 1.0／0.0へ写像する。確率的score、
criticの例外時にSDKが評価なしとして扱うこと、反復終了は合否根拠にせず、詳細は
[`openhands-integration.md`](openhands-integration.md)に従う。

承認ゲートを有効化した場合は、対象revision、入力hash、ゲート結果、予算、承認状態を
記録し、承認対象と異なる副作用を合格根拠にしない。承認ゲートの有無にかかわらず、
設計グラフと決定論的ゲートが正規の判定面である。

## OpenHandsとの境界

OpenHandsはConversation、Tool、DockerWorkspace／RemoteWorkspace、MCP、delegate、metrics、retryを
提供する。ACDはLocalWorkspaceを実行基盤として採用せず、agent-serverを前提にVS Code、noVNC、
Canvas、Webhook、OpenAI互換gatewayを利用する。Docker image digestとRemoteWorkspaceの対象
revisionを実行条件へ束ね、外部ツール版の固定と可搬性を優先する。
設計グラフと決定論的ゲートはOpenHandsのEventLogへ埋め込まず、ACDのcoreとadapterが所有する。
Conversationは計画と実行を進めるが、設計の正や合否を決めない。

agent-serverのVS Code／noVNC経路は、人間がAI候補を観察・手修正するための実行基盤境界で
ある。GUIを開いた事実やGUI操作自体は合否根拠にならず、手修正はcommit、commit receipt、
対象ゲート再実行を経て初めて下流の根拠になる。K1の視覚AIレビューとは別経路として併用する。

## 成果物とworkspaceの所在境界

ACDはファイルシステムを所有しない構成を採り得る。SDKのGit APIは読み取り中心であり、
`git_changes`、`git_diff`、`get_git_commits`、`get_commit_changes`、HEAD SHA取得などを
提供するが、typedなcommit／push／branch作成／merge APIはない。`GitHelper`にあるのは
`checkout`と`reset_hard`である。commit／pushはSDKの
`openhands-sdk/openhands/sdk/git/utils.py`にある`run_git_command`（shell injection回避、
URL資格情報のredact、timeout付き）を介してworkspaceで行う。ACDのtyped wrapperは対象revision、
commit SHA、artifact hash、ツール版、実行条件を含むcommit receiptを生成し、Evidenceへ束ねる。
終了コードだけをcommit成立の根拠にせず、commit SHAを再取得して確認する。

SDKにartifact store、manifest、content-addressed registryはない。生成ファイルの実体をOpenHandsの
`RemoteWorkspace`系workspaceに置き、ACDはworkspaceの`execute_command`、`file_upload`、
`file_download`、`git_changes`、`git_diff`をHTTP越しに利用する。リポジトリのcloneと
GitHub／GitLab／Bitbucketのprovider連携もworkspace側の契約として扱う。ACDが常時保持するのは
設計グラフのrevision識別子、artifactのhash、Evidenceのメタデータであり、ファイル実体ではない。
保存抽象が必要になった場合はSDKの`FileStore`（`LocalFileStore`／`InMemoryFileStore`）へ合わせ、
ACD独自I/Fを増やさない。SDKにはremote FileStore実装がないため、RemoteWorkspace側の保存経路
は未確定として扱う。
この構成のSDKとの責務分担は[`openhands-integration.md`](openhands-integration.md)にも従う。

workspaceのファイルシステムは揮発する前提で扱う。したがって、gitへcommitしpushされた
revisionだけをEvidenceおよび投影の所在とし、未commitの作業ツリー状態をゲート根拠にしない。
正規性は作業ツリーではなくcommit SHAに束ねる。決定論的ゲートは対象revisionのcommitから
投影を再取得して判定し、投影を正へ逆流させず、staleな成果物や`unknown`を合格扱いしない。
これは「対象revisionから投影を再生成する」という既存の不変条件を、ストレージ側にも適用する
規律である。

artifact hashはworkspace内で生成し、ツール版、形式版、ライブラリcommit、設定その他の
実行条件とともにtool envelopeへ載せる。ACDはhashの値とメタデータだけを保持して照合し、
workspaceから取得した値との不一致を検出できなければならない。workspace側に置く外部ツール
（KiCad CLI等）はworkspace imageへ版を固定し、実行環境と版をEvidenceへ記録する。ツールの
所在をworkspaceへ移しても、既存のツール契約（版・入力hash・出力hash・実行条件の記録）は
緩めない。

Gerber、STEP、3MF等のバイナリ成果物はgit本体を肥大化させるため、Git LFSまたは別artifact
storeを利用する。ただし採用する保管方式、workspace側永続化の保持期間、署名・改ざん検知の
扱いは未決であり、これらが確定するまで該当Evidenceを完全な永続保管の証拠として扱わない。
OpenHandsはこの構成でも実行基盤であり、設計グラフと合否判定の正はACDが所有する。

## task ledgerの実装方針

SDKの`task`ツールのTask状態はインメモリ辞書であり、`close()`時に破棄されるため、
再起動後の復元保証がない。`task_tracker`も全体置換型のmutableなリストを`TASKS.md`へ
保存するだけである。したがって、どちらもACD task ledgerの正にはしない。

ACD task ledgerは独立ストアを持たず、最小限のACDイベントとcommit済みEvidence artifactから
射影（read model）として実装する。task状態・実行状態の取り込みの正はEventLog replayである。
副作用journalとドメイン記録の正はcommit済みEvidence artifactであり、耐久性と可搬性をそこへ
束ねる。`RemoteConversation`のサーバ側保持期間は未確認であり、耐久性の根拠にしない。

agent-serverの`WebhookSpec`はtask ledgerと実行状態の低遅延取り込み経路に限る。webhookは
task状態・実行状態の正でも、副作用journal・ドメイン記録の正でもない。
イベントはbuffer、flush timer、リクエストサイズ上限を持つPOSTで送られるため、ACD側で
pollingを自作しない。ただし配信保証は未確認であるため、task状態・実行状態の取り込みの正は
EventLog replayに置く。副作用journalとドメイン記録の正はcommit済みEvidence artifactに置き、
webhook取り込みは重複・欠落を前提にidempotentとし、欠落を検出できない状態を合格扱いにしない。

## 未決事項

- 設計グラフのシリアライズ形式とschema migration方式。
- STEPの採用と出力経路は[`tool-selection.md`](tool-selection.md)を参照。
  IDF/IDXの採用範囲は未決である。
- GPL/AGPLツールを外部プロセス境界で利用する際の最終的な法務確認。
- Evidenceの署名、改ざん検知、保持期間。
- Gerber、STEP、3MF等のバイナリ成果物をGit LFSと別artifact storeのどちらで保管するか。
- workspace側の永続化について、保持期間、署名、改ざん検知をどの層で担保するか。
- agent-server webhookの配信保証（重複・欠落時の再送、at-least-once等）をどの層で確認するか。
- 製造APIの資格情報、地域、契約、価格snapshotの扱い。
