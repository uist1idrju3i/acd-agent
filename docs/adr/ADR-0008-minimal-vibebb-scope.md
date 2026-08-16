# ADR-0008: VibeBB最小構成とprofileによる段階有効化

> ステータス: Accepted
> 日付: 2026-08-16
> 関連: [`../../README.md`](../../README.md)、[`../roadmap.md`](../roadmap.md)、[`../reliability-practices.md`](../reliability-practices.md)、[`ADR-0002-json-schema-canonical.md`](ADR-0002-json-schema-canonical.md)、[`ADR-0007-llm-guided-physical-design.md`](ADR-0007-llm-guided-physical-design.md)

## コンテキスト

VibeBBの体験価値は「語れば試作が届き、動く」ことであり、最初の到達点は実機のLEDが光ることである。
しかし現行の契約は、そこへ到達するために量産品質の管理機構をほぼ全て前提にしている。具体的には、
Evidence失効の伝播、影響導出（impact analysis）、`ReviewFinding`のRV1／RV2処分状態と投影レビューPDCA、
tool envelope（idempotency key・副作用分類）、機械可読gate matrix、error taxonomy、waiver、
task ledger・side-effect journal、設計根拠nodeの必須化、schema14本である。

これらは重い検証を安く回すための最適化と、量産で問われる説明責任のための記録である。1〜4層・
小規模基板・1回$30規模の試作では、最適化の対象となるコストがそもそも小さく、説明責任の相手も
作者自身しかいない。結果として、機構の実装コストが体験価値の獲得を遅らせている。

一方で、削ってはいけない一点がある。ACDで実際に金と時間が出るのは発注であり、ここだけは
誤りが実物と金額で返ってくる。

## 決定

VibeBBの既定を最小構成とし、量産品質向けの機構は設計プロファイル（`hobby`／`small-production`／
`high-reliability`）で段階的に有効化する。`hobby`を既定とする。削減対象は削除ではなく、
有効化条件をprofileへ移す。

不変条件として残すのは次の一点に絞る。

**発注の直前に全ゲートを実行し、通らなければ発注しない。**

### 1. stale伝播を捨て、revisionごとに全ゲートを再実行する

影響導出とEvidence失効伝播は、高価な検証の再実行を避けるための最適化である。初期ターゲットの
規模ではERC/DRC・Gerber再読込の実行時間が小さいため、`hobby`では変更ごとに全ゲートを再実行する。
影響導出、stale伝播、Evidence失効の実装を`hobby`の前提から外す。

### 2. revision管理をgitに任せる

patch適用・revision生成・分岐調停の自作機構を`hobby`の前提から外し、設計の入力ファイルとgitを
正とする。設計根拠は会話履歴（OpenHands `EventLog`）が担い、設計グラフへ紐づけた根拠nodeを
必須にしない。

### 3. レビューをSDKへ寄せ、合否面を1つに絞る

`ReviewFinding` schema、処分状態、`RV1`／`RV2`、投影レビューPDCAを`hobby`の前提から外す。
レビューはsubagentとvisionによるbest-effortとし、自然文の指摘でよい。合格条件は
「ERC/DRCを通過し、生成物を生成経路とは別のparserで再読込できる」だけとする。fail-closedは
ツール不在、parse失敗、ゲート未実行に限定する。

### 4. 発注ガードを2条件に縮める

多次元裁量枠、承認ID、総発注額の内訳契約、見積dry-run契約を`hobby`の前提から外し、
「上限額を超えたら止める」と「全ゲート通過でなければ止める」の2条件にする。

### profileごとの有効化

| 機構 | `hobby`（既定） | `small-production`以上 |
|---|---|---|
| ゲート実行 | 変更ごとに全ゲート再実行 | 影響導出とEvidence失効伝播で再実行範囲を決める |
| revision管理 | 入力ファイル＋git | 型付き設計グラフのrevisionとpatch |
| 設計根拠 | 会話履歴に残る（node必須にしない） | 設計グラフへ紐づけた根拠nodeを必須にする |
| レビュー | subagent／visionのbest-effort、自然文可 | `ReviewFinding` schema、処分状態、`RV1`／`RV2`、PDCA |
| 合否面 | ERC/DRC＋独立parserでの再読込 | 多段ゲート、gate matrix、waiver、DFM、SI／熱 |
| 記録 | ツール名・版・入出力hash | Evidence schema、測定条件、不確実性、収束状態、対象revision |
| 発注ガード | 上限額と全ゲート通過の2条件 | 多次元裁量枠、承認ID、総発注額内訳、見積dry-run |
| 停止条件 | ツール不在、parse失敗、ゲート未実行 | 上記に加えstale、unknown影響、未処分の重大finding |

`small-production`以上の要求の正は[`../reliability-practices.md`](../reliability-practices.md)に置く。
本表は有効化の境界だけを定め、各要求の内容をここで二重管理しない。

## 検討した代替案

| 代替案 | 却下理由 |
|---|---|
| 現行の契約を維持し、実装順序だけ変える | 前提が減らないため、Phase 0の契約確定に必要な作業量が変わらない |
| 量産品質向けの機構を文書から削除する | 高信頼プロファイルの土台を失う。段階有効化なら削除せずに初期コストを外せる |
| profileではなくフェーズだけで段階化する | 実装が進んだ後もhobbyユーザーに重い機構が課される。有効化条件をリスク側の宣言に結びつける方が適切である |
| 発注ガードも最小化し、予算上限だけにする | ゲート未実行のまま発注へ到達しうる。不可逆点の損失が非対称であり、2条件は最小構成として残す |
| stale伝播を残し全ゲート再実行を採らない | 初期ターゲットでは再実行コストが小さく、最適化のために影響導出を先に実装する理由がない |

## 影響

- `hobby`ではEvidenceを「ツール名・版・入出力hashを添えたゲート出力」として扱い、失効判定を伴う
  Evidence契約は`small-production`以上で有効化する。
- 発注前最終ゲートは全profileで必須であり、`hobby`でも全ゲートの再実行を要求する。
- 探索方針（[`ADR-0007-llm-guided-physical-design.md`](ADR-0007-llm-guided-physical-design.md)）の
  三層分離は維持するが、探索仕様の機械可読契約とEvidence記録の重さは`small-production`以上へ寄せる。
- [`../roadmap.md`](../roadmap.md)のPhase 0は、`hobby`の最小構成に必要な契約だけへ縮小する。
  フェーズ境界の正はroadmapに置き、本ADRで再定義しない。
- 既に実装済みのschemaとpackageは削除せず、`hobby`で必須としない扱いに変える。

## 未確認・リスク

- 全ゲート再実行の実時間は初期ターゲット規模で未測定である。再実行が体験を損なう水準なら、
  影響導出の前倒しを再検討する。
- `hobby`で根拠nodeを必須にしないため、後から`small-production`へ上げる際に過去設計の根拠が
  会話履歴にしか無い状態が生じる。profile昇格時の移行手順は未決である。
- 合否面をERC/DRCと独立再読込に絞ると、ライブラリ記述の誤りは検出できない。`hobby`では
  この限界を受け入れ、実機での確認に委ねる。
