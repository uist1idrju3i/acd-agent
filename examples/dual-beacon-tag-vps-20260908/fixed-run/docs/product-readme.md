# 製品説明: dual-beacon-tag

- Design Graph: `dual-beacon-tag`
- revision: `r1`

この文書はDesign Graphと記録済み視覚投影から決定論的に生成された観測であり、設計の合否を判定しない。値はすべて入力由来で、推定値を含まない。

## 要求

| 要求ID | 内容 |
|---|---|
| req.dbt-req-001 | USB Type-Cバスパワー（5 V）で動作する小型状態表示タグ DUAL BEACON TAG |
| req.dbt-req-002 | 電源はUSB-C VBUS 5 Vのみとし、バッテリ、充電回路、USB PDネゴシエーションを持たない |
| req.dbt-req-003 | 最大ネット電圧は5 V、最大電流は500 mA未満とする |
| req.dbt-req-004 | USB-C CC1/CC2には5.1 kΩのプルダウンを配置し、Sourceデバイスへの接続検出を行う |
| req.dbt-req-005 | 3.3 Vは単一LDO（AMS1117-3.3）で生成する |
| req.dbt-req-006 | MCUはESP32-C3-MINI-1（内蔵アンテナ）を使用し、ファームウェアピン割り当てはグラフに従う |
| req.dbt-req-007 | BOOT/ENの起動条件はESP32-C3のstrapping規則に従う（GPIO9内部プルアップにより通常起動） |
| req.dbt-req-008 | 緑色LED（D1）をGPIO6で駆動し、500 ms周期で点滅させる |
| req.dbt-req-009 | 橙色LED（D2）をGPIO7で駆動し、緑色LEDと500 ms周期で交互に点滅させる |
| req.dbt-req-010 | ユーザーボタン（SW1）をGPIO5に接続し、内部プルアップ付きactive-low入力とする。押下でLED点滅を一時停止または再開する |
| req.dbt-req-011 | 外部センサ接続用I2Cヘッダ（4ピン: 3V3, GND, SDA, SCL）を1個配置し、SDA/SCLには4.7 kΩのプルアップを実装する |
| req.dbt-req-012 | 基板は2層FR-4、1.6 mm、1 oz、HASL、外形30 mm×22 mm、M2取付穴2個とする |
| req.dbt-req-013 | 筐体は基板を収める簡易構造とし、USB-Cコネクタ開口、2個のLED窓、ボタン開口、I2Cヘッダ開口を設ける |
| req.dbt-req-014 | ファームウェアはESP-IDF（ESP32-C3）で構築し、起動時にgraph_id由来のboot logを出力する |
| req.dbt-req-015 | ESP32-C3-MINI-1のアンテナ領域に対してkeepoutを確保する |

## 主要仕様

| 項目 | 値 |
|---|---|
| MCU | ESP32-C3-MINI-1-N4（U1） |
| FWモジュール | Dual Beacon Tag firmware |
| 基板外形 | 30 × 22 mm |
| 層数 | 2 |
| 基板材質 | FR-4 |
| 板厚 | 1.6 mm |
| 表面処理 | HASL |
| 実装面 | top |
| 最大ネット電圧 | 5 V |
| 最大電流 | 0.5 A |
| 想定用途 | author_prototype |

### 電源ネット

| ネット | 公称電圧 |
|---|---|
| +3V3 | 3.3 V |
| BOOT | 3.3 V |
| CC1 | 5 V |
| CC2 | 5 V |
| GND | 0 V |
| LED | 3.3 V |
| LED2 | 3.3 V |
| SCL | 3.3 V |
| SDA | 3.3 V |
| USB_D+ | 3.3 V |
| USB_D- | 3.3 V |
| VBUS_5V | 5 V |

### インタフェース割当（FWピン投影）

| ネット | GPIO |
|---|---|
| net.boot | IO9 |
| net.led | IO6 |
| net.led2 | IO7 |
| net.scl | IO1 |
| net.sda | IO0 |

## BOM要約

| MPN | 値 | LCSC | 実装 | 数量 |
|---|---|---|---|---|
| 0603WAF4701T5E | 4.7k | C23162 | fitted | 4 |
| 0603WAF5101T5E | 5.1k | C23186 | fitted | 2 |
| AMS1117-3.3 | AMS1117-3.3 | C6186 | fitted | 1 |
| CL10A106MQ8NNNC | 10uF | C1691 | fitted | 2 |
| CL10B104KB8NNNC | 100nF | C1591 | fitted | 2 |
| ESP32-C3-MINI-1-N4 | ESP32-C3-MINI-1-N4 | C2838502 | fitted | 1 |
| KT-0603A | KT-0603A | C2290 | fitted | 1 |
| KT-0603G | KT-0603G | C16224 | fitted | 1 |
| PinHeader_1x04_P2.54mm_Vertical | Conn_01x04_Pin |  | fitted | 1 |
| TS-1088-AR02016 | BOOT | C720477 | fitted | 1 |
| TYPE-C-31-M-12 | TYPE-C-31-M-12 | C165948 | fitted | 1 |

## 図解（視覚投影）

### レイヤ別配線投影: dual-beacon-tag-b-cu

![dual-beacon-tag-b-cu](../../fix18/dual-beacon-tag/visual/dual-beacon-tag-b-cu.svg)

- 投影種別: `layered_layout_view`（electrical lane）
- 画像hash: `sha256:c1da076f7b7b560922de4551c692f0a7108a3b1606654071f75c7edab2937d4b`

### レイヤ別配線投影: dual-beacon-tag-f-cu

![dual-beacon-tag-f-cu](../../fix18/dual-beacon-tag/visual/dual-beacon-tag-f-cu.svg)

- 投影種別: `layered_layout_view`（electrical lane）
- 画像hash: `sha256:3cd7e5afad241cd2ef0680a65da84cda04bb33bb19ceff43acfe84c1f1ca5ab0`

### 部品配置投影: dual-beacon-tag-placement

![dual-beacon-tag-placement](../../fix18/dual-beacon-tag/visual/dual-beacon-tag-placement.svg)

- 投影種別: `placement_view`（electrical lane）
- 画像hash: `sha256:598dfa2a2c8746707cb9f1ddfa0fc0195f30078d959d14dc05be4ffc101708fa`

### 電源ツリー投影: dual-beacon-tag-power-tree

![dual-beacon-tag-power-tree](../../fix18/dual-beacon-tag/visual/dual-beacon-tag-power-tree.svg)

- 投影種別: `power_tree_view`（system lane）
- 画像hash: `sha256:1b882d65886b2f60a7b342d7fe7efc03000520a54d75256c54f4d803c43f56ac`

### 回路図投影: dual-beacon-tag-schematic

![dual-beacon-tag-schematic](../../fix18/dual-beacon-tag/visual/dual-beacon-tag-schematic.svg)

- 投影種別: `schematic_view`（electrical lane）
- 画像hash: `sha256:8d0f5ed634ae8edf5c0aa820103412b3e3549ac23696b375be9621c427fa1d4d`

### 層構成投影: dual-beacon-tag-stackup

![dual-beacon-tag-stackup](../../fix18/dual-beacon-tag/visual/dual-beacon-tag-stackup.svg)

- 投影種別: `stackup_view`（electrical lane）
- 画像hash: `sha256:a21a6ad2dc51eab2004dbd9616d905253ebe3dd5fd6bd3db6e6360042a97d272`

### システムブロック投影: dual-beacon-tag-system-block

![dual-beacon-tag-system-block](../../fix18/dual-beacon-tag/visual/dual-beacon-tag-system-block.svg)

- 投影種別: `system_block_view`（system lane）
- 画像hash: `sha256:0dfd99ee1ab38ecc5f7eacfd6ebe8f0d3391465700dea7cc54e222b42ccd3d53`

## ライセンスと帰属

回路図記号・フットプリントは以下の外部ライブラリ由来であり、各ライブラリのライセンス表示と帰属を保持する。

| ライブラリ出典 | 参照 |
|---|---|
| https://github.com/espressif/kicad-libraries | dd76561812ab300351234ba6e0ec1295641796f0 |
| kicad-official (ppa:kicad/kicad-10.0-releases) | 10.0.6 |

生成物の設計データはこのリポジトリのライセンスに従う。
