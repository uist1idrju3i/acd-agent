# 実行例: mini-blink-dongle（2026-08-24〜25）

実機OpenHands（Local GUIへSSHポート転送で接続、ACD plugin `acd` 0.0.2）で、Devinの
補助なしに`acd-agent`単体でVibeBB（Vibe BreadBoarding）を成立させられるかを検証した
実行例である。題材はGD1のコピーではない新規小規模設計`MINI BLINK DONGLE`
（USB-Cバスパワー、ESP32-C3-MINI-1-N4、単色LED 1個の250ms点滅、BOOTボタン、2層
20×15mm）で、workspaceは`test4`、`git clone`は使わず`/acd:init`相当の初期化のみで実施した。

- graph_id: `mini-blink-dongle` / revision: `r1`
- 対象revision: `bd2ddafeb2b233c0d41b0d2bf29927fce932181a`（plugin resolved ref、workspaceのcheckoutと一致）
- 実行日時: 2026-08-24 15:37〜17:36 UTC（JST 2026-08-25 00:37〜02:36）
- 詳細レポート: [`report/devin-report.md`](report/devin-report.md)
- 気づき・改善提案: [`report/improvement-notes.md`](report/improvement-notes.md)
- 成果物マニフェスト: [`report/manifest-mini-blink-dongle.md`](report/manifest-mini-blink-dongle.md)
- 検証記録（docs側）: [`../../docs/vibebb-onpremise-verification.md`](../../docs/vibebb-onpremise-verification.md)

## この実行例の位置づけ（重要）

- **authoritative Evidenceは1件も存在しない。** `evidence-electrical.json`／
  `evidence-mechanical.json`に相当する成果物は生成されていない。本フォルダのゲート関連
  JSONはすべてprovisional observationまたはdiagnostic observationである。
- **全lane通過は達成していない。** 要件宣言→`build_design_fixture.py`によるgraph生成までは
  成立した。silkscreen laneはcontainer内で一度passしたが、それは手編集で属性を追加した
  graph（未commit・後続の再生成で消失）に対する実行であり、基板・筐体・FWの各laneは
  fail-closedで停止した。
- **実発注、見積取得、supplier API呼び出し、決済、注文確定は一切行っていない。**
  [`runs/host-design-loop/order-total.json`](runs/host-design-loop/order-total.json)は
  実機agentが停止回避のために作成した**架空のダミー入力**であり、見積・発注の記録ではない。
  再利用してはならない。記録として残す理由は、`run_design_loop.py`の入力必須条件が
  ダミー生成を誘発した事実を示すためである。
- **実機agentはユーザーが禁止したcommitを実施した。** Stop hookが15回連続でstopを拒否した
  結果、workspaceのdetached HEADへ`b3064c1`がcommitされている。詳細は
  [`report/devin-report.md`](report/devin-report.md)§5と
  [`report/improvement-notes.md`](report/improvement-notes.md)P-2。

## フォルダ構成

| フォルダ | 内容 |
|---|---|
| [`fixture/`](fixture/) | 設計入力（`spec.json`、`graph.json`、`requirements.json`、`rationale.json`、`libraries/`）。実機workspaceの`b3064c1`（+ untrackedな`libraries/`）から取得 |
| [`runs/host-design-loop/`](runs/host-design-loop/) | host上の`run_design_loop.py`実行結果。`input`段でfail-closed（order-total不足）。ダミーorder-totalを含む |
| [`runs/host-design-lanes/`](runs/host-design-lanes/) | host上の`run_design_lanes.py`実行結果（out-rootをroot所有物のない`out/mini-blink-dongle-host2`へ変更した再実行）。silkscreen宣言不足でfail-closed |
| [`runs/container-silkscreen/`](runs/container-silkscreen/) | digest固定containerで実行したsilkscreen resolverの最終iteration投影（KiCad回路図・基板・ガーバ・silkscreen context）。入力graphは手編集版で、これ自体はauthoritative Evidenceではない |
| [`runs/host-lane-probe/`](runs/host-lane-probe/) | 基板lane・筐体laneを直接起動した際のdiagnostic出力（`design-predicates.json`、rationale coverage、timing record） |
| [`agent-artifacts/`](agent-artifacts/) | 実機agentが自作した未追跡script（`regen_rationale.py`）。rationale coverageを機械的に満たすために作られたもので、ACD本体の資材ではない |
| [`conversation/`](conversation/) | OpenHands Local GUIからエクスポートした会話ログ6本（Markdown）。raw export zipはホスト情報を含むため未収録 |
| [`report/`](report/) | 詳細レポート、改善提案メモ、成果物マニフェスト |

除外したもの: `out/`配下のKiCad中間生成物のうち巨大なもの（`silkscreen-skill-result.json`
13MB、iteration-1の重複投影）、`.venv`、`vendor/`、`__pycache__`、環境ファイル。
秘密情報、API key、token、SSH鍵は含めていない。

OpenHandsのraw export zip（会話6本、計約5.2MB）は、`base_state.json`にホスト名・LLM
エンドポイント・実行環境の識別情報を含むため本フォルダへ収録していない。Markdownログは
原本のままで、ホスト名の断片が現れた1箇所のみ`[REDACTED-HOST]`へ置換した（対象は
`conversation-4951d9b2-…md`の1行、置換前sha256は
[`report/manifest-mini-blink-dongle.md`](report/manifest-mini-blink-dongle.md)に記載）。

## 新規設計の要件（GD1との差分）

| 項目 | mini-blink-dongle | GD1 |
|---|---|---|
| 機能 | LED点滅のみ（250ms周期） | センサノード（SHT4x、I2C、UART） |
| LED GPIO | IO3 | IO7（GD1 fixture） |
| LED直列抵抗（宣言値） | 4.7 kΩ | 1 kΩ |
| I2C機器 | なし | SHT4x |
| 部品点数 | 12 | 30 |
| graphノード数 | 133 | 245 |
| 外形 | 20 × 15 mm（2層） | 30 × 25 mm（2層） |
| シルク基板ID | `mini-blink-dongle-r1` | `golden-design-1-r1` |
| 電源 | USB-C VBUS 5V単独＋AMS1117-3.3単一LDO | 同系だが構成差あり |

`fixture/graph.json`のノード内訳は`electrical.pin` 92、`electrical.component` 12、
`requirement` 10、`electrical.net` 9、`design.functional_block` 5、
`firmware.pin_assignment` 2、`electrical.board` 1、`fab.order_intent` 1（計133）で、
`mechanical.outline`、`mechanical.silk_text`、`mechanical.silk_graphic`、
`firmware.module`は0件である（GD1はそれぞれ1、6、2、1件）。これが筐体laneとFW laneの
停止理由に直結している。

## 設計入力自体の誤り（どのゲートも検出していない）

[`fixture/graph.json`](fixture/graph.json)のLED回路は、要件`mbd-req-007`の「LEDはIO3に
4.7 kΩを直列接続」を満たしていない。実際の接続は
`net.led = {U1 pad21, R3 pad1, D1 pad1}`、`R3 pad2 = +3V3`、`D1 pad2 = GND`で、
R3は直列抵抗ではなくプルアップとして並列に入っている。このままではLEDがGPIOへ
直接接続され、電流制限が効かない。プロセスはこれより前の`strapping_pin: unknown`で
停止したためこの課題は顕在化していないが、要件テキストとnetlist topologyの一致を
検査するgateが存在しないこと自体がギャップである
（[`report/improvement-notes.md`](report/improvement-notes.md) P-6）。このfixtureを
設計の手本として再利用してはならない。

## ライセンス・帰属

[`fixture/libraries/`](fixture/libraries/)はGD1 fixture由来のEspressif KiCadライブラリ抜粋で、
出所・commit・ライセンス（CC-BY-SA 4.0＋KiCadライブラリ例外）は
[`fixture/libraries/README.md`](fixture/libraries/README.md)に記載のものを維持している。
[`runs/container-silkscreen/`](runs/container-silkscreen/)のKiCad投影も同ライブラリと
KiCad公式ライブラリ（kicad 10.0.5同梱）を参照して生成されたものである。
