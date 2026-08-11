# 外部ツール能力プローブ

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
| CAD kernel（build123d/OCP） | 在 | `build123d 0.11.1` / `cadquery-ocp 7.9.3.1.1` | Phase 3測定。Python distributionを固定版で導入。箱のSTEP/3MF出力を2回実測し、raw hashは不一致、正規化後hashは一致 |
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
- 同じ箱をbuild123dの`Mesher`（`lib3mf 2.5.0`経由）で3MFへ2回出力した。ZIP entry timestampは
  両方とも`1980-01-01 00:00:00`だったが、`3D/3dmodel.model`の`p:UUID`（object、component、
  build、item）が実行ごとに変わった。全`p:UUID`を固定UUIDへ置換し、全ZIP entry timestampを
  `1980-01-01 00:00:00`へ固定してからhashを計算する。
- 実測結果: STEP raw hashは
  `ea300b1cd8129ad190b7f6bf024bc47e6183d92cdb97a5b03a896e64ac451230` /
  `5fcd45ec54242d0eb33f586e5c0e6a63a7987d2115017ff132286c5d78300745`、
  正規化後は両方`d89aeb4b2de9015eb079b6e697318eadbd9c3943a5d2b8c4978e028f28bbc237`となった。
  3MF raw hashは
  `2c1c8cde9d8ece9acc1fb32d2e17359318fdf3d5545304746293481e229d8168` /
  `fe398ca65ddf779dea49fcd2430f1699ad84b660d6ba599e8c5b4d05f436503e`、
  正規化後は両方`14715d034c23713b611be563f72363f2204f28069151f6d3a2241cb0fce5db2f`となった。

### 非決定性の生の差分抜粋

STEP:

```text
-FILE_NAME('Open CASCADE Shape Model','2026-08-11T12:04:53',('Author'),(
+FILE_NAME('Open CASCADE Shape Model','2026-08-11T12:04:54',('Author'),(
```

3MF（`3D/3dmodel.model`）:

```text
-<object id="1" partnumber="box" type="model" p:UUID="5546ce36-f6cd-4b76-a315-d4c00d782f39">
+<object id="1" partnumber="box" type="model" p:UUID="94decefe-3263-45a3-bcba-7475597c3582">
-<object id="2" type="model" p:UUID="9e5339f6-9981-4114-9890-8d8b42d7daaa">
+<object id="2" type="model" p:UUID="f0d9a08f-abea-4734-9476-9371161aecec">
-<component objectid="1" p:UUID="d3d90cae-5593-4cd5-a84f-ed60dd710e4f"/>
+<component objectid="1" p:UUID="b627e4fb-b586-4134-82a6-3af16e1037cf"/>
-<build p:UUID="965b5f80-3a22-46a6-ca8b-324cf648fe44">
-<item objectid="1" p:UUID="fec69751-2ad9-41d7-c53b-64b23927dd49"/>
+<build p:UUID="f268a8e5-4443-4c47-8375-84df115ab8e2">
+<item objectid="1" p:UUID="c1bea829-93a6-479c-b5d9-eac7840a2300"/>
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
