# レビュー: examples/sensor-node-20260820（成果物・設計入力・会話履歴）

対象: v0.0.1 に同梱の実行例一式（fixture / board / enclosure / firmware / conversation / report）

## 1. 総合評価

設計入力と成果物の整合性・トレーサビリティは高品質。ゲート結果・Evidence・rationaleは一貫しており、製造投入ファイル（BOM/CPL/ガーバ）は実用水準。一方、**視覚射影SVGの一部に表示品質の重大な問題**があり、READMEの画像埋め込みがGitHub上で判読不能になる（後述 4.1）。

## 2. 整合性・正しさ（pass）

- **ERC**: violation 0件。**DRC**: error 0件・warning 35件のみ（lib_footprint_issues 30件=Espressifライブラリ抜粋由来、silk_edge_clearance 5件）。unconnected 0、回路図パリティ問題 0。
- **DFM**: status=pass、findings 0件。配線幅は全ネット0.15mmでDSNクラス投影と一致、via 24個、GNDプレーン連結成分1（分断なし）。
- **rationale coverage**: 669/669（missing/stale/orphan/unclassified 0）— board・enclosure両laneでgraph_id/revision一致。
- **BOM/CPL**: 13行のBOM全行にLCSC部品番号あり。設計意図と一致（CC=5.1kΩ×2、I2Cプルアップ4.7kΩ×2、EN=10k、LED=1k、SHT40 DFN-4、ESP32-C3-MINI-1、AMS1117）。CPLは19部品全てTop、回転値も整然。
- **FWとgraphのピン整合**: `acd_pins.h`（LED=7, SDA=4, SCL=5, UART=21/20, BOOT=9, USB=18/19, SHT40=0x44）が設計graphと一致。QEMUログでLEDハートビート動作を確認（SHT40エラーは仮想環境で期待どおり）。
- **Evidence**: electrical/mechanicalともdigest固定container（cc605baf…）でstatus=valid、revision r1一致。

## 3. FWコード品質（良好）

`acd_main.c` は簡潔で妥当。生成ヘッダのみからピンを参照する設計が守られており、エラー処理（ESP_ERROR_CHECK、読み取り失敗時のWARNログ）、SHT40のCRCを除く標準的な変換式も正しい。改善余地: CRC-8検証の省略、I2C外部プルアップ前提（enable_internal_pullup=false）はコメントがあると親切。

## 4. 気になった点・改善案

### 4.1 視覚射影SVGのfont-size欠落（重要）
`gd1-placement.svg` / `gd1-power-tree.svg` / `gd1-system-block.svg` は `<text>` に font-size 指定がなく、viewBox（例: 30×25ユニット）に対して既定16pxの文字が描画され、**ブラウザ/GitHubで文字が図形を覆い判読不能**。README埋め込み画像が壊れて見える。
→ 改善: 射影生成側でviewBoxに対する相対font-size（例: 板寸法の3〜5%）を必ず付与。`gd1-firmware-state/sequence.svg` も同様の相対指定が望ましい。

### 4.2 KiCad系SVGの用紙余白
`gd1-f-cu.svg` / `gd1-b-cu.svg` / `gd1-schematic.svg` はA4/A2用紙全面のプロットで、30×25mmの基板が隅に極小表示される。
→ 改善: kicad-cliのfit-to-board（クロップ）オプションやviewBox後処理の導入。

### 4.3 回路図の可読性
回路図はシンボルをグリッド配置しネットラベルのみで接続（配線なし）。電気的には正しいが人間のレビューには不向き。
→ 改善: 機能ブロック単位の配置と主要配線の描画、または「ラベル接続方式である」旨の注記。

### 4.4 evidence envelopeのexit_code=5
electrical evidenceのenvelopeに `exit_code: 5` が記録されつつ status=valid。kicad-cliのERC/DRC exit code規約（違反件数由来）と思われるが、意味論が文書化されておらず誤解を招く。
→ 改善: envelope仕様にツール別exit_code解釈を明記。

### 4.5 DFMの未実装チェックとCPL基準unknown
DFMは14ルールが `checks_not_implemented`（pad-to-track、slot類、soldermask bridge等）で、CPLの実装基準（position/rotation basis）は「fab側プレビューでの目視確認が必要」のままorder-readiness=ready。fail-closed原則との整合の観点で、readyの定義に「目視確認前提」の明示があるとよい。

### 4.6 既知の命名不整合
出力prefixとevidence subject_nodeが `gd1` 固定（設計はsensor-node）。改善メモ記載済み。graph_idから導出するのが望ましい。

## 5. 会話履歴レビュー（1,288イベント / 08:49–13:00 UTC）

イベント内訳: ActionEvent 240、ObservationEvent 223、HookExecutionEvent 493、UserRejectObservation 17（hookによる遮断=fail-closed動作の実績）、Condensation 3、MessageEvent 7。

### 使用されたツール（SDK ActionEvent 240件の内訳）
- `terminal` 183回（全pipeline実行・検証はスクリプト経由）
- `file_editor` 44回、`task_tracker` 6回、`finish` 5回、`think` 2回

### 使用されなかった登録ツール
- `canvas_ui_control`、`launch_child_conversation`（登録済みだが未使用）

### 使用されたSKILL（KeywordTriggerで活性化）
- `acd:doctor`（コマンド）、`acd-contracts`、`acd-design-rationale`、`acd-firmware-esp32c3`、`acd-cad-determinism-probe`、`acd-placement-search`、`acd-silkscreen-placement`（＋汎用: github、uv、docker）

### 使用されなかったSKILL・コマンド
- `acd-qc-seven-tools`、`acd-reliability-review`、`acd-install-doctor` は活性化されず
- `/acd:gates` コマンドは未使用（言及1回のみ）
- ACDのToolDefinition群（`acd_validate_design_graph`、`acd_run_board_pipeline`、`acd_run_enclosure_pipeline`）は**本会話ではSDKツールとして登録されておらず**、指示書の想定と異なり全て `scripts/*.py` のterminal実行で代替された（結果は同等だが、tool経路の検証機会を逃した）

→ 改善案:
1. QC/信頼性レビュー系SKILLのtriggerキーワードが実運用の語彙とずれている可能性。trigger見直しか、pipeline完了時にレビューSKILLを促す手順をdocsへ追記。
2. ACD ToolDefinitionが会話に登録される条件（plugin設定）を文書化し、doctorで「tool登録有無」を診断項目に追加。
3. hookによる17件の遮断は全て妥当（out/直下への書き込み等）だが、遮断理由の要約がレポートへ自動集計されると振り返りが容易。

## 6. 結論

製造データ・Evidence・トレーサビリティの品質は高く、JLCPCB投入ファイルはそのまま使える状態。最優先の改善は **4.1 視覚射影SVGのfont-size**（README表示が実際に壊れて見える）で、次いで 4.2/4.3 の可読性改善、5 のSKILL trigger/tool登録の見直しを推奨。
