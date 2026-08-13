# Golden Design #1

> ステータス: Draft  
> 対象プロファイル: `hobby`  
> 対象マイルストーン: 第1マイルストーン「基板＋FWで実機のLEDが光る」  
> 対象工程: `S1`、`E1`、`E2`、`S2`  
> 部品・在庫確認日時: 2026-08-11 UTC

本書は、Golden Design #1として固定する1枚の基板と、その基板で動作するFWの仕様で
ある。Phase 1（電気レーン最小縦切り）とPhase 2（FW連携と実機LED）のゴールデン
タスクが対象とする実物であり、fixtureの元になる。フェーズの完了条件は
[`roadmap.md`](roadmap.md)を正とし、本書ではこの設計に固有の入力、制約、ゲート、
Evidenceを定める。

本書は回路図、PCBレイアウト、筐体図面を作成するものではない。型付き・バージョン
付き設計グラフへ変換する前の、検証可能な仕様を記述するものである。回路図、基板、
FWパッケージ、製造データは設計グラフからの投影とする。

## 1. 位置づけ

### 1.1 マイルストーンとPhase

Golden Design #1は、第1マイルストーンの具体的な1枚である。Phase 1では本書の部品、
ネット、基板制約からGerber/drillまでを生成し、Phase 2では同じ設計グラフからFW
パッケージを投影して書き込み、実機のLED点滅とSHT40のシリアルログを確認する。

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

### 1.2 プロファイルとfixture

設計プロファイルは`hobby`である。ただし、`hobby`であることは安全境界、ピン整合、
製造可能性、実機Evidenceの省略を意味しない。設計プロファイルによるtailoringの
範囲内で、未知、矛盾、stale Evidenceはfail-closedで停止する。

本設計をfixtureへ固定する際は、少なくとも次を入力としてhash付きで管理する。

- 本書のrevisionと設計グラフrevision
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
| `GD1-REQ-005` | 最大ネット電圧は5 V、最大電流は500 mA未満とする |
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
| `Requirement.intended_use` | `hobby`の許可領域 | 作者自身の試作であり、医療・車載・航空・産業安全ではない |
| 最大ネット電圧 | 5 V | USB-C VBUSのみで、許可閾値の50 V AC / 120 V DC以下 |
| 最大電流 | 500 mA未満 | 承認必須の5 A超または25 W超に該当しない |
| バッテリ・充電 | なし | Li-ion/LiPo充電回路を持たない |
| 動力・光源 | モーター、アクチュエータ、レーザーなし | 赤色LEDは表示用である |
| 無線 | 認証済みESP32-C3モジュール | チップ直載せとアンテナ設計を行わない |

`SB1`の出力は`SafetyBoundaryResult`として記録する。モジュール認証の出所が設計
グラフへ添付されていない場合、その項目は`unknown`として工程`S1`を停止させ、説明だけで
合格させない。

### 3.2 SB2（E1で実行する確定判定）

`SB2`では、工程`E1`で設計グラフの述語により安全境界を確定判定する。次の全述語が
`pass`となり、`S2`へ渡される`SafetyBoundaryResult.status`が`pass`となる状態が
期待値である。

| グラフ述語 | 期待値 |
|---|---|
| `max(Net.voltage_nominal) <= 5 V` | `pass` |
| `max(Net.voltage_nominal) <= 50 V AC / 120 V DC` | `pass` |
| `max(Net.current_max) < 500 mA` | `pass` |
| `Part.certification`がESP32-C3モジュールに存在する | 出所Evidence付きで`pass` |
| `Part.hazard_class`にバッテリ充電器、モーター、アクチュエータ、レーザーがない | `pass` |
| `Requirement.intended_use`が許可領域にある | `pass` |
| 未知の危険区分、影響、認証、電圧、電流がない | `pass`。一つでも`unknown`なら停止 |

この設計は上記の理由から`hobby`プロファイルの許可領域に収まる。ただし、認証出所、
ネット電流の導出、部品の実装可否が設計グラフへ取り込まれていない状態は
`unknown`であり、許可領域とはみなさない。

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

| ゲート | 検出する条件 | 注入すると停止する例 | Evidence |
|---|---|---|---|
| ERC | 未接続、電源入力、駆動競合、ピン方向の電気規則違反 | VBUSとGNDの誤接続、ENの駆動競合 | `kicad-cli` ERC結果、入力hash、版 |
| DRC | クリアランス、未配線、製造形状、穴・銅の規則違反 | 短絡、未配線、能力値未確定 | `kicad-cli` DRC結果、ルール版 |
| アンテナキープアウト | アンテナ直下・周囲の銅箔、GND、部品、シルクの有無 | アンテナ下へGNDベタを追加 | グラフ述語結果、対象revision、形状hash |
| USB CC | CC1/CC2それぞれの5.1 kΩ RdとGND接続 | CC1またはCC2の抵抗を削除 | ネット述語、抵抗MPN、接続hash |
| strapping pin | IO2/IO8/IO9の起動条件を壊す割当・負荷 | LEDをIO8またはIO9へ割当 | ピン述語、FW整合結果 |
| I2C pull-up | SDA/SCLそれぞれの4.7 kΩと電源接続 | SDAまたはSCLのプルアップを削除 | ネット述語、ERC結果 |
| 電源デカップリング | LDOの入力・出力に10 µF＋100 nFがあり、ESP32-C3-MINI-1の3V3ピン直近に100 nFがあること | LDO側またはMCU側のコンデンサを削除・遠ざける | 部品・ネット述語、BOM hash |
| 電源境界 | 5 V VBUS、3.3 V生成、電流・電圧境界 | バッテリ充電回路または5 V超の電源を追加 | `SafetyBoundaryResult` |
| ピン・FW整合 | グラフの`Net`/`Pin`とFWパッケージの一致 | FWだけIO7をIO8へ変更 | 投影hash、整合ゲート結果 |

アンテナキープアウトは通常のDRCだけでは検出できないため、設計グラフの専用述語
として実装する。述語が評価不能な場合は`unknown`で停止し、配置が見た目に正しい
ことを合格根拠にしない。

## 8. negative test

| ID | 注入する変更 | 期待される不合格ゲート |
|---|---|---|
| `GD1-NEG-001` | LEDをIO8またはIO9へ割り当てる | strapping pinゲートとピン・FW整合ゲートが`fail` |
| `GD1-NEG-002` | ESP32-C3アンテナ直下へGNDベタを敷く | アンテナキープアウト述語が`fail` |
| `GD1-NEG-003` | CC1またはCC2の5.1 kΩを削除する | USB CCゲートが`fail` |
| `GD1-NEG-004` | I2C SDAまたはSCLの4.7 kΩを削除する | I2C pull-upゲートが`fail` |
| `GD1-NEG-005` | FWのIO7、IO4、IO5、IO9、IO18、IO19、IO20、IO21のいずれかをグラフと異なる値へ変更する | ピン・FW整合ゲートが`fail` |

## 9. 製造投影と配置

J1にはLibraryOverlayを適用する。公式footprintを直接改変せず、
`overlays/j1-usb-c-annular-ring.json`としてプロジェクトローカルに保持し、
JLCPCBのPTHアニュラリング推奨値を根拠にSH padを`0.20 mm`から`0.25 mm`へ拡大する。
overlayの適用後geometryは、DSN export、routing、最終board、DRC、DFMで共通に使用する。

配置は次の4段を固定順序で実行する。

1. 固定anchor（アンテナmodule、USB receptacle、取付穴）
2. 能動部品（U1、U2、U3）

配置ゲートでは、USBコネクタの本体外形とパッド重心から嵌合側の板端アンカーを導出し、
RFモジュールではfootprint内の単一アンテナkeepoutから板端アンカーを導出する。
独立DFMゲートのcheck IDは`pad-to-board-edge-clearance`、
`undeclared-board-edge-overhang`、`courtyard_board_edge_overhang`であり、
これらは発注能力違反（`capability_violation`）として扱う。CPLの回転基準（fab／LCSC
側の部品基準向き）との照合は未実施であり、KiCad回転角をそのまま出力しているため、
発注先プレビューで人手確認が必要である。
3. 能動部品の電源pinへ接続するデカップリングコンデンサ
4. 残りの部品をcourtyard面積の降順、同面積はrefdes順

第3段のデカップリング対象は設計グラフの`decoupling_target`宣言から導出し、
対象ICの電源padまでの距離を目的関数にする。推測による分類や配置不能時の制約緩和は行わない。

GD1最新実行で生成される製造データは、`out/gd1/fab/`の次のファイルである。

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

生成時の実測は、2層、外形`30.0 × 25.0 mm`、via `22`個、drill object `32`個、
pad `132`個、route wire `191`本、最小track幅`0.15 mm`、silk最小文字高`1.0 mm`、
silk最小stroke幅`0.15 mm`である。J1は`(15.0, 21.35)` mm、U1は`(15.0, 2.9)` mm、
ともに回転`0°`である。DSNの`(via_at_smd off)`とSMD pad周囲の`via_keepout`により、
SMD pad上viaを構造的に禁止している。出所は`out/gd1-fix3/fab/dfm-report.json`、
`out/gd1-fix3/routing-summary.json`、`out/gd1-fix3/fab/fab-package.json`である。
| `GD1-NEG-006` | ライブラリ照合Evidenceを削除する | ライブラリ受入ゲートが`unknown`で停止 |
| `GD1-NEG-007` | 派生状態を再計算せずにDRC結果を採用する | stale判定が`unknown`で停止 |
| `GD1-NEG-008` | 原点、単位、または軸を不明にする | 座標系ゲートが`unknown`で停止 |

各negative testは、注入前の設計グラフrevision、注入差分、実行したゲート、停止理由を
Evidenceへ記録する。検証器が異常を検出できない場合や、入力の比較対象が`unknown`の
場合は、`pass`ではなく停止とする。

### 8.1 機械レーン宣言

Phase 3では、基板外形を30 mm × 25 mm、板厚1.6 mm、取付穴4箇所として機械レーンへ
宣言する。部品のXY位置・回転は機械レーンnodeの出所付き属性で保持し、Phase 1の
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

## 9. FWの範囲とEvidence

### 9.1 FW範囲

FWはESP-IDFを採用し、ESP-IDFのバージョンを固定する。固定バージョンは未決であり、
環境プローブで実際の版、ツールチェーン、対象revisionを記録してからPhase 2のfixtureへ
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

総発注額は、基板、部品、実装、送料、税を含める。Phase 11の発注前最終ゲートでは、
筐体および機械部品を含むリポジトリ共通の総発注額定義も適用する。

現時点では見積を取得していないため、次の全項目を`unknown`とする。

| 項目 | 状態 | 確定方法 |
|---|---|---|
| 基板製造費 | `unknown` | Phase 11の見積dry-run |
| 部品費 | `unknown` | 確認時点の部品価格を用いた見積dry-run |
| 実装費 | `unknown` | JLCPCBAの実装見積 |
| 送料 | `unknown` | 配送先・納期条件を含む見積 |
| 税 | `unknown` | 配送先と取引条件を含む見積 |
| 総額 | `unknown` | 上記を合算するPhase 11の発注前最終ゲート |

部品表の単価は在庫検索時点の一次確認値であり、発注見積の代わりにはならない。価格、
在庫、納期、実装可否が期限切れまたは未確認の場合、発注へ進めない。

## 11. 未決事項

- 外形のおよそ30 × 25 mmを確定寸法、許容差、角R、取付穴位置へ落とすこと。
- ESP-IDFの固定バージョンとツールチェーンの固定方法。
- ECAD形式版の更新挙動、派生状態再計算、variant／DNP出力、検査レポートの機械可読形式、
  ライブラリ参照解決、面付け経路はPhase 0で一次確認する。
- テストポイントを単純なパッド、プローブ用ランド、または別の実測治具へするか。
- ESP32-C3モジュール認証の証明書・認証番号・出所URLを設計グラフへ添付すること。
- アンテナキープアウトの寸法と、Espressifのモジュール設計ガイドの対象版。
- USB-Cレセプタクルのフットプリントと16P各端子の投影・再読込確認。
- SHT40の電源条件、I2C速度、ログ周期、妥当な温湿度範囲のfixture値。
- LEDの極性、実装向き、必要な点灯電流の実測値。
- AMS1117-3.3の熱計算、入力電圧範囲、実際の最大負荷電流。
- 実機製造・書き込み・LED点滅・温湿度ログのEvidence取得日と測定条件。
