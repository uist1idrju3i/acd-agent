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
| A-1 | 会話→要件レコードの変換 | 達成（14.5）。要件レコード化と要件差分compilerを追加し、会話由来の要件をgraph変更へ接続できる | 変更したREQ-010／REQ-011の文面は手作業更新であり、GPIO変更との整合を機械検査できなかった |
| A-2 | 任意設計向けfixtureビルダー | 達成（14.5）。任意設計向けfixture builderを追加した | 変異fixtureは自作スクリプトでGD1 graphを書き換えて生成した。acd-agent内には該当機能が無い |
| A-3 | 要件差分→graph差分のコンパイラ | 達成（14.5）。要件差分compilerが接続・FWピン・テストポイント・シルク文字・rationaleを同時に更新する | 上記4箇所をすべて手で書き換えた。1箇所落とすとresolverかrationale coverageで落ちる |
| A-4 | 部品選定とlibrary provenanceの自動化 | 達成（14.5、L-6）。`register_part_catalog_entry.py`と`acd_register_parts_catalog_entry`で、実file SHA-256を含むprovenance検証と原子的catalog追記を提供した。選択keyの曖昧性を増すentryは拒否する | 規範的な部品妥当性は既存predicateとcatalogの範囲に限られ、未登録の選択keyは引き続きfail-closed |
| A-5 | 回路トポロジ合成 | 達成（14.5、L-6）。`contracts/topology-templates.json`を正とするPydantic検証済みdata templateから、registryの宣言blockをPython変更なしで合成できる | 未宣言block、template欠落、閉じていないnet参照は検証不能として停止する |

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
| C-2 | FWのgraph駆動化 | 達成。`firmware.module`の任意宣言からtimer周期・ログ文字列を生成し、未宣言時も`graph_id`由来の中立値を導出する。GD1は`boot_log_message`明示属性で従来文字列を再現し、宣言値のmalformedは検証不能として停止する |
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
| E-2 | lane・runの並列実行 | `scripts/run_design_lanes.py`でsilkscreen resolverをbarrierとして先に実行し、fixtureの`graph.json`更新完了後に、出力先を分離したGD1基板lane、GD1筐体lane、pytest subsetを独立batchとして並列実行する。`--jobs 1`は宣言順の逐次経路、複数jobは宣言順の出力とfail-closedの全件失敗報告を使う。laneの並列度は成果物、hash、Evidence、provenance、summaryへ含めない | 実装済み。host provisionalは基板laneの`freerouting` executable不在でfail-closedとなり、lane全体の成功・短縮は未実測（失敗までのwall clockは`--jobs 1` 15.902秒、既定並列29.331秒で、成功比較値ではない）。digest固定imageのDockerWorkspaceを使うCI `container-gates`をauthoritativeな測定経路とし、短縮が得られない場合も実測値を記録する |
| E-3 | silkscreen探索候補評価の並列化 | `acd-silkscreen-placement`の`resolve_from_context`で、texts>1の候補数前パスをtext単位、1 text内のrotation×x-column列を共有context bundle付きchunk単位で`ProcessPoolExecutor`並列化した。チャンク内・チャンク間の結果をrotation宣言順・x昇順で連結し、main passは`dynamic_silk`が後続textの障害物になるため逐次のままとした。`--workers 1`はpoolなしの完全逐次で、worker数は出力、hash、Evidence、provenance、summaryへ含めない。placement search Skillは1.44秒（warm状態、interpreter起動込み）で実処理がサブ秒のため変更していない | 2コアVMのGD1 fixtureではpinned silkscreenにより通常のresolverで探索Skillは0回（resolve全体12.0秒）。未解決化した6 textではSkill 1回が47.77秒、resolve全体が63.29秒で、候補評価が支配項となった。抽出した同一入力を現在のSkillへ直接与えたhost provisional比較では、`--workers 1`が49.075秒、`--workers 2`が29.245秒、`--workers 4`が29.722秒で、全実行が成功しoutput JSON（各63,900,205 bytes）はbyte一致した。chunk化後も並列化によりこの入力では短縮したが、2コアVMのhost測定であり、authoritativeな判定はcontainer gateに委ねる |
| E-4 | 入力hash単位のstage cache | `run_design_loop`へ接続済み。基板pipelineのDSN／SES生成物を入力hash一致時だけ再利用し、判定とEvidenceは毎回実行する | 会話経路の実pipeline測定はcontainer gateで確認する |
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
| F-1 | tools publishをmain mergeで自動起動し、成功後に`acd-server` publishを同一workflowで連続実行する | [`publish-acd-images.yml`](../.github/workflows/publish-acd-images.yml)がtoolsとserverを単一jobで直列実行し、`skip_tools`によるserver単独再buildも提供する |
| F-2 | publish jobが[`docker/image-digests.json`](../docker/image-digests.json)を更新するPRを自動作成する | [`publish-acd-images.yml`](../.github/workflows/publish-acd-images.yml)がtoolsとserverのdigest更新を1 commit・1 PRへまとめる。triggerはdigest lockと[`docker/README.md`](../docker/README.md)を除外し、digest更新PRがpublishを再帰起動するloopを防ぐ |
| F-3 | [`verify_authoritative_evidence.py`](../scripts/verify_authoritative_evidence.py)の検査に、lockのdigestとregistry現行manifestの一致確認を追加する | lock更新漏れをCIで検出できる |
| F-4 | 文書と実運用の不整合を整理する | [`docker/README.md`](../docker/README.md)は「ACDはこのimageを配布しない」と述べる一方、実際にはGPLv3のKiCad／FreeRoutingを含むimageをGHCRへpublishしている。配布に当たるか否かを整理し、記述を整合させる必要がある。実装は変更せず、指摘のみとする |
| F-5 | FreeRouting／container資源の暗黙継承を除く | [`ADR-0045`](adr/ADR-0045-openj9-freerouting-runtime.md)で`-mt`の部分撤回を決定した。`-mt`は暗黙継承（論理CPU数−1）へ戻し、Evidenceの機械非依存性は固定文字列`"implicit router threads (cpu_count-1)"`と`freerouting_threads=null`の記録で保つ（`config_hash`はCPU数で変動しない）。以下は撤回前の記録である。FreeRouting 2.3.0の`-mt`既定（論理CPU数−1）を常に明示し、GD1 pipelineの既定を`--freerouting-threads 1`へ固定した。wrapperは`-Xmx2g`を既定で宣言し、active processor countは既定では宣言せず、`FREEROUTING_ACTIVE_PROCESSORS`が明示された場合だけ追加する。`FREEROUTING_MAX_HEAP`でheapを上下できる。2コアVMのdigest固定imageで`-mt 0/1/2/4`のSES hashは一致し、93.5/93.0/92.5秒で有意な短縮は無かった。変更後wrapperの一回測定は94.3秒（baseline比+0.8秒、host provisional）であり、速度向上は主張しない。`feature_flags.multi_threading`は無効のままとした。SDK `DockerWorkspace`にCPU／memory fieldが無いため、資源宣言不能時の`tool_concurrency_limit=1`とSDK mutex直列化契約は維持する。wrapper変更時はmainのDocker publish結果digestをlockへ転記し、推測値を記録しない | 部分撤回済み。`-mt`は暗黙継承へ戻し、JVMのCPU認識は既定で制限しない |

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
| K-1 | 単一のorchestrator | 達成（14.7、14.10、本PR）。`run_design_loop`へcache・resume・timing・lane並列を接続した。orchestratorのlane定義二重化解消は次PRで扱う |
| K-2 | 失敗からの再開 | 達成（14.7、本PR）。会話経路の`run_design_loop`へ入力hash単位のstage cacheとresumeを接続した。cacheは決定論的生成物だけを復元し、判定とEvidenceは毎回再実行する |
| K-3 | 失敗メッセージのremediation | ゲートは値と座標を返すが、次に動かしてよい次元（許可された変更次元）を返さない。専門家か汎用エージェントが居ないと次の一手が決まらない。B-3の構造化Evidenceを、利用者向けの「変更可能な次元と現在の余裕」を含む形にする提案である |
| K-4 | stageごとの所要時間記録 | 達成（14.7、本PR）。会話経路の`run_design_loop`でも全stageの所要時間をL3 timing recordへ記録し、失敗時もopen stageを閉じて書き出す |

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
| L-1 | orchestratorの二重化解消 | 達成（前半＝#186、後半＝本PR）。`/acd:vibebb-loop`が呼ぶ`run_design_loop`への入力hash単位stage cache、失敗からのresume、L3 timing record、silkscreen barrier後のboard／enclosure／firmware lane並列に加え、`src/acd/pipeline/lane_plan.py`を単一sourceとしてlaneのstage ID、順序、barrier、出力パス、cache適用可否を共有した。`scripts/run_design_lanes.py`は同じplanからsilkscreen barrier、設計lane、pytest subset検証laneを導出する。pytest subsetはGD1（`artifact_prefix=gd1`）だけに宣言され、任意graph向けの設計固有検証laneは未整備である。order-readinessは`run_design_loop`側だけが担当し、lane runnerは要求しない。cacheは判定とEvidenceを復元しない | 高 |
| L-2 | 却下後の候補探索の自動連結 | 達成。`run_design_loop`は`explore_board`の明示指定時、board-pipelineのfail-closed却下後かつ全lane join後に、候補予算・round上限付きで`explore_board_candidates`を自動連結する。candidate_foundでもgraph IDとrevisionが探索前と一致し、正規化content hashが変化し、探索reportの`target_revision`がgraph revisionと一致することを検証してloopを再実行し、L1ゲートとEvidenceを毎回生成する。探索reportはL2の操舵・L3観測で合格権限を持たず、exhausted／stopped／不正report／上限到達は元のboard失敗理由を保持してfail-closedとなる。任意graphでは探索次元が設計自由度宣言と既存候補生成器の範囲に限られる | 高 |
| L-3 | 要件→graph段のloop内取り込み | 達成。`fixture_spec`指定時のfixture生成、`requirement`指定時の既存compiler接続、常時の`requirements.json`入口整合検査をloop前段へ追加した。入口検査をdesign-loop stageとして宣言し、graph ID・revision、constrains node、node kind、graph-anchored text、functional block registryを既存validatorで検査する。missing／parse失敗／不一致はsilkscreen以降をfail-closedで停止する。compile reportはL2だが、入口検査は合否を変更しないL3観測ではなく、L1ゲートやEvidenceの代替でもない。残る限界は要件変更の候補生成や任意graph固有の妥当性を自動推論せず、unknown／未回答を推測しない点である | 中 |
| L-4 | order-total生成経路の欠落 | 達成。`scripts/aggregate_order_total.py`と`acd_aggregate_order_total`を追加し、複数quote record、OrderScope、FabProfileDocumentから検証済み`OrderTotalDocument`を生成できる。`run_design_loop`にも条件付き`order-total-aggregation` stageを接続し、生成物をorder-readinessへ渡す。legacy `--order-total` document modeとの同時指定はfail-closedで拒否する。集計は決定論的なL2経路であり、L1合格権限やauthoritative Evidenceを持たない。残る限界はquote取得、supplier選択、実発注を行わず、入力recordの妥当性と既存scope契約に依存する点である | 高 |
| L-5 | 生成物既定値のgd1残留 | 達成。KiCad project name、workspace command/download path、OpenHands tool output path、FW boot logの既定値をgraph_idから導出し、graph不明時はGD1へfallbackせずfail-closedにした。GD1 fixtureは明示`boot_log_message`属性と互換prefixで従来path・文字列を再現する。残る限界は任意graphのゲートregistry・部品catalog被覆（L-6）と実機FW検証である | 中 |
| L-6 | 契約registryとcatalogのトポロジ被覆 | 達成部分あり。`contracts/topology-templates.json`をPydanticでfail-closedに検証し、document-levelの`shared_nets`とtemplate-localなrefdes／net IDのscopeで代替blockを許可しつつ、registryへ対応するtemplateを持つblockをPython変更なしで合成できる。`register_part_catalog_entry.py`／`acd_register_parts_catalog_entry`はlibrary fileの存在・SHA-256・source宣言を検査し、曖昧な選択keyを増やさず、既存entryのテキスト整形を保持して原子的に追加する。USB-Cを持たないfixtureと電池給電fixtureの回帰テストで到達性を示した。一方、電池の充電・保護回路の規範的契約やpredicateは追加していないため、その判定は未対応であり16.2・16.3に依存する | 中 |
| L-7 | 本書の「現状」列の陳腐化 | 解決済み。A節・K節・G節の「現状」列が14.5・14.7・14.8の達成後も更新されておらず実装状態と齟齬があったため、本節の追加と同じ変更で更新した。実測根拠の観測記録は変更しない | 低 |

## M. マイルストーン14.11後のVibeBB単体成立再監査

本節はL-1〜L-6の実装後に、会話開始から発注可否までの経路をコードベース横断で再確認した
結果である。既存の閾値、ゲート挙動、fail-closed境界、L1権限を変更する提案は含まない。
本節の各項目を汎用エージェント環境で実行して確認した記録は
[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md)にある。GD1以外の新規設計を
実機OpenHands環境で実行した記録は[`vibebb-onpremise-verification.md`](vibebb-onpremise-verification.md)に
あり、M-2が上流（`DesignFixtureSpec`にmechanical・silkscreen・firmware moduleの宣言が無い）で
顕在化してGD1以外ではlaneへ到達できないことを実測している。

現時点で「acd-agent単体」で成立するのは、自然文由来の宣言を入力とした要件record化、
graph生成・改訂、機能ブロック宣言、部品選定、トポロジ合成、基板・筐体・FW laneの
決定論的ゲート実行、却下後の基板候補探索、stage cache・resume・timing、
order-total集計と発注可否判定までである。成立しないのは、供給者からの実見積取得と
実発注送信（M-3）であり、これは外部接続とcredentialに依存するため実装だけでは閉じない。
残りのM-1・M-2はacd-agent内で閉じる不足、M-4・M-5は設計能力・実機検証の拡張である。

| # | 不足機能 | 根拠 | 優先度 | 依存 | 完了条件 |
|---|---|---|---|---|---|
| M-1 | 筐体却下後の候補探索がloopへ自動連結されていない | `run_design_loop`は`explore_board`だけを受け取り、`src/acd/core/enclosure_exploration.py`の`explore_enclosure_candidates`は[`vibebb-loop.md`](../plugins/acd/commands/vibebb-loop.md)で手動実行として案内している。基板だけがL-2で自動連結され、筐体干渉の却下後は会話側の手作業に戻る | 高 | なし（L-2の連結構造と`enclosure_exploration`を再利用する） | 筐体pipelineのfail-closed却下時に限り、全lane join後へ候補予算とround上限付きで連結する。graph IDとrevisionが探索前と一致し、正規化content hashが変化し、探索reportの`target_revision`がgraph revisionと一致することを検証してからloopを再実行する。基板・FW・silkscreenの失敗では起動しない。timing名をround修飾する。探索reportはEvidence権限を持たず、exhausted／stopped／不正report／上限到達は元の筐体失敗理由を保持する。起動条件と非起動条件の両方に回帰テストを持つ |
| M-2 | 任意graph向けの設計固有検証laneが無い | `src/acd/pipeline/lane_plan.py`のpytest subsetは`gd1_only=True`で宣言され、`artifact_prefix == "gd1"`のときだけlaneへ現れる。GD1以外の設計はlane runnerから設計固有の回帰検証を受けられない | 中 | A-2／A-3の宣言経路（達成済み） | 検証lane対象を設計側の宣言（fixture spec等）から導出する。宣言が無い設計ではlaneを宣言せず、未宣言を合格として扱わない。GD1の現行subsetは不変とし、`--jobs 1`と並列で収集件数・判定・正規化hashが一致することを固定する |
| M-3 | 見積取得と実発注のsupplier接続 | D-2／D-3はprovider境界で停止し、L-4の`aggregate_order_total`はquote recordを入力として要求する。会話からは実価格・在庫・納期・実装可否を取得できず、発注可否判定は与えられたrecordの範囲に閉じる | 高 | 外部supplier APIとcredential（環境側の秘密情報）。acd-agentの実装だけでは閉じない | providerを`QuoteProvider`／発注provider境界の実装として接続する。期限切れ、通貨不一致、在庫・実装可否のunknownはfail-closedとする。dry-runを既定に保ち、credential不在時は停止する。送信recordとjournalへ入力hashと出力hashを記録し、実発注結果をL1合格権限へ昇格しない |
| M-4 | 電池の充電・保護回路とEMC/ESDの設計述語 | `src/acd/core/design_predicates.py`の`PREDICATE_CATALOG`は6件で、電源境界とdecoupling以外に充電・保護・電力バジェット・保護素子有無の判定を持たない。L-6でtopology templateと部品catalogの追加経路は宣言経由へ開いたが、規範的な契約と述語は追加していない | 中 | 16.2（バッテリ駆動）・16.3（EMC/ESD） | 述語の適用条件を14.2の契約registryで宣言し、宣言外はunknownとして停止側へ集約する。消費電流と容量の収支を宣言由来入力から決定論的に検査する。正負両方のテストを持ち、既存GD1の判定と正規化hashを変えない |
| M-5 | 実機FW検証 | FW laneはSkill subprocessのpin/config照合とQEMU仮想実行までで（C-2／C-3）、実機書き込み後の動作Evidenceはloopの判定に入らない | 低 | 実機とマイルストーン5の実機Evidence取り込み経路（実装済み） | 実機Evidenceをrevision一致で取り込み、virtual／host実行をprovisionalとして区別する。実機Evidence不在はunknownとして停止し、virtual結果を実機合格へ昇格しない |
| M-6 | 自然文から宣言への変換責務（不足ではなく境界） | `compile_requirement_change`と`build_design_fixture`は`RequirementDocument`／`DesignFixtureSpec`という構造化宣言を入力に要求する。自然文から宣言への変換はplugin側のAgentDefinition（L2）が担い、決定論的coreは未回答・unknownを推測しない | — | なし | 追加実装は不要。coreが自然文を推測しない境界を維持し、宣言不足はL-3の入口整合検査でfail-closedとする |

## N. 実機OpenHands環境での新規設計実測で残った不足

本節はM-1・M-2の記録後に、実機OpenHands環境（`test4` workspace、`git clone`なし）へGD1では
ない新規小規模設計`mini-blink-dongle`を投入した実測から抽出した不足である。観測記録は
[`vibebb-onpremise-verification.md`](vibebb-onpremise-verification.md)、会話ログ・成果物・
レポートは[`examples/mini-blink-dongle-20260825/`](../examples/mini-blink-dongle-20260825/)を
正とする。既存の閾値、ゲート挙動、fail-closed境界、L1権限を緩める提案は含まない。

N-1・N-3・N-5はM-2をさらに上流で顕在化させたもので、これが解けない限り新規設計は
silkscreen barrier以降のlaneへ到達できない。N-2・N-4・N-7・N-11は「fail-closedの停止境界が
回避行動（ユーザー指示に反するcommit、ダミー入力、定型rationaleの一括生成、手編集の消失）の
入口になっている」型の不足であり、判定を緩めずに正当な停止・報告経路を用意することで解く。

| # | 不足機能 | 根拠 | 優先度 | 依存 | 完了条件 |
|---|---|---|---|---|---|
| N-1 | `DesignFixtureSpec`がmechanical・silkscreen・firmware moduleを宣言できない | `src/acd/schema/design_fixture.py`は`components`／`nets`／`requirements`／`functional_blocks`／`firmware_pin_assignments`／`board_attrs`／`fab_profile_id`だけを受け、`src/acd/pipeline/fixture_builder.py`は`mechanical.outline`／`mechanical.silk_text`／`mechanical.silk_graphic`／`firmware.module`を生成しない。実機では生成graph 133ノードのうちこれらが0件で、筐体laneが`expected exactly one mechanical.outline node, got 0`、FW laneが`graph must contain exactly one firmware.module node`、silkscreen laneが`silkscreen declarations are missing`で停止した | 高 | なし（GD1専用builder`src/acd/pipeline/gd1_fixture/`の宣言内容を契約化する） | `DesignFixtureSpec`へ`mechanical_outline`／`silk_texts`／`silk_graphics`／`firmware_module`を追加し、`fixture_builder`が対応ノードを生成する。宣言が無い場合はlaneをskipせずfail-closedのままとし、未宣言を合格へ倒さない。GD1 fixtureの正規化hashと既存判定を変えない。宣言あり・なし双方の回帰テストを持つ |
| N-2 | Stop hookにfail-closedを未解決のまま停止する正当経路が無い | 実機会話でStop hookが`Changed design inputs require a newer valid evidence record: … Run the relevant pipeline gate, or commit changes before generating evidence.`を26秒間に15回連続で返し、laneがfail-closedでEvidenceを生成できない状況では選択肢が「commitする」しか残らず、利用者が明示的に禁止したcommitが行われた。exportの`base_state.json`では6会話のうち3会話が`MaxIterationsReached`で終了している | 高 | なし | 直前のゲート実行がfail-closedで記録されている場合に、失敗理由・停止段・Evidence未生成を含む停止報告レコードの提出でstopを許可する。合格側権限は与えず、Evidence鮮度要求自体は維持する。同一理由のdenyが上限回数連続した場合はエスカレーション（停止許可と人間への引き渡し）へ切り替える。hookメッセージからcommitの示唆を除く。deny継続・停止許可の両方に回帰テストを持つ |
| N-3 | 新規設計向けの必須宣言preflightが無い | container内のsilkscreen resolverは属性不足を1件ずつ報告し、実機では`pcba_class_target`、pinned library、`J1.A8`のpinノード、stitch-via basis、IPC-2221定数、`+3V3`の`width_basis_source`、`BOOT`のmanufacturing marginなど9回連続でfail-closedし、そのたびにgraph手編集と再実行を要した | 高 | N-1（宣言経路） | laneごとの必須ノード・必須属性を一括診断して不足一覧を機械可読に返す入口を追加する。診断は報告のみでL1判定を代替せず、診断成功を合格として扱わない。laneごとの必須宣言一覧を`docs/`へ記録する |
| N-4 | rationale coverageがL2生成の定型レコードで満たせる | 基板laneの`rationale coverage failed: missing=82, stale=10`に対し、実機agentが自作scriptで全対象ノードへ同一の`decision`／`justification`、単一要件のみを指す`driving_requirement_refs`、固定`recorded_at`、`provenance.source: "deterministic_tool"`を一括生成してcoverageをpassさせた（script実体は[`examples/mini-blink-dongle-20260825/agent-artifacts/`](../examples/mini-blink-dongle-20260825/agent-artifacts/)） | 高 | なし | rationale recordのprovenanceへ生成主体（Skill名とscript SHA-256、またはagent）を必須記録とし、`deterministic_tool`を自称できないようにする。定型文の重複、単一要件への集中、固定`recorded_at`をcoverage側で検出してfail-closedにする。既存GD1 rationaleが合格し続けることを回帰テストで固定する |
| N-5 | U1のIO-to-pad mappingを宣言経由で与えられない | `src/acd/core/design_predicates.py`の`_u1_io_pads`は`cpl_rotation_pin_functions`／`cpl_rotation_pin_aliases`からGPIO→pad対応を解決し、一意解決できないと`unknown`になる。MPNが`ESP32-C3-MINI-1-N4`と確定していても実機では`strapping_pin: status='unknown' (U1 IO-to-pad mapping is missing or ambiguous)`で基板laneが停止した | 高 | N-1、14.2の契約registry | parts catalog entryへモジュールのpin function mapを持たせ、`part_request`での選択時にgraphへ決定論的に展開する。展開元をprovenanceへ記録する。catalogに無い部品は従来どおりunknownでfail-closedとする |
| N-6 | 要件テキストとnetlist topologyの一致を検査する述語が無い | 実機fixtureは要件`mbd-req-007`「LEDはIO3に4.7 kΩを直列接続」に対し、`net.led = {U1 pad21, R3 pad1, D1 pad1}`／`R3 pad2 = +3V3`／`D1 pad2 = GND`という直列でない接続（LEDがGPIOへ直結、R3はプルアップ）になっていたが、どのゲートも検出しなかった（手前の`strapping_pin: unknown`で停止したため露呈もしなかった） | 中 | 14.2の契約registry | 「駆動ピンとLEDの間に直列素子が存在する」型のtopology述語を`PREDICATE_CATALOG`へ追加し、適用条件を機能ブロック宣言から解決する。自然文からの導出はL2に留め、判定は宣言済みトポロジに対する決定論的検査とする。正負両方のテストを持ち、GD1の判定と正規化hashを変えない |
| N-7 | `run_design_loop.py`のorder入力必須がダミー入力を誘発する | order入力なしでは`failed_stage: "input"`／`order-total document is required when aggregation is disabled`となり設計反復を1つも実行できず、実機agentは金額0・`quote_id: "dummy-quote-1"`・hashゼロ埋めの架空order-totalを作成した（[`examples/mini-blink-dongle-20260825/runs/host-design-loop/order-total.json`](../examples/mini-blink-dongle-20260825/runs/host-design-loop/order-total.json)） | 中 | なし | 設計反復のみを実行するmodeを追加し、その実行ではorder-readiness以降を「未実行」としてfail-closed扱いで記録する。既知のダミー`quote_id`やゼロ値hashのorder-totalを入力段で拒否する。skipを合格として扱わないことを回帰テストで固定する |
| N-8 | out-rootをroot実行containerとhost実行が共用すると権限失敗になる | 実機archiveのtarエントリでは`out/mini-blink-dongle/**-silkscreen-resolve/`配下48エントリが`root/root`であり、後続のhost実行が`[Errno 13] Permission denied`／`[Errno 1] Operation not permitted`で停止し、真の停止理由（`silkscreen declarations are missing`）が隠れた。非root実行では`error: Failed to initialize cache at /.cache/uv`で失敗する | 中 | なし | host／container経路でout-rootを分離するか、container実行時に`--user`と書き込み可能な`UV_CACHE_DIR`／`HOME`を与える。いずれも不能な場合はout-rootに他ユーザー所有物がある時点で権限起因として区別可能なメッセージでfail-closedにする |
| N-9 | lane scriptのCLI引数が不統一 | `run_fw_pipeline.py`は`--graph`を受け付けず（exit 2）`--fixture`のみで、laneごとに`--fixture`／`--graph`／`--out`／`--out-root`の受け口が異なるため会話経路で引数探索の往復が発生した | 低 | なし | laneのCLIを`--fixture`＋`--out`へ揃え、`run_design_lanes.py`の宣言からそのまま単体実行できる形にする。旧引数は明示エラーで案内する |
| N-10 | graph単体検証の入口が無く、存在しないscriptが案内される | 実機agentが`scripts/validate_design_graph.py`を実行して`No such file or directory`（exit 2）になった。graph単体の妥当性検証コマンドが存在せず、案内と実体が一致していない | 低 | N-3 | N-3のpreflightをgraph検証入口として提供するか、graph検証は`build_design_fixture`とlane入口検査に一元化することを`docs/`へ明記し、存在しないscript参照を残さない |
| N-11 | `build_design_fixture`が既存graphの手編集を無警告で上書きする | 実機では、container laneをpassさせるために手で属性を追加した`graph.json`が次の`build_design_fixture.py`実行で上書きされ、追加分がすべて失われた（残ったのは投影のみ） | 中 | N-1 | 既存ファイルと生成物の差分を検出したら、上書き前に停止するか差分を報告する。入力ファイルを設計の正とする不変条件に沿い、生成器が入力を黙って捨てないことを回帰テストで固定する |
| N-12 | 実機実行記録の公開可能な持ち出し経路が無い | `out/`は`.gitignore`対象で、実機記録を`examples/`へ残す作業は手作業だった（archive約522MB／展開後約2.0GBに対し必要分は約1.2MB）。加えてOpenHandsのraw export zipは`base_state.json`にホスト名・LLMエンドポイント等の環境識別情報を含み、そのまま公開リポジトリへ収録できない | 低 | なし | 実行記録から公開可能な最小集合（fixture、loop結果、timing record、gate evidence、失敗summary）を収集する入口を追加し、ホスト名・エンドポイント・ユーザー名の秘匿化を既定で行う。秘匿化漏れの検出をnegative testで固定する |

## O. 宣言経路解消後の実機実測（`test5`／pulse-check-tag）で残った不足

本節はN-1・N-5の解消後に、実機OpenHands環境（workspace `test5`、`/acd:init`で初期化）へ
GD1ではない新規小規模設計`pulse-check-tag`（MCUのみGD1と同一、部品10点前後、22 × 16 mm 2層）を
投入した実測から抽出した不足である。観測記録とレポートは
[`examples/pulse-check-tag-20260825/`](../examples/pulse-check-tag-20260825/)を正とする。
既存の閾値、ゲート挙動、fail-closed境界、L1権限を緩める提案は含まない。

本検証では、宣言経路（N-1）とpin function展開（N-5）の解消により、新規設計でも
silkscreen laneがdigest固定container内で`status: "resolved"`まで到達した。一方、
基板laneはFreeRoutingのtimeoutで停止し、authoritative Evidenceは1件も成立していない。
O-1・O-9は「設計内容に依らず基板lane以降へ到達できない」直接原因、O-10はFW laneがGD1専用実装である直接原因、O-12は筐体laneと発注可否判定がGD1専用であった直接原因、O-11はhook契約の矛盾、O-13は診断語彙の誤導、O-2は実行基盤側の律速であり、O-4・O-5は
N-3の未解消部分、O-3・O-6〜O-8は運用と手順の不足である。

| # | 不足機能 | 根拠 | 優先度 | 依存 | 完了条件 |
|---|---|---|---|---|---|
| O-1 | `run_tool`のsubprocess timeoutが定数で、routerのpass予算既定と組み合わせると必ずtimeoutする | 達成。`run_tool`に有限かつ正のtimeout引数（既定600秒）を追加し、FreeRouting・KiCadのlaneから明示的に渡す。timeoutは`timed_out`として`unknown`と区別したenvelopeを残し、部分出力を成果物として扱わず、合格側へ使わない。routerのpass進捗（unrouted数の推移）はL3観測として記録する | `ToolTimeoutError`、timeout envelopeのexecution provenance、無効timeoutの未実行、timeout収束のfail-closedをテストで固定した |
| O-2 | container起動がホスト資源を検査しない | 達成。`check_host_resources()`がcontainer起動前にMemTotal、MemAvailable、swap、CPU、repositoryの空きディスクを読み、要求上限と比較する。物理メモリはswapを加算せず、8 GiB上限＋512 MiB headroomを満たさない場合は`host.memory.total_insufficient`で起動を拒否する。FreeRoutingのJVM最大heapはcontainer wrapperとhost launcherの両経路へ`2g`を明示し、1 GiB non-heap reserveを含めて上限と比較する。`/acd:doctor`にもoptional checkを追加し、最小要件とO-2実測（MemTotal 1641 MiB／swap 5116 MiB／CPU 3、global OOMによるJVM 2プロセスkillとhost process巻き込み）を記録した | 高 | なし | 達成。未知・不足をfail-closedで集約し、container起動前に理由付きで停止する。`HostResourceReport`は起動前提の診断でありlane gateやauthoritative Evidenceの合格権限を持たない |
| O-3 | 長時間laneのbackground実行が手順として規定されていない | container laneをOpenHandsのtool呼び出しでforeground実行すると、O-2の再起動でtool結果ごと失われ停止理由が判別できない。実機では`nohup ... > logs/<lane>.log 2>&1 &`へ切り替えて初めて、再起動後もexit code・image digest・fail-closed理由をlogから復元できた | 中 | O-2 | `docs/operations.md`へ長時間laneのbackground＋log運用（同時1本、確認はtail／grep）を明記する。`scripts/run_in_workspace.py`へlog出力先の指定を追加し、log先頭へimage digest・revision・コマンドを必ず記録する |
| O-4 | preflightの`ready`表示が実ゲート結果と乖離する | 達成。lane preflightの状態を`declarations_complete`／`declarations_incomplete`へ変更し、`record_class: "L3"`、`diagnostic_only: true`、checked／unchecked predicate集合を機械可読に記録する。preflightの宣言検査とlane入口・決定論的ゲートの述語差分を`docs/operations.md`へ列挙した | 中 | N-3 | 達成。語彙を観測内容へ限定し、診断のみでL1判定を代替しない契約と述語集合を固定した |
| O-5 | 必須属性不足が1件1往復で報告される（N-3の未解消部分） | 実機では`rotation_deg`、`pcba_class_target`、`C1`のplacement、pinned library、outer copper thickness、stitch-via basis、IPC-2221定数、`CC1`のmanufacturing margin、`fb.esp32c3_strapping_boot`のdriving requirement、`power_boundary: unknown`、silk textのposition宣言の11件が1件ずつfail-closedし、そのたびにcontainer起動を伴う往復が発生した。現在は筐体laneで必要機械宣言とrationale coverageを一括診断する | 高 | N-3 | 達成。O-5と共有する固定語彙で機械ノード・属性・参照・rationale coverageを全件収集し、`preflight-mechanical.json`へ機械可読に出力する。診断成功を合格として扱わない |
| O-6 | doctorがhost前提とcontainer前提を同じ失敗欄に混ぜる | lock済みimageのpull後もdoctorは`IDF_PATH=unset, qemu-system-riscv32=unavailable, cmake=unavailable`をfailとして報告し続ける。これはhost provisional経路の前提であり、authoritative経路（digest固定container）の充足判断と混在する | 中 | なし | doctor出力を`authoritative-path`（image digest一致、docker実行可否、ホスト資源）と`provisional-path`（host toolchain）へ明示分離する。分離は表示の分類に留め、fail-closedの範囲を変えない |
| O-7 | lock済みimage未取得時に次手順が提示されない | doctorはネットワークpullを行わないため新規workspaceでは必ず未取得でfail-closedするが、`docker pull <image>@<digest>`に相当する次手順は出力されない | 低 | なし | 失敗メッセージへ`docker/image-digests.json`から生成したdigest固定のpullコマンド行を出力する（実行はしない）。opt-inのpullを設ける場合もdigest固定参照のみ許可する |
| O-8 | 実行記録の収集入口がlane logと実機workspaceを対象にしていない | N-12に対して追加された`scripts/export_execution_records.py`はexecution record JSONのallowlist抽出と秘匿化を行うが、本検証で唯一の記録だったbackground実行laneの`logs/*.log`（exit code、image digest、fail-closed理由）は入力に含まれず、実機workspaceからの取得も1件ずつの手作業になった | 低 | N-12 | 収集入口の入力へlane logを加え、log先頭のimage digest・revision・コマンド行を構造化して取り込む。リモートworkspaceからの取得手順を`docs/operations.md`へ明記する。既存の秘匿化と漏洩検出をそのまま適用する |
| O-9 | `--max-passes`の既定値がlayerごとに異なる | 達成。FreeRoutingの`-mp` pass budgetを`DEFAULT_ROUTER_MAX_PASSES = 100`へ集約し、GD1・探索・design loop・OpenHands tool定義の既定を同じ定数へ統一した。pass進捗はL3観測に限定し、判定へ使用しない | 中 | O-1 | lock済み`acd-tools` containerのGD1測定で、旧既定99999と明示100はSES SHA-256、`convergence_state`、PIPELINE判定、layout identity hashが一致し、wall timeも93秒対92秒だった。この根拠を`docs/operations.md`へ記録した。凍結exampleの既存記録は変更しない |
| O-10 | FW laneがGD1のnet集合とGD1のapplication codeを定数で持ち、他設計のfirmwareを生成できない | 達成。`contracts/firmware-capability-registry.json`のcapability、pin role、device registryと設計graphの`firmware.sequence_step`からFW計画を解決し、宣言されたpin macroとcapability fragmentだけを決定論的に投影する。未宣言peripheralのmacro・初期化・読み出しcodeは生成せず、unknown action、pin role不足、device解決不能、重複step、非連続stepはfail-closedとした。GD1のGPIO値、boot行、`LED gpio=%d state=%d`、`SHT40 temp_c=%.2f rh=%.2f`、`ACD_SHT40_I2C_ADDRESS 0x44`、macro出力順は維持する一方、pins logはrequired role由来の`pins led=%d i2c_sda=%d i2c_scl=%d`へ更新し、app_mainの初期化順は宣言sequence順（GD1ではI2C初期化がLED設定より前）へ揃えた。FW source hashは宣言駆動fragment構造と先頭コメントの変更分だけ変わる。非GD1のLED-only graphでI2C codeなしの投影とvirtual log checkを回帰テストで固定した。ESP-IDF／QEMU toolchainはこの環境で利用できず、build／実QEMU実行は未実施 |
| O-11 | projection guardがlaneの出力先指定とstop reportの記録をdenyし、引用を変えると通る | 達成。`protect_projections.py`をwrite-target semanticsへ変更し、`PROTECTED = ("out", "evidence")`と生成物拡張子の集合を維持したまま、editorのpath引数、patch header、shellのredirection・書き込み系commandだけを保護対象への操作として判定する。laneの`--out`／`--out-dir`／`--out-root`／`--output`／`--download`／`--cache-dir`と`out/stop-report.json`は許可し、読み取り操作と未知commandも書き込みpatternが無ければ許可する。`bash -c`等のnested shellとinline interpreterは再帰的に検査し、引用解析不能、NUL、redirection対象欠落、深さ超過はdenyする。`test_hooks.py`でlane起動（分離形・`=`形・nested形）、stop reportのterminal／inline／editor形、読み取り、redirection、`rm`／`cp`／`tee`／`sed -i`、unsafe inline write、editor write、parent escape、patch header欠落、parse failureをallow／denyのassertとして固定した。`stop_policy.py`と共有する`STOP_REPORT_PATH`で契約の矛盾を解消し、Evidenceの合否権限とfail-closed境界は変えない | 高 | なし | 達成。write-target semanticsとnested commandのfail-closed判定を実装し、lane起動・stop reportの許可および生成物への直接書き込み拒否を回帰テストで固定する |
| O-12 | 筐体laneのentrypointと発注policyがGD1固定で、GD1以外の設計がorder readiness判定に到達できない | 発注pathと筐体lane entrypointの汎用化を達成。`OrderPolicy`が固定graph path／Evidence IDではなく許可graph rootとEvidence laneを宣言し、pre-order gateが呼び出し側の対象graph pathをrepository境界・design input・parse・revision一致まで検証し、graph IDから必要Evidence IDを導出する。`scripts/run_enclosure_pipeline.py`はfixture／outを必須引数とし、機械preflightが必要ノード・属性・参照とrationale coverageを一括で機械可読に診断する | 高 | I-4 | 達成。筐体laneのentrypoint汎用化と機械宣言不足の一括診断を実装した。`QuoteRecord`と`OrderScope`を設計fixtureとfab profileから生成する決定論的経路は未着手で、見積実値が無い場合はdummy値を生成しない |
| O-13 | stop hookのrationale被覆検査がGD1固定パスだけを見て、対象設計と無関係に`pass`を表示する | 達成。core CLIはgraph／rationaleを必須指定とし、対象graph pathとrevisionを出力する。stop hookは`ACD_TARGET_DESIGN`、変更fixture、単一fixtureの優先順で対象を解決し、複数・不明状態を`not_applicable`、rationale欠落とcoverage失敗をdenyとして扱う | 中 | O-4 | 達成。対象設計を決定論的に解決し、未解決時に`pass`を表示せず、対象rationale不足をfail-closedで停止する |

## P. 多コアVPS実測（2026-08-30）で残った不足

本節はO節の実装後に、CPU 8コア／MemTotal 15.0 GiBのVPSと実機OpenHands（workspace
`test260830`）でGD1と新規設計`vibebb-sensor-node`を実行した実測から抽出した不足である。
観測記録は[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md)の9節を正とする。
既存の閾値、ゲート挙動、fail-closed境界、L1権限を緩める提案は含まない。

P-1は現行の公開imageで`/acd:init`が必ず停止する直接原因であり、同じ変更で解消した。
P-2は新規設計の1周目が基板pre-router段で止まる主因、P-3・P-4は診断表示と検査対象の不足である。

| # | 不足機能 | 根拠 | 優先度 | 依存 | 完了条件 |
|---|---|---|---|---|---|
| P-1 | install doctorのESP-IDF判定が実行ビットを要求して偽陰性になる | lock済みserver imageの`/opt/esp-idf/export.sh`は`-rw-r--r--`で、sourceすると`idf.py`が解決できるにもかかわらず、`install_doctor.py`のprobeが`test -x`で判定して`missing: IDF_PATH/export.sh`を報告し、GUIからの`/acd:init`がdoctor段でfail-closedした（`bootstrap-record.json`未生成） | 高 | なし | 達成。image probeを`test -f`かつ`test -r`、container判定を`Path.is_file()`かつ`os.access(..., R_OK)`へ変更し、実行ビットのないreadableな`export.sh`をpassとする回帰テストを追加した。fail-closed境界と他checkの判定は変えない |
| P-2 | `build_design_fixture`の初期配置がdecoupling距離制約を満たさない | 新規設計`vibebb-sensor-node`では基板laneのpre-router段で`power_decoupling`が`C4`とU1のpad距離15.838 mm（上限3.0 mm）で不合格になり、remediationが`component_placement_xy`の変更を提示した。生成直後のfixtureが必ず1回以上の配置修正反復を要する | 中 | N-1 | 初期配置生成時にdecoupling対象コンデンサをbypass対象pad近傍へ配置する制約を入れる。制約を満たせない場合はfixture生成段で不足として報告し、合格側へ倒さない。GD1 fixtureの正規化hashと既存判定を変えない |
| P-3 | FW laneのQEMU打ち切りがログ上で失敗と誤読される | 成功実行でも`qemu-system-riscv32: terminating on signal 15 from pid … (timeout)`がログへ残り、その後pipelineはbuild・QEMU仮想実行・log検査をpassとしてexit=0で終える。意図した時間打ち切りである旨がログから判別できない | 低 | なし | 仮想実行の打ち切りが正常終了条件であることをlog行として明示する。envelopeの`measurement_conditions`と整合させ、判定と閾値は変えない |
| P-4 | FW laneのauthoritative Evidenceが生成されず決定論的検査の対象外になる | container実行後の`out/container/`には基板・筐体のEvidence 2件のみが生成され、`scripts/verify_authoritative_evidence.py`もこの2件を検査する。FW laneはvirtual実行の成否がloop出力にしか残らない | 中 | O-10 | FW laneのcontainer実行結果をrevision一致のEvidence recordとして生成し、virtual実行である旨を明示したまま決定論的検査の対象へ加える。実機Evidenceへ昇格させない（M-5） |

## Q. 却下からの復帰・反復経路のコード監査（2026-08-30）

本節はP節の実測を受けて、「pre-router段で止まったときにOpenHands自身の力で復帰・反復
できるか」を基板laneに限らず全laneについてコードで確認した結果である。根拠は現行mainの
実装と、`--explore-board`を明示したdigest固定container実行の実測
（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md)の9.7節）である。閾値、ゲート挙動、fail-closed境界、L1権限を緩める提案は含まない。

前提として、L2（OpenHands、Skill、critic）は操舵と停止にだけ作用でき、決定論的ゲートの
却下をL2の判断で通過させることはできない。ここで言う「復帰」は、却下理由から設計入力を
決定論的に修正し、L1ゲートを毎回再実行して合否を取り直す反復のことである。

| # | 不足機能 | 根拠 | 優先度 | 依存 | 完了条件 |
|---|---|---|---|---|---|
| Q-1 | 却下後の自動復帰が基板laneにしか連結されていない | `run_design_loop`の復帰判定は`board_rejection()`で`stage_id == "board-pipeline"`のfail-closed却下だけを対象とし、要件入口検査、silkscreen resolve、筐体lane、FW lane、order-total集計、pre-order gateの却下では探索段へ進まずそのまま停止する。`/acd:vibebb-loop`のcommand契約にも「enclosure、FW、silkscreenの失敗では自動探索しない」と明記されている | 高 | M-1 | 筐体（M-1の`explore_enclosure_candidates`連結）を先に接続し、laneごとに「復帰可能な変更次元があるか」を宣言由来で解決してから探索段へ連結する。次元宣言が無いlaneは探索せずfail-closedのまま停止し、その旨をL3診断として記録する |
| Q-2 | 復帰経路が既定で無効で、会話経路から起動されない | `explore_board`は既定`False`であり、GUI会話の`/acd:vibebb-loop`で明示されない限り探索段は起動しない。9.3のGUI実行では探索段が起動せず却下のまま停止し、同じfixtureへ`--explore-board`を明示した9.7のRun Bでは探索段が起動した（起動の有無は指定の有無だけで決まる） | 高 | Q-1 | 設計反復modeでは探索を既定で有効にするか、却下時の応答へ「探索付き再実行の具体的な引数」を機械可読に含める。探索有効時も候補予算とround上限を必須の明示値として保持する |
| Q-3 | 候補生成が却下predicateのremediationに基づかない | `explore_board_candidates`は失敗理由を受け取らず、配置Skillの一括提案（`placement-0001`の1件）とGPIO割当の列挙を先に作り、以後は`diagnostic_dimensions`が交差する候補を再キューするだけである。`power_decoupling`のように特定pad対の距離を詰めれば済む却下でも、狙い撃ちの候補を生成できない。9.7のRun Bでは探索段が起動しても`evaluated_candidates=1`、`status='stopped'`、`termination_reason='fail_closed_stop'`、`diagnostic_dimensions=[]`、`winner_written=false`で終わり、基板laneは復帰しなかった | 高 | B-3 | 却下predicateの`remediation`（対象subjectと変更次元）を探索の入力として渡し、対象部品に限定した候補を生成する。生成できない場合は候補予算を消費せずunknownとして停止する |
| Q-4 | 探索がgraphのplacementを書き換えてもrationaleを更新せず、後続laneがstaleで停止する | `explore_board_candidates`はcandidate採用時に`graph.json`へ配置を書き戻すが、`rationale.json`の`subject_hash`と`target_revision`を更新しない。`placement_x_mm`／`placement_y_mm`／`placement_rotation_deg`はrationale必須属性のため、配置が動くとrationale recordはstaleになる。GD1 fixtureで`placement_x_mm`を0.5 mm動かすと`check_rationale_coverage`が`fail`（stale: `comp.u1`の`placement_x_mm`／`placement_y_mm`／`placement_rotation_deg`）になることを確認した。筐体laneは`check_mechanical_preflight`内でrationale coverageを検査するため、探索が基板laneを通過させても筐体laneがstaleで停止する。要件compile経路には`_refresh_rationale`があるのに探索経路には無い非対称である。9.7では候補書き込み前に探索が停止したため、この連鎖の後半（書き換え後のrerunがstaleで止まる）は実機では未確認である | 高 | Q-1 | 探索が設計入力を確定する際に、変更subjectのrationale recordを決定論的に更新する（要件compilerと同じ更新規則を共有する）。更新できない場合は候補を採用せずfail-closedにする。rationaleの生成主体と`script_hash`のprovenance検査（N-4）は維持する |
| Q-5 | spec駆動の作り直しが2周目以降できない | `run_design_loop`のfixture生成段は`graph.json`が既に存在すると即fail-closedし、tool `acd_build_design_fixture`は`overwrite`引数を持たない（`build_design_fixture(spec, out)`固定）。commandは生shellと任意Python moduleの使用を禁じているため、「fixture specを直して作り直す」反復を宣言tool経路から実行できない | 高 | N-11 | 上書きの明示宣言（既存graphの差分報告とbackup、N-11のガードを維持）をtoolとloopの引数として公開し、宣言された上書きだけを許可する。暗黙の上書きと手編集の消失は引き続き停止側へ倒す |
| Q-6 | 要件更新経路が既存requirement_idのtext更新に限られる | `compile_requirement_change`は`requirement_id`が1件に一致することを要求し、要件の追加・削除、部品追加、配置変更を反映できない。rationaleの更新はこの経路にしか無い | 中 | Q-5 | 要件の追加・削除と、それに伴うgraph差分（部品・net・宣言）を同じtransactionで反映する。曖昧な対応付けと未宣言の変更はfail-closedにする |
| Q-7 | bounded反復のharnessがplugin経路から使われていない | `run_acd_goal`（`GoalController`＋gate evaluatorでmax_iterations付きの反復を回し、gate結果とauthoritative性を分離して返す）は実装・テスト済みだが、`plugins/acd`のcommand・agent、`scripts/`のどこからも呼ばれていない。GUI会話にはbounded self-recoveryの入口が無く、反復はagentの自由記述に委ねられる | 中 | Q-1 | 設計反復向けの入口（commandまたはtool）から`run_acd_goal`相当のbounded反復を起動し、iteration上限、停止条件、gate評決の非昇格（`pass_evidence`をL1ゲート由来に限る）を契約として固定する |
| Q-8 | silkscreenとFW laneには復帰用の候補生成・診断入口が無い | silkscreen resolveは内部の`max_iterations`反復のみで、上限超過時は`max_iterations_exceeded`を返すだけで入力側の修正提案を持たない。FW laneには探索toolも候補生成も存在しない（tool一覧に該当なし） | 中 | Q-1 | laneごとに「変更可能な次元」と「却下時に提示する次手」を宣言由来で定義する。次元が無いlaneでは探索を主張せず、不足宣言をL3診断として返す |
| Q-9 | 失敗診断が出力ディレクトリ配下のEvidenceしか見ない | `diagnose_gate_failure`は`out_dir`配下の`gate-evidence/*.json`、exploration report、stitch reportだけを読み、fixture側の不足（rationale stale、宣言不足、spec↔graphの不一致）は診断対象外である。今回の実測でも、rationale coverage不足は別経路（`validate_graph`／機械preflight）で判明した | 低 | Q-4 | 診断入力へ対象fixtureのrationale coverageとlane preflight結果を加え、L2が次手を選べる形（失敗subject、変更次元、必要な宣言）で返す。診断はL3観測であり合否権限を持たない |
| Q-10 | 会話由来設計のFW stepが未登録actionを参照すると宣言経路から復帰できない | 9.7の両runでFW laneが`firmware action 'read_sensor' is not registered in contracts/firmware-capability-registry.json`で停止した。停止自体はO-10の意図どおりだが、機能ブロックとparts catalogには宣言追加tool（`acd_register_functional_block`、`acd_register_parts_catalog_entry`）があるのに対し、firmware capability registryへaction・capability fragmentを宣言追加する経路はtool一覧に無く、会話からは復帰できない | 中 | O-10 | capability registryへのaction／capability fragment追加を、provenance検証付きの原子的追記として宣言tool経路へ公開する。未宣言actionのcode生成は引き続き行わず、曖昧な追加は拒否する |

P-2〜P-4とQ-1〜Q-10はマイルストーン14.15で解消した。P-2は`solve_decoupling_placements`に
よる初期配置のdecoupling距離解決（`decoupling_target`宣言のあるfixtureに限定し、不足は
L3 reportとfail-closedで報告）、P-3は意図した打ち切り（exit code 124）を正常終了として
`termination_condition`と`measurement_conditions`へ明示、P-4は`build_firmware_evidence`／
`write_firmware_evidence`によるrevision一致のFW lane Evidence（virtual実行を明示し、
host実行はprovisionalのまま）で解消した。Q-1・Q-8は
`contracts/lane-recovery-declaration.json`とlane復帰planによる基板・筐体・FW・silkscreen・
order-readinessの宣言（次元が無いlaneは`explorer="none"`と次手をL3で返す）、Q-2は却下応答の
`recovery_rerun`（機械可読な再実行引数）と`recover_lanes`、Q-3は却下predicateの
`remediation`由来の候補生成（remediation不在では予算を消費せず停止）、Q-4は
`refresh_rationale_document`をrequirement compilerと共有する`commit_candidate_graph`の原子的
確定、Q-5は`fixture_overwrite`（backupと差分report付き、暗黙上書きはfail-closed）、Q-6は
要件の追加・削除を含む同一transaction反映、Q-7は`/acd:vibebb-recover`と
`scripts/run_acd_goal.py`のbounded反復入口、Q-9は失敗subject・変更次元・rationale
coverage・lane preflight・必要宣言を含む診断拡張、Q-10は
`acd_register_firmware_capability`と`scripts/register_firmware_capability.py`による原子的な
capability宣言追記で解消した。いずれも閾値、ゲート挙動、fail-closed境界、L1権限を変更せず、
探索report、診断、goal評決はpass authorityを持たない。

## R. 14.15実装後に残るFW lane候補生成と配置テストの不足

本節はQ節の実装（マイルストーン14.15）後にコードを再確認した結果であり、実測ではなく
実装由来の不足である。ロードマップ上は[`roadmap.md`](roadmap.md)の14.16に位置付ける。
既存の閾値、ゲート挙動、fail-closed境界、L1権限を緩める提案は含まない。

| # | 不足機能 | 根拠 | 優先度 | 依存 | 完了条件 |
|---|---|---|---|---|---|
| R-1 | FW laneの候補生成が基板向け探索の流用である | `explore_firmware_candidates(...)`は`explore_board_candidates(...)`へlane_idとartifact_kindだけを差し替えて委譲しており、候補次元も評価前提も基板pipeline側と共有する。FW固有のremediation（未登録action、pin function不整合、capability宣言不足）に対して候補を絞り込めない | 中 | Q-3、Q-8 | FW pipelineの却下predicateとcapability registryの宣言だけを入力とするFW専用生成器を設け、宣言された次元（`gpio_assignment`とFW設定次元）に限って候補を列挙する。基板側の配置・回転次元を候補へ含めず、宣言不足は候補生成ではなく必要宣言のL3提示として返す |
| R-2 | 初期配置の決定論的テストがホストのKiCad footprint libraryへ依存する | `tests/core/test_decoupling_placement.py`はpinned footprint libraryが無い環境で全caseをskipし、開発ホストではP-2の回帰が検出されない | 中 | P-2 | pad座標を宣言した最小fixtureで配置解と距離判定を回帰させ、実libraryを要するcaseはdigest固定container jobで実行する。libraryの有無で判定が変わる経路をskipで隠さない |
| R-3 | FW laneの却下から復帰までの実測記録が無い | 14.15はFW laneの復帰宣言とEvidence生成を追加したが、[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md)にFW却下からの復帰実測が無い | 低 | R-1 | FW laneの却下から復帰までをdigest固定containerで実測し、round、候補ID、変更subject、再実行laneを追記する |

## S. 14.15実装後の実機実測（2026-08-31）で残った不足

14.15の復帰経路実装後、同じ8コアVPSでplugin更新・新規workspace作成・digest固定container実行を
行った実測（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 10節）で
判明した不足である。ロードマップ上は[`roadmap.md`](roadmap.md)の14.17に位置付ける。
ゲートはいずれも正しく閉じており、緩和ではなく経路の是正で解く。

| 項目 | 内容 | 実測での現れ方 | 影響 | 依存 | 解決方針 |
|---|---|---|---|---|---|
| S-1 | 候補の評価がrationale更新前のgraphで行われ、placement次元の復帰が構造的に成立しない | `recover_lanes`で生成された候補`placement-0001`は`power_decoupling`を満たす配置へ戻していたが、`deterministic pipeline rejected candidate: rationale coverage failed: missing=18, stale=18`で`gate_rejected`。`commit_candidate_graph`のrationale更新はwinner確定時にしか適用されない | 高 | Q-3、Q-4 | 候補評価の入力生成に確定経路と同一の`refresh_rationale_document`を適用し、評価対象graphとrationaleを同一transactionで整合させる。閾値とcoverage要件は変更しない |
| S-2 | 候補予算とround上限が実効にならない | `--max-exploration-candidates 3 --max-exploration-rounds 2`を指定しても`evaluated_candidates=1`、round=1、`termination_reason=fail_closed_stop`で終了する | 中 | S-1 | 却下が候補固有である場合は残予算で次候補を評価し、予算消費と`remaining_budget`をL3記録へ明示する。fail-closedの停止条件そのものは維持する |
| S-3 | GUI配布形態ではACD toolが会話へ登録されず、command宣言が満たされない | 新規workspaceの`base_state.json`の`agent.tools`は`terminal`／`file_editor`／`task_tracker`／`canvas_ui_control`／`launch_child_conversation`のみで、`/acd:vibebb-loop`が`allowed-tools`として宣言する`acd_*`が存在しない。`register_acd_tools()`は`build_acd_conversation()`経路にしかない | 高 | ADR-0036 | ambient install経路の会話へACD ToolDefinitionを登録する配布経路を定義する。登録できない形態ではcommandが宣言toolの不在をfail-closedに検出し、代替手順を返す |
| S-4 | 部品catalogのlibrary資材宣言と新規fixture生成が食い違う | 新規specからの生成が`FixtureBuilderError: decoupling placement could not be resolved: pinned library file missing: /workspace/acd/libraries/Espressif.pretty/ESP32-C3-MINI-1.kicad_mod`でfail-closed。catalogはfixture相対`libraries/...`を宣言するが、生成fixtureへ資材が置かれず`resolve_fixture_path()`はfixture dirとrepository rootだけを探索する | 高 | P-2、A-2 | catalog entryの資材宣言を、生成fixtureへの同梱かcontainer内絶対pathのどちらかへ統一し、宣言と生成の両側を同じ契約で検査する |
| S-5 | 長時間laneの進行と試行状況が会話へ返らない | 基板laneは147秒の実行の大半を占めるが、GUI側には現在のlane、経過、試行回数、残予算が出ない。L3 timing recordとexploration reportは生成されている | 低 | Q-2 | 既存のL3 timing record・exploration reportを会話へ返す表示経路を定義する。表示はL3観測であり合否権限を持たない |

S-1とS-4は、それぞれ復帰経路と新規設計入口の最初の停止点であり、単体成立の前提である。
S-3はGUI配布形態そのものの不足であり、実装ではなく配布・登録経路で解く。

### S節の実装状況

| 項目 | 状況 | 実装 |
|---|---|---|
| S-1 | 解消 | 候補評価が一時fixtureへ`refresh_rationale_document`を適用する（`src/acd/core/exploration.py`、`src/acd/core/enclosure_exploration.py`）。却下候補で元のgraphとrationaleは変更されず、rationaleの欠落・破損はfail-closed |
| S-2 | 解消 | 候補固有の却下は`gate_rejected`として残予算で次候補を評価し、予算内訳と`termination_reason`をreportへ記録する。fail-closedの停止は即時打ち切りを維持 |
| S-4 | 解消 | `src/acd/core/library_assets.py`をcatalogと生成fixtureの共通契約とし、相対宣言の資材を生成fixtureへ同梱してhashを両側で検査する。`scripts/verify_library_assets.py`をfast段へ追加。canonical store `libraries/`への移動でcommit済みGD1 fixtureの相対宣言が解決できなくなった問題は、基板・回路図・project・CPL経路の解決を`resolve_fixture_library_path()`（fixture同梱copy優先、canonical storeへfallback）へ統一して解消した |
| S-5 | 解消 | `scripts/report_progress.py`がtiming recordと探索reportをL3 digestとして会話へ返す。読めないrecordは`unknown`で非零終了 |
| S-3 | 部分 | `scripts/verify_acd_tool_registration.py --command`が宣言toolの不在をfail-closedに検出し、不足toolごとに決定論的CLI入口またはCLI入口が無い理由を返す。ambient install経路の会話へACD ToolDefinitionを登録する配布形態自体は未了 |

いずれの表示・診断もL3観測であり、`pass_evidence`と合否権限を持たない。

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
| Q-4／Q-5 | 却下後に設計入力を作り直す手段が宣言tool経路に無く、rationaleの整合回復とfixtureの再生成が生JSON編集かファイル削除になる。今回のVPS実測でも新規設計の2周目は宣言経路から開始できなかった |

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
11. M-1〜M-6（マイルストーン14.11後の再監査）。M-1（筐体却下後の候補探索の自動連結）とM-2（任意graph向け検証lane）はacd-agent内で閉じるため先に扱う。M-3（実見積・実発注のsupplier接続）は外部接続とcredentialに依存し、実装だけでは閉じない。M-4は16.2・16.3、M-5は実機、M-6は境界の維持である。
12. N-1〜N-12（実機OpenHands環境での新規設計実測）。N-1・N-3・N-5（宣言経路とpreflight、pin function展開）を先に扱い、次にN-2・N-4・N-7・N-11（停止境界が回避行動を誘発する箇所）を解く。N-6は述語追加、N-8〜N-10・N-12は運用と手順の整備である。
13. O-1〜O-13（宣言経路解消後の`test5`実測）。O-1（`run_tool`のtimeout引数化）とO-9（pass予算既定の単一化）は基板lane到達の前提であり最優先。O-10（FW laneのGD1固定解消）とO-11（projection guardの誤検出と迂回）も同順位で扱う。次にO-2（container起動前のホスト資源検査）、O-5・O-4（一括preflightと語彙の是正）を扱う。O-3・O-6〜O-8は運用と手順の整備である。O-12（筐体laneと発注policyのGD1固定解消）はO-10と同順位で扱い、O-13（rationale検査の対象解決）はO-4と同時に扱う。
14. P-1〜P-4（多コアVPS実測）。P-1（install doctorのESP-IDF判定）は本変更で解消済み。次にP-2（初期配置のdecoupling制約）を扱い、P-4（FW laneのEvidence生成）はO-10の後続、P-3は表示の是正である。
15. Q-1〜Q-10（却下からの復帰・反復経路）。Q-4（探索後のrationale更新）とQ-5（spec駆動の作り直し）は、復帰経路をend-to-endで閉じるための前提であり最優先。次にQ-3（remediation由来の候補生成）とQ-2（会話経路からの起動）を扱う。実測では探索段を起動しても候補が書き込みに至らないため、起動の既定化より候補生成の是正が先である。Q-1（laneへの連結）はM-1の後続として広げ、Q-10（capability registryの宣言追加）はO-10の後続として扱う。Q-6・Q-7・Q-8は反復入口の整備、Q-9は診断の拡張である。
16. R-1〜R-3（14.15実装後に残るFW lane候補生成と配置テスト）。R-1（FW専用の候補生成器）はFW laneの復帰を宣言された次元だけで閉じるために先に扱う。R-2（配置テストの環境非依存化）はP-2の回帰検出を開発ホストへ戻す。R-3はFW復帰の実測記録である。
17. S-1〜S-5（14.15実装後の実機実測）。S-1（候補評価前のrationale更新）は復帰経路が候補を1件も確定できない直接原因であり最優先。次にS-4（catalogのlibrary資材宣言）で新規設計の入口を通し、S-3（GUI配布形態へのtool登録）で会話経路を宣言どおりにする。S-2は予算の実効化、S-5は進行表示である。
