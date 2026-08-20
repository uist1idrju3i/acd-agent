# 改善メモ（GD1ベース小規模製品 設計・製造データ生成セッション）

作業中に気づいた点・改善案を随時追記する。最終報告でまとめる。
（このファイルはコミットしない。）

## 環境・接続

- OpenHands Local GUIのAPI（`/api/conversations` 等）はトンネル越しの直接curlでは `{"detail":"Unauthorized"}` になる。GUI経由でしか操作できないため、自動化・スクリプト化した検証がやりにくい。トークン発行手順がdocsにあると便利。
- `/acd:doctor` 結果: 必須チェック全pass。plugin root `/home/openhands/.openhands/plugins/installed/acd`、9 Skills / 6 agents / 2 commands / 7 hooks、Python 3.14.4 / uv 0.12.5、Docker 29.1.3 あり。host `kicad-cli` / `freerouting` は不在（observational only）。→ EDA実行はcontainer経路が前提になる。
- doctor出力に「host EDA不在時に次へ進む推奨経路（locked image + DockerWorkspace）」への誘導リンクがあると迷わない。

## fixture / pipeline

- 設計グラフの再利用: GD1 fixtureから新設計を起こす際、`graph_id`とノードIDのリネーム＋`depends_on`参照の全更新が手作業になる。「fixtureを別graph_idへ複製する」ヘルパー（`acd_clone_design_fixture`等）があると再利用しやすい。
- `run_gd1_pipeline.py` / `run_gd1_enclosure_pipeline.py` は `--fixture` にディレクトリ（graph.json + rationale.json + libraries/ + overlays/）を要求する。新設計ではlibraries/overlaysをGD1からコピーして組み立てる必要があり、この手順が`docs/operations.md`に明記されていない。
- GUIの入力欄はcontenteditableで、自動化ツールからの単純なtypeでは入らないことがある（insert_text経由で解決）。

- 基板・筐体pipelineの出力ファイル名prefixが`gd1`固定（`gd1-gerbers.zip`等）。`--fixture`で別設計（sensor-node）を渡してもgd1名で出力されるため、graph_id由来のprefixにできると混同を防げる。evidenceの`subject_node`も`electrical.board.gd1`にハードコードされており、graph実ノード（board.sensor-node）と不一致になる（ゲート判定には影響しないがprovenanceとしては紛らわしい）。
- container実行（locked image + DockerWorkspace）はresolver→基板→筐体まで一括で問題なく通り、`verify_authoritative_evidence.py`もOK。全ゲートpass。

## FW pipeline（acd-firmware-esp32c3）

- QEMU（Espressif fork 9.2.2）のセットアップに複数回の試行錯誤が必要だった: tarball展開後のPATH設定、`libslirp0`・SDL2系の共有ライブラリ不足を順に解消する必要があり、workspaceランナースクリプトを数回編集して再実行した。QEMU実行に必要なaptパッケージ一覧（libslirp0等）をSkillのSKILL.mdまたは`docs/operations.md`に明記するか、locked server imageに同梱すると再現性が上がる。
- ESP-IDFビルド自体は問題なし（v5.3.1、`acd_gd1_fw.bin` 0x30600 bytes、パーティション81% free）。
- FW成果物のディレクトリ名も`acd_gd1_fw`固定で、基板pipelineと同様graph_id由来にできると混同を防げる。
- ピン整合チェックは全pass（LED=IO7/pad21、SDA=IO4/pad18、SCL=IO5/pad19、BOOT=IO9/pad23、UART TX=IO21/pad31・RX=IO20/pad30、USB D-=IO18/pad26・D+=IO19/pad27）。
- QEMUシリアルログでIO7 LED heartbeat（500ms周期）を確認。SHT40のI2CエラーはQEMUにセンサーモデルが無いための期待動作。QEMU結果は仮想検証であり実測Evidenceの代替ではない。
