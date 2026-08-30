# 実行例: sensor-node（2026-08-20）

Golden Design #1（GD1）の要件・設計入力を用いた、小規模製品「ESP32-C3ベースの環境
センサノード」（単一2層基板＋簡易筐体＋最小ファームウェア）相当の実行例である。
実機環境のOpenHands（ACD plugin導入済み）でpipelineとauthoritative Evidence生成を
実行したが、生成された設計実体はGD1と同一であり、agentが新規設計を行った実行例ではない。

- graph_id: `sensor-node` / revision: `r1`
- 実行日: 2026-08-20（JST）
- 実行環境: 実機OpenHands（Local GUI）+ lock済みdigest固定server image
  `ghcr.io/uist1idrju3i/acd-server@sha256:cc605baff68b8d2648d208fe6c29dee57bd418b3e3da7c5f3837708a14792f3b`
  をDockerWorkspaceで実行（authoritative経路）
- 詳細レポート: [`report/devin-report.md`](report/devin-report.md)
- 気づき・改善提案: [`report/improvement-notes.md`](report/improvement-notes.md)
- セッション分析: [`report/session-analysis.md`](report/session-analysis.md)
- レビュー所見: [`report/review-notes.md`](report/review-notes.md)

注記: この実行例は設計実体としてGD1と同一である。`fixture/graph.json`との差分は
`graph_id`とノードIDのリネーム18箇所のみで、`board/gd1.kicad_pcb`のsha256は
`1c8a5f306157d2afabaa5129e14f170080f82ddff6c5ff1323b644a93e634e89`でGD1再生成物と
一致する。ガーバ9ファイルはrawバイト列では不一致だが、差分は`TF.CreationDate`等の
生成日時だけで、日時を正規化すると9/9一致する。シルクの基板IDは
`golden-design-1-r1`のままである。したがってpipelineとauthoritative Evidenceの実機動作の
証拠ではあるが、新規設計の証拠ではない。設計動作を確認するには要件を変える必要があり、
判定基準は[`../../docs/design-requirement-variation.md`](../../docs/design-requirement-variation.md)
を参照する。なお、出力ファイル名のprefixとevidenceの`subject_node`は`gd1`固定である。

## フォルダ構成

| フォルダ | 内容 |
|---|---|
| [`fixture/`](fixture/) | 設計入力（`graph.json`、`rationale.json`、`libraries/`、`overlays/`）。GD1 fixtureから派生 |
| [`board/`](board/) | 基板pipeline出力一式（回路図・配線済み基板・ガーバ・fabパッケージ・ERC/DRC/DFM・Evidence・視覚射影） |
| [`enclosure/`](enclosure/) | 筐体pipeline出力一式（STEP×3・3MF・Evidence・視覚射影） |
| [`firmware/`](firmware/) | FW pipeline出力（生成FWプロジェクトのソース、`flash.bin`、QEMUシリアルログ、summary）。ESP-IDFの`build/`ツリーはサイズとライセンスの観点から除外 |
| [`conversation/`](conversation/) | OpenHands Local GUIからエクスポートした会話ログ（Markdown）。raw export zipは環境識別情報を含むため削除済み |
| [`report/`](report/) | 詳細レポート・成果物マニフェスト・改善メモ・セッション分析・レビュー所見 |

## JLCPCB発注時にアップロードするファイル（この3点のみ）

| ファイル | sha256 |
|---|---|
| [`board/fab/gd1-gerbers.zip`](board/fab/gd1-gerbers.zip) | `396c2455dcd164b28f9d81972037ed8e342d03b23f3a24a23cb529542aa90bdb` |
| [`board/fab/gd1-bom-jlcpcb.csv`](board/fab/gd1-bom-jlcpcb.csv) | `9394fc0a25ba87d44af57ecd68da3ceda76af9213ca11a7c82b751734fce89fb` |
| [`board/fab/gd1-cpl-jlcpcb.csv`](board/fab/gd1-cpl-jlcpcb.csv) | `e7cbec56954fa2e4820cd750f9a07258826120adf81a68aba9b24d3685aed66a` |

`gd1.pos.csv`、`fab-package.json`、DFMレポート、Evidence等は内部用であり、
発注フォームへアップロードしない。詳細は
[`report/manifest-sensor-node.md`](report/manifest-sensor-node.md)を参照。

## ゲート結果（全pass）

- 基板: ERC 0 errors / DRC 0 errors・0 unconnected / routing converged /
  silkscreen measured_pass / DFM pass / order-readiness ready /
  USB CC・I2Cプルアップ・strappingピン・pin-firmware整合・デカップリング・電源境界 各pass
- 筐体: CADカーネルvalid / 干渉0.0mm³ / 内部クリアランス1.0mm / 最小肉厚2.0mm /
  normalized hashes 4/4 verified
- FW: ピン整合 全pass（LED=IO7、SDA=IO4、SCL=IO5、BOOT=IO9、UART TX=IO21/RX=IO20、
  USB D-=IO18/D+=IO19）/ ESP-IDF v5.3.1 ビルド成功 / QEMU（Espressif fork 9.2.2）実行で
  IO7 LED heartbeat（1Hz・1秒周期）を確認

authoritative Evidence: `board/evidence-electrical.json`・`enclosure/evidence-mechanical.json`
（`scripts/verify_authoritative_evidence.py`でrevision一致・valid・container provenanceを検証済み）。
QEMU実行は仮想検証であり、実測Evidenceの代替ではない。

## 成果物の射影（視覚射影）

### 回路図

![schematic](board/visual/gd1-schematic.svg)

### 基板レイアウト（部品配置）

![placement](board/visual/gd1-placement.svg)

### 銅箔（表面 / 裏面）

| F.Cu | B.Cu |
|---|---|
| ![f-cu](board/visual/gd1-f-cu.svg) | ![b-cu](board/visual/gd1-b-cu.svg) |

### 電源ツリー / システムブロック

| Power tree | System block |
|---|---|
| ![power-tree](board/visual/gd1-power-tree.svg) | ![system-block](board/visual/gd1-system-block.svg) |

### 筐体（干渉検査 / 断面）

| Interference | Section |
|---|---|
| ![interference](enclosure/visual/gd1-mechanical-interference.svg) | ![section](enclosure/visual/gd1-mechanical-section.svg) |

### ファームウェア（状態遷移 / シーケンス）

| State | Sequence |
|---|---|
| ![fw-state](board/visual/gd1-firmware-state.svg) | ![fw-sequence](board/visual/gd1-firmware-sequence.svg) |

## ライセンスと帰属

- 本実行例の成果物（ガーバ・STEP・3MF・生成FWソース・レポート等）はリポジトリの
  ライセンス（BSD 3-Clause）に従う。
- `fixture/libraries/` のシンボル・footprintは
  [espressif/kicad-libraries](https://github.com/espressif/kicad-libraries) からの抜粋であり、
  Creative Commons CC-BY-SA 4.0（KiCadライブラリ例外付き）。詳細は
  [`fixture/libraries/README.md`](fixture/libraries/README.md)を参照。
- `firmware/flash.bin` はESP-IDF（Apache License 2.0）由来のbootloader・ライブラリコードを
  含むバイナリである。ESP-IDF本体のライセンスは
  [espressif/esp-idf](https://github.com/espressif/esp-idf) を参照。
  同様の理由（およびサイズ151MB）から、ESP-IDFのコード複製を含む`build/`ツリーは
  本フォルダへ含めていない。
- `conversation/` のログは本リポジトリ利用者の作業記録である。APIキー等はマスクされている
  ことを確認済みだが、raw export zip（`base_state.json`）は実行ホスト名やLLMエンドポイントを
  含んでいたため削除した。以降、raw export zipは収録しない。

## 実機動作確認（2026-08-30）

QEMU仮想検証に加え、実機ESP32-C3へ`flash.bin`を書き込んで動作確認した。

| 項目 | 値 |
|---|---|
| 書き込み対象 | ESP32-C3 (QFN32, rev v0.4, Embedded Flash 4MB XMC, MAC `e8:3d:c1:21:39:34`) |
| 接続 | USB JTAG/serial debug unit @ `/dev/cu.usbmodem124101` |
| ツール | esptool v5.3.1（Homebrew）、GPL-2.0-or-later（ホストツールとして使用、ACDへはimportしない） |
| 書き込み | `esptool --chip esp32c3 -b 460800 write-flash 0x0 flash.bin`（4MB、5.3秒、`Hash of data verified`） |
| 読み戻し照合 | `verify-flash` で `Verification successful (digest matched)` |
| LED | IO7 で 1Hz（1秒周期）のheartbeat点滅を確認。FW定義 `ACD_LED_BLINK_PERIOD_MS 1000` と一致 |
| SHT40 | 実センサ読み取り ~31.9°C / ~47.2% RH を2秒周期で取得（QEMUログの「no SHT40 attached」とは異なり実機にはSHT40が実装） |

実機シリアルログの抜粋:

```
I (29504) acd_gd1: LED gpio=7 state=1
I (30004) acd_gd1: LED gpio=7 state=0        ← 1Hz（1秒周期）のheartbeat
I (30514) acd_gd1: SHT40 temp_c=31.89 rh=47.40
I (32524) acd_gd1: SHT40 temp_c=31.91 rh=47.18   ← 2秒周期のセンサ読み取り
```

注記: 実機観測（LED・SHT40実測値）は参考観測であり、authoritative Evidence経路
（digest固定container）で生成されたものではない。QEMU仮想検証Evidenceを実機Evidenceへ
昇格させるものではない。esptoolはGPL-2.0-or-laterのホストツールであり、ACDコードへは
import結合しない（AGENTS.mdのGPL/AGPL import不変条件に抵触しない）。

## 筐体設計上の既知の問題

実機への組み付けを試みた結果、筐体（`enclosure/`）に2つの設計不具合があることを確認した。
いずれもenclosure pipelineコードの不具合に起因する。生成物（STEP/3MF）は変更せず、
問題の記録と推奨修正方針を本節に残す。コード修正は別タスクで扱う。

### アンテナ干渉

ESP32-C3-MINI-1のアンテナは基板端から5.4mm突出する（`mechanical.board_edge_overhang.u1`、
GD1-REQ-015）。しかし生成された筐体シェルは単純箱型で、アンテナ突出部を考慮した切欠きがなく、
シェル壁がアンテナ領域と物理干渉するため組み付けられない。

根因: `fixture/graph.json`に`mechanical.board_edge_overhang`ノードが定義されているが、
`extract_mechanical_lane()`（`src/acd/core/mechanical.py`）がこのノードを抽出せず、
`_build_shapes()`（`src/acd/adapters/cad/project.py`）が単純箱型シェルを生成する。
また`run_mechanical_gates()`の干渉検査がoverhangを3D固体としてモデル化しないため、
干渉ゲートが0.0mm³でpassしてしまう。`enclosure/rationale.md`にはoverhang設計判断が
記録されているのに、コードがそれを実装していない。

推奨修正方針: アンテナ突出領域に対応するシェル切欠きを`_build_shapes()`へ追加し、
`extract_mechanical_lane()`で`board_edge_overhang`ノードを消費する。干渉ゲートへ
overhang由来の3D固体を含める。

### ネジ穴欠落

基板にはM2取付穴×4（graph.json: `mounting_hole_m2_count: 4`）があるが、生成された
スタンドオフは貫通穴のない固体円柱で、リッドも平板であり、リッドをシェルへ固定する
手段がない。

根因: `_build_shapes()`がスタンドオフを固体円柱（`Cylinder`）として生成し、貫通穴を
開けない。リッドも平板（`Box`）でネジ穴がない。

推奨ネジ穴方式: **熱圧入インサート（M2）**。PETGは比較的柔らかくタップ穴ではネジ山が
ストリップしやすいため、熱圧入インサートが最も強固。スタンドオフにインサート用穴
（φ3.5mm程度）、リッドにM2通し穴（φ2.2mm）、ネジはリッド側から締める構造を推奨する。

## 注意事項

- JLCPCBへの発注送信は行っていない（価格・在庫・総発注額はunknown）。
- 実機への書き込み・LED/センサの実測は2026-08-30に実施した（上記「実機動作確認」節）。
- 本フォルダは生成物の凍結スナップショットであり、設計入力へ逆流させない
  （投影を入力へ逆流させないというリポジトリ不変条件に従う）。
