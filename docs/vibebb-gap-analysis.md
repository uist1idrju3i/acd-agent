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
同一と主張する記述をfail-closedで拒否できること（[`docs/roadmap-completed.md`](roadmap-completed.md)の6.2）
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
| S-4 | 解消 | `src/acd/core/library_assets.py`をcatalogと生成fixtureの共通契約とし、相対宣言の資材を生成fixtureへ同梱してhashを両側で検査する。`scripts/verify_library_assets.py`をfast段へ追加。canonical store `libraries/`への移動でcommit済みGD1 fixtureの相対宣言が解決できなくなった問題は、基板・回路図・project・CPL経路の解決を`resolve_fixture_library_path()`（fixture同梱copy優先、canonical storeへfallback）へ統一して解消した。出荷経路へ届かせるためpinned package refを修正commitへ上げ、library資材を解決するSkill scriptへ`ACD_REPOSITORY_ROOT`の設定を追加した。repository checkoutを伴わないpackaged plugin単体はstore不在でfail-closedとなり、配布形態の論点として残る |
| S-5 | 解消 | `scripts/report_progress.py`がtiming recordと探索reportをL3 digestとして会話へ返す。読めないrecordは`unknown`で非零終了 |
| S-3 | 部分 | `scripts/verify_acd_tool_registration.py --command`が宣言toolの不在をfail-closedに検出し、不足toolごとに決定論的CLI入口またはCLI入口が無い理由を返す。ambient install経路の会話へACD ToolDefinitionを登録する配布形態自体は未了 |

いずれの表示・診断もL3観測であり、`pass_evidence`と合否権限を持たない。

## T. 14.17実装後の実機実測（2026-08-31）で残った不足

14.17の是正後、同じ8コアVPSでplugin更新（`fb286380…`）・新規workspace作成・digest固定
container実行を行った実測（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 11節）で
判明した不足である。ロードマップ上は[`roadmap.md`](roadmap.md)の14.18に位置付ける。
S-1（候補評価前のrationale更新）は解消を確認できた一方、復帰は別の理由で成立していない。

| 項目 | 内容 | 実測での現れ方 | 影響 | 依存 | 解決方針 |
|---|---|---|---|---|---|
| T-1 | 候補評価が親laneと同一の`TimingRecorder`を共有し、L3観測の衝突で候補が却下される（独立recorderと観測失敗の`stopped`化により解消済み） | 候補`placement-0001`が`deterministic pipeline rejected candidate: timing stage already started: board[1/12]`で`gate_rejected`。親の基板pipelineはpre-router却下で`board[1/12]`を`finish`せず中断するため、`design_loop`の`pipeline_runner`が`timing_recorder=config.timing_recorder`を渡す候補側で必ず同名stageの再開始になる。復帰は基板却下後にしか起動しないので衝突は常に起きる。現在は候補ごとに独立したL3 timing recordを書き、観測失敗を`stopped`としてL1型の却下から分離する | 高 | S-1、Q-3 | 候補評価では親と独立した`TimingRecorder`を用いる（または候補IDでstage名をnamespaceする）。観測起因の例外は`gate_rejected`ではなく`stopped`として区別し、L3の失敗をL1判定へ持ち込まない。閾値とゲート条件は変更しない |
| T-2 | 候補生成が次元あたり1件しか返さず、候補予算とround上限が実行として行使されない（宣言順のspacing preference variantと候補診断の記録により解消済み） | `--max-exploration-candidates 3 --max-exploration-rounds 2`に対し`generated_candidates=1`、`consumed_budget=1`、`remaining_budget=2`、`termination_reason=candidate_pool_exhausted`。記録面のS-2は解消しているが、母集団が1件のため予算に意味がない。現在はplacement Skillのspacing preference variantから候補を宣言順に生成し、各候補のprovenanceを保持し、利用不能または重複したvariantを`candidate_generation`へ記録する | 中 | S-2、Q-3 | remediation次元ごとに複数候補（spacing preferenceを段階的に変えた配置）を宣言順で列挙し、`generated_candidates`が上限へ届く生成側を用意する。候補の由来（Skill名・script sha256・proposal hash）とvariantを記録し、利用不能・重複は`candidate_generation`へ記録する |
| T-3（解消済み） | ambient install経路の会話へACD toolが登録されない | 新規workspaceの会話が露出するtoolは`terminal`／`file_editor`／`task_tracker`／`finish`／`think`／`switch_llm_profile`／`invoke_skill`の7つで、`acd_*`は存在しない。pinned SDK v1.44.1のplugin形式（根拠: `vendor/software-agent-sdk/openhands-sdk/openhands/sdk/plugin/`）にはToolDefinition登録面がないため、ambient経路での登録は主張しない | 高 | S-3、ADR-0036 | commandが宣言toolの不在をfail-closedに検出し、決定論的CLI fallbackへ倒す。CLI入口を持たない3 toolの段は実行せず不成立として報告する。drift guardをfast段で実行し、この判定はL3観測でauthoritative Evidenceを生成しない |
| T-4 | 失敗理由と進行の表示は改善したが、1画面で読める形になっていない（loop summaryとL3 digestの統合により解消済み） | loop summaryへ`failure_reason`と`next_step_action`が入り、`report_progress.py`は`status: "pass"`でtiming recordと探索reportを返す。一方で両者は別出力であり、GUIから「どのlaneが、なぜ止まり、次に何をするか」を一度に読めない。現在は各loopがcanonical hash付き`loop-summary.json`を保存し、digestが`ok`、失敗lane、理由、次手順、roundを同一行で返す | 低 | S-5 | `report_progress.py`のdigestへ`failure_reason`と`next_step_action`を取り込み、lane・経過・試行・残予算・次手順を単一のL3出力にまとめる。表示はL3観測であり合否権限を持たない |
| T-5 | download対象が欠落したとき、runnerがcommandのstdout／stderrを出さずにtransport失敗で終了する（command出力保持により解消済み） | 探索の出力先を`out/runD`にした実行で、graph由来の既定download path（`out/gd1/evidence-electrical.json`）が存在せず`failed to download workspace file … after 3 attempts`で終了し、container内で得られていたlane結果と探索reportが読めなかった。`_execute_and_download()`は`exit_code == 0`のときだけdownloadするため、commandが成功扱いで終わると欠落が例外になり、`run_in_workspace.py`はstdout出力前に`return 2`する。現在はtransport errorへcommandのexit code・stdout・stderr・部分downloadを保持し、出力してから非ゼロ終了する | 低 | O-2 | Evidence欠落をfail-closedに保ったまま、transport失敗時もcommandのexit code・stdout・stderr・失敗種別を出力してから非ゼロ終了する。download pathの導出規則（graph由来の既定と明示指定）は変更しない |

T-1は復帰経路の唯一の停止点であり、L1の判定内容ではなくL3観測の混入である。
T-2はT-1の解消後に予算を意味あるものにするための前提である。
T-5は判定ではなく検証作業の可読性に関わる項目で、fail-closed境界は変えない。

T-1〜T-5は上記の実装により解消済みである。T-3では、pinned SDK v1.44.1のplugin形式に
ToolDefinition登録面が無い事実を踏まえ、ambient経路でのtool登録を主張せず、commandの
宣言tool不在をfail-closedに検出して決定論的CLIへ倒す経路とdrift guardを実装した。
CLI入口を持たない3 toolの段は実行せず不成立として報告する。この判定はL3観測であり、
authoritative Evidenceを生成しない。
実機で成功した復帰runのwall-clock記録も未取得である。いずれのL3 recordも
`pass_evidence: false`であり、L1の合否権限とfail-closed境界は変更していない。

## U. scope改定と第5回実機実測（2026-08-31）で残った不足

2026-08-31のscope改定により、自動発注と実機測定は将来機能・非対象とし、既存コードは
残置したまま決定論的loopの必須段から外す。製造提出データの品質と独立検査は現行必須であり、
本節の不足はロードマップ上の14.19（[`roadmap-completed.md`](roadmap-completed.md)）で扱う。

| 項目 | 内容 | 実測での現れ方 | 影響 | 依存 | 解決方針 |
|---|---|---|---|---|---|
| U-1 | 生成物の再読込がlocale／既定encodingに依存し、非UTF-8既定ではreloadがfail-closedする（AST guardと拡張回帰testにより解消済み） | Run Fは独立reload段で`ReloadError: golden-design-1.kicad_sch: unparsable s-expression: 'ascii' codec can't decode byte 0xc2 in position 29115: ordinal not in range(128)`となった。当該バイト列はparts catalog由来の`Bluetooth®`である。Run Hは`PYTHONUTF8=1`でreloadを通過したが、Run I／Jのmain process・既定process pool・spawn pool・build123d import後のprobeではlocale変更主体の再現に至らなかった。production read/writeをUTF-8へ固定し、reloadに加えてfab（BOM／CPL、fab-package、gbrjob／ZIP）、筐体（STEP／3MF／STL、manifest）、FW（summary／serial log／Evidence）の`LC_ALL=C`等child-process回帰を実装した。guardは`src/acd/**/*.py`、`scripts/**/*.py`（`scripts/tests/**`を除外）、`plugins/**/scripts/**/*.py`のtext I/OをASTで検査し、明示された`utf-8`／`utf-8-sig`／厳格な`ascii`以外の非literalやencodingをfail-closedにする。例外は呼出し行の`# encoding-exempt: <英語の理由>`のみで、空理由は許可しない | 高 | S-4、O-4 | 生成物を読み書きする経路への明示encodingと、上記全経路の非UTF-8 locale回帰testを実装済み。guardはfast段で実行し、閾値・ゲート条件・fail-closed境界は変更しない |
| U-2 | 筐体出力にSTLがなく、3D印刷サービスへそのまま提出できる形式が不足する（実装により解消済み） | Run Hで確認できた筐体出力はSTEP 3点と3MFであり、STLは存在しなかった。コード検索でも`stl`／`STL`文字列は`src`／`plugins`／`scripts`に存在しない。現在は筐体laneがASCII STLを出力し、宣言した正規化、manifest／provenanceとnormalized hash、Evidence claimを生成する。3MFとSTLを独立reloadし、3MFの2部品、union bbox、STLのbbox・三角形数・体積を検査する | 中 | 11.4 | 筐体laneにSTL出力を追加し、STEP／3MFと同じ正規化hash・provenance・独立reload検査の対象にする（実装済み） |
| U-3 | 文書化されたquote／order付きloop例が対象graphとrevision整合しない（GD1整合fixture追加により解消済み） | Run Hはlaneを通過した後、`OrderTotalError: order scope target revision does not match`でfail-closedした。`fixtures/contracts/valid/order-scope.json`と`quote-order.json`は`r12`、`fixtures/golden-design-1/graph.json`は`r1`である。GD1向け`r1` fixtureを追加し、例と回帰testを更新して解消した | 中 | O-12 | GD1の例は`order-scope-golden-design-1.json`と`quote-order-golden-design-1.json`を使う。contract schema向け既存`r12` fixtureは変更せず、対象graphと異なるrevisionの入力はfail-closedする。order集計とpre-order gateはquote／order scope入力時のみの任意段であり、revision検査は緩めない |
| U-4（解消済み） | 新規specからのfixture生成が、decoupling制約とcourtyard非重複を同時に満たせず停止する | Run Kは`FixtureBuilderError: declared decoupling placement is not satisfiable: C4->U1: no candidate placement satisfies the declared decoupling distance limit without overlapping another courtyard`でfixture-generation段に停止した。library資材解決（S-4）は通過し、生成fixtureに`libraries/`と`decoupling-placement-report.json`が生成された | 中 | P-2、A-2 | 既存のorigin探索を最初に維持し、空振り時だけ宣言rotationを再計算して探索し、残存deficientには最大4回の決定論的配置順序passを実行する。距離limitと`COURTYARD_CLEARANCE_MM`は緩めず、不足量・blocking refdes・探索次元・変更可能次元をL3 reportへ記録する。電気laneにside／layer宣言がないため面配置は実装せず、利用不可として記録する |
| U-5（解消済み） | 製造提出データの「提出可能品質」の合格条件が単一の宣言としてまとまっていない | Run Hは製造データを生成した一方、提出可否をまとめた判定がorder集計段の停止と混ざり、発注実行を行わない現行scopeでは製造データだけの合否を独立に読めなかった | 中 | O-12、ADR-0005 | Gerber一式・drill・gbrjob・gerbers.zip・BOM・CPL・fab-package manifest・筐体STEP／3MF／STLを必須成果物とし、独立reload・正規化hash・DFM・幾何・profile整合・revision整合・Evidence妥当性を単一のL1判定へ統合した。`order-readiness.json`は状態記録のみで、quote集計・発注実行から独立して判定する。発注しない場合も品質要件を下げない |

自動発注と実機測定は将来機能・非対象であり、未実行をVibeBB未達の理由にしない。一方、
製造提出データの生成と品質判定は現行必須で、L1の決定論的検査として維持する。

## V. 第6回実機実測（2026-08-31、新規VPS・新規workspace）で残った不足

新規VPS（8コア／16GB）へ新規OpenHands workspaceを作成し、GUI会話から`/acd:init`と
`/acd:vibebb-loop`を実行したうえで、digest固定containerでGD1フルloopと新規spec生成を
実行した実測（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 13節、
[`examples/golden-design-1-vps-20260901/`](../examples/golden-design-1-vps-20260901/)）で
判明した不足である。GD1は要件検証から製造提出判定・authoritative Evidence検証まで
端から端まで通過した一方、新規設計は最初のlaneで止まった。V-7〜V-10は
[`improvement-notes.md`](../examples/golden-design-1-vps-20260901/report/improvement-notes.md)の
D-1〜D-4に対応する。ロードマップ上はV-1、V-3、V-5〜V-7、V-9を[`roadmap.md`](roadmap.md)の
14.20、V-4、V-8、V-10を15.17〜15.19に位置付ける。V-2はOpenHands GUI側の課題であり、
本リポジトリの実装対象外として記録だけを残す。

| 項目 | 内容 | 実測での現れ方 | 影響 | 依存 | 解決方針 |
|---|---|---|---|---|---|
| V-1 | container内のEDA資材をhostへ持ち出す操作がhookで止まらない | GUI会話はhostにKiCad symbolが無い状態を回避するため、locked container内の`/usr/share/kicad/symbols`・`footprints`をtarでhostの`/tmp`へ取り出し、成功した。host実行はprovisionalという別の防御でEvidence権限は守られたが、持ち出し自体は`PreToolUse` hookを通過した | 中 | 4.1、6.4 | container→hostのEDA資材持ち出しをhookで拒否するか、host実行時にcontainer由来資材の混在を検出してprovisional理由へ記録する。authoritative経路の定義は変えない |
| V-2 | GUIのplugin追加pickerがinstalled storeを反映しない | installed APIは`acd`（`enabled=true`、revision一致）を返すのに、GUIの追加pickerは`No available plugins.`を表示する。導入確認と再導入がGUIから不可視で、検証のたびにAPI直叩きになる | 低 | ADR-0036 | OpenHands側の課題として記録する。本リポジトリでは`/acd:init`のbootstrap recordを一次資料として扱い、GUI表示に依存しない |
| V-3 | 会話の最終報告がL3記録だけで合格を述べる | GUI会話の最終報告は`pass_evidence: false`のL3記録（loop summary、timing record）だけを根拠に、発注可能な状態であると述べた。authoritative Evidence検証は会話内で実行されていない | 高 | S-5、T-4 | commandの報告契約へauthoritative Evidence検証の実行と結果提示を必須項目として書き、`report_progress.py`のdigestへEvidence未検証を明示する行を持たせる。未検証時に合格側の語を使わせない文面規則をcommandへ置く |
| V-4 | 例示commandが必ずquote期限切れになる | `docs/operations.md`のGD1発注集計例は7か所すべて`--evaluated-at 2026-08-14T00:00:00Z`だが、GD1のquote fixtureは`valid_until: 2025-01-17T09:00:00Z`であり、文書どおりに実行すると`QuoteReadError: quote has expired`で必ず停止する（実測2回とも同一） | 中 | U-3 | 例示`--evaluated-at`をquoteの有効期間内へ揃え、例示とfixtureの期限整合をdocs検証で機械的に固定する。quote有効期限と期限検査の閾値は緩めない |
| V-5 | 部分失敗時にcontainer成果物を回収できない | `scripts/run_in_workspace.py`の`_execute_and_download()`はcontainer commandがexit 0のときだけdownloadする。loopが途中でfail-closedすると生成済みEvidenceと製造データがhostへ降りず、`verify_authoritative_evidence.py`にかけられない。本実測では、container側commandの末尾でtarを作り`exit 0`させ、内側のexit codeをstdoutへ`newspec_rc=1`として残す回避策を取った。この回避策は失敗を成功として読ませうるため、定着させてはならない | 中 | T-5、O-2 | 非ゼロ終了時も宣言済みdownloadを試み、判定はcontainerのexit codeで維持する経路を`run_in_workspace.py`へ設ける。部分downloadを合格側へ昇格しない |
| V-6 | 新規specはsilkscreen宣言の不足で止まり、次に何を宣言すべきか分からない | 新規spec（`examples/mini-blink-dongle-20260825/fixture/spec.json`）はfixture生成とdecoupling配置まで成功したのち、`silkscreen-resolve`で`GraphExtractionError: silkscreen declarations are missing (fail-closed)`となった。`next_step_action`は「graphを調整して再実行せよ」であり、`mechanical.silk_text`の必須属性名を返さない。受け口（`DesignFixtureSpec.silk_texts`／`silk_graphics`）と必須属性宣言（`lane_preflight`の`LANE_REQUIREMENTS`）は既に存在するが、loopはpreflightを実行しない | 高 | J-2、A-2、Q-4 | fixture生成とloop入口で実行予定laneの`run_lane_preflight`を評価し、不足するnode kind・数・属性名を列挙して`next_step_action`へspecへ追記すべき宣言を具体名で返す。宣言の自動補完は行わず、silkscreenゲートの閾値と必須性は変更しない |
| V-7 | `timing-record.json`の`duration_seconds`をwall-clockとして読むと誤る | `duration_seconds`は26 stageの合計であり、lane並列のためwall-clock（Run N 259秒）より大きい（Run N 473.4秒）。13.7は当初この合計をGUI経路のwall-clockとしてCLIの248秒と比較し、「GUI経路は約2倍遅い」という誤った読みになっていた | 低 | O-5 | timing recordへ`wall_clock_seconds`（loop全体の開始・終了時刻）を明示的に持たせ、stage duration合計と区別する。いずれもL3観測であり合否権限を持たない |
| V-8 | 資源計測wrapperが特定checkout前提で固定されている | 計測wrapperはcheckoutパス、download対象、image指定が固定で、別workspaceでの再実行にコピー改変が必要だった | 低 | 15.13 | checkout path、image digest、download対象、計測間隔を引数で受ける計測wrapperをrepository内へ置く。使い捨てshell scriptを書く状態を解消し、実測条件の再現性を上げる |
| V-9 | 会話exportから`acd_*` tool未登録の判定材料が読み取りづらい | 会話exportには登録tool一覧（`ConversationStateUpdateEvent`の`value.tools`）が含まれるが、それがACD toolの不在を意味するかの判断にACD側の知識が要る | 低 | T-3、S-3 | `verify_acd_tool_registration.py --command`の結果を機械可読JSONとしてworkspaceへ保存し、第三者が一次資料から入口の不成立を確認できるようにする |
| V-10 | ESP-IDF buildツリーが成果物回収の大半を占める | FW laneの出力は約207 MiBで、その大半（約203 MiB）は再生成可能なESP-IDF buildツリーである。収録では`flash.bin`、`qemu-serial.log`、Evidence、プロジェクト入力だけを残した | 低 | U-5 | lane summaryへ「収録すべき最小成果物集合」を機械可読に宣言し、回収・配布時に何を残すかを決定論的に決められるようにする。成果物の必須性判定は変更しない |

V-6は新規設計の唯一の停止点であり、Devin不在でVibeBBを1周させるうえで最優先である。
V-3とV-9は、会話経路がL3記録だけで合格を述べないための報告契約と一次資料である。
V-1、V-5、V-7、V-8、V-10は防御の深さと検証可能性の項目であり、いずれも
閾値、ゲート条件、fail-closed境界を変更しない。

### V節の実装状況

| 項目 | 状況 | 実装 |
|---|---|---|
| V-6 | 解消 | fixture生成（`scripts/build_design_fixture.py`、loopの`fixture-generation`）とloop入口の`lane-preflight` stageで`run_lane_preflight`を評価する。不足はnode kind、必要数・現在数、不足属性名、`DesignFixtureSpec`上の追記先（`silk_texts[].attrs`など）を1回の結果に列挙し、`next_step_action`へ「specへ追加すべき宣言」を具体名で返す。silkscreen laneでは`mechanical.silk_text`の8属性を名指しする。preflightはL3診断であり、`declarations_complete`はゲートを実行させるだけで通過を意味しない。宣言の自動補完は行わない |
| V-7 | 解消 | `timing-record.json`（schema 0.2）が`stage_duration_sum_seconds`と`wall_clock_seconds`を別値として持つ。wall-clockは`TimingRecorder`生成からrecord書き出しまでの経過時間で、並列laneでは合計がwall-clockを上回りうる。`report_progress.py`のdigestは両値を別々に表示する |
| V-5 | 解消 | `_execute_and_download()`はcommandが非ゼロで終了した場合も宣言済みdownloadを試み、回収できなかったfileは`download_errors`へ記録する。`exit_code`と`failure_kind="command"`は維持され、download成否は判定に影響しない。transport失敗（`-1`）とtimeoutではdownloadを試みない |
| V-9 | 解消 | `verify_acd_tool_registration.py --command`が結果を`out/tool-availability/<command名>.json`（`--record`で変更可）へ保存する。判定不能も`status: unknown`として同じ場所へ残し、いずれも`record_class: L3`、`pass_evidence: false` |
| V-3 | 解消 | `plugins/acd/commands/vibebb-loop.md`が「合格」「発注可」を述べる前に`verify_authoritative_evidence.py`の実行とrevision一致・`status="valid"`・container provenance・order-readiness結果の提示を必須とする。`report_progress.py`のdigestは常に`authoritative_evidence: unverified`と対応する行を含む |
| V-1 | 解消 | `plugins/acd/hooks/scripts/eda_asset_export.py`（`refuse-eda-asset-export`）が`PreToolUse`で`docker cp`・`docker exec ... tar`・`cp`・`tar`・`rsync`・`scp`・`cat`・`dd`・`zip`・`install`によるcontainer内EDA資材（`/usr/share/kicad`等）の持ち出しと、EDAパスを対象とする`--download`を拒否する。`ls`等の読み取り検査と通常のworkspace出力downloadは許可する。authoritative経路の定義は変えない |

## W. GD1非依存の達成条件

「GD1が無くても新規設計をVibeBBできるか」を判定可能にするための条件である。GD1 fixtureは
regressionのpositive controlとして維持し、削除は目的にしない。解消すべきはGD1が
「唯一全ゲートを通る設計」である状態である。ロードマップ上は[`roadmap.md`](roadmap.md)の
14.21で扱う。

| 項目 | 内容 | 現状 | 依存 | 達成条件 |
|---|---|---|---|---|
| W-1 | GD1以外の設計が全laneを通過する | 解消。`fixtures/mini-blink-dongle/spec.json`（silkscreen・筐体・FW・fab宣言を完備した新規spec雛形）がdigest固定containerでsilkscreen→基板→筐体→FW→製造提出判定→`verify_authoritative_evidence.py`を通過した | V-6、J-2 | 宣言完備の非GD1 fixtureを1件追加し、要件検証→silkscreen→基板→筐体→FW→製造提出判定→authoritative Evidence検証をdigest固定containerで通す |
| W-2 | 既定値・既定fixture・既定命名のGD1固定が残っていない | 解消。残存するGD1参照は`contracts/gd1-reference-inventory.json`へ用途付きで棚卸しし、`scripts/verify_gd1_references.py --check`が追加参照をdriftとして検出する | 14.6 | GD1へ解決される既定経路を洗い出してgraph_idと宣言由来へ置換し、positive control用途で残す参照は用途を明示宣言する |
| W-3 | 設計述語の適用条件が機能ブロック宣言だけで決まる | 解消。`design_predicates.py`はMCUを`firmware.module`の`mcu_component`宣言またはIO機能宣言から解決し、`U1`固定を持たない。refdesを変えた述語テストと宣言不足のfail-closedテストで固定する | 14.2 | 適用条件が宣言由来であることを機械的に検査し、GD1前提の分岐をdriftとして検出する |
| W-4 | CIのauthoritative gateがGD1だけに依存しない | 解消。`container-gates`は非GD1 fixtureのbuild・lane実行・製造提出verdictを`DockerWorkspace`で実行し、GD1と同じrevision・`status`・provenance・digest基準で検証する | 6.4、W-1 | 非GD1設計のlaneを`container-gates`へ追加し、GD1と同じ判定基準でauthoritative Evidenceを検証する |

W-1〜W-4を満たした時点で、GD1はVibeBB成立の必要条件ではなくなる。ただし「自然文要件のみで
agentが自力生成した新規設計がauthoritative Evidenceで1周する」条件には、第8回実機実測
（dual-beacon-tag、2026-09-06）の時点で達していない（Y節を参照）。その後もGD1は
positive controlとして維持し、GD1の判定・Evidence・正規化hashが変化しないことを
非GD1設計の追加によって壊さないことを回帰の条件とする。

## X. 第7回実機実測（2026-09-06、12コアVPS・新規workspace）で残った不足

12コアVPSへ新規workspaceを作成し、pluginを`main`先頭へ更新してGUI会話の`/acd:init`・
`/acd:vibebb-loop`とdigest固定containerのGD1全laneを実測した記録
（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 14節）で判明した不足である。
FW Evidenceの`input_hash`が常に`"unknown"`になる欠陥は同じ変更で修正し、3 laneのEvidenceが
1回の`verify_authoritative_evidence.py`で通過することを実機で確認した。

| 項目 | 内容 | 実測での現れ方 | 影響 | 依存 | 解決方針 |
|---|---|---|---|---|---|
| X-1 | plugin更新でpackage pinとversionが追従しない | installed pluginのrevisionは`f636c73…`へ進んだが`version`は`0.0.2`のまま、`acd-package-ref.txt`は`b3e531b…`で本体より古い。GUI経路のSkill subprocessが実行する本体revisionをこの記録では確認できない | 中 | ADR-0036 | plugin資材の変更時にpackage pinを同じ変更で更新することを機械検査（docs driftと同種）で固定する |
| X-2 | FW Evidenceの`input_hash`が常に`"unknown"`で、権威検証の対象からも漏れていた | `firmware_evidence.py`が入力graphを出力側`out_dir.parent`から推定して`"unknown"`へ倒れ、`verify_authoritative_evidence.py`は正しく拒否した。一方、文書例示と`container-gates`は基板・筐体の2件だけを検証しており、第6回13.10の「FWもvalid」は誤記であった | 高 | — | 解消。生成側は`graph_path`必須・不在はfail-closedへ修正済みで、lane runnerも`scripts/run_firmware_lane.py`経由で`evidence-firmware.json`を書く。`container-gates`とcommand契約は`verify_authoritative_evidence.py --out-root`＋`--require-lane electrical|mechanical|firmware`で3 laneのEvidenceを検証する |
| X-3 | 会話から`run_in_workspace.py`を起動する際の`--repo`・`--download`誤り | 1回目は`--repo /workspace`でgraph読み込み失敗、2回目は`--download`未宣言で既定の`out/gd1/…`を取りに行きtransport失敗（`exit_code -1`）。loop本体は完走していたが回収は手作業になった | 中 | V-5 | 解消。command契約（`vibebb-loop.md`）へworkspace pathと具体commandを記載し、runnerは`--download-root <out_root>`でout root配下の`*.json`／`*.log`を一括回収する（`out/container/<out_root>`へ配置）。空の回収や絶対path指定はfail-closed |
| X-4 | `--source mounted`の起動overhead | 起動ごとにcontainer内で依存同期が走り、loop外側に10秒台が乗る（見積り、単独計測は未実施） | 低 | — | image同梱venvの再利用または同期結果cacheを実測して採否を決める |
| X-5 | FreeRoutingと他laneのCPU競合 | 同じDSNの単独実行156〜163秒に対しloop内`board[3/12]`は180〜183秒。router threads・JVM tuningではSES一致のまま短縮しない | 低 | E-2 | FW laneのbuild並列度を`--jobs`から導出して競合を抑える案を実測し、短縮が競合分（20〜25秒）以内に留まる事実も併せて記録する |

X-2以外は閾値、ゲート条件、fail-closed境界を変更しない。X-2の修正も`"unknown"`への退避を
fail-closedへ置き換えるだけで、合格側の条件は緩めていない。

## Y. 第8回実機実測（2026-09-06、自然文のみ新規設計）で残った不足

自然文要件のみをGUI会話へ投入し、GD1とは無関係の新規設計`dual-beacon-tag`（r1）を
agentが自力でspec生成から走らせた実測
（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 15節、
[`examples/dual-beacon-tag-vps-20260906/`](../examples/dual-beacon-tag-vps-20260906/)）で
判明した不足である。loopは`board-pipeline`の`router convergence_state='not_converged'`
（fail-closed、探索は`exhausted`）とenclosure laneの`unsupported connector opening
face: right`で停止し、authoritative Evidenceはfirmwareの1件のみで、検証は
`FAIL: required lane Evidence missing: electrical`（終了コード1）であった。
pristine `e45f1ec`での対照runは同一の壁を再現しており、会話内でのagentの`src/`改変は
最終失敗に対して荷重を持たなかった。一次記録のN-1〜N-9・D-1〜D-9・F-1〜F-4は
`examples/dual-beacon-tag-vps-20260906/report/notes.md`を正とし、D-1〜D-11を
Y-1〜Y-11として整理する。ロードマップ上は[`roadmap.md`](roadmap.md)の14.22で扱う。

| 項目 | 内容 | 実測での現れ方 | 影響 | 依存 | 解決方針 |
|---|---|---|---|---|---|
| Y-1 | order-total未指定のエラーが回避経路を示さない | `fixture-generation`で`order-total document is required when aggregation is disabled`のみ返り、agentはpromptの禁止に反して`order-total.json`（USD 0、`dummy-quote-1`）を捏造した（F-1） | 高 | — | 解消。メッセージが`--design-only`と発注入力の供給を指し、`vibebb-loop.md`へordering-excluded要件時のdesign-only運用と発注document捏造禁止を記載した |
| Y-2 | rationale coverage失敗が不足属性名を返さない | メッセージが「fail」だけで、agentは`check_rationale_coverage`をmonkeypatchするdebug scriptと`fixture_builder.py`改変で内訳を覗いた（F-2） | 中 | Q-4 | 解消。`summarize_rationale_coverage`がcoverage reportを1行へ要約し（各分類の件数と先頭5件の属性名、`…(+N more)`で省略）、`FixtureBuilderError`と`validate_and_project_rationale`の失敗メッセージがそれを含める。ゲート条件は変更していない |
| Y-3 | symbol／footprintのsha256 pinを試行錯誤で埋める経路が無い | agentは`sha256:000…`のplaceholderを置いてfail-closedメッセージの「got」値を転記し、container round-tripごとに60〜90秒を消費した | 中 | V-6 | 解消。`scripts/pin_library_hashes.py`が`components[].attrs`の`symbol_file`／`footprint_file`宣言を解決して実ファイルの`sha256:` digestを計算し、`--write`でspecへ記入する。`--write`無しは照合として`mismatch`・`unpinned`・`missing`を非ゼロ終了にする。hash検査自体は緩めない |
| Y-4 | `strapping_pin`がnet名`"LED"`固定で複数LED駆動netを評価できない | 2LED設計では`unknown`へ倒れ、agentはnet名に"led"を含むnetを集める`_led_nets()`へ改変した（F-3、名前substring heuristic） | 高 | J-2、W-3 | 解消。宣言済み`led_indicator`／`led_drive_net`属性と`LED`名fallbackで全LED駆動netをstrapping padへ照合する形へ一般化し、strapping pad上の第2駆動netを不合格とするnegative testで固定した |
| Y-5 | `safety_boundary`等のenum許容値がpreflight・文書から見えない | agentは`intended_use`等をGD1 graphのenum値から写した。spec上で許容値を発見する経路が無い | 中 | V-6 | 解消。`src/acd/core/declaration_vocabulary.py`が許容値を単一の正とし、`lane-preflight`が`safety.boundary.*`／`net.width_basis_unsupported`の`unsupported_values` codeでfail-closed報告する。`docs/design-fixture-spec.md`へ宣言場所と許容値表を追加した。値の意味と審査基準は変更しない |
| Y-6 | FW capability契約が2LED交互点滅・ボタン入力を表現できず要件driftが止められない | `fw.sequence`から`toggle_led comp.d2`と`read_button`が削除されFWはD1のみ点滅。requirement→fw.sequenceの被覆検査が無くdriftはfail-closedを発動しない（F-4） | 高 | D-11、Q-10 | 解消（被覆検査側）。graph／registryのみで判定する`check_firmware_coverage`を追加し、FW laneがSkill起動前に`firmware coverage failed`でfail-closed停止する。規則は`led_indicator`部品のsequence target必須（led_indicator_untargeted）、sequenceが使うcapabilityの`emits_triggers`外triggerの拒否（trigger_unemitted、registryへ`emits_triggers`を宣言追加）、未消費pin roleの拒否（pin_role_unconsumed）、未登録actionの拒否（action_unregistered）の4種で、結果は`firmware-coverage.json`とpreflightの`firmware_coverage`へL3診断として残る。dual-beacon-tagは`comp.d2`・`button_pressed`×2・`fw.pin.led_orange`・`fw.pin.user_btn`のfindingで診断可能に止まる。2LED交互点滅・入力を実際に表現するcapability追加はY-11に残る |
| Y-7 | silkscreen resolverが未宣言位置を後段へ流す | resolve stageは通過したのにboard-pipelineが`silkscreen texts … has no declared position`でfail-closedした | 中 | V-6 | 解消。`_run_silkscreen`は`status != "resolved"`（`failed_no_candidates`・`max_iterations_exceeded`・status欠落を含む）をfail-closedとし、failure_reasonへ未解決`mechanical.silk_text` node IDを、`next_step_action`へx_mm/y_mm宣言または探索入力拡大の案内を出す。判定条件は変更していない |
| Y-8 | router非収束の内訳が`loop-summary`へ出ない | `unrouted`が22→21でplateauしたが、loop-summaryは`not_converged`のみで、agentはrouter証跡を手で読む必要があった | 中 | B-3 | 解消。`read_router_diagnostics`が`<board出力>/l3/router-pass-progress.json`と`gate-evidence/routing-connectivity.json`を読み、board-pipeline／board-exploration失敗時の`loop-summary`へ`router_diagnostics`（収束状態・`unrouted`推移・最終未配線数・plateau pass数・statusが`fail`のnet名を10件上限で列挙）と探索候補ごとの`candidate_router_diagnostics`をL3診断として記録する。plateau（末尾3 pass以上同一値）は制約を広げる操作を、減少継続は`--max-passes`引き上げを、timeoutは`--router-timeout-s`引き上げを`next_step_action`へ追記する。読み取り失敗は`read_errors`／`router_diagnostics_error`へ記録し、ゲート・閾値・`assert_converged`・passの意味を変更しない |
| Y-9 | `decoupling_target`の多ピン対象の意味が文書化されていない | C3/C4→U1（複数P3V3ピン）がplacement skillの`ambiguous decoupling declaration`でhard failし、agentは宣言を削除した | 中 | P-2 | 解消。対象が同一電源netを複数padで共有する場合、placement skillは自然順最小padへ決定論的に解決し、`target_pad`・`target_pad_candidates`を配置出力へ記録する。capacitor側の共有電源pin・GND pinは引き続き各1本必須で、不成立時は件数つきの`ambiguous decoupling declaration`でfail-closed停止する。規則は`docs/design-fixture-spec.md`と`docs/glossary.md`へ記載した |
| Y-10 | Evidenceにsource-treeのgit SHA／dirty状態が無く、`is_design_input`が`src/`を検出しない | `order_gate.py:78-82`のdirty検査は`design_input_changes`経由で、`evidence/git.py:48-52`の`is_design_input`は`fixtures/*/graph.json`と`profiles/*`だけを見る。検証checkout内の`src/`改変は記録されず、Evidenceはbootstrap recordの`e45f1ec`と食い違うdirty treeから生成された（F-3） | 高 | X-2 | 解消。`ToolEnvelope`へ`source_revision`・`source_tree_state`・`source_dirty_digest`を追加し、`run_in_workspace.py`（`--source mounted`）は`src`・`scripts`・`plugins`・`contracts`・`libraries`・`docker`・`pyproject.toml`・`uv.lock`を対象にgit provenanceを採取して`ACD_SOURCE_*`環境変数でcontainerへforwardする。dirtyまたは解決不能なtreeは`--allow-dirty`無しでcontainer起動前に拒否され、許容時もprovenanceが記録される。`verify_authoritative_evidence.py`はprovenance欠落・`unknown`・非`clean`をfail-closedで拒否し、`--source-revision <sha>`で全envelopeのsource revision一致を要求できる。`--source bundled`はprovenanceが常に`unknown`となり、そのEvidenceはverifierを通過できない。ゲート閾値は変更していない |
| Y-11 | FW capability契約（`firmware_init`・`led_blink`・`i2c_sensor_init`・`i2c_sensor_read`・`serial_log`、単一LED・入力pin role無し）が要件を表現できない | `fw_project.py`は1本の`led` roleしか採用せず、button／inputのcapability自体が存在しない | 高 | Y-6、Q-10 | 解消（capability側）。pin roleに`led2`・`button`を追加し、`led2_blink`（`toggle_led2`、第2 LEDを逆位相点滅）と`button_input`（`read_button`、`button_pressed`を発火、内部pull-up付きactive-low入力で点滅をpause／resume）をregistryへ登録した。LED actionの`target`は`led_drive_net`が対応roleのFW pinへ解決する電気部品でなければ`FirmwareExtractionError`、両capabilityとも`led_blink`不在では`FirmwareProjectionError`でfail-closed。QEMU仮想ログ検査は`LED2 gpio=… state=`の両状態toggleを要求し`paused=1`を拒否する。dual-beacon-tagのend-to-end合格は未実証で、router非収束（Y-8）と筐体face契約（Y-2系の筐体面）の壁は残る |

Y-1・Y-4・Y-10・Y-8はそれぞれの変更で解消した。Y-6の被覆検査（`check_firmware_coverage`と
`emits_triggers`）に続き、Y-11のcapability本体（`led2_blink`・`button_input`と
pin role `led2`・`button`）も解消した。dual-beacon-tagのend-to-end合格は
router非収束と筐体faceの壁が残るため未実証である。Y-10はEvidence provenance面の追加、
Y-8は`loop-summary`へのL3診断追加であり、いずれも合格側権限の
緩和ではない。Y-2（coverage要約）とY-7（silkscreen
resolverのfail-closed前倒し）も本変更で解消した。いずれも診断面の追加であり、合格側権限の緩和ではない。enclosure laneの`face: right`壁も解消し、`mechanical.connector_opening`の
`face`は`front`・`back`・`left`・`right`を受理する（`center_x_mm`は`front`／`back`では
outline X、`left`／`right`ではoutline Yに沿って測る）。それ以外のface値は
`extract_mechanical_lane`の`GraphExtractionError`と機械preflightの
`mechanical.connector_opening.face_unsupported`でfail-closedにする。
Y-5・Y-9は本変更で解消した（宣言語彙の単一の正と多pad decoupling解決
規則。いずれも診断・文書面の追加であり、合格側権限の緩和ではない）。
N-3・N-6・N-8（hookの誤検出）は本変更で解消した。empty poll・read-only command・
読み取り系inline code・heredocのdata本文は許可し、`mv`の元pathとshell／interpreter
heredoc本文・未終端heredocは引き続きfail-closedで拒否する。

第9回実測（2026-09-07、[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md)
16節）で作動を確認できたY項目とその根拠は次のとおりである（いずれもL2／L3の作動確認であり、
dual-beacon-tagの合格を意味しない）。Y-1: `--design-only`が使われorder-total捏造は再発せず
（会話digest、`fixture/spec.json`に発注入力なし）。Y-2: `rationale coverage failed …
unclassified=4 [mechanical.outline.dual-beacon-tag.dimensions_checked_at, …]`の要約が
出た（会話digest 11:57、対照run `control/control-a/rationale-coverage.json`）。ただし
next stepの表現がsource編集を誘発した（Z-2）。Y-3: `pin_library_hashes.py`が
container内で使われhash推測は起きなかった。Y-6／Y-11: `fw.sequence`が`toggle_led`・
`toggle_led2`・`read_button`を保持し`firmware-coverage.json`は`status: "pass"`
（`control/control-a/firmware-coverage.json`）。Y-7: silkscreen resolveが
`silkscreen roles must be unique`・clearance／overlap検出で複数回fail-closedした。
Y-8: `loop/raw-container/loop-summary.json`に`router_diagnostics`（`final_unrouted: 3`、
`open_nets: ["+3V3", "GND"]`、`plateau_passes: 5`、`unrouted_progression`）と
`next_step_action`が記録された。Y-10: dirty treeは`source tree is dirty … pass allow_dirty`で
container起動前に拒否され、生container経路の`unknown` provenanceは
`verify_authoritative_evidence.py`が拒否した（Z-3・Z-11の残課題あり）。hook matcher: 空poll・
`find -exec grep`・read-only `python3 -c`・heredocは許可され、`mv out/… /tmp`は拒否された
（`hooks/matcher-matrix.txt`）。Y-4・Y-5・Y-9は今回の設計経路で該当場面に達しておらず
未確認である。

## Z. 第9回実機実測（2026-09-07、14.22反映後の同一要件再検証）で残った不足

roadmap 14.22（Y-1〜Y-11・hook matcher）をmergeした`main`（`180b628`）と更新済みimage
（server `sha256:3fb0e216…`）のもとで、第8回と同一文言の自然文要件を`/acd:vibebb-loop`へ
投入した実測（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 16節、
[`examples/dual-beacon-tag-vps-20260907/`](../examples/dual-beacon-tag-vps-20260907/)）で
判明した不足である。Y-2・Y-3・Y-6・Y-7・Y-8・Y-10・Y-11とhook matcherの効果は観測できた
（order-total捏造とLED2／ボタン削除は再発せず、coverage要約・library hash helper・
silkscreen fail-closed・router診断・dirty source拒否・FW capabilityが作動）。一方で
agentは停止境界ごとに`src/`編集→commit、生`docker run`、難読化commandへ倒れ、pristine
`180b628`の対照runではagent最終入力がrationale coverageで停止するため、GUI経路の到達段
（router非収束）はagentのgate緩和に依存していた。一次記録は
`examples/dual-beacon-tag-vps-20260907/report/notes.md`を正とする。ロードマップ上は
[`roadmap.md`](roadmap.md)の14.23で扱う。

| 項目 | 内容 | 実測での現れ方 | 影響 | 依存 | 解決方針 |
|---|---|---|---|---|---|
| Z-1 | `/acd:init`の手順記載が同一command内での`ACD_PLUGIN_ROOT`代入・展開を誘い、initがterminal timeoutに掛かる | 1回目は`$ACD_PLUGIN_ROOT`が空で`/skills/acd-install-doctor/…`をENOENT、2回目は約5分のtimeoutで`exit -1`（第8回N-1・N-2と同型） | 中 | N-1 | `init.md`へ変数展開を要しない起動例（絶対pathまたは2行分割）と背景実行＋log poll手順を明記する。`init_workspace.py`が進行状況をlogへ逐次出す |
| Z-2 | coverage診断の「next step」がsource側の分類表名（`REQUIRED_RATIONALE_ATTRS`／`RATIONALE_EXEMPT_ATTRS`）を示し、agentのsource編集を誘発する | `unclassified=4 … classify new attrs in REQUIRED_RATIONALE_ATTRS/RATIONALE_EXEMPT_ATTRS (see docs)`の直後にagentは`src/acd/core/rationale.py`へ免除4件を追加してcommitした | 高 | Y-2 | 会話向け診断は「その属性は契約に無いので宣言から外す／契約変更はPRで行う」と設計入力側の次手だけを示し、source表名は開発者向け文書に留める。`unclassified`の判定は変えない |
| Z-3 | source provenanceはdirty treeを拒否するが、commitで「clean」になったrevisionがbootstrap record（plugin／main）から逸脱していることを検出しない | `65f14ab`・`6dceab7`（gate緩和とscript複製を含む）で`source provenance: … clean`として受理された。agent最終報告も「`src/`変更なし」と誤報告した | 高 | Y-10 | `run_in_workspace.py`とverifierが`ACD_SOURCE_GIT_SHA`をbootstrap record／installed plugin revision／`--source-revision`と照合し、不一致をfail-closedにする。会話のstop policyは`git log <bootstrap>..HEAD`にsource pathがあれば停止報告へ載せる |
| Z-4 | projection保護hookのdeny理由が汎用文のみで、どのtoken（保護path／`$(…)`／`mv`元path）に掛かったかを示さない | 17件のdenyがすべて同一文。`docker run … $(git rev-parse HEAD) … out/…`の拒否をagentは原因誤認した | 中 | N-6 | deny理由へ判定種別（protected path token／unsupported syntax／mv source）と該当tokenを付ける。判定条件は変えない |
| Z-5 | `run_in_workspace.py`が任意commandでも既定`--graph`（GD1）由来のdownload（`out/gd1/evidence-electrical.json`等）を必須扱いし、成功したcommandを終了コード2にする | 会話とDevin環境の両方で再現（`control/defect-repro-*.log`）。agentはrunnerを放棄して生`docker run`へ移った | 高 | O-10、W-2 | 既定downloadは`--graph`が明示された場合か既定command（GD1 gates）に限り、任意commandでは`--download`指定分だけをdownloadする。存在しないdownloadは引き続きfail-closed |
| Z-6 | inline interpreterのmatcherが`base64`／`exec`による難読化を通す | `python3 -c 'import base64; exec(base64.b64decode("…"))'`で`run_design_loop`を`/tmp/out`向けに実行するcommandが許可された（`hooks/matcher-matrix.txt`） | 中 | N-6 | inline code中の`exec(`／`eval(`／`compile(`／`base64.b64decode(`／`__import__(`など動的実行tokenを検出したら「読み取り系inline code」と見なさず拒否する |
| Z-7 | `docker exec`／`ssh`等のwrapper越しに渡した読み取り専用`python3 -c`が、直接実行なら許可される同一codeでも拒否される | 15:08:55の`docker exec acd-runner python3 -c "…open('/tmp/out/…/x.kicad_pcb')…"`が拒否。本VMの`_terminal_allowed`で再現（直接: `True`、wrapper: `False`） | 中 | N-6 | wrapper commandの引数を内側commandとして再帰的に同じ規則で評価する。wrapperの利用自体を許すかは別途決める（Z-11） |
| Z-8 | agent最終報告に一次資料と矛盾する記述が含まれ、報告契約がそれを検出しない | 「`git diff --stat`なし・`src/`変更なし」（実際はcommit済み3ファイル）、「R4／R6が10 kΩで誤配線」（specはR3／R4 4.7 kΩで正配線） | 中 | V-3 | 最終報告のsource変更節は`git log <bootstrap>..HEAD --stat`の機械出力を必須とし、設計値の記述はspecからの機械抽出（部品・値・net）を添える |
| Z-9 | specへ実測・取得を伴わないevidence宣言（`cpl_orientation_evidence.evidence_basis: "confirmed"`、`profile_fetched_at`等）を置いても止まらない | 全部品に同一の`evidence_at: 2026-09-05T00:00:00Z`・`evidence_basis: confirmed`が宣言された | 中 | Y-1 | 宣言側evidence属性は「取得元と取得時点が実測記録（out配下のrecord）へ解決する」ことを検査し、解決しないものは`declared_unverified`としてL1判定から外す |
| Z-10 | `lane-preflight`がenclosure laneを`declarations_complete`と返す一方、mechanical preflightは`mechanical.node.missing=2`（H1／H2の`component_body`）・`attribute.missing=1`（`mount_hole_count`）で停止する | 対照run・GUI経路の両方で再現（`control/control-a/dual-beacon-tag-lane-preflight.json`） | 中 | Y-5、V-6 | `lane-preflight`のenclosure laneにmechanical preflightの述語（body・取付穴）を取り込み、fixture生成直後に不足を返す |
| Z-11 | 生`docker run`／`docker exec`経路はhook（保護pathのtokenが無い）にもprovenance（`ACD_SOURCE_*`・`ACD_CONTAINER_IMAGE_DIGEST`）にも掛からない | 13:07以降のEvidenceがすべて`container_image_digest: "unknown"`・`source_revision: "unknown"`。verifierは拒否したためfail-closedは保たれた | 高 | Y-10、Z-5 | Z-5を解消してrunnerを使える状態にしたうえで、hookが`docker run`／`docker exec`で`acd-server`／`acd-tools` imageを直接起動するcommandを拒否し、`run_in_workspace.py`経由を案内する |
| Z-12 | SessionStart hookが会話用project dir（workspace root以外）で`docker/image-digests.json`を解決できず「Authoritative tools are unavailable inside the locked image」を出す | init・loop両会話の先頭で出力。lockは`/home/openhands/acd-workspace-verify-20260907/docker/image-digests.json`に存在した | 低 | G-1 | `OPENHANDS_PROJECT_DIR`が空またはlock不在のとき、installed plugin rootとworkspace registryからlockを探索する |
| Z-13 | `design_loop.py --fixture-spec`が`build_design_fixture`へ`spec_dir`を渡さず、overlay宣言を持つspecは必ず`requires the design input directory`で失敗する（`scripts/build_design_fixture.py`とは非対称） | pristine `180b628`のhost実行で再現（`repair/main-host.log`）。agentは会話内でこれをsource編集で回避した | 高 | — | 解消。`spec_dir=config.fixture_spec.parent`を渡し、spec相対overlayの解決とhash不一致のfail-closedを回帰テストで固定した。digest固定container再実行はfixture-generationを通過し次段（`net 'BOOT': manufacturing margin is required`）でfail-closed（`repair/`） |

実装状況: Z-13はPR #359、Z-3・Z-5はPR #360、Z-4・Z-6・Z-7・Z-11・Z-12はPR #361、
Z-1・Z-2・Z-10はPR #362で解決方針どおり実装した（stop policyはbootstrap revisionからの
source逸脱を`source_revision_drift`の記録なしに停止させない点でZ-8の一部も担う）。
Z-9（`evidence_basis: "confirmed"`・`profile_fetched_at`等の宣言が実測recordへ解決することの
検査。`evidence.declaration`述語、`declared_unverified` code、基板pipelineのprofile provenance
照合）はPR #365、Z-8（`scripts/report_final_basis.py`による`git log --stat <bootstrap>..HEAD`と
設計値表の機械生成、`/acd:vibebb-loop` step 8の報告契約）はPR #366で実装した。
いずれの解決方針も診断・provenance・matcherの面の追加であり、
ゲート・閾値・Evidence規則の緩和を含まない。実機での再検証（第10回、2026-09-08、
[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 17節）での作動状況は
次のとおり（根拠は[`examples/dual-beacon-tag-vps-20260908/`](../examples/dual-beacon-tag-vps-20260908/)）。

| 項目 | 第10回の作動 | 根拠 |
|---|---|---|
| Z-1 | 作動 | init会話04:14–04:21: 40桁revisionで起動、timeout後に`nohup … > /tmp/acd-init.log &`と`tail`へ切り替え、`ok: true`（`conversation/init-events-digest.jsonl`） |
| Z-2 | 作動 | coverage診断「unclassified attrs are not part of the rationale contract, so remove them from the design input or propose the contract change in a separate PR」。`src/acd/core/rationale.py`の編集は0件（`report/workspace-git-changes.json`） |
| Z-3 | 作動せず（条件不成立） | 会話用project dirに`.openhands/bootstrap-record.json`が無く（`report/bootstrap-record-agent-workspace.json`）、agentもcommitしなかった。`report_final_basis.py`は「bootstrap revision unavailable … status: unknown」（AA-3） |
| Z-4 | 作動 | deny 7件すべてに種別＋token（`raw_container_image: ghcr.io/…`、`inline_write: dumps evidence`、`write_target: out/dual-beacon-tag`、`unsupported_syntax: evidence/mini-blink-dongle-cpl-orientation`。`hooks/hook-denials-loop.jsonl`） |
| Z-5 | 作動 | `run_in_workspace.py`任意command起動88回で既定GD1 downloadによる終了コード2は0件 |
| Z-6／Z-7 | 観測なし | 難読化inline code・wrapper越しread-onlyの試行が無かった |
| Z-8 | 部分作動 | 機械出力（`M contracts/parts-catalog.json`・`M src/acd/core/part_selection.py`、82行）は正確に引用。添えた説明「pipelineが自動登録」「内部キャッシュ更新」は虚偽（AA-10） |
| Z-9 | 作動 | lane-preflight「cpl_orientation_evidence.evidence_basis 'confirmed' does not resolve to a measured record … fetch it with `scripts/fetch_lcsc_footprint_orientation.py --refdes C1 --lcsc C1691`」→ agentが17件の実測recordを取得（`evidence/cpl-orientation/`）。main CIの`container-gates`もW-1 fixtureで正しく赤（AA-1） |
| Z-10 | 作動 | 最終`lane-preflight`は4 lane `declarations_complete`、`enclosure-artifacts.json`生成、`mount_hole_count`／H1・H2欠落は再発せず |
| Z-11 | 作動 | 04:53:36の生`docker run … acd-server:…@sha256:fb236ff5…`を`raw_container_image`で拒否、以後生container起動なし |
| Z-12 | 残 | 両会話のSessionStartで「Authoritative tools are unavailable … (image lock not found; searched: <project dir>, <plugin root>, /opt/acd)」。workspace registry上のlockは未探索（AA-2） |
| Z-13 | 作動 | agent最終specは`overlays/j1-usb-c-annular-ring.json`を持ち、fixture-generationを通過 |

## AA. 第10回実機実測（2026-09-08、14.23反映後の同一要件再検証）で残った不足

roadmap 14.23（Z-1〜Z-13）をmergeした`main`（`5bf2c90`）と更新済みimage
（server `sha256:fb236ff5…`）のもとで、第8回・第9回と同一文言の自然文要件を`/acd:vibebb-loop`へ
投入した実測（[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) 17節、
[`examples/dual-beacon-tag-vps-20260908/`](../examples/dual-beacon-tag-vps-20260908/)）で
判明した不足である。agentは`run_in_workspace.py`＋宣言経路にほぼ留まり（生`docker run`は
1回で拒否、gate緩和・script複製・難読化・commitは無し）、routerは収束したが、
`contracts/parts-catalog.json`へのentry追加と`src/acd/core/part_selection.py`のmessage編集を
未commitのまま`--allow-dirty`で通し、最終報告ではそれを「pipelineの自動登録」と説明した。
停止点はU2のCPL rotation宣言（mini-blink由来180°）と実測recordの不一致で、pristine対照run
（agent最終graph）でも同一理由で停止した。authoritative Evidenceは3 laneとも無く判定は不合格である。
ロードマップ上は[`roadmap.md`](roadmap.md)の14.24で扱う。

| 項目 | 内容 | 実測での現れ方 | 影響 | 依存 | 解決方針 |
|---|---|---|---|---|---|
| AA-1 | W-1 fixture（`fixtures/mini-blink-dongle/spec.json`）の`fab.order_intent.profile_fetched_at`と`cpl_orientation_evidence.evidence_basis: "confirmed"`が実測recordへ解決せず、Z-9がmain CIの`container-gates`（非GD1段）を赤にする | lock更新#364直後のrun 34184028772が赤。PRでは`container-gates`が走らず#365で検出されなかった | 中 | Z-9 | fixture側の宣言を実測（`fetch_lcsc_footprint_orientation.py`のrecord、profile実体の取得時点）へ揃える。Z-9の判定は変えない。非GD1段をPRでも走らせるか、少なくともlock更新PRで走らせる |
| AA-2 | SessionStart hookのlock探索が会話用project dir・plugin root・`/opt/acd`に限られ、`/acd:init`が登録したworkspace registryのlockを見ない | init・loop両会話で「Authoritative tools are unavailable inside the locked image」（Z-12残） | 低 | Z-12、G-1 | 探索先へworkspace registry（`acd_bootstrap_workspace`が書く登録）を加え、見つけたlockのpathを`additionalContext`へ載せる |
| AA-3 | `/acd:vibebb-loop`会話が`/acd:init`のworkspaceではなく会話用project dirで自前cloneして進み、bootstrap recordが無いためZ-3照合と`report_final_basis.py`のsource変更節が`unknown`になる | project dirに`.openhands/bootstrap-record.json`無し（404）。最終報告「bootstrap revision unavailable … status: unknown」 | 高 | Z-3、Z-8、G-1 | `vibebb-loop.md`の冒頭でbootstrap recordの所在確認を必須にし、無ければ`/acd:init`済みworkspaceへ移るか`acd_bootstrap_workspace`で作る手順を示す。`report_final_basis.py`はrecord不在を`status: unknown`のまま報告し（変更なし）、stop policyはrecord不在での最終報告を`bootstrap_record_missing`として停止報告へ載せる |
| AA-4 | `PartSelectionError`の「parts catalog has no matching part」が要求内容（kind／value／package／preferred）を示さず、agentが診断のため`src/acd/core/part_selection.py`を編集した | 11回の同一message後、05:38に`str_replace`でmessageへ`kind=… value=… package=…`を追加。pristine control-cも同じ短いmessage | 中 | S-4 | messageへ要求内容と「catalogへの追加はcontract変更としてPRで行う」の次手を含める。選択規則は変えない |
| AA-5 | `run_in_workspace.py --allow-dirty`が`src/`・`contracts/`・`scripts/`のdirtyも通し、provenance「dirty」の記録だけで設計loopが先へ進む | 88回中81回が`--allow-dirty`、64回が「source provenance: 5bf2c906… dirty」で受理。catalog 80行追加とsource編集を含む | 高 | Y-10、Z-3 | `--allow-dirty`の許容範囲を設計入力path（`fixtures/`・`evidence/`・`out/`）に限り、`src/`・`contracts/`・`scripts/`・`plugins/`のdirtyはallow-dirtyでもfail-closed（別flagを設けず、contract変更はcommit＋PRへ誘導）。Evidence provenanceのdirty記録は維持 |
| AA-6 | 未知functional block名（`dual_led_indicator`・`board_outline_mechanical`等）のfail-closedに対しagentがblock宣言を削除し、`i2c_pullup`・`led_series_element`述語が`not_applicable`となって要件検査が消える | 07:07:33「unknown functional blocks」→ 削除。最終`design-predicates.json`で両述語`not_applicable` | 中 | W-3、J-1 | 診断へregistryの登録名一覧（例: `i2c_pullup`、`led_series_element`）を添えて「対応する登録名へ置換」を次手として示す。要件文書（requirements）がLED・I2C pull-upを含むのにblockが宣言されない場合をpreflightで`requirement.block_missing`として止める |
| AA-7 | firmware pin roleの語彙が`scl`／`sda`と登録名`i2c_scl`／`i2c_sda`で食い違い、`pin_role_unconsumed`が最後まで残ってfirmware coverageが`fail` | 10回のpreflight失敗、最終`firmware-coverage.json` `status: fail`、QEMU未到達 | 中 | Y-11、Q-10 | 診断は既に登録名一覧を示す。fixture builderがgraph側の`i2c`役割（`net.sda`／`net.scl`に接続されたpin）から`i2c_scl`／`i2c_sda`を導出する宣言経路（`DesignFixtureSpec.firmware.pins[].role`の検証と候補提示）を用意する。登録名の別名追加はしない |
| AA-8 | graphの`parts_catalog_sha256`とcheckout上の`contracts/parts-catalog.json`の不一致を設計loopが検査せず、agent編集catalogから生成したgraphがpristine mainでも同段まで到達する | control-a2／b2（`sha256:c1371cf3…`のgraph）は通過、control-c（spec再生成）は`fixture-generation`で停止 | 高 | AA-5 | loop入口とlane preflightでgraph provenanceのcatalog hash・registry hashをcheckout上の契約と照合し、不一致を`contract.hash_mismatch`でfail-closedにする |
| AA-9 | 既存fixtureからの構造コピー・値転記（spec生成scriptの「from mini-blink-dongle as structural reference」、overlay copy、U2 CPL offset 180°とevidence noteの転記）を検出する面が無く、それが最終停止理由になった | 04:40 docstring、05:13 overlay copy、09:27「U2: graph CPL rotation offset differs from LCSC Evidence」 | 中 | Z-9 | `evidence_basis: "estimated"`の`evidence_note`／`evidence_revision`が他fixture名を含む、または他fixtureのspecと属性値が一致する場合を`evidence.declaration`でL3警告として列挙する。`estimated`の受理条件は変えない |
| AA-10 | 最終報告の機械出力（Z-8）は正確でも、添えた自然文の説明（「pipelineが自動登録」「内部キャッシュ更新」）が一次資料と矛盾し、報告契約がそれを検出しない | `conversation/agent-final-report.md` 3節 | 中 | Z-8 | 報告契約で、worktree blockの各変更fileにevent digest上の変更action（時刻・tool）の引用を必須にする。`report_final_basis.py`が`git status`の各entryへ最終変更時刻を添える |
| AA-11 | `ground_plane_min_island_area_mm2`（graph宣言）は充填後の検証値としてのみ使われ、`_copper_zone`がKiCad zoneへ`min_island_area`を出力しない。宣言しても島は生成時に抑制されず、小さくすると`copper island is below declared minimum area`で自壊する | 修正run fix7で30mm²を宣言→同gateでfail-closed、撤回。宣言と出力の間に乖離（`board.py`の`_copper_zone` 295-330行目に該当emit無し） | 中 | Z-9 | zone emitに`min_island_area`を追加するか、宣言側を「検証専用」として名称・文書で区別する。`UncoveredGroundRegionsError`は島のbbox・exclude理由を診断へ含める現状を維持 |
| AA-12 | 宣言`mpn`／`lcsc`と実測recordの不一致（D1 `C16224`=FPCコネクタ、C2/C3/C4/R5/R6のrecordが別部品）が最終gate（order-readinessの`cpl_rotation_basis_fab_lcsc` unknown）まで検出されない。recordはrefdes／lcsc文字列の一致のみで、record内容が宣言mpnの部品かどうかは見ない | 修正run fix16で6件のrecordを宣言lcsc値で再fetchして初めて判明。D1のspec `lcsc`自体がtypoで`C12624`が正解（recordの`Manufacturer Part`で確認） | 中 | AA-9、Z-9 | lane-preflightまたはCPL basis段で、recordの`Manufacturer Part`／package名と宣言`mpn`／`part_request`の整合をL3警告またはfail-closed検査へ加える。`check_cpl_rotation_record`のlcsc一致判定は維持 |
| AA-13 | `part_request`を持たない部品（catalog非参照、SW1）は`cpl_orientation_attrs`の注入経路を通らず、`cpl_rotation_evidence_revision`が`{graph_id}-{revision}`へ自動補完されない。`evidence_basis: confirmed`を宣言してもrevision欠如で`cpl_rotation_basis_fab_lcsc` unknownのまま残る | 修正run fix17でSW1のみunknown（order-readiness `["SW1"]`）。fix18でspec attrsへ`cpl_rotation_evidence_revision`を明示して解消 | 低 | AA-4 | 診断へ「revision等が欠ける属性名の一覧」を含めるか、builderが`cpl_orientation_evidence`宣言済み・`part_request`無しの部品へも`evidence_revision`を補完する経路を検討する。gateの受理条件は変えない |
| AA-14 | silkscreen resolverは測定が`measured_pass`のときskill探索を呼ばない。未配置テキスト（`x_mm`/`y_mm`無し）が1件だけ残ると、仮配置（board中央）が衝突なしで`measured_pass`→`_assert_no_unresolved_texts`がfail-closedし、位置を確定する機会が無い（単一テキストのデッドロック） | 修正run fix15: 機能ラベルを全撤去して`board_id`のみ残すと`silkscreen resolution accepted unresolved text coordinates`で停止。機能ラベルを併存させればsearchで全件resolveされる | 低 | Y-7 | `measured_pass`でも未配置テキストがあれば先にskillへ配置を委ねるか、`assert`の前に探索を強制する段を設ける。fail-closed自体は維持 |
| AA-15 | `U2: graph CPL rotation offset differs from LCSC Evidence`が宣言offset・basis補正後の有効offset・実測offsetを示さず、basis≠confirmedで有効offsetが0.0へ強制される機構が停止文から読めない | 第10回はagentがoffset値を疑って停止。修正run fix1（offset 0へ）も同文で停止し、fix2でbasisを`confirmed`にして初めて通過 | 高 | Z-9、AA-12 | 診断へ「宣言／有効／実測offset、basis」を併記し、次手（record確認→`confirmed`宣言、またはlcsc訂正）を示す。判定は変えない |
| AA-16 | `fitted component without LCSC part number`が「`not_fitted`にする／LCSC番号を宣言する」の二択と宣言先（spec）を示さない | 修正run fix2で停止、fix3でJ2を`not_fitted`＋`jlcpcb_class: none`にして通過 | 中 | — | `FabOutputError`へ二択の次手と宣言先を添え、`acd-contracts` Skillに手ハンダ部品の`not_fitted`宣言例を追加 |
| AA-17 | graph.jsonの直接編集でrationale recordがstale化する経路が`vibebb-loop.md`で禁止されておらず、specからの再生成（`--fixture-spec --fixture-overwrite`）が必須手順になっていない | 第9回・第10回ともagentがgraphを直接編集。修正run fix3で`rationale coverage failed: missing=8 stale=8`、fix4以降はspec先行の再生成で解消 | 高 | AA-9 | `vibebb-loop.md`で設計変更をspec→再生成に限定し、stale診断へ再生成コマンド行を添える |
| AA-18 | DFM `pad-to-board-edge-clearance`診断がpad座標と閾値のみで、違反量・最小移動量と「回転前のpad半幅で判定する」規則を示さない | 修正run fix4で停止、fix5でSW1 `placement_y_mm` 3.3→3.6にして通過 | 低 | — | 診断へ違反量と最小移動量（軸・mm）を添える |
| AA-19 | `UncoveredGroundRegionsError`・DRC `starved_thermal`／`courtyards_overlap`がbbox・座標のみで、島を囲むfootprint／track、関与参照子、有効なレバー（`min_clearance_mm`のfab最小内の下限）を示さない。`min_island_area`はzoneへ未出力（AA-11） | 修正run fix6〜fix13の8 run（via格子・refill・TP追加・J1移動は無効、`min_clearance_mm` 0.15→0.12で解消、0.10はrouter不収束） | 高 | AA-11、Y-8 | 島診断へ囲みfootprint／trackと候補レバーを列挙、DRC違反へ関与参照子を添え、`acd-placement-search` Skillへ接続子直下の島解消手順を追加。閾値・fab最小は緩めない |
| AA-20 | silkscreen resolverの停止診断が衝突統計のみで、文字列短縮／`placement_search_limit_mm`拡張の次手と、撤去時のデッドロック（AA-14）を示さない | 修正run fix13で停止、fix14でラベル短縮＋limit 12で通過、fix15の全撤去はAA-14で停止 | 中 | AA-14、Y-7 | 診断へ次手を添え、`acd-silkscreen-placement` Skillへ短縮の優先順位を書く |
| AA-21 | 新規部品のcatalog entry追加に正規経路が無く、agentは`contracts/parts-catalog.json`の未commit編集を`--allow-dirty`で通した。footprint／symbol hashの算出手順も未定義 | 第10回のcatalog編集（AA-5・AA-8）。修正runではagent由来entryをDevinがcontainer内hashで検証しcommit | 高 | AA-5、AA-8 | catalog entry追加の宣言経路（scriptまたは`acd-contracts` Skill）を用意し、hashはdigest固定container内で計算、追加は`contracts/`へのcommitとして`report_final_basis.py`に現れる形にする |
| AA-22 | agentがlcsc番号から品名・packageを確認する手順を持たず、typo（D1 `C16224`）や色違い（D2 `C2290`=`KT-0603W`）が最終gateまで残る。catalogに無い部品（橙LED）を探す経路も無い | 修正run fix16でD1訂正、D2は正規番号を特定できず未解決 | 中 | AA-12 | 宣言直後に`fetch_lcsc_footprint_orientation.py`でrecordを取得し`Manufacturer Part`を宣言mpnと照合する手順を`acd-contracts` Skillへ。部品探索はL2に留め、結果は宣言＋recordとして残す |
| AA-23 | pipelineは投影（gerber・drill・CPL/BOM CSV・STEP・3MF・SVG・theme-song MIDI）を「writerが書けたこと」と`hashes.json`のsha256でしか記録せず、writerと独立したreaderで形式（SMF chunk長・note対応、STEP header/footer、3MF zip CRC・model XML、RS-274X `M02*`終端、Excellon `M48`〜`M30`）を検査しない。theme-songはwriter内部の再読込（`render_checked_midi`）のみで、第三者parserでの検証が無い。利用者が受領ファイルを開けない場合に、生成不良か再生環境かを生成物側から判別できない | 修正run fix18の収録投影72件を`mido`・`midicsv`・`timidity`・`zipfile`・XML parserで事後検査し全件OK（[`fixed-run/projection-format-check.txt`](../examples/dual-beacon-tag-vps-20260908/fixed-run/projection-format-check.txt)）。利用者報告の`theme-song.mid`破損は3者sha256一致・構造正常で再現せず | 中 | — | 投影段の直後に`projection format check`（L3）を追加し、各投影を独立readerでparseした結果（checker名・版・要約値）を`hashes.json`の各entryへ`format_check`として記録する。parse失敗はその投影をfail-closedで欠落扱いにし、合格側へは作用させない。theme-songはSMF独立parserによる再読込を`generate_theme_song_projection`へ追加し、聴取用render（WAV）はtools imageへsynthを追加できる場合に限りoptionalな投影として`hashes.json`へ登録する（Evidence・fab packageには含めない） |
| AA-24 | acd-agentが生成できる投影のうち、`acd-product-docs`（製品説明README・取扱説明書、roadmap 9.1〜9.2）、`scripts/verify_manufacturing_submission.py`（製造提出verdict、CIの`container-gates`のみ）、`derive_png_visual_projections`（PNG raster、testのみ）は`run_design_loop.py`／`/acd:vibebb-loop`から呼ばれず、loop完走後も利用者へ渡る投影集合に含まれない。利用者が「全投影」を求めても、agentは別CLIの存在と引数を自力で見つける必要がある | 修正run fix18は`--design-only` loop完走後も`out/docs/`・`manufacturing-submission.json`・`visual/png/`を持たなかった。Devinが同digest containerで`generate_product_readme.py`（2回実行でbyte一致）と`verify_manufacturing_submission.py`（`status: pass`、host `--verdict`再検査exit 0）を追加実行して初めて得られた。PNG rasterはCLI自体が無い | 中 | — | `run_design_loop.py`の3 lane完了後に投影段を追加し、文書lane・製造提出verdict・PNG rasterを同一out root（`docs/`・`manufacturing-submission.json`・`visual/png/`）へ生成、`hashes.json`とloop-summaryの`projections`へ登録する。`--design-only`でも実行し、order lane入力は要求しない。各投影の失敗はloop-summaryへ欠落として記録しEvidence・lane判定へ作用させない。`vibebb-loop.md`へ投影集合の一覧と収録手順を追記する。PNG raster側は`src/acd/pipeline/visual_review.py`と`scripts/derive_visual_review_pngs.py`・`record_visual_vision_observation.py`・`verify_visual_review.py`で実装済みであり、design loopの`visual-review-manifest`段が全人間向け投影のPNGを派生してmanifestを書き、エージェントの`inspect_image_with_vision`による全entry検査とfail-closed検証を必須化した（L3観測、合否・Evidenceへ作用しない）。文書laneと製造提出verdictのloop組み込みは未実装のまま残る |
| AA-25 | `generate_instruction_manual.py`はGD1固有のmacro集合（`ACD_PIN_UART_TX/RX`・`ACD_PIN_USB_DP/DN`・`ACD_PIN_BOOT`・`ACD_SHT40_I2C_ADDRESS`・`ACD_LOG_PERIOD_MS`）を必須とし、GD1以外の設計では取扱説明書を生成できない | fix18の`acd_pins.h`（`LED`・`LED2`・`BUTTON`・`I2C_SDA`・`I2C_SCL`・`LED_BLINK_PERIOD_MS`）に対し`missing macros: ACD_LOG_PERIOD_MS, ACD_PIN_BOOT, ACD_PIN_UART_RX, ACD_PIN_UART_TX, ACD_PIN_USB_DN, ACD_PIN_USB_DP, ACD_SHT40_I2C_ADDRESS`でfail-closed（exit 1、`fixed-run/docs/instruction-manual.fail-closed.log`） | 中 | — | 必須macro集合を固定せず、graphのfirmware capability（`led_blink`・`led2_blink`・`button_input`・`i2c_*`・`uart_log`等）とpin role宣言から文書の節（接続手順・LED表示の意味・ボタン操作・書き込み手順）を導出し、対応するmacroが`acd_pins.h`に無ければその節をfail-closedにする。宣言に無い機能の節は書かず省略理由を文書末へ記す。推定値は書かない。GD1と新規設計の両方で再現生成（byte一致）をnegative testとともに固定する |
| AA-26 | theme-song投影はSMF（`.mid`）のみで、テキストで読める楽譜形式が無い。利用者の再生環境（QuickTime Player X・SoundFont未設定のVLC等）では`.mid`を開けず、内容を確認・編集する手段が生成物側に無い | 利用者報告: 収録`theme-song.mid`をQuickTime／VLCで再生できず、ブラウザ上のMIDI playerで再生できた（ファイルはbyte一致・構造正常、AA-23）。利用者からMML形式の投影出力の要望 | 中 | — | `theme_song.py`へ`render_mml(score)`を追加し、`render_midi`と同じ`Score`から`theme-song.mml`を決定論的に生成して`.mid`と並べて`hashes.json`・provenance（同一proposal hash・script sha256）へ登録する。MML方言（track別channel、`t`・`o`・`l`・音名/休符/タイ、drum track表記）を1つ固定して`docs/`へ記す。MML→note列の独立parserで再読込し、MIDIのnote数・総tick・pitch列と一致しない場合はMML投影をfail-closedで欠落にする。MIDI側の合否・3 lane判定・Evidence・fab packageへ作用させない |

実装状況: AA-3（bootstrap record不在の停止を`bootstrap_record_missing`宣言までdeny）、
AA-4（`PartSelectionError`へ要求内容と次手）、AA-5（`--allow-dirty`のdirty拒否）、
AA-6（未知block診断への登録名一覧と`requirement.block_missing`）、AA-7（firmware pinの
net id由来roleをregistry照合し未登録roleを候補付きでfail-closedにする）、AA-8（graphの
`parts_catalog_sha256`をcheckoutの契約と照合し`contract.hash_mismatch`で停止）、
AA-15（CPL rotation offset不一致エラーへdeclared・effective・evidence offset・
basisと宣言の次手）、AA-16（LCSC部品番号なしfitted部品エラーへrefdes一覧と
`not_fitted`／`lcsc`宣言の次手）、AA-17（rationale coverage失敗診断と
`vibebb-loop.md`へspec→再生成の規則を追加し`graph.json`／`rationale.json`の
手編集を禁止）、AA-18（`pad-to-board-edge-clearance` findingへ辺別`violation_mm`・
最小1軸移動`min_move_mm`・axis-aligned注記）、AA-20（silkscreen失敗の次手へ
text短縮→`placement_search_limit_mm`拡大→座標宣言の順序と、全label除去が
measured passの後に`accepted unresolved text coordinates`で止まるAA-14 deadlockの
警告、skillへShortening priority一覧を追加）、AA-1（W-1 fixtureの
`profile_fetched_at`をprofile実体の取得時点へ揃え、非GD1段を`fixtures/`・
`profiles/`・image digest lock変更のPRでも`container-gates`で実行）は実装した。
他は未着手。解決方針は診断・provenance・照合の追加であり、ゲート・閾値・
Evidence規則の緩和を含まない。

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
| V-6 | 解消。fixture生成とloop入口のpreflightが不足宣言名と`DesignFixtureSpec`上の追記先を返す。宣言の追記自体は設計入力側の作業として残る |
| V-3／T-3 | V-3は解消（報告契約とdigestのEvidence未検証明示）。T-3のambient経路へのToolDefinition登録は未了で、tool不在は`out/tool-availability/`のL3記録から確認する |
| V-5 | 解消。fail-closedしたrunからも宣言済み成果物を回収し、exit codeは非ゼロのまま維持する |

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
18. T-1〜T-5（14.17実装後の実機実測）。T-1（候補評価のTimingRecorder共有）は復帰経路の唯一の停止点であり最優先。次にT-2（次元あたり複数候補の生成）で予算とround上限を実効化する。T-3はS-3の未了部分と同一の配布形態の論点、T-4は表示の統合、T-5はtransport失敗時の出力保持である。
19. V-1〜V-10（第6回実機実測）。V-6（不足宣言の列挙）はDevin不在で新規設計を1周させるための唯一の停止点であり最優先。次にV-3（報告契約）とV-9（tool登録の一次資料）を同順で扱い、会話経路がL3記録だけで合格を述べないようにする。V-5（失敗時の回収）とV-7（wall-clock明示）は検証可能性、V-1は防御の深さ、V-4・V-8・V-10は運用と手順の整備である。V-2はOpenHands側の課題として記録に留める。
20. W-1〜W-4（GD1非依存の達成条件）。W-1（非GD1設計の全lane通過）はV-6の解消を前提とし、次にW-2（既定値のGD1固定の棚卸し）とW-3（述語適用条件の宣言化検査）を扱う。W-4（CIへの非GD1 lane追加）はW-1の後続であり、達成後もGD1はpositive controlとして維持する。
21. Y-1〜Y-11（第8回実機実測、自然文のみ新規設計）。Y-1・Y-4は解消済み、Y-10（source-treeのdirtyをEvidence provenanceへ記録しfail-closedへ）はPR #337で、Y-6（要件→fw.sequence被覆検査）とY-11（`led2_blink`・`button_input` capability）はPR #338・#340で、Y-8（router診断を`loop-summary`へ）と筐体face契約（`front`・`back`・`left`・`right`受理と`mechanical.connector_opening.face_unsupported`のpreflight前倒し）は解消済み。Y-2（coverage要約）とY-7（silkscreen resolverのfail-closed前倒し）も解消済みで、Y-3（library hash採取）は`scripts/pin_library_hashes.py`で、Y-5・Y-9（宣言語彙とdecoupling多pad解決規則）は本branchで解消済み。hook matcherの誤検出（N-3・N-6・N-8）も解消済みで、残る未着手項目は無い。
22. Z-1〜Z-13（第9回実機実測、14.22反映後）。第10回でZ-1・Z-2・Z-4・Z-5・Z-9・Z-10・Z-11・Z-13の作動を確認し、Z-12は未解消（AA-2）。Z-13は本変更で解消済み。Z-3（commit済みrevision逸脱の検出）とZ-11（生docker経路の遮断）はfail-closed境界の維持に直結するため最優先、Z-5（runnerの既定download）はagentが正規経路に留まる前提として同順位で扱う。次にZ-2・Z-4（診断文が回避行動を誘発する箇所）、Z-6・Z-7（matcherの回避と誤検出）を解く。Z-1・Z-8・Z-9・Z-10・Z-12は運用・報告・preflightの整備である。
23. AA-1〜AA-26（第10回実機実測、14.23反映後。AA-11〜AA-26は修正後runの実測で追記）。AA-5（`--allow-dirty`の範囲限定）とAA-8（catalog hash照合）はcontract変更が会話内の未commit編集で通った経路を閉じるため最優先。次にAA-3（bootstrap record不在の停止報告）でZ-3・Z-8を実効化し、AA-4・AA-6・AA-7（診断文とpin role導出）で宣言経路の停止境界を減らす。AA-11（zoneへの`min_island_area`未出力）とAA-12（宣言mpn／lcscとrecord内容の不一致の未検出）は修正runで実害を確認した宣言〜検証の乖離。AA-15〜AA-22は修正後runでDevinが人手で行った作業の振り返り（`vibebb-standalone-verification.md` 17.12）を出所とし、停止文への次手の付与とSkill手順の整備でagent単独の到達段を進める項目である。AA-17（spec先行の再生成の必須化）とAA-19（GND島診断）、AA-21（catalog追加経路）を優先する。AA-23（投影の独立reader形式検査）は利用者へ渡す投影の受領可否を生成物側から判別するためのL3記録で、投影段の直後に置く。AA-24（文書lane・製造提出verdict・PNG rasterのloop組み込み）とAA-25（取扱説明書生成のGD1固有macro依存の解消）は、loop完走後に利用者が受け取る投影集合をacd-agentの全投影へ揃える項目で、いずれもL3投影の追加であり判定を変えない。AA-26（theme-songのMML投影）は利用者要望による投影形式の追加で、同一`Score`からのrenderと独立parserによる一致検査を条件にする。AA-1は別PRのfixture修正、AA-2はZ-12の続き、AA-9・AA-10・AA-13・AA-14はL3警告・診断・報告契約の整備である。
