# Devin分析レポート: 第7回VibeBB検証（2026-09-06、12コアVPS・新規workspace）

本レポートは`docs/vibebb-standalone-verification.md` 14節の実測を、本ディレクトリに収録した
成果物・会話ログ・資源sampleに紐づけて分析したものである。判定の根拠はauthoritative Evidenceと
決定論的ゲート出力に限り、GUI会話の記述とL3記録は観測として扱う。

## 1. 実行環境

| 項目 | 値 |
|---|---|
| host | 実機OpenHands VPS、12コア、MemTotal 30.2 GiB、Docker 29.1.3、Python 3.14.4 |
| plugin revision | `f636c73dbff64e40a7d87a0aa38c6bea6c9e0ca5`（`5e85256…`から`force=true`で再install） |
| server image | `ghcr.io/uist1idrju3i/acd-server@sha256:26ac3a2ee8c7fa3fd8f7e43cba61baefdff72540775d06cc739f1042115251ae` |
| OpenHands workspace | `/home/openhands/acd-workspace-verify-20260906`（新規作成） |
| 会話ID | init `9b62e53b-…`、loop `af617b5d-…`（model `openai/preview/Kimi-K2.6`） |
| container上限／`--jobs` | 8 GiB／4 |

`gui/bootstrap-record.json`のとおり、`resolved_revision`と`server_image_digest`は
指定値およびlockと一致した（`source: "mounted"`、`record_class: "L3"`、`pass_evidence: false`）。
installed pluginの`version`は`0.0.2`で変わらず、`acd-package-ref.txt`のpackage pinは
本体revisionより古い（X-1）。

## 2. GUI会話の経路

`conversation/conversation-af617b5d-vibebb-loop.md`から、会話は次の順で進んだ。

1. `verify_acd_tool_registration.py`で`acd_*` 9 toolの不在を確認し
   （`gui/tool-availability-vibebb-loop.json`）、宣言済みCLIへ退避した。
2. host経路の`run_design_loop.py`は`silkscreen-resolve`でKiCad symbol不在によりfail-closedした
   （`gui/loop-summary.json`）。第6回で観測したcontainer資材のhost持ち出し（V-1）は試行されなかった。
3. `run_in_workspace.py`でdigest固定containerへ切り替えた。1回目は`--repo /workspace`で
   graph読み込み失敗、2回目は`--download`未宣言でrunner既定の`out/gd1/evidence-electrical.json`
   を取りに行き`404`（transport失敗）。loop本体は完走していた（`prefix-run/loop-summary.json`）。
4. 生成物はworkspaceからtarで回収した。

会話は`acd_*` tool経路を実現していない（T-3残）。収録物は「会話が退避したCLI経路」の出力である。

## 3. FW Evidenceのprovenance欠陥

回収した3 laneのEvidenceを検証すると、基板・筐体は通り、FWは
`envelope contains unknown values`で拒否された（`prefix-run/evidence-firmware.json`、
`input_hash: "unknown"`）。原因は生成側が入力graphを出力側`out_dir.parent / "graph.json"`から
推定していたことで、loopとOpenHands tool双方の呼び出しで常にunknownへ倒れていた。
検証側は正しく拒否していたが、文書例示とCIの`container-gates`は基板・筐体の2件しか
検証対象にしておらず、露出しなかった（X-2）。`examples/golden-design-1-vps-20260901/firmware/evidence-firmware.json`
にも同じ`"unknown"`が残っている。

修正（`graph_path`必須、不在は`FirmwareEvidenceError`）をworkspaceへcheckoutし、同じcontainerで
再実行したRun Pでは、3件を1回の`verify_authoritative_evidence.py`にかけて通過した
（`firmware/evidence-firmware.json`、`input_hash` = `sha256_paths([fixtures/golden-design-1/graph.json])`）。

## 4. 所要時間と資源

| 区間 | wall | host CPU peak/mean | host mem peak | Docker mem peak | swap |
|---|---:|---:|---:|---:|---:|
| GUI起動のcontainer run（修正前） | 233.6秒 | 11.97 / 3.35 cores | 4.74 GiB | 2.48 GiB | 32 KiB |
| Run P（修正後） | 230.6秒 | 11.99 / 2.73 cores | 4.96 GiB | 2.86 GiB | 36 KiB |

Run Pのstage内訳はsilkscreen-resolve 14.9秒、board-pipeline 215.5秒（FreeRouting `board[3/12]`
180.2秒、`board[8/12]` 14.6秒）、enclosure-pipeline 24.2秒、firmware-pipeline 116.0秒。
critical pathはsilkscreen→基板laneで、FW・筐体laneは完全に基板laneの影に隠れる。
FreeRoutingがwall-clockの78%を占める。sampleは`measure/samples-*.tsv`。

## 5. FreeRoutingの多コア再評価

loopが生成したDSN（`board/golden-design-1.dsn`、SHA-256 `94b8677d…d181`）を同じcontainerで
単独実行し（`measure/freerouting-bench.sh`、`measure/freerouting-bench.log`）、4構成を比較した。

| 構成 | wall |
|---|---:|
| `-mt`暗黙（11 threads）＋`-Xtune:footprint` | 157.8秒 |
| `-mt 1`＋`-Xtune:footprint` | 156.3秒 |
| `-mt`暗黙＋`-Xtune:virtualized` | 162.8秒 |
| `-mt 1`＋`-Xtune:virtualized` | 160.2秒 |

SES SHA-256は全構成で`808ee965…897d9`に一致し、unrouted 0である。router threadsとJVM tuningでは
短縮しない。loop内の180秒との差は他laneとのCPU競合分である（X-5）。

## 6. 最適化の判断

速度に関する既定値は変更しない。支配項のFreeRoutingは`-mp`やoptimizer閾値を変えなければ
短縮できず、それらはSES出力＝正規化hashを変える。FW・筐体laneはcritical path上に無い。
反復実行（loop 2周目以降）には既存の`--cache-dir`／`--resume`（入力hash単位のDSN／SES cache）が
有効で、会話のfallback commandはこれを指定していなかった。

## 7. 結論

GD1に限れば、修正後のacd-agentはdigest固定containerで全laneを通過し、3 laneすべての
authoritative Evidenceが検証できる。修正前はFW laneが必ずunknownを含むため、acd-agent単体で
VibeBBの権威検証を完結できていなかった。GUI会話経路は`acd_*` tool未登録のCLI退避のままであり、
containerの起動引数の誤りとEvidenceの手回収が残る。
