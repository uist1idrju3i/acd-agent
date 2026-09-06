# 実行例: golden-design-1（2026-09-06／12コアVPS・新規workspace・FW Evidence修正前後）

第7回VibeBB検証（`docs/vibebb-standalone-verification.md` 14節）で実際に生成された成果物、
GUI会話ログ、資源実測、FreeRouting多コア再評価、Devinの分析レポートを収録した実行例である。
閾値、ゲート挙動、fail-closed境界は変更していない。本検証で見つけたFW Evidenceの
provenance欠陥（`input_hash: "unknown"`）は修正前後の両方を収録している。

## 条件

| 項目 | 値 |
|---|---|
| 対象graph | `golden-design-1`（`fixtures/golden-design-1`） |
| plugin revision | `f636c73dbff64e40a7d87a0aa38c6bea6c9e0ca5`（当時の`origin/main`、`5e85256…`から更新） |
| 修正branch | `devin/1788701814-firmware-evidence-input-hash`（Run Pで使用） |
| server image | `ghcr.io/uist1idrju3i/acd-server@sha256:26ac3a2ee8c7fa3fd8f7e43cba61baefdff72540775d06cc739f1042115251ae` |
| OpenHands workspace | `/home/openhands/acd-workspace-verify-20260906`（本検証で新規作成） |
| 会話ID | init `9b62e53b-66ab-47cd-b00d-01ad973a2577`、loop `af617b5d-377c-4cf1-84ef-9068aa453455` |
| host | 実機OpenHands VPS 12コア／MemTotal 30.2 GiB／Docker 29.1.3／Python 3.14.4 |
| container上限／`--jobs` | 8 GiB／4 |
| 評価時刻 | `--evaluated-at 2025-01-14T00:00:00Z` |
| 実行日 | 2026-09-06（UTC） |

## 権限

- **authoritative（L1）**: `board/evidence-electrical.json`、`enclosure/evidence-mechanical.json`、
  `firmware/evidence-firmware.json`。いずれも`execution_context: "container"`、
  `container_image_digest`が上記lockと一致、`target_revision: "r1"`、`status: "valid"`であり、
  3件を1回の検証にかけて通る。

  ```text
  $ uv run python scripts/verify_authoritative_evidence.py \
      --revision-from fixtures/golden-design-1/graph.json \
      examples/golden-design-1-vps-20260906/board/evidence-electrical.json \
      examples/golden-design-1-vps-20260906/enclosure/evidence-mechanical.json \
      examples/golden-design-1-vps-20260906/firmware/evidence-firmware.json
  OK: 3 authoritative Evidence file(s) verified
  ```

- **拒否されるEvidence（negative control）**: `prefix-run/evidence-firmware.json`は修正前の
  同一container・同一入力の出力で、`input_hash: "unknown"`を含む。

  ```text
  $ uv run python scripts/verify_authoritative_evidence.py \
      --revision-from fixtures/golden-design-1/graph.json \
      examples/golden-design-1-vps-20260906/prefix-run/evidence-firmware.json
  FAIL: examples/golden-design-1-vps-20260906/prefix-run/evidence-firmware.json: envelope contains unknown values
  ```

- **L3観測（合否権限なし）**: `loop/`、`gui/`、`measure/`、`prefix-run/`の
  summary・timing。いずれも`pass_evidence: false`である。
- **L2観測（合否権限なし）**: `conversation/`の会話ログ。

## ディレクトリ

| path | 内容 |
|---|---|
| `board/` | 基板lane出力（Run P）。Gerber、drill、BOM/CPL、DFM report、fab package、`hashes.json`、KiCad source・routed、DRC/ERC、netclass positive control、SVG投影と再現投影、authoritative Evidence |
| `enclosure/` | 筐体lane出力（Run P）。STEP／3MF／STL、`envelope-cad.json`、干渉・断面SVG、authoritative Evidence |
| `firmware/` | FW lane出力（Run P）。`flash.bin`、`qemu-serial.log`、`summary.json`、ESP-IDFプロジェクト入力、authoritative Evidence。buildツリーは再生成可能なため除外 |
| `silkscreen/` | silkscreen resolverのiteration-1出力とwork-fixture |
| `loop/` | Run Pのloop summary、timing record、発注集計（`order-total.json`）、lane preflight |
| `prefix-run/` | 修正前（plugin revision `f636c73`そのまま）のcontainer実行。拒否されるFW Evidenceとsummary・timing |
| `gui/` | GUI会話が生成した`bootstrap-record.json`、tool登録検査結果（`tool-availability-vibebb-loop.json`）、host経路のfail-closed記録（`loop-summary.json`：`failed_stage: silkscreen-resolve`） |
| `conversation/` | 2会話のMarkdown化（`render_markdown.py`が生成器） |
| `measure/` | 1秒sampler出力（init、GUI起動container run、Run P）、Run Pのcontainer実行ログ、FreeRouting多コア再評価のscriptとログ、host諸元 |
| `report/` | Devinの分析レポート、改善提案メモ、収録物manifest |

## 結果

Run P（wall-clock 230.6秒）は全stageが通過し、発注集計はUSD 93.00で
pre-order gateは`ready`である。stage別の所要時間はsilkscreen-resolve 14.9秒、
board-pipeline 215.5秒（うちFreeRouting `board[3/12]` 180.2秒）、enclosure-pipeline 24.2秒、
firmware-pipeline 116.0秒で、critical pathはsilkscreen→基板laneである。

基板出力はGD1として決定論的であり、`board/golden-design-1.dsn`（SHA-256 `94b8677d…d181`）と
`board/golden-design-1.ses`（`808ee965…897d9`）は`examples/golden-design-1-vps-20260901/`の
同名ファイルと一致する。異なるVPS、異なるplugin revision、異なるworkspaceでも
routing結果が変わらないことの実例である。

資源実測（Run P）はhost CPU peak 11.99／mean 2.73 cores、host memory peak 4.96 GiB、
Docker memory peak 2.86 GiB、swap 36 KiBである。FreeRouting単独実行（`measure/freerouting-bench.log`）
は`-mt`暗黙／`-mt 1`、`-Xtune:footprint`／`-Xtune:virtualized`の4構成で156〜163秒、
SES SHA-256は全構成で一致した。速度に関する既定値は変更していない。

## 制約と非対象

- **GUI会話は`acd_*` toolが未登録である。** `gui/tool-availability-vibebb-loop.json`のとおり、
  登録toolは`terminal`、`file_editor`、`invoke_skill`、`finish`だけで、宣言9 toolは不在である。
  収録物は会話が退避した決定論的CLI経路（およびそれをcontainerで再実行した経路）の出力である。
- **host経路はfail-closedした。** `gui/loop-summary.json`は`/usr/share/kicad/symbols/power.kicad_sym`
  不在で`silkscreen-resolve`に停止しており、合格側Evidenceを生成していない。
- **会話から`run_in_workspace.py`を正しく起動するまでに2回の指定ミスがある**
  （`--repo /workspace`、`--download`未宣言）。詳細は`report/devin-report.md`。
- **修正前のFW laneはauthoritative検証を通過しない。** `prefix-run/`はその実例であり、
  `examples/golden-design-1-vps-20260901/firmware/evidence-firmware.json`も同じ欠陥を持つ。
- **新規specの実行、却下からの復帰、実発注、supplier API、実機測定は行っていない。**
- 会話ログはraw exportをそのまま収録せず、eventから生成したMarkdownだけを収録した。
  VPSのアドレスとtunnel hostは生成器側で除去し、system promptは含めていない。
  12,000文字を超えるtool出力は末尾を省略している。

## ライセンスと帰属

収録した基板・筐体・FW成果物は`fixtures/golden-design-1`から本リポジトリのpipelineが
生成したものである。KiCad公式ライブラリ由来の部品は複製せず、container内の
`/usr/share/kicad`をhash付きでpin参照している。
