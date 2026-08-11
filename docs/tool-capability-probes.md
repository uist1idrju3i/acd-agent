# 外部ツール能力プローブ（Phase 3）

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
| CAD kernel（build123d/OCP） | 在 | `build123d 0.11.1` / `cadquery-ocp 7.9.3.1.1` | Python distributionを固定版で導入。箱のSTEP/3MF出力を2回実測し、raw hashは不一致、正規化後hashは一致 |
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

## 正規化規則（Phase 3実測確定）

- 版は固定したdistribution版を比較に使い、ビルドメタデータは`detail`に保持する。
- 実行は隔離した設定ディレクトリで行い、ユーザー設定の影響を排除する。
- 同一の`build123d 0.11.1`の箱（10 mm x 10 mm x 10 mm）を同一プロセスから2回出力した。
  STEPのraw bytesは一致せず、差分は`FILE_NAME`のtimestampだけだった。
  `FILE_NAME` timestampを`1970-01-01T00:00:00`へ置換してからhashを計算する。
- 同じ箱を`lib3mf`（`lib3mf 2.5.0`）で3MFへ2回出力した。ZIP entry timestampは両方とも
  `1980-01-01 00:00:00`だったが、`3D/3dmodel.model`の`p:UUID`（object、build、item）が
  実行ごとに変わった。全`p:UUID`を固定UUIDへ置換し、全ZIP entry timestampを
  `1980-01-01 00:00:00`へ固定してからhashを計算する。
- 実測結果: STEP raw hashは
  `0af4239debba8de72899ba94edc6939a5b46d86bc02c661223153133b558e0bb` /
  `dd39569c564b3b217c51e45f0d73cfb69cd30394dc53400970e8a77432ec6cd0`、
  正規化後は両方`d89aeb4b2de9015eb079b6e697318eadbd9c3943a5d2b8c4978e028f28bbc237`となった。
  3MF raw hashは
  `d17c8bef943243a51605b797a055bc182966e0c66737fe110a08512eb86cb5c1` /
  `9831ee2881f1b1a757e6eb75def16f91917e1baa71a1020fb99b9458b5e64592`、
  正規化後は両方`892a1e5ab35d48e738d2a5c511d8f7b89cbff306c376ce6b3344fbc5f917041f`となった。

### 非決定性の生の差分抜粋

STEP:

```text
-FILE_NAME('Open CASCADE Shape Model','2026-08-11T11:57:12',('Author'),(
+FILE_NAME('Open CASCADE Shape Model','2026-08-11T11:57:13',('Author'),(
```

3MF（`3D/3dmodel.model`）:

```text
-<object id="1" name="box" type="model" p:UUID="f7b1dbd1-9729-4812-c778-3d169717d92c">
+<object id="1" name="box" type="model" p:UUID="5b541227-408b-421d-cbf4-a412ec840f01">
-<build p:UUID="615bfe6f-a119-4c1f-a278-1befcb61819d">
-<item objectid="1" p:UUID="4ccb0bd8-16fd-4a2a-bdaa-541386602f69"/>
+<build p:UUID="60d97de2-ed24-4c06-9142-a76033dea646">
+<item objectid="1" p:UUID="0221a0d9-c2f1-420b-a9e2-d06b6f50afae"/>
```

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
