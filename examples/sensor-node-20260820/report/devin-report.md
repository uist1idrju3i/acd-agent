# 詳細レポート: sensor-node 設計・製造データ生成（2026-08-20）

GD1（Golden Design #1）を参考モデルとして、ESP32-C3ベースの環境センサノード
（単一2層基板＋簡易筐体＋最小FW）を設計し、JLCPCB発注用の製造データを生成した
セッションの詳細記録である。

## 1. 実行環境

### 実機OpenHands環境

- 接続: SSHトンネル経由でOpenHands Local GUI（`127.0.0.1:8000`）をブラウザ操作
  （トンネルアカウントはポート転送専用、リモートシェル実行不可）
- OpenHands: Software Agent SDK v1.42.1（Local GUI）
- LLM: さくらのAI Engine `Kimi-K2.6`（preview）
- ワークスペース: `test`（リポジトリ`acd-agent` main `692932d` のcheckout）
- ACD plugin: `acd` v0.0.1（`github:uist1idrju3i/acd-agent`、
  install先 `/home/openhands/.openhands/plugins/installed/acd`）

### `/acd:doctor` 結果（必須8・任意4 全pass）

| チェック | 結果 |
|---|---|
| plugin manifest / install location / assets（9 Skills, 6 agents, 2 commands, 7 hooks） | pass |
| agent prompt manifest / skill declarations / Skill package reference | pass |
| runtime prerequisites（Python 3.14.4, uv 0.12.5） | pass |
| hook plugin root resolution / hook invocability / installed plugin store | pass |
| docker capability（Docker 29.1.3） | pass |
| host EDA（kicad-cli・freerouting 不在。observational only） | pass |

doctorはL3観測でありEvidenceではない。host EDAが不在のため、EDA実行はすべて
container経路（下記）で行った。

### authoritative実行経路

基板・筐体pipelineはlock済みdigest固定server image

```text
ghcr.io/uist1idrju3i/acd-server@sha256:cc605baff68b8d2648d208fe6c29dee57bd418b3e3da7c5f3837708a14792f3b
```

を`scripts/run_in_workspace.py`（SDKの`DockerWorkspace`）で実行した。
host実行によるprovisional Evidenceは生成していない。

## 2. タイムライン・実行時間（JST 2026-08-20）

OpenHands会話（id `345d29da-593d-4451-8d28-38e64c4b43db`）のイベントログに基づく。

| 時刻 | フェーズ | 所要 |
|---|---|---|
| 08:49 | `/acd:doctor` 実行 | 約3分 |
| 08:52 | 設計グラフ・rationale作成（GD1 fixtureから派生、Pydantic検証、coverage確認） | 約21分 |
| 09:13 | 基板pipeline＋筐体pipeline（authoritative container経路、Evidence検証含む） | 約38分 |
| 09:51 | FW pipeline（ESP-IDFビルド、ピン整合、QEMUセットアップ試行錯誤＋実行） | 約3時間1分 |
| 12:52 | 最終確認（summary/ログ/ピン整合の出力確認） | 約6分 |
| 12:58 | 成果物整理（manifest作成、sha256算出） | 約3分 |
| 13:00 | 完了 | — |

合計: 約4時間11分（イベント数1,288）。FWフェーズの大半はQEMU（Espressif fork）の
実行環境整備（PATH設定、`libslirp0`・SDL2系共有ライブラリの解消）に費やされた。
詳細は`improvement-notes.md`を参照。

## 3. トークン使用量

OpenHands Local GUIの使用量表示:

| 項目 | 値 |
|---|---|
| コンテキストウィンドウ | 163,140 |
| 入力トークン | 32,717,982 |
| 出力トークン | 104,427 |
| 合計 | 32,822,409 |

さくらのAI Engine（Kimi-K2.6 preview）側の使用量:

| 項目 | 値 |
|---|---|
| 入力トークン数 | 32,763,992 |
| 出力トークン数 | 109,896 |
| チャット生成リクエスト | 252 |

## 4. 設計内容

- ESP32-C3-MINI-1-N4、USB-C（電源sinkのみ、CC1/CC2に5.1kΩ Rd）、AMS1117-3.3
- レギュレータ入出力に10µF＋100nF、ESP32-C3ローカル100nF
- SHT40（I2Cアドレス0x44）、SDA=IO4/SCL=IO5、プルアップ4.7kΩ
- LED=IO7（1kΩ）、BOOT=IO9、RESET=EN、UART TP（TX=IO21/RX=IO20）、
  USB D-=IO18/D+=IO19、TP: 3V3/GND/SDA/SCL/IO7
- 2層FR-4 1.6mm、HASL、片面実装、約30×25mm、M2×4穴、アンテナは基板端から突出し
  keepout（銅箔・GND・部品・シルク排除）を設定
- 設計グラフ: 239ノード、`DesignGraph.model_validate` pass
- rationale coverage: 必須属性669/669（100%）、missing/stale/orphan/unclassifiedなし

## 5. ゲート結果

### 基板（electrical）— 全pass

| ゲート | 結果 |
|---|---|
| ERC | 0 errors / 0 unconnected |
| DRC | 0 errors / 0 unconnected |
| routing converged | True |
| silkscreen | measured_pass |
| DFM | pass |
| order readiness | ready |
| USB CC / I2Cプルアップ / strappingピン / pin-firmware整合 / デカップリング / 電源境界 | すべてpass |

### 筐体（mechanical）— 全pass

| ゲート | 結果 |
|---|---|
| CADカーネル | valid |
| 干渉 | 0.0 mm³ |
| 内部クリアランス | 1.0 mm |
| 最小肉厚 | 2.0 mm |
| normalized hashes | 4/4 verified |

### FW — 全pass

- ピン整合: LED=IO7(pad21)、SDA=IO4(pad18)、SCL=IO5(pad19)、BOOT=IO9(pad23)、
  UART TX=IO21(pad31)/RX=IO20(pad30)、USB D-=IO18(pad26)/D+=IO19(pad27)
- ESP-IDF v5.3.1 ビルド成功: `acd_gd1_fw.bin`（0x30600 bytes、パーティション81% free）
- QEMU 9.2.2（esp_develop_9.2.2_20260417）で15秒実行: IO7 LED heartbeat 1Hz（1秒周期）を確認。
  SHT40のI2CエラーはQEMUにセンサモデルが無いための期待動作
- 実機動作確認（2026-08-30）: esptool v5.3.1で実機ESP32-C3 (rev v0.4) へ`flash.bin`を書き込み、
  `verify-flash`でdigest一致を確認。IO7 LED 1Hz heartbeatとSHT40実測（~31.9°C / ~47.2% RH、
  2秒周期）をシリアルログで確認。実機観測は参考観測でありauthoritative Evidence経路の生成物ではない
- `summary.json`: `target_revision=r1`、`source_hash`・`artifact_hash`記録済み

### Evidence検証

`scripts/verify_authoritative_evidence.py` により
`evidence-electrical.json`・`evidence-mechanical.json` の2件が
revision一致（r1）・`status="valid"`・既知のcontainer provenance・digest一致で
「OK: 2 authoritative Evidence file(s) verified」。

## 6. 未決事項・既知の注意点

- JLCPCBへの発注送信は未実施（ユーザーが実施）。価格・部品在庫・総発注額はunknown。
- 出力ファイル名prefixが`gd1`固定であり、evidenceの`subject_node`も
  `electrical.board.gd1`ハードコード（graph実ノードは`board.sensor-node`）。
  ゲート判定には影響しないがprovenance上紛らわしい（改善提案に記載）。
- 実機書き込み・LED/センサ実測は2026-08-30に実施した（§5 FW節に記録）。QEMU結果は
  仮想検証でありEvidenceの代替ではないが、実機観測も参考観測扱いである。
- FW成果物ディレクトリ名も`acd_gd1_fw`固定。
- 筐体設計不具合（2026-08-30実機組み付けで確認）:
  - **アンテナ干渉**: ESP32-C3-MINI-1アンテナ（5.4mm突出）が筐体シェル壁と干渉し組み付け不可。
    根因は`extract_mechanical_lane()`が`mechanical.board_edge_overhang`ノードを未消費で、
    `_build_shapes()`が単純箱型シェルを生成するため。干渉ゲートもoverhangを3D固体として
    評価しないため0.0mm³でpassしてしまう。
  - **ネジ穴欠落**: スタンドオフが貫通穴のない固体円柱で、リッドも平板のため締結不可。
    推奨方針は熱圧入インサート（M2）。詳細は`review-notes.md` §4.7/4.8 および
    `improvement-notes.md`の筐体pipeline節を参照。コード修正は別タスク。

## 7. 気づき・改善提案

`improvement-notes.md`（同フォルダ）を参照。主な項目:

- fixture複製ヘルパー（graph_id/ノードIDリネームの自動化）
- 新設計fixture組み立て手順（libraries/overlaysのコピー）のdocs化
- 出力prefix・evidence subject_nodeのgraph_id由来化
- QEMU実行に必要なaptパッケージ（libslirp0、SDL2系）のSKILL.md/operations.md明記
  またはlocked imageへの同梱
- OpenHands Local GUI APIのトークン発行手順のdocs化
