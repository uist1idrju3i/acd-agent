# アーキテクチャ

> ステータス: Draft
> 対象: ACDコンセプト段階、OpenHands SDK v1.42.1

本書は、設計グラフ、レイヤ境界、投影、ツール契約のアーキテクチャを正とする。
工程の入力・出力・還流は [`design-flow.md`](design-flow.md)、SDKの責務境界は
[`openhands-integration.md`](openhands-integration.md)、ECADの詳細契約は
[`ecad-domain-notes.md`](ecad-domain-notes.md)を参照する。

## 正規データモデル

正規データモデルは、Pydanticモデルで表す入力ファイルである。gitを変更履歴として使い、
少なくとも次のドメインを持つ。

- 電気: Requirement、FunctionalBlock、Part、Pin、Net、Footprint、Stackup、Layout。
  `Requirement.intended_use`、`Net.voltage_nominal`、`Net.current_max`、`Part.hazard_class`、
  `Part.certification`を安全境界の判定入力として持つ。
- 機械: BoardEnvelope、ComponentEnvelope、Enclosure、Opening、Fastener、Material、
  Tolerance、AssemblyStep、ThermalPath。
- 製造: FabProfile、ExportFormat、AssemblyClass、MachineProfile、Process、Cost、LeadTime、
  Quantity、DFMReport、FabPackage。
- 発注: OrderEnvelope（金額、納期、月間発注回数、fab指定、地域）、`fab.order_intent`、
  `fab.process_allowance`。
- 根拠: Source、VerificationResult、Assumption。
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

入力ファイルとgit commitが変更履歴を表し、変更後は全ゲートを再実行する。

回路図、KiCad project、Gerber、BOM、STEP/3MF、図面、FW packageはすべて派生投影であり、
入力ファイルを置き換えない。
この方針はZener、atopile、tscircuitから得られる教訓である。

投影は意味的にマージせず、投影から入力ファイルへ逆流させない。変更後は全ゲートを再実行する。
投影へ写す属性は、ピン電気種別、内部接続ピン、netclass／ルール、variant／DNP、
原点・単位・軸、stackup・基板厚、メタデータ、安定identifierとrefdesを含む。
定義とインスタンスは分離し、共有情報と固有情報を入力ファイルで管理する。

実行側の代替案探索は`Conversation.fork(from_event_id=...)`へ対応付ける。各枝の比較結果は
自然文の作業メモとして残し、採用した入力ファイルから投影を再生成する。

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

パッケージ分割はPydantic契約、adapters、pipeline scripts、pluginを単位とし、
依存は一方向とする。電気・機械・FWの3レーンは工程の軸であってモジュール分割の軸ではない。
3レーンは共通のgraph coreを共有し、レーン固有の事情はadapterとgate policyへ置く。

原則として、1 adapterは1つの外部ツールかつ1つの形式版系列に対応させる。複数ツールを
1つのadapterへ束ねず、ツールを差し替えても入力契約を変更しない構造を維持する。
契約はPydanticモデルで定義し、文書は入力ファイルと実装の使い方を説明する。

coreは外部ツール固有の型、ファイル形式、
座標系変換を持たず、adapterはACDの設計意味論と合否判定を持たない。

生成と判定は別モジュールにする。判定モジュールは生成モジュールへ依存しない。これは
[`projection-review.md`](projection-review.md)のレビュー独立性と
[`reliability-practices.md`](reliability-practices.md)の「生成と判定の分離、独立性」を
コード構造へ落としたものである。

配置・回転・配線探索では、探索器・整合化器・代理指標を生成側モジュールに置き、外部router等の
実測とゲートを判定側モジュールに置く。判定側は生成側へ依存せず、生成側の候補や代理指標を
合格根拠として直接信頼しないことで、生成と判定の分離を具体化する。

分割の判定基準は、独立に版管理するツール、形式、ライブラリ、設定の境界である。

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

投影は入力ファイルから再生成でき、生成時のtool version、input/output hash、時刻を保持する。
再読込できない、またはtool versionが不明な投影は合格根拠にしない。

レビュー用投影は別コンテキストのAIレビューに渡す。所見は自然文で修正ループへ渡し、
合否は決定論的ゲートだけで判定する。詳細は[`projection-review.md`](projection-review.md)に定める。

レビュー投影は機械可読投影と視覚投影に分ける。視覚投影のメタデータには画像hash、
renderer種別、vision profile／model、解像度を含める。視覚投影は観察入力であり、
決定論的ゲートの入力や合否根拠には
しない。

ゾーン塗りつぶし等の派生状態は、外形・ルール・接続の変更後に再計算してから検証する。
再計算前の結果は合格根拠にしない。図面、3D形状、ブラウザ閲覧形式などのレビュー用投影は
正ではなく、観察の入力に限る。投影側の編集や期待hash不一致は出所不明の派生物として検出し、
設計グラフから再生成する。

## ツール契約

Pydanticモデルを契約として使う。adapterは形式版、隔離した設定ディレクトリ、言語、単位、
解決済みライブラリ参照を固定し、外部ツールの版、入力・出力hash、収束状態、実行時刻を記録する。
出力は独立parserで再読込し、決定論的ゲートで判定する。

## イベントログとチェックポイント

SDKの`EventLog`を汎用の実行履歴層として利用する。
SDKは`events/event-{idx:05d}-{event_id}.json`への追記保存、ファイルロック、event ID重複拒否、
parent ID検証、Pydantic型付きevent union（`extra="forbid"`、`frozen=True`）、parent-child
event treeと`path_to_root()`、branch navigation、`fork(from_event_id=...)`、
conversation stateの永続化、異常終了後の未完了tool call検出を提供する。

ACD独自のevent層は作らず、SDKの会話履歴とworkspaceを使う。合否はEventLogではなく
決定論的ゲートが判定する。

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

発注前は、入力を管理するgit commit、入力hash、ゲート結果、予算を
記録し、発注と異なる副作用を合格根拠にしない。設計グラフと決定論的ゲートが
判定面である。

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
URL資格情報のredact、timeout付き）を介してworkspaceで行う。ACDのadapterはgit commit、
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
決定論的ゲートは入力ファイルから生成した投影を再取得して判定し、投影を正へ逆流させず、
壊れた成果物や`unknown`を合格扱いしない。

artifact hashはworkspace内で生成し、ツール版、形式版、ライブラリcommit、設定その他の
実行条件とともに記録する。workspace側に置く外部ツール
（KiCad CLI等）はworkspace imageへ版を固定し、実行環境と版をEvidenceへ記録する。ツールの
所在をworkspaceへ移しても、既存のツール契約（版・入力hash・出力hash・実行条件の記録）は
緩めない。

Gerber、STEP、3MF等のバイナリ成果物はgit本体を肥大化させるため、Git LFSまたは別artifact
storeを利用する。ただし採用する保管方式、workspace側永続化の保持期間、署名・改ざん検知の
扱いは未決であり、これらが確定するまで該当Evidenceを完全な永続保管の証拠として扱わない。
OpenHandsはこの構成でも実行基盤であり、入力ファイルと決定論的ゲートが合否判定の正を所有する。

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
