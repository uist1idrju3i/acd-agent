## 最終報告：DUAL BEACON TAG 設計ループ停止状況

### 1. 停止した段と fail-closed の理由・router 診断

**停止段（failed_stage）**: `board-pipeline`  
**失敗理由**: `GateError: router convergence_state='not_converged' (fail-closed)`

**router_diagnostics（L3 観測）**:
- `convergence_state`: `not_converged`
- `final_unrouted`: 3
- `plateau_passes`: 5
- `unrouted_progression`: `[5, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2, 1, 3, 3, 3, 3, 3]`
- `open_nets`: `["+3V3", "GND"]`（実際には 2 ネットの接続不良）

**ルーティング接続詳細（gate-evidence/routing-connectivity.jsonより）**:
- **+3V3**: `status=fail`、未接続 pad は `R4.2`（R4 は I2C SDA プルアップ抵抗）。さらに `C2.1` と `C5.1` 間など unconnected_pad_pairs が 3 件存在。
- **GND**: `status=fail`、未接続 pad は `R6.2`（R6 は I2C SCL プルアップ抵抗）。unconnected_pad_pairs が 1 件存在。

**根本原因（L3 診断）**: `spec.json` における I2C プルアップ抵抗の net 接続に誤りがあります。
- `R4`（SDA プルアップ、10kΩ）: pin1 が `net.i2c_scl`（誤り、本来は `net.i2c_sda`）、pin2 は `net.p3v3`（+3V3）。
- `R6`（SCL プルアップ、10kΩ）: pin1 が `net.cc2`（誤り、本来は `net.i2c_scl`）、pin2 は `net.gnd`（誤り、本来は `net.p3v3`）。
これにより I2C プルアップ回路が全く機能せず、かつ +3V3/GND ネットの接続性検査で fail-closed となっています。

**next_step_action（loop-summary.jsonより）**:
> "Explore declared placement and GPIO candidates from the rejected predicate remediation, then rerun every deterministic stage.; router unrouted plateaued at 3 for 5 passes; broaden candidate axes within declared constraints (outline size, layer count, component spacing/placement) or make the constraint explicit in the design input; do not relax DRC or routing rules"

### 2. `verify_authoritative_evidence.py` の実行結果

実行コマンド：
```bash
uv run python scripts/verify_authoritative_evidence.py \
  --revision-from fixtures/dual-beacon-tag/graph.json \
  --out-root /tmp/out \
  --require-lane electrical --require-lane mechanical --require-lane firmware
```

**終了コード**: `1`

**標準出力**: `FAIL: required lane Evidence missing: electrical`

**各 lane の Evidence 状況**:

| Lane | Evidence ファイル | target_revision | status | container digest | 備考 |
|------|-------------------|-----------------|--------|------------------|------|
| electrical | **なし** | — | — | — | router fail のため DRC gate 未実行で evidence 未生成 |
| mechanical | **なし** | — | — | — | `evidence-mechanical.json` は存在せず。enclosure-pipeline は preflight のみで authoritative evidence 未生成 |
| firmware | `/tmp/out/dual-beacon-tag-fw/evidence-firmware.json` | `r1` | `valid` | `unknown`（provenance 不完全） | 存在するが `container_image_digest: "unknown"` で container provenance が確立されていない |

**重要**: 全 3 lane の authoritative evidence が揃っておらず、特に electrical lane は evidence 自体が存在しません。したがって「合格」「order-ready」の主張はできません。

### 3. 設計入力以外の変更ファイル

**git status --short**:
```
?? .openhands/
?? fixtures/dual-beacon-tag/
```

**git diff --stat**: なし（tracked ファイルへの変更はゼロ）。

設計入力（`fixtures/dual-beacon-tag/` 内の `spec.json`, `graph.json`, `rationale.json`）以外に、**リポジトリのソースコード（`src/`, `scripts/` 等）の変更はありません**。
ホスト上の `/tmp/` に一時的なデバッグ用ファイル（`/tmp/test-fixture/`, `/tmp/current_pcb.kicad_pcb` 等）が存在しますが、これらは git 管理外であり設計入力でもありません。

### 4. 当初製品要件から落ちた・変更した項目

| 当初要件 | 最終的な spec / graph の状況 | 理由・誠実な説明 |
|----------|----------------------------|----------------|
| **筐体: LED窓（2個）、ボタン開口** | `spec.json` の `connector_openings` には **USB-C（J1）と I2C ヘッダ（J2）のみ**が宣言されており、LED 窓とボタン開口が欠落 | spec 作成時の omission。筐体設計で開口を追加すべきだったが、宣言漏れ。 |
| **I2C ヘッダ: SDA/SCL プルアップ 4.7kΩ** | **R4, R6 の net 接続が誤っている**。R4(SDA pull-up) の pin1 が `net.i2c_scl`、R6(SCL pull-up) の pin1 が `net.cc2`、pin2 が `net.gnd`。正しくは R4→SDA/+3V3、R6→SCL/+3V3。 | spec.json の components pads 宣言時の copy/paste ミス。回路図レベルでプルアップが機能しない重大な誤り。 |
| **BOOT/EN の起動条件: ESP32-C3 strapping 規則に従う** | EN (U1 pin 3) は `net.p3v3` にプルアップ（正）。BOOT ボタンは U1 pin 23 に接続。しかし **U1 pin 9 (GPIO0/BOOT** 相当) は `no_connect`。 | GPIO0 の strapping ピンが floating のまま。ESP32-C3-MINI-1 モジュール内部で処理される可能性があるが、明示的な strapping 規則への完全な準拠は不十分。 |
| **FW: I2C 機能の使用** | `graph.json` に `fw.pin.i2c_sda`, `fw.pin.i2c_scl` の pin assignment ノードは存在するが、**firmware sequence に I2C 初期化や通信 step はない**。 | ACD firmware pipeline では capability registry に基づき sequence step を生成。I2C 用の capability が graph/firmware registry に宣言されていないため、FW からは I2C ヘッダにアクセスしない。ハードウェア上のヘッダのみ存在。 |
| **LED 色: 緑1個、橙1個** | **正しく実装**。D1=`KT-0603G`（緑）、D2=`KT-0603A`（橙/Amber）で部品選定済み。 | 部品選定時に色を考慮した。 |
| **FW: 緑・橙 500ms 交互点滅、ボタンで pause/resume** | **正しく graph 宣言済み**。`toggle_led`→D1、`toggle_led2`→D2、`read_button`→SW1。state transition で `boot`→`blink`→`paused`→`blink` を実現。 | firmware capability registry の `led_blink`, `led2_blink`, `button_input` を使用。 |

**以上の通り、電気回路（I2C プルアップの誤接続）と筐体開口の宣言漏れという重大な設計入力の問題があるため、ループは board-pipeline で fail-closed して停止しています。**