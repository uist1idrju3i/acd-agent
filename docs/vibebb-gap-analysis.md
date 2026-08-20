# VibeBBをacd-agent単体で実現するための機能ギャップ一覧

本書は、`compact-sensor-node-1`の設計演習から得た改善提案（実装計画）である。
VibeBBの体験ループは[`README.md`](../README.md)の定義に従い、
「語る → AIが設計し決定論的ゲートで検証する → 作って試す → 測定結果を次の設計へ返す」
である。ここで言う「acd-agent単体」は、**設計判断の探索と収束をacd-agent側
(Skill + 決定論的ゲート + pipeline)が担い、人間や汎用コーディングエージェントが座標・
GPIO・寸法を手で決めない状態**を指す。

本一覧は、GD1と要件の異なる小型ボードを実機OpenHands環境で設計した際に実際に
詰まった箇所を根拠とする。「実測根拠」欄が空の項目は文書由来の未実装項目である。
決定論的ゲートの権限とfail-closed境界を変更する提案ではない。

## A. 会話から設計入力を作る経路（最大の欠落）

| # | 不足機能 | 現状 | 実測根拠 |
|---|---|---|---|
| A-1 | 会話→要件レコードの変換 | [`README.md`](../README.md)は「対話を検証可能な要件へ変換する」を掲げるが、実装は`req.*` nodeの手書き。要件文は自由文で、ゲートと機械的に結び付いていない | 変更したREQ-010／REQ-011の文面は手作業更新であり、GPIO変更との整合を機械検査できなかった |
| A-2 | 任意設計向けfixtureビルダー | [`src/acd/pipeline/gd1_fixture/`](../src/acd/pipeline/gd1_fixture/)はGD1専用。新規設計はGD1のgraphを複製して手編集するしかない | 変異fixtureは自作スクリプトでGD1 graphを書き換えて生成した。acd-agent内には該当機能が無い |
| A-3 | 要件差分→graph差分のコンパイラ | 「LEDをIO6へ」という要件変更に対し、`pin.*`接続、`fw.pin.*`、テストポイント名、シルク文字、rationaleを同時に更新する経路が無い | 上記4箇所をすべて手で書き換えた。1箇所落とすとresolverかrationale coverageで落ちる |
| A-4 | 部品選定とlibrary provenanceの自動化 | 部品・footprint・provenanceはGD1 fixtureに固定。カタログ検索や代替品選定の機構が無い | 部品点数を変えない要件に限定したため回避したが、部品を増やす要件は現状扱えない |
| A-5 | 回路トポロジ合成 | net構成はGD1のコピーが前提。機能ブロックからnetlistを合成する層が無い | I2C・LED以外の構成変更は検討不能だった |

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

## C. 筐体・FW lane

| # | 不足機能 | 現状 |
|---|---|---|
| C-1 | 開口・締結の自動生成と干渉解決探索 | 筐体は宣言寸法から生成するのみで、干渉時に寸法を探索して収束させる機構が無い |
| C-2 | FWのgraph駆動化 | timer周期・ログ文字列がGD1ハードコードで、「FW周期・ログ挙動を変える」という要件が成果物へ反映されない |
| C-3 | FW側の整合gate | [`ADR-0008`](adr/ADR-0008-minimal-vibebb-scope.md)／[`ADR-0009`](adr/ADR-0009-openhands-delegation-and-skills.md)によりFW検査はOpenHands側の責務で、ACD本体にFW gateが無い。自律loopではpin割当整合の破れをacd-agent側で止められない |
| C-4 | CPL orientation期待値のfixture非依存化 | 期待値がGD1固定 |

## D. 実機フィードバックと発注（VibeBBの後半loop）

| # | 不足機能 | 現状 |
|---|---|---|
| D-1 | 測定結果の入力反映 | [`propose_input_feedback.py`](../scripts/propose_input_feedback.py)の提案止まりで、適用は人手または別工程。loopが閉じていない（設計判断としては妥当だが、単体自律にはpolicy付き適用経路が必要） |
| D-2 | 見積の自動取得 | 価格・在庫・納期・実装可否は期限付き手入力fixture。供給者からの自動取得は将来範囲 |
| D-3 | 実発注 | 実providerへの送信と発注完了は未実装（dry-runまで）。「語れば試作が届く」の最後の一手が欠けている |

## E. 実行基盤・性能

| # | 不足機能 | 現状 | 実測根拠 |
|---|---|---|---|
| E-1 | pipeline stageの並列化 | Gerber／BOM／CPL／SVG生成、rationale検査、graph正規化は独立なのに逐次。Python側stageは1コアしか使わない | 実行中のプロセス観察でPython stageが単一コア律速 |
| E-2 | lane・runの並列実行 | 4点証拠のためGD1再生成が毎回必要だが、variantとGD1のrunを直列で回している | GD1再生成とvariant生成を順に実行した |
| E-3 | JVM／containerの資源宣言 | FreeRoutingへ`-mp 99999`を渡す一方でJVM thread・heap指定とcontainerの`--cpus`指定が無い | routerが実行時間の支配項 |
| E-4 | 入力hash単位のstage cache | 配置だけ変えた再試行でもDSN exportからやり直す | 候補ごとに全stageを再実行した |
| E-5 | output prefix／`subject_node`のgd1固定 | graph_id由来にすべき。ファイル名で設計同一性を判断できない | variant成果物も`gd1-*`名で出力される |

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

## G. ワークスペース初期化の自動化

OpenHands側のworkspaceは現在ユーザーが手で`mkdir`→`git init`／`clone`して用意しており、
acd-agent側に初期化経路が無い。[`plugins/acd/commands/ask.md`](../plugins/acd/commands/ask.md)、
[`doctor.md`](../plugins/acd/commands/doctor.md)、[`gates.md`](../plugins/acd/commands/gates.md)の
3 commandは存在するが、初期化commandは存在しない。今回の作業でもworkspaceが空で、こちらで
cloneして立ち上げた。現在のDocker workspace経路は
[`docs/operations.md`](operations.md)に記載された
[`scripts/run_in_workspace.py`](../scripts/run_in_workspace.py)への手順依存である。

| # | 改善提案 | 現状と理由 |
|---|---|---|
| G-1 | `/acd:init` command（または[`acd-install-doctor` Skill](../plugins/acd/skills/acd-install-doctor/SKILL.md)の拡張）を追加し、workspace作成→clone／submodule取得→`uv sync`→plugin読み込み確認→`/acd:doctor`までを1経路にまとめる | 各段の失敗はfail-closedにする |
| G-2 | [`/acd:doctor`](../plugins/acd/commands/doctor.md)にworkspace健全性検査を追加する | 現行doctorはplugin資材・runtime・Docker・host EDA能力を見るが、workspaceにrepositoryが存在しない状態を検出しない。submodule初期化、`uv.lock`との同期、lock digestのpull可否も対象にする |
| G-3 | 会話開始時のbootstrap経路（対象repo revisionとlock digestを記録してworkspaceを用意する）を用意する | VibeBBの「語るだけで始まる」入口として必要 |

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

## 優先順位（VibeBB単体成立に効く順）

1. B-3（構造化失敗理由）→ B-4（前倒し評価）→ B-1／B-2（探索loop）。この3点が揃わない限り、候補生成は必ず人間側に残る。今回の作業がまさにその状態だった。
2. A-2／A-3（任意fixtureと要件差分compiler）。無いと新規設計の入口が手編集になる。
3. B-5／B-6／B-7（結合制約・単一datum・島fallback）。探索が空回りする原因を潰す。
4. E-1〜E-4（並列化とcache）。1候補あたりの時間が探索の実現可能性を決める。
5. F-1〜F-4（image publishとdigest lock更新）。運用の再現性を強化するが、VibeBB自律成立のblocking要因ではない。
6. G-1〜G-3（workspace初期化とbootstrap）。体験の入口としてAと同程度に重要だが、設計探索loopより下位に置く。
7. C-2／C-3（FWのgraph駆動と整合gate）、D-1〜D-3（loopの閉じと発注）。
