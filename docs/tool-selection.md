# 実装ツール選定

> ステータス: Draft  
> 対象: Phase 0〜1を主とする実装ツールの採否、調査日 2026-08-11 UTC

本書は、ACD実装で呼び出す外部ツールの採否と、その設計根拠・代替案・未決事項を正とする。
各ツールの機能・ライセンス・版の調査事実は [`prior-art.md`](prior-art.md)、ツール契約と
adapter境界は [`architecture.md`](architecture.md)、工程ごとのゲートは
[`design-flow.md`](design-flow.md)、フェーズ境界は [`roadmap.md`](roadmap.md)を参照する。

本書は選定「判断」を記録するものであり、ライセンスの法的結論ではない。GPL/AGPL/LGPLの
利用形態、binary同梱、改変配布、ネットワーク提供の評価は法務判断を要する。

## 選定基準

### 失格条件（いずれかに該当すれば一次候補にしない）

- ヘッドレスで実行できない、またはGUI操作を前提とする。
- 入力・出力がファイルまたは構造化データとして固定できない。
- 版を固定できない、または対象版の一次情報を確認できない。
- ACD本体（BSD 3-Clause想定）へのimport結合がライセンス上未解決である。
- 実行に外部サービスの認証・契約が必須で、既定の検証経路に組み込むと再現できない。

### 必須条件

- 版番号を固定でき、同一入力・同一版で同じ成果物またはレポートを生成できる。
- ツール名、版、入力hash、出力hash、収束状態を記録できる。
- 失敗時に成功と区別できる終了状態または構造化診断を返す。
- adapter境界で差し替えられる（特定ツールをcoreの意味論に埋め込まない）。

### 加点条件

- ライセンスがpermissive（MIT／BSD／Apache-2.0）で、import結合の選択肢を残せる。
- テキスト形式の入出力で、差分レビューとgit保存に向く。
- 出力を別ツールで再読込・交差検証できる。

### 判定区分

| 区分 | 意味 |
|---|---|
| 一次採用 | Phase 0〜1の実装で既定として呼ぶ |
| 二次保持 | adapterの代替実装として設計に残すが、既定にはしない |
| 継続調査 | 一次情報またはライセンスが未確認で、採否を保留する |
| 不採用 | 上記の失格条件または用途不一致で候補から外す |

## 結合方式の方針

ライセンス境界（[`prior-art.md`](prior-art.md) 20章）を実装形態へ落とすと、次の3方式になる。

| 方式 | 対象 | 実装上の意味 |
|---|---|---|
| import結合 | permissiveのみ | ACDのPython依存として宣言し、同一プロセスで呼ぶ |
| 外部プロセス | GPL／AGPL／LGPL／混在／未確認 | 実行ファイルを別プロセスで起動し、ファイルと終了状態だけを受け取る |
| ユーザー環境前提 | AGPL、同梱条件が重いもの | ACD配布物へ同梱せず、利用者環境の既存インストールを検出して使う |

外部プロセス化はライセンス義務を消さない。binary同梱、改変、再配布、ネットワーク提供の
可否は別に判断する。

## 電気レーンの選定

### 回路の意図記述とnetlist生成

| 候補 | ライセンス | 判定 | 根拠 |
|---|---|---|---|
| ACD設計グラフ→netlist投影（自前） | 該当なし | 一次採用 | 正規データはACDの設計グラフである。外部DSLを正にすると正が二重化し、根拠・出所・Evidenceの結び付けを外部実装へ依存させる |
| [SKiDL](https://github.com/devbisme/skidl) | MIT | 二次保持 | MITでimport可能。netlist投影の交差検証、またはKiCad netlist生成の実装短縮に使える |
| [atopile](https://github.com/atopile/atopile)、[diodeinc/pcb](https://github.com/diodeinc/pcb)、[tscircuit](https://github.com/tscircuit/tscircuit) | MIT | 不採用（設計参照） | いずれも自身のDSL／JSONを正とする設計であり、ACDの正規グラフと競合する。制約表現とKiCad投影の設計参照としては有用 |

ACDは回路図レスであり、人間が書くDSLを入力の既定にしない。この判断は、DSLを正とする
先行実装群との最大の差分であり、[`architecture.md`](architecture.md)の「投影」原則に従う。

### ECAD投影と決定論的検証（`kicad-cli`以外の検討）

| 候補 | ライセンス | ヘッドレス実行 | 判定 |
|---|---|---|---|
| KiCad 10 `kicad-cli` | GPL-3.0-or-later（第三者・例外あり） | `fp`／`jobset`／`pcb`／`sch`／`sym`。ERC、DRC、Gerber、drill、BOM、PDF、STEP | 一次採用（外部プロセス限定） |
| [LibrePCB](https://librepcb.org/docs/cli/) `librepcb-cli` | LICENSE本文を取得できず | `open-project --erc --drc --run-jobs --outdir`。公式docsがCI利用を明記。ただしX serverが必要で、ヘッドレス環境では`xvfb-run`が必要 | 二次保持 |
| [Horizon EDA](https://github.com/horizon-eda/horizon) | 公式表記はGPLv3、LICENSE本文は取得できず | 安定したバッチ用サブコマンド契約を公式docsで確認できず | 継続調査 |
| [pcb-rnd（Ringdove）](https://github.com/pcb-rnd/pcb-rnd) | 取得できず | 版ごとのCLI契約を一次確認できず | 継続調査 |
| gEDA/PCB | 取得できず | 現行版のヘッドレス契約を一次確認できず | 不採用 |
| [PcbDraw](https://github.com/yaqwsx/PcbDraw) | 未確認 | KiCad PCBの2D renderのみ | 不採用（用途不一致） |

`kicad-cli`を一次採用する理由は、(a)ERC/DRC/Gerber/drill/BOM/STEPを単一のCLIで
ファイル→成果物として実行でき、(b)版と入力を固定した検証Evidenceを作れ、(c)初期ターゲット
（1〜4層リジッド基板）に対する製造データ形式が実務で通っていることである。GPLである点は、
ACDへlibrary結合せず外部プロセスとして呼ぶことで境界を分ける。

`librepcb-cli`を二次保持にする理由は、公式docsがERC/DRCとoutput jobのCI実行を明記して
おり、ECAD engineをadapterで差し替えられることを設計上示せる点にある。X server依存と
LICENSE本文未取得のため、Phase 0〜1の既定にはしない。

したがって、ECAD adapterは`kicad-cli`固有の引数をcoreへ露出させず、「ERC実行」「DRC実行」
「製造データ出力」「STEP出力」という能力単位のインターフェースにする。

### KiCadファイルのparse／patch

| 候補 | ライセンス | 判定 | 根拠 |
|---|---|---|---|
| [sexpdata](https://pypi.org/project/sexpdata/) ＋ ACD側のKiCadスキーマ層 | BSD-2-Clause（1.0.2、2024-01-09、PyPI） | 一次採用 | permissiveでimportでき、S-expressionの読み書きが決定論的。KiCadの意味論はACD側で型付けし、対応形式版を明示する |
| [kicad-skip](https://github.com/psychogenic/kicad-skip) | LGPL-2.1-only | 二次保持 | LGPLのため結合条件の確認が前提。外部プロセス化またはユーザー環境前提でのみ検討 |
| [kiutils](https://github.com/mvnmgrx/kiutils) | GPL-3.0-only | 不採用 | Python importがGPL結合になる。parserを外部プロセス化する利点が小さい |
| [kicad_parse_gen](https://crates.io/crates/kicad_parse_gen) | MIT OR Apache-2.0（7.0.2、2018-01-29） | 不採用 | permissiveだが2018年で、KiCad 10形式の網羅を確認できない |
| `kicadfiles`（PyPI） | metadataにlicenseなし、本文取得できず | 継続調査 | ライセンスと形式網羅が未確認 |
| KiCad IPC API／[kicad-python](https://docs.kicad.org/kicad-python-main/) | KiCad配布物と同体系 | 不採用（Phase 0〜1） | KiCad 10のIPCはGUI起動中のPCB editorが対象で、回路図ファイルのAPIは公開されていない。ヘッドレスIPC serverは公式docsでKiCad 11の追加とされる |

ACDのpatchは正規グラフ側で表現し、KiCadファイルは投影である。したがって必要なのは
「投影の生成」と「投影の再読込確認」であり、外部の高機能KiCad patcherへの依存は最小にする。
生成物の再読込は`kicad-cli`と自前parserの二重で確認し、片方だけを合格根拠にしない。

### 配置（placement）

一次情報で、permissiveかつ現行のPCB placement最適化OSSを確認できなかった。ASIC向けの
OpenROAD、Coloquinte、CoriolisはPCB配置の代替と確認していない。

したがってPhase 1の配置は、[`roadmap.md`](roadmap.md)どおりACD自前の決定論的配置とする。
候補生成をLLMに任せる場合も、判定は幾何・製造制約チェックで行う。

### 配線（routing）

| 候補 | ライセンス | 判定 |
|---|---|---|
| [freerouting](https://github.com/freerouting/freerouting) | GPL-3.0-only | 一次採用（外部プロセス、ユーザー環境前提） |
| KiCad内蔵router | KiCad本体 | 不採用 |
| その他OSS autorouter | 未確認 | 継続調査 |

KiCadの内蔵routerは対話操作用であり、公開されたヘッドレスautoroute契約を確認できなかった。
permissiveな代替も一次情報の範囲で確認できていない。よってPhase 1はfreeroutingを
DSN→SES／DRCレポートの交換境界で呼び、JavaコードはACDへ結合しない。JRE前提と
GPL binaryの同梱可否は未決事項として残す。SES単独を合格証拠にせず、KiCadへ再読込して
`kicad-cli pcb drc`で判定する。router差し替え余地を保つため、adapterの入出力はDSN/SESと
DRCレポートに限定する。

### 製造データの独立検証

| 候補 | ライセンス | 判定 | 根拠 |
|---|---|---|---|
| `kicad-cli pcb drc`／`sch erc` | GPL（外部プロセス） | 一次採用 | 設計側ルールの判定 |
| [gerbonara](https://gitlab.com/gerbolyze/gerbonara) | Apache-2.0（1.6.3、2026-04-25、PyPI） | 一次採用（import） | Gerber RS-274-X、Excellon/XNC、IPC-356を独立に再読込でき、出力形式・座標・数量の検証に使える |
| [gerbv](https://github.com/gerbv/gerbv) | 取得できず | 継続調査 | 版ごとのCLI契約が未確認 |
| [gerber2blend](https://github.com/antmicro/gerber2blend) | Apache-2.0 | 不採用（用途不一致） | Gerber→Blender 3Dモデル生成であり、DFM判定器ではない |

gerbonaraはDFM合否判定器ではない。fab能力との突き合わせ（クリアランス、アニュラリング、
最小穴径など）はfab profileを入力とするACD側の判定として実装し、gerbonaraは出力の
再読込と幾何抽出に使う。

### 電気シミュレーション

| 候補 | ライセンス | 判定 |
|---|---|---|
| [ngspice](https://ngspice.sourceforge.io/) | 混在（要SBOM） | 一次採用（外部プロセス） |
| [Xyce](https://xyce.sandia.gov/) | BSD-3-Clause（本文未取得） | 二次保持（外部プロセス） |
| PySpice、spicelib | GPL-3.0系 | 不採用 |
| Qucs-S | GPL-2.0-or-later、かつGUI frontend | 不採用 |
| lcapy | licenseを確認できず | 継続調査 |
| SPICE OPUS、cpp-spice系 | 未確認 | 継続調査 |

netlistとmodelの生成、収束判定、測定値の抽出はACD側で行い、simulator実行ファイルは
外部プロセスとする。modelの出所と収束状態を記録しない結果は合格扱いにしない。

### SI／RF、EM

`scikit-rf`（BSD想定、本文未取得）と`openEMS`（GPL想定、外部プロセス）は、Phase 2以降の
対象として継続調査に置く。初期ターゲットの1〜4層基板では既定のゲートにしない。

## 機械レーンの選定

### code-CAD／kernel

| 候補 | ライセンス | 判定 | 根拠 |
|---|---|---|---|
| [build123d](https://github.com/gumyr/build123d) | Apache-2.0 | 一次採用（import） | permissiveでPython APIがBREPを直接扱い、STEP/STL出力とヘッドレス実行ができる |
| [OCP](https://github.com/CadQuery/OCP)／[OCCT](https://www.opencascade.com/license/) | Apache-2.0（wrapper）／LGPL-2.1 WITH OCCT-exception-1.0 | 一次採用（build123dの依存として） | kernel本体の結合条件はwheel構成に依存するため、法務確認を未決事項に残す |
| [CadQuery](https://github.com/CadQuery/cadquery) | Apache-2.0 | 二次保持 | 同一kernel上の代替API |
| [trimesh](https://github.com/mikedh/trimesh) | MIT（5.0.0、2026-08-01） | 一次採用（import） | mesh healing、watertight判定、体積・bboxなどの事前検査 |
| [manifold](https://github.com/elalish/manifold) | Apache-2.0（v3.5.2、2026-06-27） | 二次保持 | 堅牢なmesh booleanが必要になった場合の候補。BREPの代替ではない |
| [FreeCAD](https://github.com/FreeCAD/FreeCAD) | LGPL-2.1中心、混在 | 不採用（Phase 0〜1） | 同一kernelへPythonから直接到達できるため、GUIアプリを介する必要がない |
| [OpenSCAD](https://openscad.org/) | GPL想定 | 不採用 | mesh CSGで公差・BREP診断に向かず、GPL境界を追加する利点がない |
| [OpenJSCAD](https://github.com/jscad/OpenJSCAD.org) | MIT | 不採用 | Node.js依存を追加し、BREP kernelを持たない |
| [libfive](https://github.com/libfive/libfive) | core／bindingsはMPL-2.0、Studio等はGPL系 | 不採用 | 単一ライセンスとして扱えず、BREP前提の診断に合わない |
| [sdfx](https://github.com/sdfxai/sdfx) | AGPL-3.0 | 不採用 | ライセンスと用途の双方が不一致 |
| [Zoo/KCL](https://zoo.dev/docs) | OSS境界・SPDX未確認 | 継続調査 | 商用サービスとOSS CLIの境界を一次確認できず |

筐体生成はbuild123dのPython APIを直接使い、外部の筐体生成CLIを既定にしない。
[cad-khana](https://github.com/cyberchitta/cad-khana)と
[agentcad](https://github.com/jdilla1277/agentcad)（ともにApache-2.0）は、diagnostics
JSONの設計参照および二次保持とし、ACDのゲートは自前のdiagnostics契約で定義する。

### ECAD↔MCAD交換

| 候補 | 判定 | 根拠 |
|---|---|---|
| `kicad-cli pcb export step` | 一次採用 | 公式CLIでboard→STEPを実行でき、`--board-only`、`--no-components`、`--include-tracks`、`--user-origin`等で出力範囲を固定できる。使用した3D modelとオプションを入力Evidenceに含める |
| [KiCad StepUp](https://github.com/easyw/kicadStepUpMod) | 不採用 | LICENSE本文が未確認で、FreeCAD workbench前提のため境界が複雑 |
| IDF 2.0/3.0、prostep ivip IDX、STEP AP242 | 継続調査 | 交換契約としてPhase 3以降に評価する |

STEP出力の成功は嵌合の合格ではない。干渉・クリアランス・肉厚はkernel側で再計算する。

### 造形可能性（slicer）

PrusaSlicer、CuraEngine、OrcaSlicerはいずれもAGPL（Orcaは本文未取得）である。よって
ACD配布物へ同梱せず、ユーザー環境前提の外部プロセスとし、Phase 9まで既定ゲートにしない。
採用時はslicer名、版、profile、入力hashをEvidenceに固定する。

## FWレーンの選定

FWの実装とビルドはOpenHands本来のソフトウェア開発能力を使う（[`openhands-integration.md`](openhands-integration.md)）。
ACDが選ぶのは、ピン割当整合とログ取得のための外部ツールである。

| 用途 | 候補 | ライセンス | 判定 |
|---|---|---|---|
| 仮想実機 | [Renode](https://github.com/renode/renode) | MIT（v1.16.1、2026-02-16） | 一次候補（Phase 7） |
| 仮想実機 | QEMU | GPL-2.0-or-later | 二次保持（外部プロセス） |
| 仮想実機 | [wokwi-cli](https://github.com/wokwi/wokwi-cli) | MIT（v0.26.1、2026-02-23） | 二次保持 |
| 実機書き込み・ログ | [probe-rs](https://github.com/probe-rs/probe-rs) | MIT OR Apache-2.0（release pageは0.32.0） | 一次候補（Phase 7） |
| 実機書き込み・ログ | [pyOCD](https://github.com/pyocd/pyOCD) | Apache-2.0（PyPI 0.45.1、2026-07-21） | 二次保持 |

wokwi-cliはMITだがtokenと外部サービスが必要であり、既定の検証経路には置かない。
probe-rsとpyOCDは物理probe前提であり、仮想実機の代替ではない。仮想実機のログを
実測Evidenceとして扱わない原則は[`AGENTS.md`](../AGENTS.md)のとおりとする。

## 調達・製造APIの選定

| 用途 | 候補 | 判定 | 根拠 |
|---|---|---|---|
| 部品価格・在庫・lifecycle | Nexar/Octopart、Digi-Key、Mouser | 一次候補（Phase 5） | 公式APIで出所・取得時点・通貨・地域を記録できる。契約と資格情報が前提 |
| 部品データ | LCSCの非公式endpoint、`jlcparts`のmirror | 不採用（既定にしない） | 公式APIではなく、規約・rate limit・安定性が未確認。snapshotを固定した参考情報にとどめる |
| KiCadライブラリ生成 | [easyeda2kicad](https://github.com/uPesy/easyeda2kicad.py) | 不採用 | AGPL-3.0 |
| PCB見積・発注 | JLCPCB API、PCBWay partner API | 一次候補（Phase 8） | 見積と発注を分離し、総発注額と最終ゲートを前提にする |
| 筐体見積・発注 | JLC3DP、Slant3D、Xometry partner API | 継続調査（Phase 8〜9） | 権限範囲が契約依存 |

認証不要でpermissiveな部品データAPIは一次確認できなかった。よって部品Evidenceは、
契約済みAPIまたは利用者が投入したデータシート・型番を出所として扱う。

## 環境前提と運用上の注意

- `kicad-cli`、freerouting、ngspice、slicerは外部プロセスであり、版検出と不在検出を
  adapterの責務とする。不在時はunknownとして扱い、合格にしない。
- freeroutingはJREを必要とする。`librepcb-cli`を評価する場合はX server（`xvfb-run`）が必要になる。
- import依存は現時点でpermissiveのみ（`sexpdata`、`gerbonara`、`build123d`、`OCP`、`trimesh`）とし、
  依存追加時にSPDXとSBOMを更新する。
- 外部プロセスのbinaryはACD配布物へ同梱しない前提で設計し、同梱が必要になった時点で
  法務確認を行う。

## 未決事項

- OCCTのLGPL＋例外が、OCP wheel経由のimport結合でどう適用されるか。
- GPL/AGPL binary（`kicad-cli`、freerouting、slicer）の同梱・配布方針と、
  本リポジトリのLICENSE（BSD 3-Clause）との整合。
- LibrePCB、Horizon EDA、pcb-rnd、gerbv、`kicadfiles`、lcapy、Zoo/KCLのLICENSE本文と現行版。
- freeroutingの代替となるpermissive autorouter、およびPCB placement最適化OSSの再調査。
- KiCad 11のヘッドレスIPC serverが提供された場合の、`kicad-cli`とIPCの責務分担。
- 部品データのpermissiveな一次入手経路。
- `sexpdata`ベースのKiCadスキーマ層が対応するKiCadファイル形式版の範囲。

## 検証状況の注記

本書の版・日付・SPDXは、公式docs、公式releaseページ、PyPI／crates.ioの公開metadata、
LICENSE本文のうち、調査時に取得できたものだけを根拠にした。今回の調査環境ではGitHub
APIが403を返したため、多くのGitHub由来の`releases/latest`と`tags`を取得できていない。
「取得できず」「未確認」は解消済みとして扱わず、採用確定前に一次情報を再取得する。
