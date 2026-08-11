# ACDロードマップ

> ステータス: Draft  
> 対象: ACD固有のPhase 0〜11、初期ターゲット（1〜4層基板＋小規模筐体）

本書は、ACD固有Phase 0〜11の内容、やらないこと、完了条件を正とする。工程の詳細は
[`design-flow.md`](design-flow.md)、SDK統合の境界は [`openhands-integration.md`](openhands-integration.md)、
外部ツールの採否は [`tool-selection.md`](tool-selection.md)を参照する。

## 原則

- トレーサーバレット方式（要件から製造・実測までを貫く最小の縦切りを先に通す）。
- 借りられるものは借りる。router、CAD kernel、slicer、solver、OpenHandsを自作しない。
- 各フェーズに実機または実artifactの完了条件を置く。
- 常に出荷可能な成果物を保ち、未検証の成果物を次フェーズへ渡さない。
- 契約（schema、gate、error、event）は機械可読な正本を一つ置き、文書はそこから導く。
- フェーズを実機測定の待ちで止めない。実測Evidenceは「実機Evidence待ち」として別管理する。

## 完了条件の書式

各フェーズの完了条件は、次の5要素をそろえたゴールデンタスクとして起こす。5要素が
そろわない完了条件は未定義として扱い、フェーズ完了の根拠にしない。

1. 入力fixture（tracked、hash付き）。
2. 実行コマンド（同一コマンドでCIとローカルの双方から再実行できる）。
3. 観測する成果物とその再読込方法。
4. negative test（判定対象を故意に壊すと不合格になること）。
5. 記録するEvidence（ツール名・版・入力hash・出力hash・収束状態・予算実測）。

フェーズ着手時は、そのフェーズの作業単位・順序・撤退条件を`docs/phaseN-plan.md`として
起こす。本書ではフェーズ境界だけを管理し、作業単位を二重管理しない。

## フェーズ横断の検証要件

以下は全フェーズの完了条件に共通して要求する。フェーズ固有の完了条件が満たされても、
ここに反する実装は合格にしない。これらは別リポジトリでの先行実装で繰り返し発生した
欠陥の型に基づく設計判断であり、外部リポジトリの記述を権威として引くものではない。

| # | 要件 | 禁止する構造 |
|---|---|---|
| 1 | 判定の両辺は別の出自から取る | 自分が生成した成果物の存在を自分の合格根拠にする（自己証明）。replay結果同士、生成器同士の比較 |
| 2 | 導出できない入力は`unknown`として停止側へ集約する | `continue`・早期return・既定値補完でskipを合格に見せる。宣言の欠如を0や空と同一視する |
| 3 | 実行中のstageを入場時に宣言し、失敗はその宣言から帰属させる | 直前の成功結果や末尾要素を失敗の帰属先にする |
| 4 | CIが読み込む入力・fixture・scriptはtrackedにし、typecheck／lintの対象に含める | 検査対象外の領域を「検査済み」と扱う。gitignore下のデータに依存する回帰 |
| 5 | 外部ツールの保存バイト列を設計状態の権威にしない。非決定な出力は正規化規則を契約に書き、規則外の差異は停止条件とする | 外部ツールの決定論性を説明で仮定する（timestamp、再保存時のセグメント構成差など） |
| 6 | 契約は単一の機械可読正本（gate matrix、error taxonomy、event payload schema、tool envelope）から導く | runnerと文書でgate番号・状態を二重管理する。用途の異なるhashを同一semanticsで共有する |
| 7 | 安全条件・保護対象は書き換わる部分木で判断する | pathの完全一致だけで許可・却下を決める |
| 8 | 予算（token、money、wall-clock、外部process回数）を各ゴールデンタスクで実測して記録する | 予算次元を`unknown`のまま次フェーズへ渡す |

## フェーズ

| フェーズ | 内容 | やらないこと | 完了条件（ゴールデンタスク） |
|---|---|---|---|
| Phase 0 契約とツール能力確認 | Phase 1に必要な電気・Evidenceの設計グラフschema、tool envelope（型付き入出力・idempotency key・副作用分類）、機械可読gate matrix、error taxonomy、event log payload schema、SDK統合骨組みを最小限確定する。FWパッケージschemaは後付けによるEvidence一斉失効を避けるため、このフェーズで確定する。`kicad-cli`とfreeroutingの能力プローブ（版検出、不在検出、非決定性の実測と正規化規則の確定）を行う | 自然言語対話、汎用最適化、自動発注、Phase 1〜3の投影一貫生成、Phase 1で不要なschemaの作り込み | 手書きの最小グラフがPhase 1に必要なschema検証を通り、patchから影響node・再実行gate・失効Evidenceを導出できる。`kicad-cli`とfreeroutingの版・不在・非決定性をプローブしEvidenceとして記録できる。schema違反・版不明・非決定を注入すると停止する（negative test） |
| Phase 1 電気レーン最小縦切り | fixture要件→固定部品→netlist/BOM→決定論的配置→外部router（freerouting DSN/SES）→`kicad-cli` ERC/DRC→Gerber/drill | 筐体、知識ベース、FW実装、自然言語入力、自動発注、汎用router自作 | 単一コマンドでfixtureからGerber/drillまで到達し、`kicad-cli`と独立parser（sexpdata系＋gerbonara）の二重で再読込できる。同一入力の再実行で成果物hashが一致し、外部processの副作用が重複しない。配線不能・ERC違反・router不在を注入すると停止する（negative test） |
| Phase 2 機械レーン最小縦切り | 外形・部品高さ・connector位置からbuild123dで筐体を生成→干渉/clearance/肉厚→STEP/3MF | 電気レーン、レーン統合、知識ベース、FW実装、自然言語入力、自動発注 | 単一コマンドでfixtureから筐体を生成し、CAD kernelの妥当性・干渉・clearance・肉厚チェックを通過する。出力を再読込でき、同一入力の再実行で成果物hashが一致する。干渉・肉厚不足・CAD kernel不在を注入すると停止する（negative test） |
| Phase 3 レーン統合と共通ゲート | 同一fixtureから基板＋筐体を再生成し、ECAD↔MCAD交換（`kicad-cli pcb export step`）と高さ・keepoutの受け渡しを通す。tool envelopeを`kicad-cli`／freerouting／CAD kernelの主要経路へ適用 | 片レーンだけの合格で次段へ進むこと、協調修復、知識ベース、FW実装、自動発注、汎用router自作 | 基板＋筐体を同一fixtureから再生成し、ECAD↔MCAD交換、高さ・keepout、干渉・clearance・肉厚の共通ゲートに合格する。片レーンだけを合格させたfixtureを注入すると停止する（negative test） |
| Phase 4 検証ゲートと根拠 | 多段検証、Evidence失効の伝播、実機テスト項目の自動生成 | 協調修復の自動化、長期知識loop、高精度SI・熱解析 | 上流変更でstale化するEvidenceを検出して下流を不合格にでき、根拠付きテスト計画を生成できる。テスト項目は上流の設計根拠・チューニング注記から導出し、placeholderの存在をcoverage合格にしない |
| Phase 5 電気↔機械協調修復 | 相互制約の反復解決、優先度・根拠・調停の記録 | 自由な要件変更、未知影響の自動無視 | 配線不能、部品高さ超過、開口不足のfixtureを両レーンで修復できる。注入caseに加えて未注入caseで一般化を測り、保護対象は祖先pathの丸ごと置換も却下する。修復の合否は修復器と独立な検証で判定する |
| Phase 6 知識ループ | fab DFM、造形不良、実測を構造化し次設計へ適用 | 未検証のLLM学習、設計データの無断共有 | 同一スコープの不良が再発しない候補ルールをEvidence付きで登録できる。適用は実際にツール入力へ届いていることをnegative testで示す（ルールやライブラリ修正を壊すと検証が不合格になる）。`applicability: unknown`の知識は適用対象にせず合格に到達させない。入力の少なくとも1件は実fab指摘または実測とし、fixtureのみでは完了としない |
| Phase 7 要件対話とsourcing | 自然言語→構造化要件、sourcing API、データシート抽出、部品ライブラリの設計経路への接続 | 自動発注、契約判断の自動化 | 部品候補と筐体材料候補を出所・取得時点付きで比較し、未確認事項を質問できる。価格・在庫の期限切れは停止条件として働く。token／moneyの実測値と`unknown`境界を記録する |
| Phase 8 長時間ラン運用 | task ledger、checkpoint/resume、side-effect journal、予算、watchdog、golden task回帰 | 無制限retry、根拠なしの自動復旧 | 強制終了後に同じrevisionから再開して完走し、成果物hash・gate結果・event列・台帳が一致する。同一入力の外部副作用を重複させない |
| Phase 9 FW連携と仮想実機 | FWパッケージ投影、OpenHandsによるFW実装、ピン割当整合ゲート<br/>仮想実機（Renode一次候補、QEMU／wokwi-cliは二次保持）<br/>実機書き込みとログ取得（probe-rs一次候補、pyOCDは二次保持） | 独自コンパイラ・独自シミュレータの開発<br/>仮想試験を実測の代替にすること | 同一設計グラフから基板・筐体・FWパッケージを生成し、FWのビルドとピン割当整合ゲートを通す。ピン割当を故意にずらすと不合格になる。仮想実機のログは仮想検証Evidence、実機のログは実測Evidenceとして、条件・版付きで分類して設計グラフへ記録できる |
| Phase 10 自働発注 | 見積dry-run、基板＋部品＋実装＋送料＋税＋筐体の**総発注額**、発注前最終ゲート、API ordering | 予算超過、価格stale、契約不明の発注 | 副作用のない見積dry-runで総発注額と最終ゲート結果を再現でき、実発注は予算内かつ最終ゲート合格のときだけ実行される。予算超過・stale価格・ゲート未実行を注入すると発注に到達しない |
| Phase 11 ローカル製造 | 3Dプリンタ、卓上CNC、材料・機械profile、ローカル版と外注版 | 量産能力の無根拠な保証 | 同じgraphからローカル試作版と外注版を生成し、機械条件・測定Evidenceを比較できる |

フェーズ境界の変更は本表を更新し、既存のゴールデンタスクを再実行する。

## 最短で動かす経路

最初のマイルストーンはPhase 0＋Phase 1とする。Phase 0ではPhase 1のゴールデンタスクに
必要な契約だけを最小限確定し、契約を作り込みすぎない。Phase 1到達時点で、fixtureを
入れると単一コマンドでGerber/drillが出る状態を作る。筐体とレーン統合はPhase 2・3へ
分離するため、最初の動く到達点を待たせない。

## 依存関係と並行

```mermaid
flowchart LR
    P0["Phase 0 契約とツール能力確認"] --> P1["Phase 1 電気レーン最小縦切り"]
    P0 --> P2["Phase 2 機械レーン最小縦切り"]
    P1 --> P3["Phase 3 レーン統合と共通ゲート"]
    P2 --> P3
    P3 --> P4["Phase 4 検証ゲートと根拠"]
    P4 --> P5["Phase 5 電気↔機械協調修復"]
    P5 --> P6["Phase 6 知識ループ"]
    P4 --> P7["Phase 7 要件対話とsourcing"]
    P3 --> P8["Phase 8 長時間ラン運用"]
    P0 -.->|FWパッケージschema| P9["Phase 9 FW連携と仮想実機"]
    P7 --> P10["Phase 10 自働発注"]
    P8 --> P10
    P6 --> P11["Phase 11 ローカル製造"]
```

Phase 1とPhase 2は入力の性質が異なるため並行できる。Phase 9のFWパッケージschemaは
Phase 0の契約に含め、投影と整合ゲートの実装だけをPhase 9で行う。schemaを後から
追加すると、Phase 1〜8のEvidenceが一斉に失効するためである。Phase 10はPhase 7の
価格出所とPhase 8の副作用journalの両方を前提にする。

## 実機Evidence待ちの扱い

実機の製造・組立・測定はユーザー側の作業であり、エージェントの実行時間で閉じない。
したがって各フェーズの完了判定は、(a)測定計画の生成、(b)測定Evidenceの取り込み経路、
(c)取り込んだEvidenceによる合否判定と失効伝播、までを対象とする。実測値そのものは
「実機Evidence待ち」として対象revisionごとに管理し、フェーズを無期限にblockしない。
仮想検証Evidence（仮想実機・シミュレーション結果）は実測Evidenceの代替にはしない。
実機ログだけを実測Evidenceとして扱い、仮想実機のログは仮想検証Evidenceとして分類する。

## 撤退・見直し条件

次のいずれかに該当した場合、当該フェーズを止めて本書と[`tool-selection.md`](tool-selection.md)を
見直す。回避策を実装で隠さない。

- 外部ツールの非決定性が正規化規則で閉じない。
- 一次採用ツールのライセンス条件が想定した結合方式と整合しない。
- ゴールデンタスクの完了条件を、negative testなしでしか満たせない。
- 予算実測が想定の桁を超え、golden task回帰を日常的に回せない。
- Phase 0でPhase 1に不要な契約・schemaの作り込みが先行し、最短で動かす経路を遅延させる。

## 未決事項

- Phase 9のFW範囲。FWパッケージschemaはPhase 0に含めるが、投影の一部（ピン割当表のみ）を
  Phase 9で先行生成するかは未決。
- Phase 6の「実fab指摘または実測を1件以上」を満たす入手経路（実発注時期に依存）。
- Phase 10の見積dry-runを提供しない発注APIがある場合の代替検証手段。
- golden taskの実行頻度と、CIで回す範囲・ローカル限定にする範囲の切り分け。
