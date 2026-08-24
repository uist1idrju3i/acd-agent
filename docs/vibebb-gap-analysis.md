# VibeBBをacd-agent単体で実現するための機能ギャップ一覧

本書は、`compact-sensor-node-1`の設計演習から得た改善提案（実装計画）である。
ロードマップ上は[`roadmap.md`](roadmap.md)のマイルストーン14に位置付ける。
VibeBBの体験ループは[`README.md`](../README.md)の定義に従い、
「語る → AIが設計し決定論的ゲートで検証する → 作って試す → 測定結果を次の設計へ返す」
である。ここで言う「acd-agent単体」は、**設計判断の探索と収束をacd-agent側
(Skill + 決定論的ゲート + pipeline)が担い、人間や汎用コーディングエージェントが座標・
GPIO・寸法を手で決めない状態**を指す。

本一覧は、GD1と要件の異なる小型ボードを実機OpenHands環境で設計した際に実際に
詰まった箇所を根拠とする。「実測根拠」欄が空の項目は文書由来の未実装項目である。
決定論的ゲートの権限とfail-closed境界を変更する提案ではない。

A〜Gは設計演習で直接詰まった箇所、H〜Kは演習後に文書とコードベース全体を横断して
再確認した結果であり、汎用エージェントが不在の場合にVibeBB体験を妨げる項目を含む。

## A. 会話から設計入力を作る経路（最大の欠落）

| # | 不足機能 | 現状 | 実測根拠 |
|---|---|---|---|
| A-1 | 会話→要件レコードの変換 | 達成（14.5）。要件レコード化と要件差分compilerを追加し、会話由来の要件をgraph変更へ接続できる。ただし要件→graph段のloop内取り込みはL-3として残る | 変更したREQ-010／REQ-011の文面は手作業更新であり、GPIO変更との整合を機械検査できなかった |
| A-2 | 任意設計向けfixtureビルダー | 達成（14.5）。任意設計向けfixture builderを追加した。ただし要件→graph段のloop内取り込みはL-3として残る | 変異fixtureは自作スクリプトでGD1 graphを書き換えて生成した。acd-agent内には該当機能が無い |
| A-3 | 要件差分→graph差分のコンパイラ | 達成（14.5）。要件差分compilerが接続・FWピン・テストポイント・シルク文字・rationaleを同時に更新する。ただしloop内取り込みはL-3として残る | 上記4箇所をすべて手で書き換えた。1箇所落とすとresolverかrationale coverageで落ちる |
| A-4 | 部品選定とlibrary provenanceの自動化 | 達成（14.5）。部品選定とlibrary provenanceを追加した。ただし契約registryとparts catalogの被覆はL-6として残る | 部品点数を変えない要件に限定したため回避したが、部品を増やす要件は現状扱えない |
| A-5 | 回路トポロジ合成 | 達成（14.5）。機能ブロックから回路トポロジを合成する経路を追加した。ただし契約registryとparts catalogの被覆はL-6として残る | I2C・LED以外の構成変更は検討不能だった |

## B. 物理設計の自律探索（今回の直接のfailure源）

| # | 不足機能 | 現状 | 実測根拠 |
|---|---|---|---|
| B-1 | 配置・回転の自動探索 | 探索Skillはsilkscreen配置のみ。部品配置と回転は入力に座標を書くしかない | 配置候補を人間側が出し、router非収束、デカップリング距離、GND島の各gateで却下された |
| B-2 | GPIO割当solver | strapping pin制約と配線可能性を同時に満たすGPIO割当を探索する機構が無い | pad 6/16案・pad 18/20/21案が未配線で却下され、最終的に「LEDを隣のpadへ1つ動かすだけ」まで人間が縮退させた |
| B-3 | 却下理由の構造化Evidence | routerログには未配線netとpad対が出るが、gateは`router convergence_state='not_converged'`の文字列で停止し、機械可読な失敗理由を返さない | 次候補の立案は毎回ログの目視解析に依存した |
| B-4 | gateの依存順・前倒し評価 | 配置だけで判定できる述語（デカップリング距離など）がrouter実行後に評価される | `C5 distance 3.319 mm exceeds 3.0 mm`がrouter完走後に判明し、1候補あたり数十分を無駄にした |
| B-5 | 結合制約（機能グループ）の表現 | U3を動かすとC5・R4も動かす必要があるという結合がgraphに無い | U3のみ移動した候補がデカップリング距離で却下された |
| B-6 | 単一datum化されていない機構寸法 | 取付穴がoutline宣言と`comp.h*`配置の二重定義 | 34 mm化の際に両方を手で合わせる必要があった |
| B-7 | stitch via候補が全滅した島のfallback | `inject_stitch_vias`の候補は原点固定グリッドで、配線が0.043 mm近接するだけで島にGND接続点が無くなりfail-closed | `Conductor region lacks a GND connection point`。島内の唯一の候補(21.698,18.684)が+3V3配線2本で除外されていた |
| B-8 | 探索用の設計自由度の宣言 | 線幅・層数・clearance・via規則・router pass上限は固定値で、要件に応じた探索対象になっていない | 収束しない候補に対して打てる手が配置しか無かった |
| B-9 | `stitch_candidate_report`の常時保存 | 呼び出し側が明示的に渡した場合のみ生成され、Evidenceに残らない | 事後解析のためホスト側で独自のKiCad s-expression parserを書く必要があった（provisional） |

### Bの一部解決（マイルストーン14.3）

B-3は、設計述語の実測値・閾値・比較方向・単位・量（`quantity`）・対象と、
routerのnet単位の接続成分・成分ペアごとの代表的な未接続pad対を構造化した診断Evidence
として常時保存することで解決した。
SESの欠落・parse失敗は`status: "unavailable"`として記録するが、既存の収束gateや
DRC gateの判定を変更しない。EvidenceはL3の診断情報であり、L1の合否権限を持たない。
B-4は、6述語すべてを`pre_router`として評価段階catalogへ宣言し、catalogの被覆検査を
追加することで、既に実施されていたrouter前評価を回帰固定した。DRC、stitch via、
Gerber検査はrouting結果に依存するため、従来どおりrouter後に配置している。

| 項目 | 14.3後の状態 | 優先度 |
|---|---|---|
| B-3 | 達成。述語失敗のmeasurement／subjectとrouterの未接続net・pad対を決定論的な診断Evidenceへ保存 | 解決済み |
| B-4 | 達成。述語catalogの評価段階を宣言し、6述語の`pre_router`被覆と既存評価順を回帰固定 | 解決済み |
| B-1 | 未着手。候補生成・探索loopは14.4の範囲 | 14.4 |
| B-2 | 未着手。候補の反復評価は14.4の範囲 | 14.4 |
| B-5〜B-7 | 未着手。結合制約、datum化、stitch via fallbackは14.4の範囲 | 14.4 |
| B-8・B-9 | 「Bの一部解決（マイルストーン14.4 第1セッション）」を参照 | 14.4 第1セッション |

### Bの一部解決（マイルストーン14.4 第1セッション）

B-8は、物理設計の探索対象を9つの設計自由度として宣言する契約を追加して解決した。
宣言は値を確定したり既存の閾値を複製したりせず、現在の値の出所、境界の根拠、権威を
持つ決定論的ゲート、探索可否だけを記録する。機能ブロックregistryの変更次元が宣言
済みかつ探索可能であることをfail-closedで検査し、無根拠の変更次元を探索経路へ渡さない。
銅層数と機械datumは、それぞれfab profile選択・基板投影とB-6の単一datum化に依存する
ため、後続セッションまで探索を無効化した。

B-9は、stitch via候補を呼び出し側の指定に依存せず常時生成・保存するようにした。
初回候補とrefill各反復の候補、選択結果、除外理由、allowed-points override、GND島の
未被覆測定を決定論的なartifactへ保存し、DFM reportには従来のbounded summaryだけを
残す。これはL3観測であり、L1の収束・DRC・Gerber gateの閾値、停止条件、合否権限を
変更しない。

| 項目 | 14.4 第1セッション後の状態 | 優先度 |
|---|---|---|
| B-8 | 達成。9次元の設計自由度宣言、出所・bound basis・gate authority、探索可否、registry整合検査を追加 | 解決済み |
| B-9 | 達成。初回・refill反復の候補reportとGND島未被覆測定を常時保存し、DFMにはbounded summaryを埋め込む | 解決済み |
| B-1・B-2 | 未着手。宣言した自由度を使う候補生成・探索loopは後続セッション | 14.4 |
| B-5〜B-7 | 未着手。結合制約、単一datum化、stitch via fallbackは後続セッション | 14.4 |

## C. 筐体・FW lane

| # | 不足機能 | 現状 |
|---|---|---|
| C-1 | 開口・締結の自動生成と干渉解決探索 | 達成。宣言された内部clearance・壁厚・standoff寸法をboundedに候補列挙し、筐体pipelineの機械gate結果をL2探索reportへ記録する。候補はgraphへ自動確定せず、`pass_evidence`も生成しない |
| C-2 | FWのgraph駆動化 | 達成。`firmware.module`の任意宣言からtimer周期・ログ文字列を生成し、未宣言時は既存GD1既定値を維持する。宣言値のmalformedは検証不能として停止する |
| C-3 | FW側の整合gate | 達成。Skill subprocessが出力したpin/config reportをACD側でgraphと再照合するL1 gateを追加した。欠落・parse失敗・不一致はfail-closed |
| C-4 | CPL orientation期待値のfixture非依存化 | 達成。部品catalogの任意orientation宣言と設計fixture側のplacement確認宣言から汎用fixture builderが`cpl_rotation_*`属性とgraph_id由来のEvidence pathを生成し、設計確認が無い場合は属性を補わず既存CPL gateでfail-closedとする。GD1もcatalog由来へ移行した |

## D. 実機フィードバックと発注（VibeBBの後半loop）

| # | 不足機能 | 現状 |
|---|---|---|
| D-1 | 測定結果の入力反映 | 達成。宣言apply policyのwhitelist・bounds・toleranceを検査し、dry-run、hash、multi-file rollback付きL3適用経路を追加した。適用後も全L1 gateを再実行する |
| D-2 | 見積の自動取得 | 境界を達成。期限付きfixtureを選択する`QuoteProvider`とCLIを追加した。実supplier接続はprovider境界へ接続する後続作業 |
| D-3 | 実発注 | 境界を達成。dry-run既定を維持し、明示providerと環境credentialがある場合だけsubmission recordとjournalを作成してprovider境界で停止する。実supplier接続は後続作業 |

## E. 実行基盤・性能

| # | 不足機能 | 現状 | 実測根拠 |
|---|---|---|---|
| E-1 | pipeline stageの並列化 | 基板pipelineでは`--pipeline-workers`により、rationale／設計predicate、独立reload、fab測定、Gerber gate、visual projectionの独立stageをProcessPoolExecutorで並列化済み。筐体pipelineではCAD専用spawn runnerをpipeline全体で再利用し、worker数分のmodule warm-up jobをBarrierで待ち合わせ、rationale／lane抽出／筐体投影中にimportを重ね、機械gate／artifact測定／断面・干渉visual projectionを同じrunnerへsubmitする。warm-up失敗・timeoutは最適化の警告として判定を変えずに続行する。2コアVMでCAD経路の既定を逐次（worker=1）とし、並列はopt-inにした。CPL／BOM chainは逐次のまま、E-2のlane／run並列化とE-4のstage cacheは未実装 | 基板のロック済みcontainerの3回比較は、逐次A（worker=1）145.1秒、逐次B（worker=1）152.0秒、並列C（worker=4）144.0秒。筐体は2コアVMの同一fixtureで`--pipeline-workers 1`が8.309秒、`--pipeline-workers 4`が26.492秒（現在の実装によるhostのprovisional測定）。4 workerのspawn＋`build123d` warm-up待ちは4.870秒（1 workerあたりの測定値）、shutdownは0.915秒で、逐次区間との重複後も2コア環境ではCAD stageのCPU競合が支配的となり短縮しなかった。Linux既定forkでOCP状態を継承すると停止するためCAD経路だけspawnを明示し、worker起動をpipelineごとに1回へ抑える。CAD stage実処理がworker起動コストを上回る大規模設計や多コア環境では明示指定で並列化できる。基板のA/BとA/Cの差分hashキー集合は一致し、SESとrefill前boardも一致した。外部CAD kernel／kicad-cli／FreeRoutingが支配的で、短縮幅は実行環境に依存する |
| E-2 | lane・runの並列実行 | `scripts/run_gd1_lanes.py`でsilkscreen resolverをbarrierとして先に実行し、fixtureの`graph.json`更新完了後に、出力先を分離したGD1基板lane、GD1筐体lane、pytest subsetを独立batchとして並列実行する。`--jobs 1`は宣言順の逐次経路、複数jobは宣言順の出力とfail-closedの全件失敗報告を使う。laneの並列度は成果物、hash、Evidence、provenance、summaryへ含めない | 実装済み。host provisionalは基板laneの`freerouting` executable不在でfail-closedとなり、lane全体の成功・短縮は未実測（失敗までのwall clockは`--jobs 1` 15.902秒、既定並列29.331秒で、成功比較値ではない）。digest固定imageのDockerWorkspaceを使うCI `container-gates`をauthoritativeな測定経路とし、短縮が得られない場合も実測値を記録する |
| E-3 | silkscreen探索候補評価の並列化 | `acd-silkscreen-placement`の`resolve_from_context`で、texts>1の候補数前パスをtext単位、1 text内のrotation×x-column列を共有context bundle付きchunk単位で`ProcessPoolExecutor`並列化した。チャンク内・チャンク間の結果をrotation宣言順・x昇順で連結し、main passは`dynamic_silk`が後続textの障害物になるため逐次のままとした。`--workers 1`はpoolなしの完全逐次で、worker数は出力、hash、Evidence、provenance、summaryへ含めない。placement search Skillは1.44秒（warm状態、interpreter起動込み）で実処理がサブ秒のため変更していない | 2コアVMのGD1 fixtureではpinned silkscreenにより通常のresolverで探索Skillは0回（resolve全体12.0秒）。未解決化した6 textではSkill 1回が47.77秒、resolve全体が63.29秒で、候補評価が支配項となった。抽出した同一入力を現在のSkillへ直接与えたhost provisional比較では、`--workers 1`が49.075秒、`--workers 2`が29.245秒、`--workers 4`が29.722秒で、全実行が成功しoutput JSON（各63,900,205 bytes）はbyte一致した。chunk化後も並列化によりこの入力では短縮したが、2コアVMのhost測定であり、authoritativeな判定はcontainer gateに委ねる |
| E-4 | 入力hash単位のstage cache | 配置だけ変えた再試行でもDSN exportからやり直す | 候補ごとに全stageを再実行した |
| E-5 | output prefix／`subject_node`のgd1固定 | 達成。graph_id由来のprefixとgraph nodeからsubjectを導出し、GD1互換aliasを明示した | variant成果物も`gd1-*`名で出力される |
| E-6 | 検証段階の並列実行 | pytestは`-n auto --dist loadgroup`、`verify_all.py`は`--jobs N`（既定はCPU数と4の小さい方）でbarrierのない連続コマンドを並列実行する。standardとfullの`uv sync`およびfullの後続pipelineはbarrierとして単独実行する。docs stageは文書検証3本を環境同期なしで並列実行する。`--jobs 1`は最初の失敗で停止して子プロセス出力を直接流し、並列時は開始行を出して起動済みコマンドを完走させ、失敗をすべて報告する | 2コアVMの同一入力でpytestは195.13秒（逐次）から108.73秒（自動並列）、standard検証は141.21秒（`--jobs 1`）から126.66秒（既定並列）になった。各条件1回（詳細は[`docs/operations.md`](operations.md)） |

## F. image publishとlock更新の自動化

`acd-tools`（ツールチェーン層、版とSHA-256固定）と、それをbaseにSDKの
[`build.py`](../vendor/software-agent-sdk/openhands-agent-server/openhands/agent_server/docker/build.py)
が生成する`acd-server`（agent-server実行層）の2層構成であり、
`DockerWorkspace(server_image=...)`が使うのは後者である。分離の理由は、SDK版更新と
ツールチェーン更新を独立にpublishでき、base digestとderived digestを別々に記録して
同一と主張する記述をfail-closedで拒否できること（[`docs/roadmap.md`](roadmap.md)の6.2）
である。

| # | 改善提案 | 現状と理由 |
|---|---|---|
| F-1 | tools publishをmain mergeで自動起動し、成功後に`acd-server` publishを`workflow_run`で連鎖起動する | [`publish-acd-server.yml`](../.github/workflows/publish-acd-server.yml)は`workflow_dispatch`のみ |
| F-2 | publish jobが[`docker/image-digests.json`](../docker/image-digests.json)を更新するPRを自動作成する | 現状はjob summaryからの人手転記で、転記ミスの余地がある。ただし[`publish-acd-tools.yml`](../.github/workflows/publish-acd-tools.yml)のtriggerがdigest lockと[`docker/README.md`](../docker/README.md)を除外しており、digest更新PRがpublishを再帰起動するloopは構造的に防がれている |
| F-3 | [`verify_authoritative_evidence.py`](../scripts/verify_authoritative_evidence.py)の検査に、lockのdigestとregistry現行manifestの一致確認を追加する | lock更新漏れをCIで検出できる |
| F-4 | 文書と実運用の不整合を整理する | [`docker/README.md`](../docker/README.md)は「ACDはこのimageを配布しない」と述べる一方、実際にはGPLv3のKiCad／FreeRoutingを含むimageをGHCRへpublishしている。配布に当たるか否かを整理し、記述を整合させる必要がある。実装は変更せず、指摘のみとする |
| F-5 | FreeRouting／container資源の暗黙継承を除く | FreeRouting 2.3.0の`-mt`既定（論理CPU数−1）を常に明示し、GD1 pipelineの既定を`--freerouting-threads 1`へ固定した。wrapperは`-Xmx2g`を既定で宣言し、active processor countは既定では宣言せず、`FREEROUTING_ACTIVE_PROCESSORS`が明示された場合だけ追加する。`FREEROUTING_MAX_HEAP`でheapを上下できる。2コアVMのdigest固定imageで`-mt 0/1/2/4`のSES hashは一致し、93.5/93.0/92.5秒で有意な短縮は無かった。変更後wrapperの一回測定は94.3秒（baseline比+0.8秒、host provisional）であり、速度向上は主張しない。`feature_flags.multi_threading`は無効のままとした。SDK `DockerWorkspace`にCPU／memory fieldが無いため、資源宣言不能時の`tool_concurrency_limit=1`とSDK mutex直列化契約は維持する。wrapper変更時はmainのDocker publish結果digestをlockへ転記し、推測値を記録しない | 実装済み。FreeRoutingの`-mt`だけを固定し、JVMのCPU認識は既定で制限しない |

## G. ワークスペース初期化の自動化

OpenHands側のworkspaceは`/acd:init`（G-1）で初期化でき、repositoryのcloneまたはclean
checkout再利用、submodule取得、`uv sync`、plugin読み込み確認、doctorまでを一経路で実行する。
[`plugins/acd/commands/ask.md`](../plugins/acd/commands/ask.md)、
[`doctor.md`](../plugins/acd/commands/doctor.md)、[`gates.md`](../plugins/acd/commands/gates.md)に
加えて初期化commandも提供している。現在のDocker workspace経路は
[`docs/operations.md`](operations.md)に記載された
[`scripts/run_in_workspace.py`](../scripts/run_in_workspace.py)への手順依存である。

| # | 改善提案 | 現状と理由 |
|---|---|---|
| G-1 | `/acd:init` commandと`init_workspace.py`を追加し、workspace作成→clone／clean checkout再利用→submodule取得→`uv sync`→plugin読み込み確認→`/acd:doctor`までを1経路にまとめる | 達成。各段の失敗はfail-closed JSONで停止する |
| G-2 | [`/acd:doctor`](../plugins/acd/commands/doctor.md)にworkspace健全性検査を追加する | 達成。repository、submodule、`uv.lock`同期、lock digestのローカルinspect、ESP-IDF／QEMU／CMakeを検査する。検証不能な必須項目はunknownとして停止する |
| G-3 | 会話開始時のbootstrap経路（対象repo revisionとlock digestを記録してworkspaceを用意する）を用意する | 達成。`acd_bootstrap_workspace`と`.openhands/bootstrap-record.json`を提供する。記録はL3観測であり合否権限を持たない |

## 実測したfail-closed結果とEvidence境界

以下は`compact-sensor-node-1`の設計演習で確認した拒否結果である。
決定論的ゲートとpipelineの実行は、すべてlock済みdigest固定containerによる
authoritative実行である。hostで行った島のblocker解析だけはprovisionalであり、
authoritative Evidenceではない。

| 候補／変更 | verbatim gate message | 判定 |
|---|---|---|
| 初回のI2C GPIO案 | `PIPELINE FAILED (fail-closed): router convergence_state='not_converged' (fail-closed)` | authoritative、却下 |
| U3を180度回転 | `PIPELINE FAILED (fail-closed): Conductor region lacks a GND connection point (fail-closed): layer=F.Cu, bbox_mm=(19.469397, 17.676544, 22.239241999999997, 19.5886)` | authoritative、却下 |
| U3をx=19.0 mmへ移動（C1） | `PIPELINE FAILED (fail-closed): power_decoupling: status='fail' (C5 distance 3.319 mm exceeds 3.0 mm)` | authoritative、却下 |
| U3をx=19.0 mmへ移動し、reset switchも移動（C2） | `PIPELINE FAILED (fail-closed): power_decoupling: status='fail' (C5 distance 3.319 mm exceeds 3.0 mm)` | authoritative、却下 |
| U3をx=19.0 mmへ移動（D1） | `PIPELINE FAILED (fail-closed): router convergence_state='not_converged' (fail-closed)` | authoritative、却下 |
| TP2を(20.85,18.63)へ移動（E1） | `PIPELINE FAILED (fail-closed): router convergence_state='not_converged' (fail-closed)` | authoritative、却下 |
| R5を(30.0,17.0,90)へ移動（H1） | `PIPELINE FAILED (fail-closed): router convergence_state='not_converged' (fail-closed)` | authoritative、却下 |
| variant筐体（J1） | `PIPELINE FAILED (fail-closed): mechanical gates failed: interference` | authoritative、却下 |

GD1を同じdigest固定containerで変更なしに実行すると、FreeRoutingは0 unrouted、
19 violations、`convergence_state=converged`となり、variantの収束時も同じ19 violations
だった。したがって19 violationsはvariant固有の増加ではなく、このrouter versionのbaselineで
ある。これはauthoritative container観測である。

一方、孤立島の調査では、島内の唯一のdeterministic stitch candidate
`(21.698,18.684)`が`+3V3`のF.Cu／B.Cu wireにより除外されることを確認した。
このblocker行とKiCad boardの読み取りはhost-onlyのprovisional analysisであり、
pipelineのgate結果やEvidenceを置き換えない。

## H. Skill scriptのacd版skew（致命的、FW laneが停止する）

[`ADR-0037`](adr/ADR-0037-pep723-skill-scripts.md)により、`acd`をimportするSkill scriptは
PEP 723メタデータで`acd`をgit refへpinし、`uv run --script`が実行時に隔離環境を作る。
pinの正は[`plugins/acd/skills/acd-package-ref.txt`](../plugins/acd/skills/acd-package-ref.txt)である。
このrefは導入commit以降更新されておらず、`4cca489…`（2026-08-19）を指したままである。
一方でmainは`firmware.state`／`firmware.state_transition`／`firmware.sequence_step`を
`NodeKind`へ追加しており、GD1 fixtureのgraphもこの3種を使う。

その結果、FW pipelineは設計内容に関係なく次で停止する。

```text
PIPELINE FAILED: 15 validation errors for DesignGraph
nodes.207.kind
  Input should be 'requirement', …, 'firmware.module', 'firmware.pin_assignment',
  'safety.boundary' or 'evidence.anchor'
  [type=literal_error, input_value='firmware.state', input_type=str]
```

pinされたcommitの`NodeKind`には`firmware.module`と`firmware.pin_assignment`しか無く、
mainおよびcontainer image build元commitには3種が存在する。つまりこれはvariant固有の
設計エラーではなく、**pinned acdとリポジトリのschemaのversion skew**であり、GD1のgraphでも
同じく失敗する。VibeBBのFW laneは現在誰が実行しても成立しない。

| # | 改善提案 | 現状と理由 |
|---|---|---|
| H-1 | schema／APIを変更した変更に対し、後続でrefを更新する運用ではなくCIでskewを検出する | 現在はrefが古いまま検査を通る。検査は「全scriptがref fileと一致するか」だけを見るため、refが実装より古い状態は合格になる |
| H-2 | [`/acd:doctor`](../plugins/acd/commands/doctor.md)のSkill package reference検査に、pinned refがplugin資材のrevisionと互換かの判定を追加する | [`install_doctor.py`](../plugins/acd/skills/acd-install-doctor/scripts/install_doctor.py)の`_package_ref_check`はref書式とscript metadataの一致のみで、今回のskewを検出できなかった |
| H-3 | main merge後のref更新を自動化する（F-2と同じ形の自動PR） | ADR-0037は「refは後続の変更で更新する」と定めており、更新漏れが構造的に起きる |
| H-4 | CIでSkill scriptをリポジトリのfixtureに対して実際に実行し、pinned acdでgraphが読めることを検査する | 現在CIはscriptをmoduleとしてimportするだけで、pinned acdでの実行経路は検査されない |
| H-5 | pinned `acd`をdigest固定image側へ事前導入し、FW laneが実行時にgitとネットワークへ依存しないようにする | `uv run --script`はcontainer内で毎回依存を解決する（今回のログでも241 packagesを実行時に取得）。offline環境では初回実行がfail-closedになり、digest固定による再現性の主張とも整合しない |

### Hの解決（マイルストーン14.1）

H-1は`verify_skill_package_ref.py`をstandard CIへ追加し、refの祖先性、schema tree、
pinned API、fixture kind、script hashを`acd-package-contract.json`と比較して解決した。
H-2はinstall doctorが同じcontractをgit/importなしで評価し、欠落・parse不能・不一致を
required failureとすることで解決した。H-3はmain push後にcheckerがskew時だけmerge commitへ
更新するauto-PR workflowを追加した。一致時は何もせず、auto-PR merge後にretriggerされても
ループしない。H-4はpinned `acd`でGD1 graphをvalidateし、firmware Skillの
`extract_firmware_lane`を呼ぶprobeをCIへ追加した。H-5は同一PEP 723 environmentをimage
build時にwarmし、offline probeを再実行するprebakeで解決した。

観測された`4cca489…`とmainのschema差分、GD1での15 validation errorsという観測記録は
変更しない。refは現行main commitへ再pinし、checkerとprobeが同じ失敗を再発させないことを
検査する。実行時のネットワークを不要にしても、L1 authority、閾値、fail-closed境界、
authoritative Evidenceのdigest固定条件は緩めない。

## I. 会話からの入口とgd1固定（Devin抜きでVibeBBが成立しない直接原因）

| # | 不足機能 | 現状 |
|---|---|---|
| I-1 | VibeBB loopのcommand | 達成。`/acd:vibebb-loop`が要件、graph検証、silkscreen barrier、基板・筐体・FW、発注可否を固定順序のfail-closed loopとして実行する |
| I-2 | agent向けtoolの網羅 | 達成。[`src/acd/openhands/tools/definitions.py`](../src/acd/openhands/tools/definitions.py)にFW pipeline、fixture編集、発注可否、失敗診断、候補探索、design loopを含む13本のtoolを登録済み |
| I-3 | workspace既定値のgd1固定 | 達成。対象graphのgraph_idからcommand、Evidence path、required anchorを決定論的に導出する |
| I-4 | 発注可否判定のsubject固定 | 達成。order policyを対象graphと照合し、graph-scoped Evidence anchorの欠落をfail-closedにする |
| I-5 | 生成物名のgd1固定 | 達成。KiCad、筐体part number、visual projection、CPL pathをgraph_id由来にし、既存GD1互換prefixを保持する |

## J. ゲート契約がGD1のトポロジ族しか受け付けない（最も根本的な制約）

[`src/acd/core/design_predicates.py`](../src/acd/core/design_predicates.py)は、net名
`CC1`／`CC2`／`I2C_SDA`／`I2C_SCL`、refdes `U1`、ESP32-C3のstrapping pin構成を契約として
固定している。該当netが存在しない設計では`_evaluate_pullups`が
`required net resolution failed`で`unknown`を返し、fail-closedになる。

つまり、USB-Cを持たない設計、I2Cを使わない設計、センサ構成の異なる設計は、
設計として妥当であってもゲートを通過できない。VibeBBが掲げる「自然言語の要件から
小型基板を設計する」に対し、現在の合格可能領域はGD1の1トポロジ族に限られる。

| # | 改善提案 | 現状と理由 |
|---|---|---|
| J-1 | 述語の適用条件（applicability）を宣言化し、宣言された機能ブロックに対応する述語だけを必須にする | 現在は「netが無い＝unknown＝fail-closed」であり、機能を持たない設計と検証不能な設計を区別できない。fail-closed境界は維持したまま、適用対象の宣言を要件側へ移す提案である |
| J-2 | 機能ブロック単位の契約registry（USB-C CC、I2C pull-up、単一LDO等）を導入し、新トポロジの追加を述語コード改変ではなく契約追加で行えるようにする | [`design-requirement-variation.md`](design-requirement-variation.md)が述べるとおり、現状の新トポロジ追加は述語・negative test・ADRの同時改変であり、会話からは到達できない |
| J-3 | fab profileを複数持てるようにする | [`profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json`](../profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json)の1種のみで、層数・工程・供給者の選択肢が無い |

### Jの解決（マイルストーン14.2）

J-1はgraphの`design.functional_block`宣言と、宣言から導出する適用述語集合で解決した。
宣言された機能ブロックの述語だけを必須評価し、宣言されたブロックの入力不足は
`unknown`のまま停止する。機能ブロックが宣言されていない述語だけを`not_applicable`と
し、両者をEvidence境界でも分離する。

J-2は`contracts/functional-block-registry.json`で解決した。registryと固定述語catalogの
相互被覆を検査するため、未知述語や契約に属さない述語は黙って適用外にならない。
GD1は安全電源境界を含む6ブロックを宣言し、別トポロジは契約を追加して述語コードを
変更せずに適用範囲を定義できる。

J-3は`profiles/fab-profile-registry.json`で解決した。`--fab-profile`の明示パス互換を
維持しつつ、`--fab-profile-id`またはgraphの`fab.order_intent.fab_profile`から
registry経由でprofileを選択する。profile本体とのID、fab、processの不一致とpath欠落は
fail-closedで停止する。

| 項目 | 14.2後の状態 | 優先度 |
|---|---|---|
| J-1 | 達成。宣言された機能ブロックに対応する述語だけを必須評価し、`unknown`と`not_applicable`を分離 | 解決済み |
| J-2 | 達成。機能ブロック契約registryの被覆検査とEvidence追跡を実装 | 解決済み |
| J-3 | 達成。fab profile registryによるID／graph宣言選択を実装 | 解決済み |

## K. 手順の連結と失敗時の回復（体験としての詰まり）

| # | 不足機能 | 現状 |
|---|---|---|
| K-1 | 単一のorchestrator | 達成（14.7、14.10）。`scripts/run_gd1_lanes.py`と`run_design_loop`でsilkscreen resolver→基板pipeline→筐体pipeline→FW pipeline→発注可否の順序を固定した。ただしcache・resume・timing・lane並列を会話経路へ接続していない点はL-1として残る |
| K-2 | 失敗からの再開 | 達成（14.7）。`scripts/run_gd1_lanes.py`に入力hash単位のstage cacheと失敗からのresumeを追加した。ただし会話経路（`/acd:vibebb-loop`）から未接続である点はL-1として残る |
| K-3 | 失敗メッセージのremediation | ゲートは値と座標を返すが、次に動かしてよい次元（許可された変更次元）を返さない。専門家か汎用エージェントが居ないと次の一手が決まらない。B-3の構造化Evidenceを、利用者向けの「変更可能な次元と現在の余裕」を含む形にする提案である |
| K-4 | stageごとの所要時間記録 | 達成（14.7）。stageごとの所要時間を記録する機能を追加した。ただし会話経路（`/acd:vibebb-loop`）から未接続である点はL-1として残る |

### K-3の解決（マイルストーン14.3）

K-3は、機能ブロックregistryに許可された変更次元を宣言し、述語失敗のEvidenceと
`GateError`へ由来block、対象、現在のマージン、超過量、人間向けremediationを追加する
ことで解決した。registryに宣言のない次元は推測せず`unknown`として扱い、安全境界の
`dimensions_source: "unknown"`として扱い、変更次元は空にする。安全境界のように空集合を
宣言したblockは`dimensions_source: "registry"`のまま追加変更を許可しない。remediationは診断情報であり、
決定論的なゲートの閾値・停止条件・合否権限を変更しない。

| 項目 | 14.3後の状態 | 優先度 |
|---|---|---|
| K-3 | 達成。registry由来の許可変更次元と現在の余裕を述語失敗へ表示 | 解決済み |

## L. マイルストーン14.10後に残る会話駆動loopの不足

本節はマイルストーン14.10（I-1）の完了後に、コードベースを横断して再確認した結果である。
既存の閾値、ゲート挙動、fail-closed境界、L1権限を変更する提案は含まない。

| # | 不足機能 | 現状 | 優先度 |
|---|---|---|---|
| L-1 | orchestratorの二重化解消 | `/acd:vibebb-loop`が呼ぶ`run_design_loop`は、入力hash単位のstage cache（E-4）、失敗からの再開（K-2）、stageごとの所要時間記録（K-4）、lane並列（E-2）を使わない。これらを持つ`scripts/run_gd1_lanes.py`は出力先が`out/gd1`・`out/gd1-enclosure`・`out/gd1-fw`のGD1固定で、FW整合gate後の発注可否段を持たない。結果として会話経路からはcacheと再開が使えない | 高 |
| L-2 | 却下後の候補探索の自動連結 | board段が却下された際に`explore_board_candidates`（B-1／B-2）へ接続する経路がloopに無く、次候補の起動が会話側のtool呼び出しに依存する。探索はL2の操舵に留め、L1ゲートの権限と閾値は変更しない | 高 |
| L-3 | 要件→graph段のloop内取り込み | `scripts/compile_requirement_change.py`と`scripts/build_design_fixture.py`（A-1〜A-3）はloopの外にあり、要件revisionと対象graph revisionの整合をloop入口で検査していない | 中 |
| L-4 | order-total生成経路の欠落 | `aggregate_order_total`にCLIもtool入口も無く、`out/order-total.json`の生成手順は[`operations.md`](operations.md)にも無い。発注可否段は既存fileを前提とするため、会話からは発注可否判定へ到達できない | 高 |
| L-5 | 生成物既定値のgd1残留 | `DEFAULT_PROJECT_NAME = "gd1"`、`src/acd/openhands/workspace.py`の既定evidence path、agent toolの既定出力`out/gd1-*`、FW既定の`boot_log_message`のGD1文字列が残る。いずれも宣言で上書きできるが、任意graphでは既定値が誤誘導になる | 中 |
| L-6 | 契約registryとcatalogのトポロジ被覆 | `contracts/functional-block-registry.json`はGD1系の6契約、`contracts/parts-catalog.json`は24 entryのみで、USB-Cを持たない設計や電池駆動設計は契約・catalog追加が前提となり会話からは到達できない（マイルストーン16.2・16.3に依存） | 中 |
| L-7 | 本書の「現状」列の陳腐化 | 解決済み。A節・K節・G節の「現状」列が14.5・14.7・14.8の達成後も更新されておらず実装状態と齟齬があったため、本節の追加と同じ変更で更新した。実測根拠の観測記録は変更しない | 低 |

## Devinのような汎用エージェントが不在なら止まる項目

VibeBB体験を「acd-agent単体」で成立させるうえで、外部の汎用エージェントによる代替が
効かない、または代替されている項目を明示する。

| 項目 | 不在時に起きること |
|---|---|
| H-1／H-5 | FW pipelineが常に失敗する。設計内容に依存しないため回避手段が無い |
| J-1／J-2 | 契約registryへの機能ブロック追加は可能になった。任意graphの生成・差分反映はI-2／A-2／A-3が未達だと生JSON編集になる |
| I-4 | GD1以外の設計は発注可否判定に到達できない |
| I-2／A-2／A-3 | 要件変更をgraphへ落とす作業が生JSON編集になる。今回はこれを私が代行した |
| B-1／B-2／B-3 | 却下後の次候補立案が人手になる。今回8候補の却下はすべて人間側の再立案で進めた |
| G-1／G-2 | 達成。`/acd:init`とworkspace指定doctorがcloneから健全性検査までをfail-closedに実行する |

## 優先順位（VibeBB単体成立に効く順）

1. H-1／H-5（Skill scriptのacd版skew）。現在FW laneが常に失敗しており、設計内容によらず回避できない。最小のコストで最大の停止要因を除ける。
2. I-2／A-2／A-3（任意graphと要件差分compiler）。14.5で要件document、任意fixture builder、compiler、agent tool入口を接続し、手編集依存を解消した。registry entryは14.2の達成済み機能である。
3. B-3（構造化失敗理由）→ B-4（前倒し評価）→ B-1／B-2（探索loop）。この3点が揃わない限り、候補生成は必ず人間側に残る。今回の作業がまさにその状態だった。K-3はB-3の利用者向け表現として同時に扱う。
4. A-2／A-3（任意fixtureと要件差分compiler）、I-2（agent向けtoolの網羅）。14.5で達成済み。部品catalogとトポロジtemplateを追加して新規設計の入口を宣言経由へ移した。
5. B-5／B-6／B-7（結合制約・単一datum・島fallback）。達成済み。SkillはL2の候補生成に限定し、L1ゲートの権限とfail-closed条件は維持する。
6. E-1〜E-4／K-1／K-2／K-4（並列化・cache・orchestrator・再開・timing）。14.7で達成済み。resumeはartifactだけを復元し、L1ゲートを省略しない。
7. G-1〜G-3（workspace初期化とbootstrap）。達成済み。`/acd:init`または`acd_bootstrap_workspace`から、対象revisionを宣言して会話開始用workspaceを準備できる。
8. I-3〜I-5／E-5、C-2／C-3、D-1〜D-3は14.6で達成した。実supplier接続はprovider境界の後続作業として残る。
9. F-1〜F-4（image publishとdigest lock更新）。達成済み。digest lockとregistry manifestの照合、配布文書の整合を含む。残存するH-2〜H-4／K-4（skew検出と計測）は運用の再現性と回帰防止を強化する。
10. L-1〜L-7（マイルストーン14.10後に残る会話駆動loopの不足）。会話経路へのcache・resume・timing・lane並列の接続、候補探索と要件→graphのloop内取り込み、order-total生成、gd1既定値、契約registry・catalog被覆、本書の現状列更新を扱う。
