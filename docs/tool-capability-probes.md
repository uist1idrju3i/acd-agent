# 外部ツール能力プローブ（Phase 0）

> ステータス: Draft
> 測定日: 2026-08-11

プローブ実装は`packages/acd-tools`、実行は`uv run python scripts/probe_tools.py`。
不在・版不明は`unknown`として構造化記録し、成功扱いしない（fail-closed）。
能力プローブ候補の背景は[`docs/ecad-domain-notes.md`](ecad-domain-notes.md)を参照。

## 本環境での測定結果

| ツール | 検出 | 版 | 備考 |
| --- | --- | --- | --- |
| kicad-cli | 在 | `10.0.5` | ppa:kicad/kicad-10.0-releases、`/usr/bin/kicad-cli`（GitLab tag最新の10.0.5と一致） |
| freerouting | 在 | `2.3.0` | jar（OpenJDK 25）、GitHub releases最新のv2.3.0、`--version`は版バナー出力後にexit 1（プローブは許容） |
| CAD kernel（build123d/OCP） | 不在 | `unknown` | Python distribution未インストール（Phase 3で導入） |
| ESP-IDF | 在 | `v6.0.2` | GitHub releases最新のv6.0.2、`/home/ubuntu/tools/esp-idf`、`idf.py`はIDF専用Python環境（`IDF_PYTHON_ENV_PATH`）経由で起動 |
| qemu-system-riscv32（Espressif fork） | 在 | `9.2.2 (esp_develop_9.2.2_20250817)` | ESP-IDF tools同梱、`-M esp32c3`対応。仮想実機の実行系として採用（下記Renode注記参照） |
| Renode | 在（ESP32-C3非対応） | `1.16.1` | portable版を実測プローブ。同梱CPU/プラットフォーム定義にESP系が0件のためESP32-C3の仮想実機として使用不可。仮想実行はroadmapの二次候補QEMUで実施 |
| probe-rs | 在（実機プローブ不在） | `0.32.0` | `/usr/local/bin/probe-rs`。`probe-rs list`はデバッグプローブ0件（本VMは`/sys/bus/usb/devices/`不在）。実機書き込み・実機LED/ログEvidenceは`unavailable`のまま |

CAD kernelが`unknown`である間、CAD kernelを要求するゲートは合格しない。
Renodeは一次候補だったが、実測でESP32-C3モデル不在を確認したため、Phase 2の
仮想実機はQEMU（Espressif fork）を採用した。仮想実行のEvidenceは仮想検証として
明示分類し、実機測定Evidenceの代替にしない。
freeroutingの「版バナー出力＋非ゼロexit」は実測した仕様として
`probe_freerouting()`に正規化規則を記録した。

## 正規化規則（版が確認でき次第、実測で確定する）

- 版はsemver部分（`X.Y.Z`）のみを比較に使い、ビルドメタデータは`detail`に保持する。
- 実行は隔離した設定ディレクトリで行い、ユーザー設定の影響を排除する。
- 同一入力・同一版での出力hash差（タイムスタンプ埋め込み等）は非決定性として
  記録し、正規化（該当フィールドの除去）後のhashをEvidenceに使う。

## Phase 1前に実測すべき能力プローブ候補

以下は[`docs/ecad-domain-notes.md`](ecad-domain-notes.md)の候補一覧の転記であり、
kicad-cli等が利用可能な環境で実測し、結果をEvidence（版、形式版、設定hash、
入力hash、出力hash、実行環境、測定条件）として記録する。

- 派生状態（ratsnest等）の再計算の有無と契機
- 原点・単位・軸の既定と設定依存性
- ライブラリ参照解決の規則と失敗モード
- variant／DNPの表現と投影への影響
- 面付けの表現
- 内部接続ピンの扱い
- ルール重大度・除外（waiver相当）の機械可読性
- レポートの機械可読形式（JSON等)の有無
- ファイル形式版の更新タイミング
- 設定ディレクトリの隔離可否
- 描画依存機能（画像出力等）のheadless動作
- plugin／backend互換性
- simulationのpin/node対応
- ファイルロック検出とハンドル解放の確認方法
