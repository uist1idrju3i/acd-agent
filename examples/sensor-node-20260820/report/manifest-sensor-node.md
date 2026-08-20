# sensor-node 成果物マニフェスト

graph_id: sensor-node
revision: r1   
注記: ファイル名プレフィクスは gd1 だが、中身は sensor-node 設計（graph_id=sensor-node, revision=r1）。

---

## JLCPCB 発注時にアップロードするファイル

以下 3 点のみを JLCPCB 発注フォームへアップロードしてください。

| ファイル | パス | サイズ | sha256 |
|---|---|---|---|
| Gerber | `out/sensor-node/fab/gd1-gerbers.zip` | 70,596 bytes | `396c2455dcd164b28f9d81972037ed8e342d03b23f3a24a23cb529542aa90bdb` |
| BOM | `out/sensor-node/fab/gd1-bom-jlcpcb.csv` | 789 bytes | `9394fc0a25ba87d44af57ecd68da3ceda76af9213ca11a7c82b751734fce89fb` |
| CPL（部品実装位置） | `out/sensor-node/fab/gd1-cpl-jlcpcb.csv` | 741 bytes | `e7cbec56954fa2e4820cd750f9a07258826120adf81a68aba9b24d3685aed66a` |

---

## 発注に使ってはいけない内部ファイル

以下のファイルは製造・検証の内部用作成物です。JLCPCB 発注フォームへアップロードしないでください。

| ファイル | パス | 用途 |
|---|---|---|
| ピックアンドプレース完全版 | `out/sensor-node/fab/gd1.pos.csv` | 全座標（エンジニア用） |
| ピックアンドプレース完全版証拠 | `out/sensor-node/fab/gd1.pos.csv.envelope.json` | 座標生成の証跡 |
| 内部パッケージ | `out/sensor-node/fab/fab-package.json` | 製造パイプライン内部データ |
| DFM レポート | `out/sensor-node/fab/dfm-report.json` | 設計フォルタビリティ検査結果 |
| CPL ベースレポート | `out/sensor-node/fab/cpl-basis-report.json` | CPL 根拠レポート |
| 発注準備状況 | `out/sensor-node/fab/order-readiness.json` | 発注前チェック結果 |
| 機械証拠 | `out/sensor-node-enclosure/evidence-mechanical.json` | ACD 機械ゲート証拠 |
| 機械レショナーレ | `out/sensor-node-enclosure/rationale.md` | 設計根拠文書 |

---

## 筐体成果物

| ファイル | パス |
|---|---|
| 筐体アセンブリ STEP | `out/sensor-node-enclosure/enclosure-assembly.step` |
| 筐体シェル STEP | `out/sensor-node-enclosure/enclosure-shell.step` |
| 筐体リッド STEP | `out/sensor-node-enclosure/enclosure-lid.step` |
| 筐体 3MF | `out/sensor-node-enclosure/enclosure.3mf` |

---

## ファームウェア成果物

| ファイル | パス |
|---|---|
| マージ済み Flash バイナリ | `out/sensor-node-fw/flash.bin` |
| ESP-IDF アプリバイナリ | `out/sensor-node-fw/acd_gd1_fw/build/acd_gd1_fw.bin` |
| QEMU シリアルログ | `out/sensor-node-fw/qemu-serial.log` |
| サマリ JSON | `out/sensor-node-fw/summary.json` |

---

## out/sensor-node/fab/ 全ファイル一覧

```
-rwxrwxr-x       4,520  cpl-basis-report.json
-rwxrwxr-x   1,031,720  dfm-report.json
-rwxrwxr-x   1,026,504  fab-package.json
-rwxrwxr-x         789  gd1-bom-jlcpcb.csv
-rwxrwxr-x         741  gd1-cpl-jlcpcb.csv
-rwxrwxr-x      70,596  gd1-gerbers.zip
-rwxrwxr-x       1,655  gd1.pos.csv
-rwxrwxr-x         976  gd1.pos.csv.envelope.json
-rwxrwxr-x         184  order-readiness.json
```
