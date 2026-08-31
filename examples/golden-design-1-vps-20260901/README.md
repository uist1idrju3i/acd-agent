# 実行例: golden-design-1（2026-08-31／新規VPS・新規workspace）

第6回VibeBB検証（`docs/vibebb-standalone-verification.md` 13節）で実際に生成された成果物と
会話ログ、資源実測、Devinの分析レポートを収録した実行例である。閾値、ゲート挙動、
fail-closed境界は変更していない。

## 条件

| 項目 | 値 |
|---|---|
| 対象graph | `golden-design-1`（`fixtures/golden-design-1`） |
| plugin revision | `5c8c7b245809edb4ce25d35a5f126e13365e2cc7`（当時の`origin/main`） |
| server image | `ghcr.io/uist1idrju3i/acd-server@sha256:20828162dc33b5832c551cfee0a8c634fe17533a3daf78a96b2f7c52ba707104` |
| OpenHands workspace | `/home/openhands/repos/test260901b/acd-ws`（本検証で新規作成） |
| 会話ID | `469844e5-415a-44d2-ae0f-7b4ce47a7594` |
| host | 検証用VPS 8コア／MemTotal 15.1 GiB／Docker 29.1.3／Python 3.14.4 |
| container上限／`--jobs` | 8 GiB／4 |
| 評価時刻 | `--evaluated-at 2025-01-14T00:00:00Z` |
| 実行日 | 2026-08-31（UTC） |

収録した基板・筐体・FW成果物は、上記workspace上でdigest固定container内に実行した
GD1全lane（Run N）の出力である。新規spec側（Run O）はfail-closedしたため、
生成できたfixtureと停止記録だけを収録した。

## 権限

- **authoritative（L1）**: `board/evidence-electrical.json`、`enclosure/evidence-mechanical.json`、
  `firmware/evidence-firmware.json`、および`loop/manufacturing-submission.json`。
  いずれも`execution_context: "container"`で、`container_image_digest`は上記lockと一致し、
  `target_revision: "r1"`、`status: "valid"`である。host側の再検証も通る。

  ```text
  $ uv run python scripts/verify_authoritative_evidence.py \
      --revision-from fixtures/golden-design-1/graph.json \
      examples/golden-design-1-vps-20260901/board/evidence-electrical.json \
      examples/golden-design-1-vps-20260901/enclosure/evidence-mechanical.json
  OK: 2 authoritative Evidence file(s) verified
  ```

- **L3観測（合否権限なし）**: `loop/loop-summary.json`、`loop/timing-record.json`、
  `loop/progress-report.json`、`gui/`配下、`measure/`配下。いずれも`pass_evidence: false`である。
- **L2観測（合否権限なし）**: `conversation/`の会話ログ。GUI会話がどこで何を判断したかの記録であり、
  合格の根拠にはならない。

## ディレクトリ

| path | 内容 |
|---|---|
| `board/` | 基板lane出力。Gerber 8面＋drill＋gbrjob＋Gerber ZIP、BOM/CPL（JLCPCB形式含む）、DFM report、fab package、`hashes.json`、KiCad source・routed、DRC/ERC、netclass positive control、SVG投影と再現投影、authoritative Evidence |
| `enclosure/` | 筐体lane出力。STEP 3点（assembly／shell／lid）、3MF、STL、`envelope-cad.json`、干渉・断面SVG、authoritative Evidence |
| `firmware/` | FW lane出力。`flash.bin`、`qemu-serial.log`、`summary.json`、`firmware-config-report.json`、ESP-IDFプロジェクト入力（`main/`・`sdkconfig`）、authoritative Evidence。ESP-IDFのbuildツリー（`build/`、約200 MiB）は再生成可能なため除外した |
| `silkscreen/` | silkscreen resolverのiteration-1出力とwork-fixture（`graph.json`ほか） |
| `loop/` | GD1全laneのloop summary、timing record、発注集計（`order-total.json`）、製造提出判定（`manufacturing-submission.json`）、progress report |
| `newspec/` | 新規spec（`examples/mini-blink-dongle-20260825/fixture/spec.json`）からの`--design-only`実行結果。生成できたfixtureとfail-closed記録 |
| `gui/` | GUI会話が生成した`bootstrap-record.json`、loop summary、timing record |
| `conversation/` | GUI会話ログのMarkdown化（`render_markdown.py`が生成器） |
| `measure/` | 資源sampler出力（`samples-run{N,O}.jsonl`）、container実行ログ（`runN.log`／`runO.log`）、各runのwall-clock summary、`host-resources-run{N,O}.json` |
| `report/` | Devinの分析レポート、改善提案メモ、収録物manifest |

## 結果

GD1（Run N、wall-clock 259秒）は全26 stageが通過した。

| stage | 結果 |
|---|---|
| requirement-entry-validation | pass |
| silkscreen-resolve | pass |
| board-pipeline | pass |
| enclosure-pipeline | pass |
| firmware-pipeline | pass |
| order-total-aggregation | pass |
| order-readiness | pass |

発注集計はUSD 93.00（components 42.00／board 25.00／assembly 18.00／mechanical 8.00、
`target_revision: "r1"`）で、上限USD 100.00に対しpre-order gateは`ready`である。
製造提出判定は`status: "pass"`、`authoritative: true`で、8項目すべてPASSである。

```text
PASS: required_artifacts / independent_reload / normalized_hashes / dfm
PASS: geometry / fab_profile_consistency / revision_consistency / evidence_validity
```

新規spec（Run O、wall-clock 45秒）はfixture生成とdecoupling配置調整までは通過したが、
次段でfail-closedした。

```text
failed_stage: silkscreen-resolve
failure_reason: GraphExtractionError: silkscreen declarations are missing (fail-closed)
```

## 制約と非対象

- **GUI会話は`acd_*` toolが未登録である。** 会話のToolDefinitionは`terminal`、`file_editor`、
  `task_tracker`、`canvas_ui_control`、`launch_child_conversation`だけで、agentは
  `verify_acd_tool_registration.py`でtool不在を確認したうえで決定論的CLIへ退避している。
  つまり収録物は「GUI会話が起動したCLI経路」の出力であり、`acd_*` tool経路の出力ではない。
- **GUI会話の最終報告はL3記録だけで「発注可」と述べている。** 会話はEvidenceをhostへ
  downloadせず、`verify_manufacturing_submission.py`と`verify_authoritative_evidence.py`を
  実行していない。本ディレクトリのauthoritative Evidenceと製造提出判定は、
  会話とは別に決定論的経路で実行・検証した結果である。
- **新規specは基板laneへ到達しない。** silkscreen宣言不足でfail-closedするため、
  GD1以外の設計の完走例は本ディレクトリにも存在しない。
- **却下からの復帰は未観測である。**
- **実発注、支払い、supplier APIの呼び出し、実機測定は行っていない。** 発注集計と
  pre-order gateはfixtureのquote recordに対する決定論的計算であり、実際の見積・購買ではない。
- 会話ログはOpenHandsのraw export（`base_state.json`にhostとLLM endpointの情報を含む）を
  そのまま収録せず、eventから生成したMarkdownだけを収録した。検証用VPSのアドレスは
  生成器側で除去している。system prompt（47,670文字）はログに含めていない。
  12,000文字を超えるtool出力は末尾を省略している。

## ライセンスと帰属

`newspec/fixture/libraries/`と`newspec/mini-blink-dongle-silkscreen-resolve/work-fixture/libraries/`の
シンボル・footprintは[espressif/kicad-libraries](https://github.com/espressif/kicad-libraries)由来であり、
各ディレクトリの`README.md`に取得元・commit・ライセンス（CC-BY-SA 4.0、KiCadライブラリ例外付き）を記載している。
KiCad公式ライブラリ由来の部品は複製せず、container内の`/usr/share/kicad`をhash付きでpin参照している。
