/acd:vibebb-loop

以下の自然文要件から新規設計を起こし、VibeBB loopを最後まで実行してください。GD1（golden-design-1）や既存fixture（mini-blink-dongle等）をコピーせず、この要件からspecとfixtureを新規に生成してください。

## 製品要件: DUAL BEACON TAG
- 用途: 机上に置く小型の状態表示タグ。USB Type-Cバスパワー（5V）で動作し、電池は搭載しない。
- MCU: ESP32-C3-MINI-1（内蔵アンテナ、アンテナkeepoutを確保）。3.3Vは単一LDOで生成。
- 表示: LEDを2個（緑1個、橙1個）。FWは緑と橙を500ms周期で交互に点滅させる（緑ON/橙OFF → 緑OFF/橙ON）。
- 入力: ユーザーボタン1個（GPIO入力、押下でLEDの点滅を一時停止／再開）。BOOT/ENの起動条件はESP32-C3のstrapping規則に従う。
- 拡張: 外部センサ接続用のI2Cヘッダ（4ピン: 3V3, GND, SDA, SCL）を1個。SDA/SCLには4.7kΩのプルアップを実装する。
- 基板: 2層FR-4、1.6mm、1oz、HASL、外形30mm×22mm、M2取付穴2個。製造はJLCPCBの2層FR-4 1oz能力に収める。
- 筐体: 基板を収める簡易筐体。USB-Cコネクタ開口、2個のLED窓、ボタン開口、I2Cヘッダ開口を設ける。
- FW: ESP-IDF（ESP32-C3）。起動時にgraph_id由来のboot logを出し、QEMU仮想実行で点滅ロジックの動作を確認する。
- graph_id は dual-beacon-tag、revision は r1 とする。

## 進め方の要件
- 設計値（LED電流制限抵抗、プルアップ値、外形など）の採用理由はrationaleとして記録してください。
- 基板・筐体・FWの3 laneすべてを実行し、Evidenceはdigest固定のserver container内で生成してください。host実行のprovisionalな結果を合格として扱わないでください。
- 見積record・発注scopeなどの実発注に関わる入力は作らないでください。order-total段は省略し、pre-order gateの結果はそのまま報告してください。実発注や決済は行いません。
- 途中で停止した場合は、停止した段と原因（fail-closedの理由）を生成物から読み取って報告し、ゲート・閾値・Evidence規則を緩める回避はしないでください。
- 最後に `verify_authoritative_evidence.py` を3 lane必須で実行し、その終了コードと出力、各Evidenceのtarget_revision・status・container digestを報告に含めてください。