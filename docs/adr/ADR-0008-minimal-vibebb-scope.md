# ADR-0008: VibeBBの最小構成とSDK優先の実装境界

> 追補: ADR-0009により、探索・採点・FW検査はOpenHandsへ委譲し、実装資産は`plugins/acd/skills/`のSkillとして提供する。

> ステータス: Accepted
> 日付: 2026-08-16
> 関連: [`../../README.md`](../../README.md)、[`../roadmap.md`](../roadmap.md)、[`ADR-0002-json-schema-canonical.md`](ADR-0002-json-schema-canonical.md)、[`ADR-0007-llm-guided-physical-design.md`](ADR-0007-llm-guided-physical-design.md)

## コンテキスト

VibeBBの体験価値は「語れば試作が届き、動く」ことであり、最初の到達点は実機のLEDが光ることである。
しかし従来の契約は、そこへ到達するために量産品質の管理機構をほぼ全て前提にしていた。具体的には、
Evidence失効の伝播、影響導出（impact analysis）、`ReviewFinding`の処分状態と`RV1`／`RV2`の合否機構、
tool envelope（idempotency key・副作用分類）、機械可読gate matrix、error taxonomy、waiver、
task ledger・side-effect journal、設計根拠nodeの必須化、JSON Schema正本14本である。

これらは重い検証を安く回すための最適化と、量産で問われる説明責任のための記録である。ACDの対象は
趣味・研究・小規模試作の1〜4層基板と3Dプリント・卓上切削の筐体であり、1回$30規模の試作では
最適化対象のコストがそもそも小さく、説明責任の相手も作者自身しかいない。機構の実装コストが
体験価値の獲得を遅らせている。

実装済みコードの内訳も同じことを示している。adapters（KiCad／Gerber／router／機械の生成と独立
再読込）が中心的な価値であり、tool executor、独自event、schema正本、レビュー処分機構は
OpenHands SDKまたはgitで置換できる。

一方で、削ってはいけない一点がある。ACDで実際に金と時間が出るのは発注であり、ここだけは
誤りが実物と金額で返ってくる。

## 決定

対象を趣味・研究・小規模試作の単一の既定に固定する。`small-production`／`high-reliability`という
複数プロファイルの段階有効化を行わず、量産品質向けの機構は本リポジトリの要求から外す。将来の
高信頼化は[`../roadmap.md`](../roadmap.md)の将来展望としてのみ扱い、規範として先取りしない。

不変条件として残すのは次の一点に絞る。

**発注の直前に全ゲートを実行し、通らなければ発注しない。**

### 1. stale伝播を捨て、変更ごとに全ゲートを再実行する

影響導出とEvidence失効伝播は、高価な検証の再実行を避けるための最適化である。対象規模では
ERC/DRC・Gerber独立再読込の実行時間が小さいため、変更ごとに全ゲートを再実行する。影響導出、
stale伝播、Evidence失効の契約と実装を要求から外す。Evidenceはゲート出力ファイルに
ツール名・版・入力hash・出力hashを添えたものとして扱う。

### 2. revision管理をgitに任せる

patch適用・revision生成・分岐調停の自作機構をやめ、設計の入力ファイルとgitを正とする。revisionは
git commitである。設計根拠は会話履歴（OpenHands `EventLog`）が担い、設計グラフへ紐づけた
根拠nodeを必須にしない。投影を正へ逆流させない原則は維持する。

### 3. レビューはLLMの判断材料とし、合否面を1つに絞る

機械可読投影（netlist、寸法、干渉、DRC/ERC出力）と視覚投影（レンダリング画像、3Dビュー）の
2種類は、LLMが次の修正を判断するための入力として残す。視覚投影は`ImageContent`／
`inspect_image_with_vision`で読み、レビューはsubagentによるbest-effortとする。所見は自然文でよい。

`ReviewFinding` schema、処分状態、`RV1`／`RV2`の合否機構は要求から外す。合格条件は
「ERC/DRCを通過し、生成物を生成経路とは別のparserで再読込できる」だけとする。fail-closedは
ツール不在、parse失敗、ゲート未実行、安全境界の`unknown`に限定する。

### 4. 発注ガードを2条件に縮める

多次元裁量枠、承認ID、総発注額の内訳契約、見積dry-run契約をやめ、「設定した上限額を超えたら
止める」と「発注直前の全ゲートに通っていなければ止める」の2条件にする。

### 5. JSON Schema正本を捨て、契約はPydanticのみとする

`schemas/*.schema.json`を機械可読契約の正本とする[`ADR-0002-json-schema-canonical.md`](ADR-0002-json-schema-canonical.md)
を廃止し、契約は`packages/acd-schema`のPydanticモデルだけで表現する。往復検証テストと
JSON Schemaの維持コストを外す。失うのは他言語実装からの契約参照と、契約差分をJSON Schemaの
差分としてレビューできることである。

### 6. ACD独自のtool層とexecutorを捨てる

`graph_query`／`graph_patch`等のACD独自tool群と共通executor、tool envelope（idempotency key、
副作用分類、`unknown`意味論）をやめる。agentはSkill経由でパイプラインスクリプトをworkspaceの
シェルで実行する。副作用の防護はSDKの`ConfirmationPolicy`を発注スクリプトへ適用することで行う。
失うのは型付きtool結果による早期検出と、tool単位の細かい権限分離である。

### 7. ACD独自eventとレビュー実装を捨てる

ACDドメインevent型、event payload契約、`SessionStart` hookでの資材hash照合、独自のレビュー
実行実装をやめる。履歴はSDKの`EventLog`とgit commit、レビューはsubagentとvisionに置く。
起動時確認は外部ツールの版プローブとACD packageのimport検証までとする。失うのはドメイン
eventのreplayと構造化レビュー記録である。

### 8. ファームウェアの独自契約を捨てる

FWパッケージの機械可読契約をやめ、ファームウェアはSDKの標準的なソフトウェア開発能力へ委譲する。
ピン割当整合を生成スクリプト内の検査として残す判断はADR-0009で撤回した。FW検査は全て
OpenHands側（`acd-firmware-esp32c3` Skillおよび通常のテスト）の責務であり、ACD本体はFWゲートを
持たない。

### 実装として残るもの

- adapters: KiCad、freerouting、Gerber、機械CADの生成と、生成経路とは独立なparserによる再読込。
- パイプラインスクリプト: fixtureまたは入力ファイルから製造データまでを一括生成し、全ゲートを実行する。
- fab profileの宣言データと発注ガード。
- OpenHands plugin: Skill、`AgentDefinition`、SDK ToolDefinition、hooks。

## 検討した代替案

| 代替案 | 却下理由 |
|---|---|
| 従来の契約を維持し実装順序だけ変える | 前提が減らないため契約確定に必要な作業量が変わらない |
| 複数プロファイルで段階有効化する | 対象が単一なので分岐そのものが記述と実装のコストになる。将来の高信頼化は将来展望として扱えば足りる |
| 量産品質向けの機構を将来の要求として文書に残す | 規範として先取りすると、実装しない要求が常に矛盾源になる |
| 発注ガードも上限額だけにする | ゲート未実行のまま発注へ到達しうる。不可逆点の損失が非対称であり2条件は最小構成として残す |
| KiCad読み取りを第三者MCPへ委ねる | 生成と検証を同一実装に任せると独立再読込の独立性が失われ、GPL境界の問題も持ち込む |
| ERC/DRCの判断をLLMへ委ねる | 誤りが実物と金額で返る唯一の場所であり、代替が効かない |
| OpenHands外でも動く形を維持する | 実行基盤の二重実装になる。SDK前提へ振り切り、headlessな再現実行は諦める |

## 影響

- [`ADR-0002-json-schema-canonical.md`](ADR-0002-json-schema-canonical.md)は本ADRにより廃止（Superseded）とする。
- [`ADR-0007-llm-guided-physical-design.md`](ADR-0007-llm-guided-physical-design.md)の三層分離は維持するが、
  探索仕様の機械可読契約と探索固有Evidenceの記録は要求から外す。代理指標を合格根拠にしないことは維持する。
  LLMに座標・回転角を直接出力させない制約は[`ADR-0009-openhands-delegation-and-skills.md`](ADR-0009-openhands-delegation-and-skills.md)で撤回した。
- 量産品質向けの機構を前提にした記述と文書は削除する。信頼性・安全性・QC手法・先行事例の調査記録は、
  将来の高信頼化の参照として残し、規範ではないことを明示する。
- `schemas/`、`packages/acd-events`、`packages/acd-runtime`の該当実装、独自tool層の削除は
  本決定に基づく別変更として行う。

## 未確認・リスク

- 全ゲート再実行の実時間は対象規模で未測定である。再実行が体験を損なう水準なら影響導出の導入を再検討する。
- 設計根拠が会話履歴にしか残らないため、後から高信頼化へ進む際に過去設計の根拠を再構成できない可能性がある。
- 合否面をERC/DRCと独立再読込に絞ると、ライブラリ記述の誤りと設計意図の誤りは検出できない。実機での確認に委ねる。
- Pydanticのみを契約とするため、契約変更の影響範囲はテストでのみ検出される。
