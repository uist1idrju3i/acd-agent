# Phase 2 振り返り

> ステータス: Draft  
> 対象: Phase 2実装（PR #21、FW連携と実機LED）  
> 日付: 2026-08-11

[`roadmap.md`](roadmap.md)のPhase 2定義と[`phase1-retrospective.md`](phase1-retrospective.md)の
持ち越し事項に対する実施結果、逸脱、残課題、教訓を記録する。

## 達成事項

| 項目 | 結果 |
| --- | --- |
| FW投影 | 設計グラフの`firmware.pin_assignment`を唯一の出所として、ESP-IDFプロジェクト（生成ヘッダ`acd_pins.h`＋静的アプリコード）を決定論的に投影。再生成はbyte一致 |
| FWビルド | ESP-IDF v6.0.2（版pin、`IDF_PYTHON_ENV_PATH`の専用Python環境経由で起動）。ビルドはtool envelopeで包み、source hash・artifact hashを`fw-package.json`へ記録 |
| ピン整合ゲート | FwPackage投影・グラフのFWレーン・電気レーンのU1パッド（データシートpinのpad→GPIO対応表で解決）の3出自を突き合わせ。欠落・unknown・不一致はfail-closed |
| negative test | LED GPIOの故意ずらし（グラフ側）、パッケージpin改変（投影側）、pad対応表の欠落、buildのunknown hash、仮想ログのboot行・revision・LED遷移・SHT40試行欠落がすべて不合格になる |
| 仮想実機 | QEMU（Espressif fork 9.2.2、`-M esp32c3`）で4MB flash像を`timeout`付き実行し、シリアルログを取得。boot行のtarget revision照合、LED 1Hz両状態遷移、SHT40読み取り試行をゲート化 |
| Evidence分類 | 仮想実行のenvelope `measurement_conditions`へ仮想検証であることを明示し、実機LED測定は`unavailable`・未検証claimとして分離記録 |
| 単一コマンド | `uv run python scripts/run_gd1_fw_pipeline.py --out out/gd1-fw` |
| 再現性 | 同一入力の再実行はenvelope一致でskipし、idf.py／QEMUの副作用が重複しない（2回目は約1秒で完走） |

## 計画からの逸脱

- 仮想実機の一次候補Renode v1.16.1は、能力プローブで同梱CPU／プラットフォーム定義に
  ESP系が0件であることを実測した。仮想検証をでっち上げず、二次保持だったQEMU
  （Espressif fork）へ一次採用を入れ替えた（[`tool-selection.md`](tool-selection.md)、
  [`tool-capability-probes.md`](tool-capability-probes.md)へ反映済み）。
- 実機書き込み・実機LEDは未達である。本環境にはデバッグprobeがなく
  （`probe-rs list`が0件、`/sys/bus/usb/devices/`不在）、実機Evidenceは`unavailable`の
  まま「実機Evidence待ち」として管理する。roadmapの追加到達条件（実機LED点灯）は
  実機が使える環境での持ち越しとする。
- `idf.py`はPATH上の呼び出しだとACDのuv仮想環境のPythonを拾って壊れるため、
  `IDF_PYTHON_ENV_PATH`のIDF専用Python環境から明示起動する方式へ変更した。
  外部ツールの実行環境隔離（Phase 1のKiCad設定コンテキストと同型の教訓）である。
- QEMUは自発終了しないため、`timeout`でwall-clockを固定しexit 124を許容exit code
  として契約化した。ログ内容のゲートは別段（`assert_virtual_log_ok`）で判定する。
- QEMUにはSHT40のデバイスモデルがなく、I2C読み取りは`ESP_ERR_INVALID_RESPONSE`で
  失敗する。仮想ログゲートは「読み取りの試行」を要求し、成功をでっち上げない。
  センサ値の実測はSHT40実装ボードでの実機Evidenceに委ねる。

## Phase 3以降への持ち越し

1. 実機Evidence（probe-rsによる書き込み、実機LED点灯、実機シリアルログ、SHT40実測）。
   実機・probeが使える環境が前提で、Phase 2完了条件の残余として対象revision付きで管理する。
2. OpenHandsによるFW実装経路（現状は静的な参照実装をグラフ投影ヘッダに接続する構成。
   LLMがFWを書く経路でも同じピン整合・ビルド・ログゲートが判定する構造は準備済み）。
3. CAD kernel（build123d/OCP）導入とPhase 3機械レーン。
4. CIでのFWパイプライン実行範囲の決定（ESP-IDF導入はblueprint化済みだが、GitHub
   ActionsでのESP-IDFビルドはキャッシュ戦略が必要）。

## Phase 0〜2横断の見直しと文書への反映

Phase 0〜2を通した振り返りから、次の見直しを各文書へ反映した。

| 見直し | 根拠（Phase 0〜2の実績） | 反映先 |
| --- | --- | --- |
| 一次候補ツールの能力プローブをフェーズ着手時の最初の作業単位とする原則を追加 | Phase 0のCAD kernel不在検出、Phase 1のkicad-cli/freerouting版更新、Phase 2のRenode不採用がいずれも早期プローブで低コストに確定した | [`roadmap.md`](roadmap.md)の原則 |
| 仮想実機の一次採用をRenodeからQEMU（Espressif fork）へ入れ替え | Renode v1.16.1にESP32-C3モデルが不在（実測） | [`tool-selection.md`](tool-selection.md)、[`roadmap.md`](roadmap.md)のPhase 2行、[`tool-capability-probes.md`](tool-capability-probes.md) |
| 実機Evidence待ちの最初の適用例としてPhase 2実機LEDを明記 | デバッグprobe不在環境で実機Evidenceが取得できず、仮想検証で代替しない原則を運用で確認した | [`roadmap.md`](roadmap.md)の実機Evidence待ち節・未決事項 |
| 外部ツールは版だけでなく実行環境（設定コンテキスト・Python環境・起動経路）ごとpinする | Phase 1のKiCad project設定隣接配置、Phase 2の`IDF_PYTHON_ENV_PATH`明示起動で同型の欠陥を2度検出した | 本書教訓、[`phase1-retrospective.md`](phase1-retrospective.md) |
| FWパイプラインのCI実行範囲を未決事項として明示 | ESP-IDFビルドはローカルで約1分（初回）だがCIにはツールチェーンキャッシュが必要 | [`roadmap.md`](roadmap.md)の未決事項 |
| 振り返り文書（phaseN-retrospective）を文書索引へ組み込み、次フェーズ前提の確認起点とする | Phase 1→2の持ち越し確認が振り返り文書起点で機能した | [`README.md`](README.md)（docs索引） |

設計面では、Phase 0で確定した契約（fw-package schema、tool envelope、Evidence分類）が
Phase 2でそのまま使えており、schema後付けによるEvidence失効は発生していない。
「投影は正へ逆流させない」「AIは提案し決定論的ゲートが判定する」の不変条件も
3フェーズを通して構造の変更なしに維持できているため、アーキテクチャの見直しは不要と
判断した。横断検証要件#1（判定の両辺は別の出自から取る）は、Phase 2のピン整合ゲートで
データシート由来のpad→GPIO対応表という第三の出自を導入する形で強化した。

## 教訓

- 一次候補ツールの能力プローブは、フェーズ着手時の最初の作業単位に置くべきである。
  Renodeの不採用が早期に確定したため、QEMUへの切り替えコストは小さかった。
- ピン整合ゲートは「投影と生成器の一致」だけでは自己証明になる。電気レーンの
  パッド接続とデータシート由来のpad→GPIO対応表という独立出自を突き合わせて
  初めて、グラフ自体の誤りも検出対象になる（横断検証要件#1の適用例）。
- 終了しない外部プロセス（エミュレータ）のenvelope化は「wall-clock固定＋許容exit
  code＋ログ内容の別段ゲート」で決定論と両立できる。
- 実行環境（Python環境、PATH）はツールの一部である。版のpinだけでなく起動経路の
  pinも契約に含めないと、ホスト環境の変化で結果が変わる。
