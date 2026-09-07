# 実装ロードマップ 将来構想

> ステータス: マイルストーン化していない将来構想

本書は[`roadmap.md`](roadmap.md)から分離した将来構想を保持する。いずれも現在の実装範囲の
約束ではなく、マイルストーンへ移す際は[`roadmap.md`](roadmap.md)の現行実装計画と
フェーズ横断の検証要件に従って完了条件を定義する。

## 将来構想

現行実装計画の次に残る機能は、次の構想として保持する。既にマイルストーン化した
範囲は各マイルストーンへのpointerとして示し、未着手の構想だけを残す。

- routing後のvia mask開口を含む投影・実測・再配置の反復
- 複数fab profileと製造データ契約の拡張はマイルストーン14.2へ移行済み
- 長時間運用、ローカル製造
- 高密度基板、認証設計は将来構想として残し、多層・EMC/ESD相当はマイルストーン16.1・16.3へ、熱・SIはマイルストーン10.2・10.3へ移行済み
- agent自体のコンテナ化と配布済みACD image
- 複数instanceのshared storage負荷検証
- OpenBlink（mruby/cとBLEによる無線コード差し替え）を用いたFW動作の反復探索
- FPGA（GOWIN等）への対応。FPGAロジック（HDL・ネットリスト）とビットストリーム生成を
  宣言由来の設計contractとして扱い、既存のFW laneやピン割当ゲートと同様の決定論的な
  投影・検証境界を持たせる。合否は決定論的ゲートで判定し、ツールチェーン（GOWIN EDA等）は
  subprocess呼び出しに限定する。導出できない割当・制約はunknownとしてfail-closedにする。
- 組み合わせて使用するPC側のソフト開発（WebGUI等）。完成した基板・製品と組み合わせて
  動作するPC側アプリ・WebGUIの生成
- 組み合わせて使用するサーバ側のソフト開発（バックエンド・フロントエンド）。製品と連携する
  サーバ側ソフトの開発
- 組み合わせて使用するスマホアプリ開発。製品と連携するスマホアプリの開発
- 分野横断の責務割当と、ものづくりアイデアのブラッシュアップはマイルストーン21へ移行済み
- ワイヤハーネス設計。基板外配線（電線、ケーブル、FFC/FPC、コネクタ）を宣言由来の
  設計contractとして扱い、基板設計と同じ決定論的ゲートで検査する
- 信頼性試験（EMC、環境試験）の設計。試験規格への準拠確認にとどめず、規格が成立した
  背景と規格が模擬している実使用環境まで設計入力として宣言する
- ASIC製造（MPWシャトル）への対応。OpenSUSI-MPW（TR-1um）やTiny Tapeout等のオープンPDK
  シャトルへGDSIIを提出できるシリコンlaneと提出先アダプタを、基板laneと同じ決定論的
  ゲートとOrder Readiness Gateの拡張として扱う
- 長時間処理へのGPU活用。実機実測でwall-clockの78%を占めるFreeRouting（`board[3/12]`）に
  対し、GPU autorouter（OrthoRoute等）を宣言で選べる代替routerとして追加し、router差し替えを
  正規化hashと決定論的ゲートの境界内に収める。GPUが効かない段（kicad-cli、ESP-IDF build、QEMU、
  CAD kernel）はcache・並列度で扱う

上記のPC側ソフト、サーバ側ソフト、スマホアプリは、いずれもVibeBBが設計するハードウェアと
組み合わせて動作する周辺ソフトウェアである。生成物はマイルストーン9の文書lane同様の
provenance規則に従い、authoritative Evidence境界とハードウェア設計の決定論的ゲートを
侵さない。採用する場合は認証・権限・Evidence境界の受入条件を新規ADRで定義し、
未定義の項目はunknownとしてfail-closedにする（agent-serverを対象外とする現行方針と同じ扱いである）。

### ワイヤハーネス

現行のlaneは基板と筐体を対象としており、基板外の配線は設計contractを持たない。取り込む
場合は、結線（from-to）、電線種別・断面積・絶縁体の耐圧と耐熱、シールドと撚り対、長さと
余長、曲げ半径、固定・保持点、コネクタのハウジング・端子・圧着仕様、誤挿入防止の
キーイングと極性を宣言contractとして定義し、Design Graphのnetと同じ正本から導出する。
検査は既存方針と同じく決定論的ゲートで行い、電圧降下と許容電流（周囲温度と束線による
ディレーティングを含む）、信号クラスが非互換なネットの同一ハーネス・隣接収容、筐体内の
経路長と可動部の屈曲、コネクタの嵌合回数と保持力といった宣言に対する述語を置く。
適用条件と有効域はマイルストーン14.2の契約registryで宣言し、宣言のない範囲はunknownとして
停止側へ集約する。冗長経路が同一ハーネスを共有していないかの検査はマイルストーン16.5の
単一故障点／共通原因検査と同じ述語群へ接続し、組付け順序の観点はマイルストーン18.3の
DFAレビューをL2所見として使う。ハーネス図、切断長表、圧着仕様表は再現可能な投影として
生成し、投影を設計入力へ逆流させない。採用する場合は、ハーネスnodeとコネクタnodeの
contract境界、基板netlistとの一貫性検査の範囲、実測Evidenceの境界を新規ADRで定義する。

### 信頼性試験（EMC・環境試験）

EMCと環境試験を、規格の試験項目を満たすかどうかの確認としてではなく、規格が模擬して
いる実使用環境のストレスに製品が耐えるかの設計として扱う構想である。試験規格は、過去の
事故・故障事例と、制定当時に想定された妨害源・設置環境・技術前提から導かれた代理条件で
ある。したがって、試験項目そのものではなく「その項目が模擬しているストレスと、それが
自製品の実使用でどう現れるか」を設計入力として宣言する。

取り込む場合は次を宣言contractとして定義する。

- 想定実使用環境。設置場所と設置形態、電源系統（系統電源、電池、車載、PoE等）と
  想定される過渡、近傍の妨害源と被妨害機器、気候区分と温湿度・結露・塵埃・腐食性ガス、
  振動・衝撃・落下、輸送と保管、ユーザ操作と接触経路、想定寿命と稼働率。
- 試験項目↔ストレス↔実使用条件の対応表。各試験項目について、模擬しているストレスと
  想定している実環境、その項目が成立した背景（一次情報の出所を含む）、自製品の実使用
  条件に対する厳しさの過不足を記録する。
- 対応表から導く設計要求。保護素子、リターンパスと接地、遮蔽と開口、コネクタと
  ケーブル引き回し、機構シールと材料選定、実装と接合部の熱疲労といった、既存の設計述語
  （マイルストーン16.3、16.5、10.2）へ落ちる要求として宣言する。

検査は、対応表の被覆をゲート化する。規格由来の試験項目が自製品の想定実使用ストレスを
覆っていない箇所（規格の想定外にあるストレス）はgapとして列挙し、設計要求か受容判断の
いずれかを宣言するまでunknownとしてfail-closedにする。逆に、想定実使用に照らして過剰な
項目も過剰として記録し、根拠なく緩めない。

境界は既存方針を維持する。規格への適合判定と認証の合否は行わず、L1は宣言と設計述語の
整合だけを判定する。加速試験モデルによる寿命換算（温度、温度サイクル、湿度等）は推定で
あることを明示し、authoritative Evidenceへ昇格しない。実試験の結果を取り込む場合は
マイルストーン5の実機フィードバックと同じく`measured` Evidenceとして扱い、測定条件・
設備・日時・供試体revisionを伴わない結果は受け付けない。規格文書は再配布せず、
参照は識別子と版のみを記録する。採用する場合は、対応表のcontract境界、背景記述の出所
要件、gap判定の停止条件、試験Evidenceの境界を新規ADRで定義する。

### ASIC製造（MPWシャトル）

基板・筐体・FWに加えて、設計者自身の集積回路をMPW（Multi-Project Wafer）シャトルで
製造する経路を取り込む構想である。前提となる調査結論は[`research/README.md`](research/README.md)の
「MPW shuttle services」に置く。調査の要点は、オープンPDK系シャトル（OpenSUSI-MPW、
Tiny Tapeout、ChipFoundry chipIgnite、IHP Open-Silicon MPW、wafer.space）の提出インタフェースが
「テンプレートrepoをfork → `info.yaml`相当の宣言 → GDS/netlistを配置 → GitHub Actionsで
precheck/DRC/LVS → Webフォームでrepo URLを提出 → 締切まで再提出可」に収斂していること、
および価格モデル（固定枠・tile課金・面積課金）、公開義務、地理制約、返却形態が提出先ごとに
異なることである。

取り込む場合は次を宣言contractとして定義する。

- PDK契約。`pdk.repo`、`pdk.ref`（commit hash）、`pdk.dir`（runset）を宣言し、provenanceへ
  記録する。import対象はApache-2.0等のNDAフリーPDK（TR-1um、SKY130、GF180MCU、
  IHP SG13G2）に限定し、GPL/AGPL資材はimport結合しない。
- シリコン設計契約。top cell名、die／ユーザ領域寸法、dbu、pad配置とESD規約、netlist
  （LVS対象）、デジタルの場合はRTLとハード化flow（LibreLane／OpenROAD）の版を宣言する。
- 提出先（shuttle）契約。提出先、対応PDK、締切、面積またはtile制約、価格、公開義務、
  地理制約（OpenSUSIは国内限定）、返却形態（DIP、devkit PCB、bare die、QFN、COB）を
  宣言し、締切・枠残数・価格が保存済み見積入力（マイルストーン7.1と同型）に無い場合は
  unknownとして停止側へ集約する。

検査は既存方針と同じく決定論的ゲートで行う。precheck（top cell一致、top-level cellの
唯一性、dbu、領域内）、DRC clean、LVS一致、antenna/ERC、MDP（Drawing layer→Mask layer）
変換後GDSのhashを、提出先テンプレートのCIと同じrunsetをdigest固定container内で実行して
判定する。ツールチェーン（KLayout、Magic／Netgen、xschem、ngspice、LibreLane／OpenROAD、
IIC-OSIC-TOOLS相当）はADR-0047のdocker-only方針に従いホストへ入れず、ホスト実行は
provisionalにとどめる。提出先が公開必須の場合は設計repoのライセンス表記と第三者IPの
帰属を検査し、非公開要件の設計からは公開必須の提出先を候補から除外する。提出repoの生成
（テンプレート準拠のディレクトリ、`info.yaml`、GDS、netlist）は再現可能な投影として扱い、
投影を設計入力へ逆流させない。

段階は、第1段でTR-1um（アナログ・小規模、DIP返却で既存基板laneへ接続しやすい）を
DryRun TEST枠で申込からSubmitまで通し、第2段でTiny Tapeout（デジタルRTL、国際）で
FW laneのRISC-V資産と接続し、第3段でIHP／GF180（面積課金、bare die／QFN）で基板上への
実装（COB／QFN footprint）まで電気・機械laneを通す順を想定する。採用する場合は、
シリコンlaneのcontract境界、PDK版とrunsetの固定方法、提出先アダプタのEvidence境界、
公開義務とライセンス検査の受入条件を新規ADRで定義し、未定義の項目はunknownとして
fail-closedにする。

### 長時間処理のGPU活用（GPU autorouterを含む）

第7回実機実測（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 14.5〜14.8）
では、GD1全lane（26 stage）のwall-clock 230〜234秒のうちFreeRoutingの`board[3/12]`が180秒
（78%）を占め、critical pathは`silkscreen-resolve`→`board-pipeline`であった。FW lane
（ESP-IDF build＋QEMU、116秒）と筐体lane（24秒）は基板laneの影に隠れ、基板laneの非routing段
（kicad-cli起動とGerber計測、約35秒）は既にprocess並列である。FreeRoutingはrouter threads・
JVM tuningのいずれでも短縮せず（156〜163秒、差4%以内）、12コア化の効果も約7%にとどまった。
第8回（15.3）では30×22mm・2層の`dual-beacon-tag`でFreeRouting 2.4.1が100 passで
`unrouted` 22→21にplateauし`not_converged`でfail-closedした。すなわち、短縮対象は
router単体であり、routerには「時間」と「収束」の2つの壁がある。GPU活用の調査結論は
[`research/README.md`](research/README.md)の「GPU acceleration」に置く。

調査の要点は次のとおりである。GPUで実質的に効く段はrouterだけである。OrthoRoute（MIT、
CUDA/CuPy、KiCad 9 IPC plugin、`.ORP`入力→`.ORS`出力のheadless mode、`--cpu-only` fallback、
Apple Metal fork）はPathFinder（負のcongestion交渉）をManhattan格子上でGPU SSSPにより解き、
rip-up／rerouteの反復回数で収束させる設計だが、対象は多層backplane・BGA escapeであり、
層ごとに水平／垂直を固定した格子とblind／buried viaを前提とするため、GD1級の2層・小面積
基板と一般fab profileには格子前提の整合検査が要る。ESP-IDF build、QEMU、kicad-cli、
Gerber計測、build123d／OCPはGPUの対象外であり、ngspiceのGPU版（CUSPICE）は数千トランジスタ
規模以上・ngspice-27系branchに限られ、現行のGD1回路規模では効果が無い。クラウドAI router
（DeepPCB等）は設計データを外部へ送るうえ再現可能なrunsetを固定できないため、L1の対象に
しない。

取り込む場合は次を宣言contractとして定義する。

- router契約。`routing_config.router`で`freerouting`（既定）／`orthoroute`／将来のCPU代替
  （Rust A*系のKiCadRoutingTools等、MIT）を選択し、router名・版・container digest・入力
  （DSNまたは`.ORP`）hash・出力（SESまたは`.ORS`）hash・反復回数上限をprovenanceへ記録する。
  routerを変えれば配線結果＝正規化hashは変わるため、router選択は設計入力の一部として
  revisionに束縛し、速度目的で暗黙に切り替えない。
- GPU実行環境契約。CUDA／ROCm／Metalのbackend、driver版、GPU名、VRAM、
  container runtime（`--gpus`／NVIDIA Container Toolkit）を宣言し、起動前preflightで検査する。
  GPU不在・VRAM不足・driver不整合はunknownとして停止側へ集約し、CPU fallbackへ
  黙って倒さない（fallbackもrouter契約で明示選択した場合だけ許す）。OrthoRouteの格子
  VRAMは面積×層数÷pitch²で決まり、100×100mm・6層・0.4mm pitchで8〜12 GBが目安である。
- 格子・fab整合契約。routerがManhattan格子とblind／buried viaを前提とする場合、fab profile
  （層数、via種別、最小trace／clearance）と格子pitch・層方向割当の整合を述語として置き、
  不整合はfail-closedにする。

検査は既存方針と同じく決定論的ゲートで行う。router出力をKiCadへ取り込んだ後のDRC、
未配線数0、netlist一致（配線後のconnectivity）を合否とし、routerが報告する収束状態は
参考値にとどめる。GPU実行は浮動小数の縮約順序やatomicの競合で非決定になり得るため、
router契約に「同一入力を2回実行して出力hashが一致すること」の再現性検査を含め、不一致を
出すbackendはprovisionalに限定してauthoritative Evidenceを生成しない。ツールはADR-0047の
docker-only方針に従い、CUDA runtimeを含むdigest固定imageへ置き、ホストGPU実行は
provisionalにとどめる。routerの反復回数上限・pass数・optimizer閾値は出力＝hashを変えるため、
速度目的で緩めない。

GPUが効かない段は別手段で扱う。反復（VibeBB loopの2周目以降）はDSN／SES cache
（`--cache-dir`／`--resume`）で`board[3/12]`を省き、FW laneはESP-IDF `--ccache`
（`IDF_CCACHE_ENABLE`）とcontainer内cache dirの永続化、`run_in_workspace.py --source mounted`
の依存同期overhead（約10秒台）はimage同梱venvの再利用で削る。いずれも短縮を主張する場合は
同一入力の実測を[`operations.md`](operations.md)へ記録する（AGENTS.mdの並列実行規約と同じ）。

段階は、第1段でGD1と`dual-beacon-tag`をOrthoRoute headless（`--cpu-only`とGPU）で
単独実行し、収束・DRC・所要時間・再現性を実測して採否を決める。OrthoRouteの`.ORP`は現状
KiCad GUIのIPC経由でplugin側が書き出すため、`.kicad_pcb`から`.ORP`を決定論的に生成する経路
（またはkicad-cli相当のheadless IPC）が無ければcontainer実行に載らない点をこの段で確認する。
第2段でrouter契約とGPU
preflightをpipelineへ入れ、第3段でGPU付きdigest固定imageと`container-gates`のGPU runner
（self-hosted）を整備する順を想定する。採用する場合は、router差し替えのcontract境界、
GPU非決定性の扱い、fallback条件、GPU imageのdigest固定とCI runnerの受入条件を新規ADRで
定義し、未定義の項目はunknownとしてfail-closedにする。

### OpenBlink

OpenBlinkはmruby/cのVMをBLE経由で差し替えることで、マイコンを再起動せずに
Rubyコードを入れ替える構想である。ACDへ取り込む場合は、ドライバ、BLEスタック、
RTOSを含むC層を宣言由来のFW契約として扱い、無線で差し替えるRuby層はL2の探索・
操舵経路に限定する。差し替えたコードの実行結果はauthoritative Evidenceへ昇格させず、
合否は既存のQEMU実行・実機フィードバックとdigest固定containerの決定論的ゲートで判定する。
採用する場合は、対象ハードウェア（ESP32系を含む）、mruby/cおよびOpenBlink本体の
ライセンス境界、BLE接続・鍵素材の取り扱い境界を新規ADRで定義し、未定義の項目は
unknownとしてfail-closedにする。
