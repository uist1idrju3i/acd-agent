# アーキテクチャ

> ステータス: Draft  
> 対象: ACDコンセプト段階、OpenHands SDK v1.41.0

本書は、設計グラフ、レイヤ境界、投影、ツール契約のアーキテクチャを正とする。
工程の入力・出力・還流は [`design-flow.md`](design-flow.md)、SDKの責務境界は
[`openhands-integration.md`](openhands-integration.md)を参照する。

## 正規データモデル

正規データモデルは、型付き・バージョン付き設計グラフである。少なくとも次の
ドメインを持つ。

- 電気: Requirement、FunctionalBlock、Part、Pin、Net、Footprint、Stackup、Layout。
- 機械: BoardEnvelope、ComponentEnvelope、Enclosure、Opening、Fastener、Material、
  Tolerance、AssemblyStep、ThermalPath。
- 製造: FabProfile、MachineProfile、Process、Cost、LeadTime、Quantity。
- 根拠: Rationale、Source、Evidence、VerificationResult、Waiver、Approval。

グラフのnodeとedgeはrevision、schema version、出所、入力hash、状態を持つ。
設計変更はpatchとして表現し、影響するnode、再実行するgate、無効になるEvidenceを
導出する。回路図、KiCad project、Gerber、BOM、STEP/3MF、図面、FW package、
監査文書、Q7/N7図表はすべて派生投影であり、正規データを置き換えない。
グラフはテキストとしてシリアライズ可能なJSON形式にし、差分比較、レビュー、gitでの
保存を容易にする。この方針はZener、atopile、tscircuitから得られる教訓である。

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

依存方向は上から下への一方向とする。adapterはcoreの意味論を知らずに勝手な
設計判断をせず、typed contractで入出力を返す。agent toolはLLMの自由文を受けて
直接ファイルを編集せず、schema検証済みのActionへ変換する。

## 投影

投影は対象revisionから再生成でき、生成時のtool version、input/output hash、
Evidence、時刻を保持する。再読込できない、対象revisionが違う、またはtool version
が不明な投影はstaleである。

## 監査文書の投影

設計グラフから、要求トレーサビリティマトリクス、設計履歴・レビュー記録、
ECO相当の変更記録、検証・試験報告、出所付きBOM、リスク／FMEA風ビュー、
PPAP／PSW相当の量産引き渡し証拠パッケージを生成する。これらは対象revisionと
Evidenceから再生成できる派生投影である。

形式はISO 9001の設計記録や医療機器DHFの形式に整合する方向性を持つが、これらの
投影によって認証・法規制適合や顧客承認を自動的に主張しない。

## ツール契約

すべてのtoolは型付きinput/output、schema version、idempotency key、side-effect
classificationを持つ。副作用はread、可逆、不可逆に分類する。readは再実行可能、
可逆操作はrollbackまたは新revisionで戻せ、不可逆操作は予算・最終ゲート・承認状態
を共通executorが確認する。

tool結果には、success/fail/unknown、diagnostics、warnings、Evidence、artifact
hash、収束状態を含める。外部プロセスのstdoutだけをEvidenceにせず、構造化結果と
再読込確認を要求する。

## イベントログとチェックポイント

OpenHands SDKのEventLog、snapshot、resume、forkは実行履歴の土台として利用できる。
ただし、外部CAD/EDAの副作用、外部状態、idempotency、監査署名までSDKは保証しない。
ACD固有の追記専用ログ、side-effect journal、artifact hash、再現モード、
チェックポイント仕様は後続PRで`runtime.md`として定義する。

## AIオーケストレーション

計画エージェントは各段階をステップへ分解し、型付きツールを呼び出す。対象には
部品検索、データシート抽出、ネットリスト構築、配置、ルーター、DRC、シミュレーター、
DFMチェッカー、CADカーネル、slicerが含まれる。AIの出力はすべて決定論的検証を通し、
ツール版、入力、出力、測定条件、Evidenceを記録する。

承認ゲートを有効化した場合は、対象revision、入力hash、ゲート結果、予算、承認状態を
記録し、承認対象と異なる副作用を合格根拠にしない。承認ゲートの有無にかかわらず、
設計グラフと決定論的ゲートが正規の判定面である。

## OpenHandsとの境界

OpenHandsはConversation、Tool、workspace、MCP、delegate、metrics、retryを提供する。
設計グラフと決定論的ゲートはOpenHandsのEventLogへ埋め込まず、ACDのcoreとadapterが
所有する。Conversationは計画と実行を進めるが、設計の正や合否を決めない。

## 未決事項

- 設計グラフのシリアライズ形式とschema migration方式。
- KiCad最低対応版とIPC/APIの固定範囲。
- build123d、CadQuery、FreeCAD、OCCT/OCPのcode-CAD engine選定。
- STEP/IDF/IDXの採用範囲。
- 外部プロセスとimportのライセンス整合。
- 本リポジトリのLICENSE（BSD 3-Clause）と採用ツール群のライセンス整合の再検討。
- Evidenceの署名、改ざん検知、保持期間。
- 製造APIの資格情報、地域、契約、価格snapshotの扱い。
