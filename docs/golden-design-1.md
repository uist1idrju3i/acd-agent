# Golden Design #1

> ステータス: Draft
> 理由: GD1実機の測定Evidence未取得で、§11に未決事項と総発注額unknownが残るため。
> 対象: 趣味・研究・小規模試作の単一構成
> 対象マイルストーン: 第2「電気レーンの独立検証」、第3「機械レーンの決定論的検証」、第5「実機フィードバック」
> 対象工程: `S1`、`E1`、`E2`、`S2`
> 部品・在庫確認日時: 2026-08-11 UTC

本書は、Golden Design #1として固定する1枚の基板と、その基板で動作するFWの仕様で
ある。マイルストーン2（電気レーンの独立検証）、マイルストーン3（機械レーンの決定論的検証）、
マイルストーン5（実機フィードバック）のゴールデンタスクが対象とする実物であり、fixtureの元になる。
マイルストーンの完了条件は
[`roadmap.md`](roadmap.md)を正とし、本書ではこの設計に固有の入力、制約、ゲート、
Evidenceを定める。

本書は回路図、PCBレイアウト、筐体図面を作成するものではない。型付き・バージョン
付き入力ファイルから投影を生成する前の、検証可能な仕様を記述するものである。回路図、基板、
FWパッケージ、製造データは入力ファイルから生成する投影とする。

## CPL回転Evidence

U1、J1を含むfitted部品のCPL回転は、まず保存済みJLC/EasyEDA部品ライブラリのピン機能と
独立パーサで再読込したKiCadパッドの機能を対応付け、0/90/180/270度で照合して導出する。
機能対応が成立しない場合の幾何のみの照合は、USB Type-Cレセプタクルのように機構的な
向きまたは仕様上の機能対称性を出所付きで宣言した例外に限る。左右反転は回転では解消
できないため、幾何的一意性だけでなく電気的な機能対称性も確認する。
ネットワーク取得は`fetch_lcsc_footprint_orientation.py`に限定し、パイプラインは保存済み
Evidenceのhashを再計算する。これはメーカーのtape&reel図そのものではないため、
`fab_library_footprint`として出所と限界を記録し、JLCPCB公式FAQの包装内向き要件を
再現可能なライブラリ照合で補助する。hash欠落・不一致・一意に決まらない向きは
発注可否をfail-closedにする。

## 1. 位置づけ

### 1.1 マイルストーン

Golden Design #1は、マイルストーン2、3、5にまたがる具体的な1枚である。
マイルストーン2では本書の部品、ネット、基板制約からGerber/drillまでを生成し、
マイルストーン3では筐体の決定論的検証を行う。マイルストーン5では同じ入力ファイルから
FWパッケージを投影して書き込み、実機のLED点滅とSHT40のシリアルログを確認する。

対応する工程IDは次のとおりである。

| 工程ID | 本設計での役割 |
|---|---|
| `S1` | 作者自身の試作という要求と`SB1`（安全境界の予備判定） |
| `E1` | 部品、回路、ネット、ピン割当、`SB2`（安全境界の確定判定） |
| `E2` | 2層基板の配置・配線、DRC、アンテナキープアウトを含むアートワーク |
| `S2` | Gerber/drill、部品表、実装指定などの製造出力 |

工程IDの定義は[`glossary.md`](glossary.md)を参照する。安全境界の判定段階は工程IDとは
別体系の`SB1`／`SB2`で表す。`SB1`は工程`S1`で実行し、`SB2`は工程`E1`で実行する。
ゲートの正は`SB2`であり、工程`S2`（製造出力）は`SB2`の`pass`結果を前提に進む。

### 1.2 対象範囲とfixture

対象は趣味・研究・小規模試作である。安全境界、ピン整合、製造可能性、実機測定を確認し、
未知、矛盾、ゲート未実行はfail-closedで停止する。

本設計をfixtureへ固定する際は、少なくとも次を入力としてhash付きで管理する。

- 本書と入力ファイルを管理するgit commit
- 部品MPN、ライブラリ参照、フットプリント、3D modelの出所
- ネット一覧、ピン割当、電源条件、アンテナキープアウト述語
- 2層、FR-4、1.6 mm、HASL、片面実装、外形およそ30 × 25 mmという基板条件
- ESP-IDFの版、環境プローブ結果、FWパッケージの投影条件
- JLCPCBの部品在庫・単価確認値と確認日時
- negative testの入力差分と期待する停止ゲート

## 2. 要件

要求は、設計グラフの`Requirement`として次の粒度で記録する。

| Requirement | 内容 |
|---|---|
| `GD1-REQ-001` | 作者自身が試作し、USB-Cから給電して実機の赤色LEDを1 Hzで点滅させる |
| `GD1-REQ-002` | USB-Serial-JTAG経由でFWを書き込み、同じ経路からシリアルログを取得する |
| `GD1-REQ-003` | SHT40から温度・湿度を読み、一定周期でシリアルログへ出力する |
| `GD1-REQ-004` | 電源はUSB-C VBUS 5 Vのみとし、バッテリ、充電回路、USB PDネゴシエーションを持たない |
| `GD1-REQ-005` | 最大ネット電圧は5 V、最大電流は500 mA以下とする |
| `GD1-REQ-006` | USB-Cは電力シンク専用とし、CC1/CC2にそれぞれ5.1 kΩのプルダウンを置く |
| `GD1-REQ-007` | 3.3 VはAMS1117-3.3で生成し、入力・出力に10 µFと100 nFを置く |
| `GD1-REQ-008` | MCUはESP32-C3-MINI-1-N4とし、IO18/IO19の内蔵USBを使用する |
| `GD1-REQ-009` | RESETはENをGNDへ接続するボタン、BOOTはIO9をGNDへ接続するボタンで行う |
| `GD1-REQ-010` | LEDはIO7に1 kΩを直列接続し、IO2、IO8、IO9をLEDへ割り当てない |
| `GD1-REQ-011` | I2CはIO4=SDA、IO5=SCL、アドレス0x44のSHT40とし、各線に4.7 kΩを置く |
| `GD1-REQ-012` | テストポイントとして3V3、GND、SDA、SCL、IO7、UART TX(IO21)、RX(IO20)を出す |
| `GD1-REQ-013` | 基板は2層FR-4、板厚1.6 mm、HASL、片面実装、外形およそ30 × 25 mmとする |
| `GD1-REQ-014` | M2取付穴を4箇所設け、第2マイルストーンの筐体と共用する |
| `GD1-REQ-015` | ESP32-C3モジュールのアンテナを基板端からはみ出させ、アンテナ直下・周囲に銅箔、GND、部品、シルクを置かない |
| `GD1-REQ-016` | `intended_use`は作者自身の試作であり、医療、車載、航空、産業安全用途ではない |
| `GD1-REQ-017` | JLCPCBの実装部品ライブラリで在庫を一次確認でき、部品支給なしでJLCPCBAへ実装まで依頼できる部品だけを初版の採用対象とする |

## 3. 安全境界の判定

### 3.1 SB1（S1で実行する予備判定）

`SB1`では、工程`S1`でRequirementと部品候補から次を予備判定する。

| 判定項目 | 期待値 | 根拠 |
|---|---|---|
| `Requirement.intended_use` | 許可領域 | 作者自身の試作であり、医療・車載・航空・産業安全ではない |
| 最大ネット電圧 | 5 V | USB-C VBUSのみで、許可閾値の50 V AC / 120 V DC以下 |
| 最大電流 | 500 mA以下 | `width_basis=current_ipc2221`の電源ネットを対象とし、対象ネットの電流宣言欠落は`unknown`で停止する。承認必須の5 A超または25 W超に該当しない |
| バッテリ・充電 | なし | Li-ion/LiPo充電回路を持たない |
| 動力・光源 | モーター、アクチュエータ、レーザーなし | 赤色LEDは表示用である |
| 無線 | 認証済みESP32-C3モジュール | チップ直載せとアンテナ設計を行わない |

`SB1`の出力は`SafetyBoundaryResult`として記録する。モジュール認証の出所が設計
グラフへ添付されていない場合、その項目は`unknown`として工程`S1`を停止させ、説明だけで
合格させない。

`SafetyBoundaryResult`は電圧、電流、認証、危険区分、intended useの各述語を保持し、
unknownをfailより優先してfail-closedに集約する。

### 3.2 SB2（E1で実行する確定判定）

`SB2`では、工程`E1`で設計グラフの述語により安全境界を確定判定する。次の全述語が
`pass`となり、`S2`へ渡される`SafetyBoundaryResult.status`が`pass`となる状態が
期待値である。

| グラフ述語 | 期待値 |
|---|---|
| `max(Net.voltage_nominal) <= 5 V` | `pass` |
| `max(Net.voltage_nominal) <= 50 V AC / 120 V DC` | `pass` |
| `max(Net.current_max) <= 500 mA` | 電源ネット（`width_basis=current_ipc2221`）を対象に、宣言欠落は`unknown`、0.5 A以下で`pass` |
| `Part.certification`がESP32-C3モジュールに存在する | 出所Evidence付きで`pass` |
| `Part.hazard_class`にバッテリ充電器、モーター、アクチュエータ、レーザーがない | `pass` |
| `Requirement.intended_use`が許可領域にある | `pass` |
| 未知の危険区分、影響、認証、電圧、電流がない | `pass`。一つでも`unknown`なら停止 |

この設計は上記の対象範囲に収まる。電流境界は`width_basis=current_ipc2221`の電源ネットを
対象とし、その対象ネットの`current_max_a`が欠落していれば`unknown`として停止する。
`width_basis=manufacturing_minimum`の信号ネットは電流境界の対象外だが、そこに電流値が
宣言されている場合は同じ0.5 A以下の閾値で検査する。認証出所、電流の導出、部品の実装可否が
入力ファイルへ取り込まれていない状態も`unknown`であり、許可領域とはみなさない。
`SafetyBoundaryResult`の各述語が`pass`であることを、電気Evidenceの電源境界claimへ
固定順序で記録する。認証出所はU1のgraph属性から決定論的に検証する。

## 4. 部品表

在庫数と単価は、**2026-08-11 UTC時点のJLCPCB実装部品ライブラリ検索での一次確認値**
である。恒久的な在庫・価格ではなく、Golden Designのfixtureに確認日時と検索結果の
出所を記録する。個別部品の実装可否は、発注時点で再確認する。

初版の採用条件は、JLCPCB実装部品ライブラリのBasicまたはExtendedに在庫があり、
部品支給なしでJLCPCBAへ実装まで依頼できることである。将来は支給部品およびGlobal
Parts Sourcing経由の部品を許容範囲へ含めるが、本設計の初版には適用しない。

| 役割 | MPN | LCSC | 区分 | 在庫（2026-08-11 UTC） | 単価（1個、同日時点） |
|---|---|---|---|---:|---:|
| MCU モジュール | `ESP32-C3-MINI-1-N4` | `C2838502` | Extended | 24,830 | $3.81 |
| USB-C レセプタクル 16P | `TYPE-C-31-M-12` | `C165948` | Extended | 453,410 | $0.18 |
| LDO 3.3V | `AMS1117-3.3` | `C6186` | Basic | 1,442,521 | $0.20 |
| タクトスイッチ ×2 | `TS-1088-AR02016` | `C720477` | Basic | 801,489 | $0.055 |
| 温湿度センサ（I2C） | `SHT40-AD1B-R3` | `C2848306` | Extended | 15,640 | $1.82 |
| LED 赤 0603 | `KT-0603R` | `C2286` | Basic | 6,673,573 | $0.0074 |
| R 5.1 kΩ 0603 ×2（CC1/CC2） | `0603WAF5101T5E` | `C23186` | Basic | 9,172,725 | $0.0043 |
| R 10 kΩ 0603（EN） | `0603WAF1002T5E` | `C25804` | Basic | 3,277,011 | $0.041 |
| R 4.7 kΩ 0603 ×2（I2C pull-up） | `0603WAF4701T5E` | `C23162` | Basic | 10,222,438 | $0.0117 |
| R 1 kΩ 0603（LED） | `0603WAF1001T5E` | `C21190` | Basic | 34,786,211 | $0.0057 |
| C 100 nF 0603 ×3（LDO入出力、ESP32-C3-MINI-1 3V3直近） | `CL10B104KB8NNNC` | `C1591` | Extended | 8,033,248 | $0.0158 |
| C 1 µF 0603（EN RC） | `CL10A105KB8NNNC` | `C15849` | Basic | 15,369,424 | $0.075 |
| C 10 µF 0603 ×2（LDO入出力） | `CL10A106MQ8NNNC` | `C1691` | Extended | 2,926,770 | $0.0293 |

二次保持のセンサ候補は`AHT20`（`C2757850`、Extended、49,096個、$0.79）である。
USB D+/D-のESD保護（`TPD2E009DBZR`系）は任意扱いであり、初版には実装せず将来
リビジョンで評価する。

## 5. 回路構成

### 5.1 機能ブロック

| ブロック | 構成 | 設計上の目的 |
|---|---|---|
| USB給電 | USB-C VBUS、CC1/CC2の5.1 kΩ Rd | 5 Vの電力シンク専用給電 |
| 3.3 V電源 | AMS1117-3.3、入力10 µF/100 nF、出力10 µF/100 nF | MCU、センサ、LEDへの3.3 V供給 |
| MCU電源デカップリング | ESP32-C3-MINI-1の3V3ピン直近に100 nF | MCU電源の局所デカップリング |
| MCU | ESP32-C3-MINI-1-N4 | USB-Serial-JTAG、FW実行、I2C、LED制御 |
| USB通信 | IO18=D-、IO19=D+ | 書き込みとログ取得。外部USB-UARTブリッジは置かない |
| ユーザー入力 | ENボタン、IO9ボタン | RESET、BOOT（ダウンロードモード兼入力） |
| 表示 | IO7、1 kΩ、赤色LED | 1 Hz点滅による実機動作確認 |
| センサ | SHT40、IO4/IO5、各4.7 kΩ | 温湿度取得 |
| 実測点 | 3V3、GND、SDA、SCL、IO7、IO21、IO20パッド | 実測Evidenceの取得 |

### 5.2 ネット一覧

| ネット | 接続 | 条件 |
|---|---|---|
| `VBUS_5V` | USB-C VBUS → AMS1117入力 | 5 V、USB PDなし |
| `CC1` | USB-C CC1 → 5.1 kΩ → GND | 電力シンクRd |
| `CC2` | USB-C CC2 → 5.1 kΩ → GND | 電力シンクRd |
| `GND` | USB-C GND、LDO GND、MCU、SHT40、各部品 | 共通リターン |
| `+3V3` | AMS1117出力 → MCU、SHT40、LED、プルアップ。ESP32-C3-MINI-1の3V3ピン直近に100 nF | 3.3 V |
| `MCU_3V3_DECOUPLING` | ESP32-C3-MINI-1の3V3ピン → 100 nF → GND | MCU直近の局所デカップリング |
| `USB_D-` | USB-C D- ↔ ESP32-C3 IO18 | 内蔵USB-Serial-JTAG |
| `USB_D+` | USB-C D+ ↔ ESP32-C3 IO19 | 内蔵USB-Serial-JTAG |
| `EN` | 10 kΩで`+3V3`へプルアップ、1 µFでGND、RESETボタンでGND | RCリセット |
| `BOOT` | ESP32-C3 IO9、BOOTボタンでGND | ダウンロードモード兼ユーザー入力 |
| `LED` | ESP32-C3 IO7 → 1 kΩ → LED → GND | 1 Hz点滅 |
| `I2C_SDA` | ESP32-C3 IO4 ↔ SHT40 SDA、4.7 kΩで`+3V3` | SHT40アドレス0x44 |
| `I2C_SCL` | ESP32-C3 IO5 ↔ SHT40 SCL、4.7 kΩで`+3V3` | SHT40アドレス0x44 |
| `UART_TX` | ESP32-C3 IO21 →テストポイント | 実測ログ観測点 |
| `UART_RX` | ESP32-C3 IO20 →テストポイント | 実測入力観測点 |
| `TP_3V3`、`TP_GND`、`TP_SDA`、`TP_SCL`、`TP_IO7` | 各信号のパッド | 設計グラフの測定点 |

### 5.3 ピン割当

| MCU pin | 機能 | グラフ上の接続 | 制約 |
|---|---|---|---|
| IO4 | I2C SDA | `I2C_SDA` | SHT40と4.7 kΩ |
| IO5 | I2C SCL | `I2C_SCL` | SHT40と4.7 kΩ |
| IO7 | LED | `LED` | strapping pinを使用しない |
| IO9 | BOOT | `BOOT` | strapping pin。LEDへ再割当しない |
| IO18 | USB D- | `USB_D-` | USB-Serial-JTAG |
| IO19 | USB D+ | `USB_D+` | USB-Serial-JTAG |
| IO20 | UART RX test point | `UART_RX` | 実測点 |
| IO21 | UART TX test point | `UART_TX` | 実測点 |
| EN | RESET | `EN` | 10 kΩ＋1 µF RC |

IO2、IO8は未使用とし、strapping条件へ影響する負荷を追加しない。ピン割当はこの表を
手書きFWへ複製せず、設計グラフの`Net`と`Pin`からFWパッケージへ投影する。

## 6. 基板仕様

| 項目 | 仕様 | 状態・出所 |
|---|---|---|
| 層数 | 2層 | 確定 |
| 材質 | FR-4 | JLCPCB公式能力ページで確認 |
| 外層銅箔厚 | 1 oz | JLCPCB公式能力ページに基づく本設計条件 |
| 板厚 | 1.6 mm | JLCPCB公式能力ページの選択肢で確認 |
| 板厚公差 | 1.44〜1.76 mm（±10%） | 1.6 mm指定、板厚1.0 mm以上の値 |
| 表面処理 | HASL | 鉛入り／鉛フリーの選択は未決 |
| ソルダーマスク色 | `unknown` | 未決 |
| 外形 | およそ30 × 25 mm | 概略値。確定値は未決 |
| 外形寸法公差 | ±0.2 mm（regular） | high precisionの±0.1 mmは本設計の30 × 25 mmでは選択不可 |
| 実装面 | 表面のみ | 片面実装の設計要求 |
| 取付穴 | M2 ×4 | 第2マイルストーンの筐体と共用 |
| アンテナ | 基板端から突出 | Espressifモジュール設計条件に基づく専用ゲート |

JLCPCB公式の[PCB manufacturing capabilities](https://jlcpcb.com/capabilities/pcb-capabilities)
を2026-08-11 UTCに確認した。確定した製造能力は次のとおりである。

| 項目 | 確定値 |
|---|---|
| 最小線幅／最小間隔（1 oz、1〜2層） | 0.10 / 0.10 mm（4 / 4 mil） |
| 線幅公差 | ±20% |
| PTHアニュラリング | ≥0.20 mm（2層1 ozは推奨0.25 mm以上、絶対最小0.18 mm） |
| NPTHパッドアニュラリング | ≥0.45 mm |
| 最小ビア（2層） | 穴0.15 mm／ビア径0.25 mm。推奨最小穴径0.20 mm。ビア径は穴径より0.1 mm以上（0.15 mm推奨）大きくする |
| ドリル径（2層） | 0.15〜6.3 mm |
| 穴径公差 | スルーホール +0.13 / −0.08 mm |
| 穴位置公差 | ±0.05 mm |
| 最小NPTH | 0.50 mm |
| ビア穴間隔／パッド穴間隔 | 0.2 mm／0.45 mm |
| シルク最小線幅 | ≥0.15 mm |
| シルク最小文字高 | 1.0 mm（40 mil） |
| パッド−シルク間隔 | ≥0.15 mm |
| 基板端からの銅箔クリアランス（ルーター外形） | ≥0.2 mm |
| 外形寸法公差 | ±0.2 mm（regular）／±0.1 mm（high precision） |
| 板厚公差（≥1.0 mm） | ±10%（1.6 mm指定で1.44〜1.76 mm） |
| 最小基板寸法 | 3 × 3 mm（板厚≥0.6 mm） |
| ブラインド／ベリードビア | 非対応（貫通のみ） |

high precisionの±0.1 mmは、最小50 × 50 mmかつ異なる隅に直径1.5 mm以上の
ツーリングホール3個が必要であり、本設計の30 × 25 mmでは選択できない。したがって
M2取付穴と将来の筐体の嵌合公差は、外形の±0.2 mm（regular）を前提に設計する。
また、ブラインド／ベリードビアは使用せず、2層の貫通ビアのみで配線する。

## 7. 設計ルールとゲート

追加の受入ゲートとして、部品ライブラリのピン番号・パッド番号・極性・3Dモデル姿勢を
照合Evidenceで確認し、座標の単位・原点・軸を固定する。外形・配線変更後は派生状態を
再計算してから検査し、variant／DNPの対象と出力を固定する。ツール版、形式版、設定、
ライブラリcommitはEvidenceへ記録し、未確認項目は`unknown`で停止する。

| ゲート | 検出する条件 | 注入すると停止する例 | Evidence | 実装状況 |
|---|---|---|---|---|
| ERC | 未接続、電源入力、駆動競合、ピン方向の電気規則違反 | VBUSとGNDの誤接続、ENの駆動競合 | `kicad-cli` ERC結果、入力hash、版 | 実装済み |
| DRC | クリアランス、未配線、製造形状、穴・銅の規則違反 | 短絡、未配線、能力値未確定 | `kicad-cli` DRC結果、ルール版 | 実装済み |
| アンテナキープアウト | アンテナ直下・周囲の銅箔、GND、部品、シルクの有無 | アンテナ下へGNDベタを追加 | グラフ宣言、投影Gerberの独立測定、形状hash | 実装済み |
| USB CC | CC1/CC2それぞれの5.1 kΩ RdとGND接続 | CC1またはCC2の抵抗を削除 | ネット述語、抵抗MPN、接続hash | 実装済み |
| strapping pin | IO2/IO8/IO9の起動条件を壊す割当・負荷 | LEDをIO8またはIO9へ割当 | ピン述語、FW整合結果 | 実装済み |
| I2C pull-up | SDA/SCLそれぞれの4.7 kΩと電源接続 | SDAまたはSCLのプルアップを削除 | ネット述語、ERC結果 | 実装済み |
| 電源デカップリング | LDOの入力・出力に10 µF＋100 nFがあり、ESP32-C3-MINI-1の3V3ピン直近に100 nFがあること | LDO側またはMCU側のコンデンサを削除・遠ざける | 部品・ネット述語、BOM hash | 実装済み |
| 電源境界 | 5 V VBUS、3.3 V生成、電流・電圧境界 | バッテリ充電回路または5 V超の電源を追加 | `SafetyBoundaryResult` | 実装済み |
| ピン・FW整合 | グラフの`Net`/`Pin`とFWパッケージの一致 | FWだけIO7をIO8へ変更 | 投影hash、整合ゲート結果 | 実装済み |

電源デカップリングの100 nF級判定は、`0.1 µF ± 0.02 µF`（±20%）の範囲を用いる。
1 µF以下の小容量は高周波過渡応答のため対象電源padから3.0 mm以下、
1 µF超のbulk容量はレール上のエネルギー保持を担うため対象電源padから8.0 mm以下とする。

実装状況は次のとおりである。ERC、DRC、アンテナキープアウトの3件は実装済みである。
ERCとDRCは共通の決定論的gate関数で検査し、アンテナキープアウトはグラフ宣言を生成した
後、投影Gerberを独立測定してfail-closedにする。6件はlaneとgraphから決定論的に評価し、
生成される電気Evidenceのclaimへ固定順序で含める。strapping pinはIO2/IO8を未接続または
no-connect、IO9をBOOT網だけへ接続し、BOOT網にはIO9 pad、GNDへ落とすボタン1個、
任意の3.3 Vプルアップ抵抗（0個または1個）だけを許容する。GPIO9のリセット既定値は
Espressif ESP32-C3 datasheetのBoot ConfigurationsおよびESP Hardware Design Guidelines
のSchematic Checklist > Strapping Pins > Boot Mode Controlにある`1 (Pull-up)`（約45 kΩ
内部プルアップ）であり、外部プルアップは任意である。IO9の`fw.pin.boot`だけを例外として
許可する。

## 8. negative test

| ID | 注入する変更 | 期待される不合格ゲート |
|---|---|---|
| `GD1-NEG-001` | LEDをIO8またはIO9へ割り当てる | strapping pinゲートとピン・FW整合ゲートが`fail` |
| `GD1-NEG-002` | ESP32-C3アンテナ直下へGNDベタを敷く | アンテナキープアウト述語が`fail` |
| `GD1-NEG-003` | CC1またはCC2の5.1 kΩを削除する | USB CCゲートが`fail` |
| `GD1-NEG-004` | I2C SDAまたはSCLの4.7 kΩを削除する | I2C pull-upゲートが`fail` |
| `GD1-NEG-005` | FWのIO7、IO4、IO5、IO9、IO18、IO19、IO20、IO21のいずれかをグラフと異なる値へ変更する | ピン・FW整合ゲートが`fail` |

`GD1-NEG-001`〜`GD1-NEG-008`に対応する注入fixtureとnegative testは未整備であり、
マイルストーン2.1の後続変更で整備する。

## 9. 製造投影と配置

J1にはLibraryOverlayを適用する。公式footprintを直接改変せず、
`overlays/j1-usb-c-annular-ring.json`としてプロジェクトローカルに保持し、
JLCPCBのPTHアニュラリング推奨値を根拠にSH padを`0.20 mm`から`0.25 mm`へ拡大する。
overlayの適用後geometryは、DSN export、routing、最終board、DRC、DFMで共通に使用する。

配置は次の4段を固定順序で実行する。

1. 固定anchor（アンテナmodule、USB receptacle、取付穴）
2. 能動部品（U1、U2、U3）
3. 能動部品の電源pinへ接続するデカップリングコンデンサ
4. 残りの部品をcourtyard面積の降順、同面積はrefdes順

配置ゲートでは、USBコネクタの本体外形とパッド重心から嵌合側の板端アンカーを導出し、
RFモジュールではfootprint内の単一アンテナkeepoutから板端アンカーを導出する。
独立DFMゲートのcheck IDは`pad-to-board-edge-clearance`、
`undeclared-board-edge-overhang`であり、これらは発注能力違反
（`capability_violation`）として扱う。CPLの回転は、fab側ライブラリのピン機能付き
パッド配置とKiCad symbolの独立検証から部品ごとのオフセットを導出し、基板実測回転へ
宣言オフセットを加えて出力する。生成CPLは、実測回転と宣言オフセットのcross-validation
でも検証する。

第3段のデカップリング対象は設計グラフの`decoupling_target`宣言から導出し、
対象ICの電源padまでの距離を目的関数にする。推測による分類や配置不能時の制約緩和は行わない。

GD1最新実行で生成される製造データは、`out/gd1-final/fab/`の次のファイルである。

- `gd1-gerbers.zip`
- `gd1-bom-jlcpcb.csv`
- `gd1-cpl-jlcpcb.csv`
- `gd1.pos.csv`
- `dfm-report.json`
- `fab-package.json`

発注用BOMの行同一性はfab部品番号（LCSC、MPN、footprint）で決まり、設計グラフ上の
`value`が異なるだけでは行を分割しない。同一部品番号でvalueが一致する場合はvalueを
Commentへ出し、不一致の場合はMPNをCommentへ出す。Designatorは自然順のrefdesを
カンマ区切りでまとめ、未実装部品は含めない。生成後にDesignator集合、LCSC、footprintを
グラフと独立に照合し、不一致はfail-closedで停止する。

CPLの`Mid X`/`Mid Y`はJLCPCB公式のcomponent centroid定義を参照するが、算出方法は
公式に明記されていない。GD1では独立測定とビューワ実測の符号・大きさが一致したため、
U1/J1のpad bbox中心を基準として宣言した。これは独立実測とビューワ表示の一致に基づく
基準であり、JLCPCBが公式に確定した算出定義ではない。U1/J1の位置Evidenceは
`confirmed`（確認手段`fab_side_preview`、確認日`2026-08-13`）である。
回転はfitted 19部品すべてについてfab側ライブラリのピン機能付きパッド配置から導出し、
KiCad symbolのpathとsha256を独立検証した。これはメーカーのtape&reel図そのものでは
なく、`fab_library_footprint`由来の再現可能な照合Evidenceである。製造データ生成と発注
可否は分離し、全位置・回転Evidenceが揃ったGD1の`order-readiness.json`は`ready`となる。
`evidence/gd1-cpl-orientation/`自体が無い場合は製造データ生成をfail-closedで停止し、
個別部品のEvidence欠落は`order-readiness.json`の回転unknownとして扱う。

GD1のGNDプレーンはグラフの`GND`ネットをF.Cu/B.Cuへ投影し、板端clearanceから導出した
インセットで定義する。塗りは自前計算せず、KiCad 10.0.5の`--refill-zones --save-board`
で実行し、塗り済み基板のhashを製造Evidenceへ記録する。ステッチviaのpitchは最高動作
周波数、FR-4の比誘電率、採用波長分数からguided wavelengthを計算して導出し、根拠宣言
が無い場合は停止する。GD1では2.4 GHz、εr=4.3、λ/20を採用し、via追加の工程・コスト
影響はfab profileのvia関連ドライバと実測via/drill数で記録する。keepout、pad、track、
板端clearance違反位置は決定論的に除外し、塗り後F.Cu/B.Cu Gerberの銅面積、連結成分、
最小島面積、全stitch viaの銅被覆を独立測定する。

ステッチviaは決定論的な外周リングを基本とし、孤立したzone islandをGNDへ接続する必要が
ある場合は、同じ宣言pitchによる内部gridも候補にする。外周はGND planeを拘束し、内部
候補は信号wire、pad、via、アンテナkeepoutとの衝突を除外したうえで、塗り後の銅被覆を
独立検証する。配置根拠はグラフのcost/process宣言にも記録する。

生成時の実測は、2層、外形`30.0 × 25.0 mm`、route via `24`個、stitch via `7`個、
ground-plane drill object `41`個、pad `132`個、route wire `188`本である。塗り後Gerberの独立測定は
F.Cu `2`領域、B.Cu `1`領域、銅面積`1066.8861574973707 mm²`、連結成分`1`、
最小島面積`33.343936651752315 mm²`、stitch via被覆`7/7`、keepout内銅面積`0.0 mm²`、
塗り後剪定`1`反復、剪定`0`個であった。ERCは`0` errors、DRCは`0` errors・
`0` unconnected、DFM findingsは`0`である。
最小track幅`0.15 mm`、silk最小文字高`1.0 mm`、silk最小stroke幅`0.15 mm`である。
塗り後Gerberのflash中心を座標照合した達成pitchの独立実測は、宣言pitch
`3.011932521069266 mm`に対して、外周隣接最大gap `40.8478 mm`、全stitch viaの
最近傍距離最大 `9.610355810790772 mm`であり、`declared_pitch_satisfied: false`である。
この未達は今回のpipeline合否ゲートにはせず、Evidenceへ明示的に記録する。証拠の欠落や
Gerber座標の照合不能はfail-closedとする。stitch候補は`93`点で、除外ヒット数は
footprint body/courtyard `82`、wire `51`、pad `48`、keepout `1`、via `1`、
板端インセット `0`、相互間隔 `0`である（理由は重複計上）。選択は`7`点であり、
body/courtyardとwire、padが支配的な制約だった。回転後軸平行bbox判定を回転矩形そのもの
の判定へ置き換える比較では、候補`93`点、選択`7`点で差がなかった。clearanceは変更していない。
Freeroutingのwire方式の実測は、`188` route wire、`24` route via、0 unroutedで収束し、
KiCad DRCは`0` errors・`0` unconnected、銅面積`1066.8861574973707 mm²`、stitch via
`7`点、上記pitch値である。plane方式はDSNの`(plane F.Cu GND ...)`入力で
`Plane.read_scope: String expected at 'Via_600:300'`および`DSN structure parsing failed`
を実測し、CLI status `0`でも有効なrouting outputや収束とは扱わなかった。
板端から`via diameter + clearance = 0.6 + 0.15 = 0.75 mm`の帯をF.Cu/B.Cu keepout
として予約する比較では、Freeroutingは`188` wire、`24` via、0 unroutedで収束したが、
最終scoreは`956.81`（`19` violations）であり、KiCad DRC 0/0へ到達した証拠は得られなかった。
この比較経路の最終Gerber再生成・stitch via挿入は既定経路へ反映していないため、帯方式の
stitch数・達成pitch・銅面積は`unknown`として合格根拠にしない。
via profileとの突合では、route `24`個に対してstitch `7`個を追加し、routing via合計は
`31`個、ground-plane drill objectは`41`個（stitchなし推定`34`個、追加`7`個）となった。
via径`0.6 mm`、drill`0.3 mm`であり、profileの`via-hole-prefer-020`、
`via-hole-015-cost`、`via-hole-small-diameter-cost`、`via-diameter-margin-quality`
の閾値へ照合した。profileには数量単位のper-via surchargeが無いため、該当数値は追加工程負荷
として`fab-package.json`へ記録し、金額・納期の確定値とは扱わない。

### 8.0 GD1計画2: netclass別配線幅の実測

計画2では、各`electrical.net`へ`width_basis`を宣言し、基板の銅厚・許容温度上昇・
IPC-2221定数・式の出所・突合許容差をグラフへ宣言した。必要最小幅は、宣言basisからの
導出値、グラフ最小track幅、fab profile最小track幅の最大値で決定した。電源系の
`VBUS_5V`、`+3V3`、`GND`は、プレーンとは独立に測定する routed conductor の電流容量
根拠として`current_ipc2221`を採用した。その他の信号系は、電流容量ではなく製造最小幅が
支配的である理由を`width_basis_source`へ宣言した。
式の同定は散文の部分一致ではなく、`width_basis_equation =
ipc2221_external_current_capacity`という構造化値で行い、未知の式種別と空の出典は
fail-closedとした。製造最小幅はnetへ複製せず、fab profileの
`capabilities.min_track_width`に宣言マージンを加えて導出した。

塗り後・保存後KiCad基板から出力したF.Cu/B.Cu Gerberの導体オブジェクトを種類別に
数え、`Line`だけを保存基板の`segment`端点・層・netへ座標照合して、Gerber aperture径を
ネット別に独立測定した。`Line`以外の`Region`と`Flash`も読み取り済み導体として記録し、
未知の種類はfail-closedとした。全導体オブジェクトは520個（route `Line`は325個）で、
許容差は`0.01 mm`であり、照合不能な導体は合格扱いにしていない。KiCad 10.0.5では
`net_settings.classes`に`Default`と決定論的な`ACD_0150um`を投影し、
`netclass_patterns`で全15ネットを明示的に割り当てた。`+3V3`のclass幅を意図的に
`0.4 mm`へ膨らませ、2つの別projectでDRCを実行した。Arm Aはclass幅だけを変更し、
board-level `min_track_width`を`0.15 mm`に据え置いた。Arm Bはclass幅とboard-level
最小幅をともに`0.4 mm`へ変更した。Arm Aでは幅違反0件、Arm Bでは幅違反199件
（うち`+3V3`対象54件）となった。したがってKiCad 10.0.5の既存track DRCへ
class幅が直接適用されることは未実証であり、board-level最小幅の適用だけが確認された。
どちらのArmでも違反が出ない場合はfail-closedとする。通常projectのDRCは
0 errors・0 unconnectedへ到達した。
DSNは独立にparseし、class ruleの幅と、塗り後Gerberのnet別実測最小幅を照合した。
今回の`ACD_0150um`はDSN幅`0.15 mm`、全15ネットの実測最小幅も`0.15 mm`で、
Freeroutingへ渡したclass幅と生成物の対応を確認した。

| ネット | basis | 導出幅(mm) | 採用幅(mm) | Gerber実測最小(mm) | 全導体長(mm) | 直列抵抗上界(Ω) | IR drop上界(V) | 最遠pad間経路抵抗(Ω) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| VBUS_5V | current_ipc2221 | 0.115469 | 0.15 | 0.15 | 20.222430 | 0.066407 | 0.033203 | 0.052694 |
| +3V3 | current_ipc2221 | 0.115469 | 0.15 | 0.15 | 98.300328 | 0.322800 | 0.161400 | 0.215703 |
| GND | current_ipc2221 | 0.115469 | 0.15 | 0.15 | 138.688073 | 0.455425 | 0.227713 | 0.129320 |
| その他11ネット | manufacturing_minimum | 0.100000 | 0.15 | 0.15 | — | — | — | — |

電源ネットのIPC-2221導出値は約`0.115469 mm`で、採用・実測幅`0.15 mm`が上回る。
したがって現行幅は電流容量上十分であり、幅を広げることによる定量的な改善がないため
既存幅を維持した。全導体長を一つの直列経路とみなす抵抗・IR dropは、分岐による
並列経路を無視した悲観的な上界である。特にGNDはベタ面の帰路をモデル化していないため、
通常の負荷端子間IR dropではない。併せて、保存基板のsegment/via端点グラフ上で全pad
terminal pairの最短抵抗を測定し、最遠pad pairの経路抵抗をEvidenceへ記録した。
抵抗は1 oz外層銅厚`35 µm`、抵抗率`1.724e-5 Ω·mm`、実測幅から計算した。採用幅／
導出幅比率、導出値をグラフ最小値またはprofile最小値が上回る事実は数値フィールドで
記録し、固定文言による判定は行わない。
最短経路のvia接続は、barrel plating抵抗を測定していないため理想0 Ωとして扱い、
この仮定もEvidenceへ記録した。

計画2の出力は`out/gd1-plan2-default/fab/dfm-report.json`および
`out/gd1-plan2-default/fab/fab-package.json`である。route wireは`188`、route viaは
`24`、stitch viaは`7`、DRCは`0/0`、Freeroutingは収束済みである。計画1で記録した
stitch via `7`、銅面積`1066.8861574973707 mm²`、連結成分`1`、最小島面積
`33.343936651752315 mm²`、`declared_pitch_satisfied: false`は変更していない。
今回の`graph.json`はJSON parse後にnode ID、kind、attrs、depends_on、edgesを比較した。
node数は215→215、edgesは同一で、意味差分は式種別の追加
`board.gd1.attrs.width_basis_equation`と、製造下限の重複宣言を削除した12 netの
`manufacturing_minimum_mm`だけだった。キー順や空白の差は比較対象にしていない。
J1は`(15.0, 21.35)` mm、U1は`(15.0, 2.9)` mm、
ともに回転`0°`である。U1の板端はみ出し宣言は本体外形基準で`5.4 mm`である。DSNの
`(via_at_smd off)`とSMD pad周囲の`via_keepout`により、
SMD pad上viaを構造的に禁止している。出所は`out/gd1-plan2-default/fab/dfm-report.json`、
`out/gd1-plan2-default/routing-summary.json`、`out/gd1-plan2-default/fab/fab-package.json`である。
| `GD1-NEG-006` | ライブラリ照合Evidenceを削除する | ライブラリ受入ゲートが`unknown`で停止 |
| `GD1-NEG-007` | 派生状態を再計算せずにDRC結果を採用する | ゲート未実行として停止 |
| `GD1-NEG-008` | 原点、単位、または軸を不明にする | 座標系ゲートが`unknown`で停止 |

各negative testは、注入前の入力ファイル、注入差分、実行したゲート、停止理由を
Evidenceへ記録する。検証器が異常を検出できない場合や、入力の比較対象が`unknown`の
場合は、`pass`ではなく停止とする。`GD1-NEG-001`〜`GD1-NEG-008`に対応する
注入fixtureとnegative testは未整備であり、マイルストーン2.1の後続変更で整備する。

### 8.1 機械レーン宣言

マイルストーン3では、基板外形を30 mm × 25 mm、板厚1.6 mm、取付穴4箇所として機械レーンへ
宣言する。部品のXY位置・回転は機械レーンnodeの出所付き属性で保持し、マイルストーン2の
placementやKiCad実行時状態を読み出して補完しない。

今回、基板上の全電気部品を機械レーンへ対応付ける。実体を持たないテストポイントと
取付穴は`body_type=none`、高さ0 mm、bodyなしの根拠付き属性で明示する。

| 部品 | 宣言寸法（mm） | 高さ（mm） | 出所 |
|---|---:|---:|---|
| ESP32-C3-MINI-1 | 13.2 × 16.6 | 2.4 | [Espressif datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-c3-mini-1_datasheet_en.pdf) |
| USB-C receptacle | 9.0 × 7.0 | 3.2 | [KiCad 10.0.5 footprint](https://github.com/KiCad/kicad-footprints/tree/10.0.5/Connector_USB.pretty) |
| AMS1117 SOT-223 | 6.5 × 3.5 | 1.8 | [AMS1117 datasheet](https://www.advanced-monolithic.com/pdf/ds1117.pdf) |
| SHT40 DFN-4 | 1.5 × 1.5 | 0.5 | [Sensirion SHT4x datasheet](https://sensirion.com/resource/datasheet/sht4x) |
| 0603 LED | 1.6 × 0.8 | 0.55 | [LCSC KT-0603R datasheet](https://www.lcsc.com/datasheet/lcsc_datasheet_C2286.pdf) |
| TS-1088 tactile switch ×2 | 6.0 × 6.0 | 4.3 | [TS-1088 datasheet](https://www.lcsc.com/datasheet/lcsc_datasheet_C720477.pdf) |
| 0603 resistor/capacitor | 1.6 × 0.8 | 0.8 | [LCSC 0603 component datasheet](https://www.lcsc.com/datasheet/lcsc_datasheet_C1591.pdf) |
| TestPoint ×7 | 1.5 × 1.5 | 0.0 (`body_type=none`) | [KiCad 10.0.5 TestPoint footprint](https://github.com/KiCad/kicad-footprints/tree/10.0.5/TestPoint.pretty) |
| MountingHole ×4 | 2.2 × 2.2 | 0.0 (`body_type=none`) | [KiCad 10.0.5 MountingHole footprint](https://github.com/KiCad/kicad-footprints/tree/10.0.5/MountingHole.pretty) |

全componentに対応するbody nodeが無い場合、機械レーン抽出は`unknown`として停止する。

筐体CADはshellとlidを別部品として出力する。製造・組立の成果物は次の構成であり、
STEP部品を融合して1ファイルにすることはしない。

| 成果物 | 用途 | 内容 |
|---|---|---|
| `out/gd1-enclosure/enclosure-shell.step` | shell製造部品 | shellソリッドのみ |
| `out/gd1-enclosure/enclosure-lid.step` | lid製造部品 | lidソリッドのみ |
| `out/gd1-enclosure/enclosure-assembly.step` | 組立確認 | shellとlidの統合STEP |
| `out/gd1-enclosure/enclosure.3mf` | 3Dプリント確認 | `gd1-enclosure-shell`と`gd1-enclosure-lid`の2オブジェクト |
| `out/gd1-enclosure/enclosure-artifacts.json` | 構成物provenance | 各成果物の役割・形式・正規化SHA-256 |

部品別STEPは独立再読込でソリッド数、体積、bboxを確認し、統合STEPとの差異も検証する。
Evidenceのenvelopeは部品別STEP、統合STEP、3MF、構成物manifestをすべてhash対象に含める。
ねじ、ボス、スナップ等の新しい締結機構はこの出力分割では追加しない。

## 9. FWの範囲とEvidence

### 9.1 FW範囲

FWはESP-IDFを採用し、ESP-IDFのバージョンを固定する。固定バージョンは未決であり、
環境プローブで実際の版、ツールチェーン、git commitを記録してからマイルストーン5のfixtureへ
固定する。

機能範囲は最小限とする。

- LEDを1 Hzで点滅する。
- SHT40から温度・湿度を読み取る。
- USB-Serial-JTAG経由のシリアルログへ一定周期で温湿度を出力する。
- ピン割当、ペリフェラル設定、ログ経路を設計グラフから投影する。

独自コンパイラ、独自シミュレータ、仮想実機を実測の代替にする仕組みは作らない。
仮想実機はRenodeを一次候補とし、そのログは仮想検証Evidenceとして実測Evidenceと
明確に区別する。

### 9.2 Evidence

実機Evidenceは次の4件を個別に記録する。

1. ESP-IDFの固定版でビルドが成功したこと。
2. ESP32-C3-MINI-1-N4への書き込みが成功したこと。
3. LEDが点灯・1 Hzで点滅したこと。
4. シリアルログに妥当な温度・湿度値が一定周期で出たこと。

各Evidenceには、ツール名・版、入力hash、出力hash、実行条件、生成時刻、対象設計
グラフrevision、実測または仮想の分類を付ける。ビルド成功やログ文字列の存在だけでは
実機Evidenceとしない。仮想実機ログは仮想検証Evidenceとして別分類する。

## 10. 総発注額の構成

総発注額は、基板、部品、実装、送料、税を含める。[`roadmap.md`](roadmap.md)の
マイルストーン7（発注前最終ゲートと自働発注）では、
筐体および機械部品を含むリポジトリ共通の総発注額定義も適用する。

現時点では見積を取得していないため、次の全項目を`unknown`とする。

| 項目 | 状態 | 確定方法 |
|---|---|---|
| 基板製造費 | `unknown` | マイルストーン7の見積dry-run |
| 部品費 | `unknown` | 確認時点の部品価格を用いた見積dry-run |
| 実装費 | `unknown` | JLCPCBAの実装見積 |
| 送料 | `unknown` | 配送先・納期条件を含む見積 |
| 税 | `unknown` | 配送先と取引条件を含む見積 |
| 総額 | `unknown` | 上記を合算するマイルストーン7の発注前最終ゲート |

部品表の単価は在庫検索時点の一次確認値であり、発注見積の代わりにはならない。価格、
在庫、納期、実装可否が期限切れまたは未確認の場合、発注へ進めない。

## 11. 未決事項

- 外形のおよそ30 × 25 mmを確定寸法、許容差、角R、取付穴位置へ落とすこと。
- ESP-IDFの固定バージョンとツールチェーンの固定方法。
- ECAD形式版の更新挙動、派生状態再計算、variant／DNP出力、検査レポートの機械可読形式、
  ライブラリ参照解決、面付け経路はマイルストーン番号に紐づかない事前の一次確認で扱う。
- テストポイントを単純なパッド、プローブ用ランド、または別の実測治具へするか。
- ESP32-C3モジュール認証の証明書・認証番号・出所URLを設計グラフへ添付すること。
- アンテナキープアウトの寸法と、Espressifのモジュール設計ガイドの対象版。
- USB-Cレセプタクルのフットプリントと16P各端子の投影・再読込確認。
- SHT40の電源条件、I2C速度、ログ周期、妥当な温湿度範囲のfixture値。
- LEDの極性、実装向き、必要な点灯電流の実測値。
- AMS1117-3.3の熱計算、入力電圧範囲、実際の最大負荷電流。
- 実機製造・書き込み・LED点滅・温湿度ログのEvidence取得日と測定条件。

## 12. GD1計画3: シルクの宣言・探索・独立測定

計画3では、F.SilkSを機能ラベル専用とし、`RESET`（SW1）、`BOOT`（SW2）、
`D1`、`USB`（J1）だけを表面へ投影した。`DEV BOARD`、グラフIDとrevisionから導出した
基板品番、VibeBB独自ベクターロゴは、機能ラベルとの責務を分離するためB.SilkSへ置いた。
Bluetoothの語・ロゴ・ライセンス文言は使用していない。

シルク要素は`mechanical.silk_text`または`mechanical.silk_graphic`としてグラフへ宣言し、
KiCadのboard-level `gr_text` / `gr_poly`へ投影する。基板品番は
`golden-design-1-r1`としてグラフIDとrevisionから導出し、コード側へ文字列を複製していない。
ロゴはグラフ宣言のpolygonをそのままベクター投影し、bitmapは使用していない。

### 12.1 決定論的候補探索

機能ラベルは対象footprintの配置とpad形状を初回のシルクなし投影から読み取り、
グラフ宣言の探索順
`top,bottom,right,left,top_right,bottom_right,bottom_left,top_left`と、
宣言された刻み`0.25 mm`、上限`4.0 mm`で候補を生成した。候補は順序を固定し、
初回投影で利用できるpad、mask開口、既存／固定シルク、同じ面のbody/courtyard、
基板外形、最近傍部品帰属、および保守的なテキスト外形を満たすものだけを採用する。
最終判定は引き続き塗り後Gerberの独立測定が行う。候補の棄却理由と
採用座標は`fab-package.json`の`silkscreen.placement_evidence`へ保存し、未解決の
機能ラベルを裏面へ移す経路は持たない。

裏面のbranding/識別情報は、表面の機能ラベル探索で記録されたpad/mask混雑を根拠に
グラフ宣言位置を採用した。表面へ置けなかった根拠は、生成物上の代表的なpad/mask
干渉bboxを含むresolver Evidenceへ記録する。なお、機能ラベルが1つでも候補を持たない
場合はfail-closedで停止する。

### 12.2 独立Gerber測定

出力`out/gd1-plan3-rotation-final/`では、Gerberを`sexpdata`と`gerbonara`で独立再読込し、
F.Silkscreen/B.Silkscreen、F.Mask/B.Mask、Edge.Cutsを対象に、Line/Arc/Region/Flashの
幾何を測定した。recognized object countは568（Arc 14、Line 552、Region 2）であり、
未知オブジェクト、未対応aperture、parse失敗は合格扱いしない。

文字の実測高さは宣言回転角を逆回転したテキスト局所座標系で測定した。したがって、
`RESET`の軸平行bbox高さ5.2911−0.4982=4.7929 mmを文字高とは扱わず、
局所座標の高さ1.6500 mmを記録する。表の高さは
`宣言height → 局所座標実測height`、線幅の順である。

| 要素 | layer | 宣言位置 mm | 宣言高さ → 実測高さ mm | 実測線幅 mm | 実測インク面積 mm² |
|---|---|---|---|---:|---:|
| RESET | F.SilkS | (24.55, 2.5375) | 1.5000 → 1.6500 | 0.15 | 1.83185 |
| BOOT | F.SilkS | (6.30, 4.7875) | 1.5000 → 1.6500 | 0.15 | 1.57470 |
| D1 | F.SilkS | (17.6725, 12.78) | 1.5000 → 1.6500 | 0.15 | 1.07539 |
| USB | F.SilkS | (25.9325, 19.79) | 1.5000 → 1.6500 | 0.15 | 1.39271 |
| DEV BOARD | B.SilkS | (25.0, 1.0) | 1.0000 → 1.1500 | 0.15 | 2.44104 |
| golden-design-1-r1 | B.SilkS | (15.0, 24.0) | 1.0000 → 1.4614 | 0.15 | 3.21779 |
| VibeBB vector logo | B.SilkS | polygon宣言 | — | 0.15 | 1.54045 |

軸平行の実測bboxは、RESET `(23.6611, 0.4982, 25.3111, 5.2911)`、
BOOT `(4.1893, 3.8986, 7.8393, 5.5486)`、D1
`(16.4904, 11.8911, 18.9261, 13.5411)`、USB
`(24.1075, 18.9011, 27.8289, 20.5511)`、DEV BOARD
`(21.9488, 0.3798, 28.0988, 1.5298)`、基板品番
`(9.4012, 23.3798, 20.1226, 24.8632)`である。これらは位置・インク存在・
クリアランス確認用であり、回転テキストの文字高ゲートには使用しない。

Fab capabilityは最小文字高`1.0 mm`、最小線幅`0.15 mm`である。測定結果は全要素で
この値以上で、pad-to-silk重なり`0`、mask開口-to-silk重なり`0`、板外overflow`0`で
あった。ロゴもRegion/Lineから面積と最小線幅を独立測定した。

最終ゲートは、宣言位置近傍の実インク面積が正であること、実測高さ・線幅がcapability
以上であること、実形状のpad/mask/Edge.Cutsとの干渉がないことを同時に要求する。
bboxは候補の予選に限り、footprint body bboxも候補を保守的に絞るためだけに使う。
最終的な合否はGerberのstroke、arc、flash、regionと、実形状のpad/mask/Edge.Cuts
との測定で判定する。body bboxを最終測定の代用にはしない。

最終探索のplacement evidenceでは、機能ラベルをすべて決定論的に解決した。
RESETは`(24.55, 2.5375)` mmで408候補、BOOTは`(6.30, 4.7875)` mmで508候補、
D1は`(17.6725, 12.78)` mmで1485候補、USBは`(25.9325, 19.79)` mmで1365候補を
棄却してから、各々最初の合格候補を採用した。棄却理由はboard-edge overflow、
pad overlap、およびfootprint body bboxによる保守的な候補除外であり、採用後は
独立Gerber測定で実形状のpad/mask重なり0を再確認した。

SW1の実配置中心は`(24.05, 9.05)` mm、回転は90°である。RESETの採用位置
`(24.55, 2.5375)` mmは、SW1中心から`(+0.50, -6.5125)` mmの上側候補であり、
回転を考慮した局所座標測定でも宣言高さ1.5 mmに対して実測1.65 mmとなる。

### 12.3a SVG由来の裏面アート

裏面アートは、グラフへハンドコードの近似polygonを記録せず、固定したSVG資材から
決定論的に生成する。`assets/vibebb-silkscreen.svg`は`40 × 18 mm`を
scale `0.4`で`7.2 × 16.0 mm`へ縮小し、90°回転、中心`(21.9, 8.3)` mmへ配置する。
`assets/qr-repository-silkscreen.svg`は`36 × 36 mm`を
scale `0.375`で`13.5 × 13.5 mm`へ縮小し、中心`(11.05, 7.05)` mmへ配置する。グラフには相対source path、source
SHA-256、viewBox、縮尺、配置後寸法と、塗り・複数輪郭・`evenodd`穴を含む
`graphic_parts`を保存する。SVG内の`id="board-preview"`グループは変換しない。

両資材は`B.SilkS`であり、裏面テキストの`justify mirror`とは別に、基板中心を基準に
X座標を反転して物理面での向きを保つ。投影はDesign Graphから生成し、Region/Lineを
含むGerberを独立測定する。スケール後のロゴ最小ストロークは`0.16 mm`であり、
profile最小幅`0.15 mm`未満のストロークはクランプせずfail-closedとする。QRは
version 5の37 moduleと4-module quiet zoneを保持する。source cell pitchは`0.8 mm`、
scale後の期待projected cell pitchは`0.3 mm`（`0.8 × 0.375`）、報告上の
data-module基準寸法は`13.5 / 37 = 0.364864... mm`である。塗り図形に輪郭strokeは
付けず、投影Gerberの実ジオメトリから最小印刷幅と最小未印刷gapを独立に測定する。
現行投影のQR実測値は最小印刷幅`0.3 mm`、最小未印刷gap`0.3 mm`であり、期待値を
測定値として代用しない。QRはsource SVGのSHA-256一致、セル単位のmodule行列、
expected/projected pitch、quiet zoneをGerberから検証し、1セルでも不一致なら
fail-closedとする。白いシルク下地と素地に残すdata moduleの極性反転は意図した仕様
であり、将来反転しない。

採用矩形はQR`[4.3, 0.3, 17.8, 13.8]` mm、VibeBBロゴ
`[18.3, 0.3, 25.5, 16.3]` mmである。両者の正立を優先し、pad、mask開口、
既存シルク、裏面既存文字、板端マージン、要素間ギャップを一切緩めずにresolverと
Gerber独立測定で検証する。合格後の微小な平行移動だけを許容し、サイズ変更は
設計判断なしに行わない。

### 12.3 グラフ意味差分と再生成

JSON parse後にnode ID、kind、attrs、depends_on、edgesを比較した。計画3親コミットの
グラフ（215 nodes）から今回のグラフ（222 nodes）への差分は、シルク7 nodeの追加、
既存nodeの削除なし、既存component 19 nodeのCPL Evidence属性更新、edge同一である。
追加された7 nodeはすべて`mechanical.silk_text`または
`mechanical.silk_graphic`である。

既存19 nodeの差分は、シルク候補探索による非決定性ではない。`build_gd1_fixture.py`
へ計画3作業中に追加したCPL Evidenceの決定論的宣言を、グラフ再生成時に反映した結果で
ある。対象は`comp.c1`〜`comp.c6`、`comp.r1`〜`comp.r6`、`comp.sw1`、`comp.sw2`、
`comp.d1`、`comp.j1`、`comp.u1`〜`comp.u3`で、主な変更は固定revision/sourceを持つ
`cpl_rotation_*` Evidence、J1/U1の`cpl_position_*` Evidence、J1の幾何例外source、
U3の露出pad理由である。生成時刻に依存する値ではなく、同じ入力から同じ値を出す
宣言更新であり、シルク追加の幾何的必然ではない。したがって、キー順変更だけの
差分や無関係なランダム性としては扱っていない。

### 12.4 PNGレンダリング

KiCad 10.0.5の`kicad-cli pcb render`で、銅、pad、Edge.Cuts、実装部品を含む
上面・下面をレンダリングした。画像はEvidence確認用であり、コミット対象外である。

- F.SilkSを含む上面: `out/gd1-plan3-rotation-final/fab/gd1-top.png`
- B.SilkSを含む下面: `out/gd1-plan3-rotation-final/fab/gd1-bottom.png`

### 12.5 拡張探索後の可読性ゲート結果（計画4入力）

計画3の最終探索では、機能ラベルをF.SilkSに限定したまま、グラフ宣言の
回転集合`[0, 90, 180, 270]`、探索上限`8.0 mm`、刻み`0.25 mm`を使用した。候補は
参照部品中心からの距離が最小のものを選び、同点は宣言探索順、回転順、
courtyard重なり面積の順で決定した。pad、mask開口、板外／宣言板端マージン、body、
courtyard、既存footprintシルク、固定シルク、最近傍部品帰属はhard gateである。
D1/USBも参照部品付きの機能ラベルとして同じ探索対象に含め、固定座標を合格根拠に
しない。

宣言した候補探索は全機能ラベルについて候補を返したが、Gerber独立測定の最終
ゲートで合格にはならなかった。fail-closedの最終測定値は次のとおりである。

| ゲート | 実測値 | 判定 |
|---|---:|---|
| pad-to-silk重なり | 31 | fail |
| mask開口-to-silk重なり | 31 | fail |
| Edge.Cuts外形はみ出し | 0 | pass |
| 宣言板端マージン違反 | 0 | pass |
| body重なり | 0 | pass |
| courtyard重なり | 10 | Evidenceのみ |
| 既存footprintシルク重なり | 29 | fail |
| 最近傍部品帰属不一致 | 5 | fail |

代表的なpad/mask干渉は、USB候補付近のインク
`[22.982914, 20.893571, 23.204342, 21.257857]`とpad
`[22.88, 20.13, 23.68, 21.08]`、および
`[18.915477, 12.698866, 19.827382, 12.848866]`とmask開口
`[19.05, 12.55, 20.55, 14.05]`である。既存footprintシルク重なりは
29件で、今回のhard gateにより見逃さない。RESETを含む全候補の棄却内訳は、
次のようにEvidenceへ記録した。

| 要素 | 採用候補（位置、回転） | 棄却候補 | body | pad | 板端 |
|---|---|---:|---:|---:|---:|
| RESET | `(24.8, 3.2125)`, 90° | 33278 | 13180 | 3450 | 16648 |
| BOOT | `(5.3, 3.6625)`, 90° | 33268 | 13329 | 1283 | 18656 |
| D1 | `(8.9625, 12.78)`, 90° | 33005 | 25829 | 6591 | 585 |
| USB | `(23.1575, 22.79)`, 90° | 33202 | 10584 | 7142 | 15476 |

採用候補は最終Gerberインクとの対応で再測定されるため、候補Resolverの
保守的なbbox判定だけを合格根拠にはしない。今回の最終状態は
`out/gd1-plan3-final-failclosed2/`に生成し、silkゲートで停止した。工程1〜7
（投影、ERC、routing、DRC、Gerber生成、独立reload）までは完走し、DRCは
`0 errors / 0 unconnected`、ERCは`0 errors`、DFMは`0 findings`だったが、
silkの未達により全体はfail-closedである。

PNGは数値ゲートと独立した目視Evidenceとして再生成した。

- F.SilkSを含む上面: `out/gd1-plan3-final-failclosed2/fab/gd1-top.png`
- B.SilkSを含む下面: `out/gd1-plan3-final-failclosed2/fab/gd1-bottom.png`

計画4では、RESET周辺のSW1、H2、C6、TP5/TP6および周辺既存footprintシルクを
再配置または基板外形変更の対象として検討する。現行探索で空きが残る領域は、
RESETではSW1上側の板端までの帯、BOOTではSW2周辺の上側／左側、D1ではD1の
左側、USBではJ1下側である。ただしUSB下側にはR5のpadと既存シルクがあり、
最終的な空きとしては未確定である。courtyardは探索優先度にのみ使い、物理占有
の根拠にはしていない。

上記の計画3失敗値は過去の探索入力に対する履歴Evidenceである。現行fixtureでは、
四方向回転、mask開口、既存／固定シルク、同じ面のbody/courtyard、最近傍部品帰属を
候補段階で検査し、D1/USBも固定座標なしで探索する。現行resolverは
`status=measured_pass`となり、最終配置は次のとおりである。

| 要素 | layer | 位置 mm | 回転 | 参照部品までの距離 mm |
|---|---|---:|---:|---:|
| RST | F.SilkS | `(26.325, 5.4)` | 0° | SW1: 0.120181 |
| BOOT | F.SilkS | `(2.3, 5.15)` | 0° | SW2: 0.370181 |
| D1 | F.SilkS | `(9.1, 12.4)` | 0° | D1: 0.339286 |
| USB | F.SilkS | `(8.075, 23.9)` | 0° | J1: 0.220477 |
| DEV BOARD | B.SilkS | `(24.925, 16.9614905)` | 0° | — |
| golden-design-1-r1 | B.SilkS | `(8.95, 15.305683004)` | 0° | — |

現行context測定では、上記6文字列のbody/courtyard重なりはすべて`0`であり、
resolverの最終状態は候補生成だけでなく投影後の測定でも合格している。なお、
最終製造受入れは引き続きauthoritative projection、独立reload、Gerber測定の
各ゲートで判定する。
この座標表とresolverの最終statusはpinning testで固定する。
