# Phase 3 振り返り

> ステータス: Draft  
> 対象: Phase 3実装（PR #23、機械レーン最小縦切り）  
> 日付: 2026-08-11

[`roadmap.md`](roadmap.md)のPhase 3定義と[`phase3-plan.md`](phase3-plan.md)の作業単位
（P3-1〜P3-8）に対する実施結果、逸脱、残課題、教訓を記録する。Phase 4の前提条件は
ここを起点に確認する。

## 達成事項

| 項目 | 結果 |
| --- | --- |
| CAD kernel能力プローブ | build123d 0.11.1／cadquery-ocp 7.9.3.1.1を固定版で導入し、STEP/3MFの非決定性を実測。決定性プローブに失敗したkernelは`version="unknown"`として使用可能扱いにしない |
| 正規化規則 | STEPは`FILE_NAME` timestamp、3MF（build123d `Mesher`経由）は`3D/3dmodel.model`の`p:UUID`だけが実行ごとに変わることを実測し、`acd_core.cad_normalize`を正本とした。規則に合致しない入力は`CadNormalizationError`で停止 |
| 設計グラフ契約 | `mechanical.outline`／`mechanical.component_body`／`mechanical.connector_opening`／`mechanical.enclosure`をschemaとPydanticへ追加し、往復検証を維持 |
| 機械レーン抽出 | `acd_core.mechanical`。属性欠落・単位不明・電気レーンとの不整合はfail-closed。基板上の全`electrical.component`に対応する占有体宣言を要求する |
| CAD投影 | `packages/adapters/acd-adapter-cad`（ボトムシェル＋standoff＋connector開口＋蓋）。STEP/3MFを出力し、判定は持たない |
| 機械ゲート | `acd_runtime.mechanical`。CAD kernel妥当性、干渉、clearance、肉厚を、エクスポート済みSTEPの独立再読込geometryに対して実測判定 |
| 再現性 | CAD生成はsubprocessでないため`acd_core.process.run_in_process`を追加。入力hash・config hash・tool版・正規化後出力hashが一致し出力が健在なら再生成をskip |
| 単一コマンド | `uv run python scripts/run_gd1_enclosure_pipeline.py --out out/gd1-enclosure`。2回実行で正規化後hash一致・2回目skipを実測 |
| negative test | 干渉、肉厚不足（全体）、局所薄肉、CAD kernel不在のいずれでも停止 |
| CI | 外部CLIに依存しないため、本パイプラインをCIのgolden taskとして追加 |

golden fixtureの実測値は、最小肉厚2.0 mm、最小clearance約1.0 mm、最大干渉体積0.0 mm³、
正規化後hash `sha256:30023b5c...`である。

## 計画からの逸脱

- 部品のXY位置・回転はfixtureの宣言値（出所attr付き）とし、Phase 1の決定論的配置を
  実行時に呼ばない構成にした。CIにKiCadが無いこと、および実データのECAD↔MCAD交換
  （`kicad-cli pcb export step`）がroadmap上Phase 4の範囲であることによる。
- 3MF出力は当初lib3mfを直接呼ぶ実装だったが、build123dの`Mesher`経由へ変更し、
  非決定性と正規化後hashを取り直した。後続adapterと同じ経路に揃えるためである。
- 正規化規則は当初`acd-tools`に置いたが、レイヤ依存（adapters → `acd-tools`）により
  adapterから参照できないため`acd-core`へ移した。
- connector開口は`front`面のみ、蓋は平板、部品占有体は直方体近似とした
  （[`phase3-plan.md`](phase3-plan.md)に明記）。
- 本VMには`/usr/share/kicad`のシンボル・フットプリントが無く（`kicad-symbols`／
  `kicad-footprints`が未導入）、`scripts/build_gd1_fixture.py`の通し実行ができなかった。
  そのため機械ノード生成部分だけを取り出し、tracked fixtureとの完全一致をKiCadライブラリ
  なしで検証するテストを追加した。
- CIのGitHub Actions runnerはASCIIロケールであり、`read_text()`の既定encodingでUTF-8の
  fixtureを読むと`UnicodeDecodeError`で落ちた。encodingを明示して修正した。

## 実装レビューで差し戻した設計欠陥

いずれも「自己証明」と「宣言の欠如をskipとして合格に見せる」型であり、横断検証要件
#1・#2に該当する。記録として残す。

| 差し戻した実装 | 問題 | 採用した実装 |
| --- | --- | --- |
| 肉厚を、再読込ソリッドの体積から宣言値（肉厚・standoff・開口寸法）を使って逆算 | 局所的に薄い壁を原理的に検出できず、判定の両辺が同じ出自に寄る。実測値が宣言値と一致する（自己証明の兆候） | 対向する平面faceの`distance_to()`最小値を実測。1面だけを薄くしたSTEPで停止することをnegative testで実証 |
| 内面位置を「外形bbox＋宣言肉厚」で再構成し、bbox同士でclearanceを比較 | 内面が実測でなく宣言値の再構成 | 再読込ソリッドの内面faceと部品占有体の距離を実測 |
| 干渉判定で体積（mm³）を長さtolerance（mm）と比較 | 次元不整合 | `interference_tolerance_mm3`を宣言値として分離 |
| 寸法根拠が見つからない部品を占有体から除外 | 宣言の欠如をskip＝合格に見せる | 全部品の占有体宣言を必須化し、bodyを持たないTestPoint／MountingHoleは`body_type=none`として明示宣言。高さ・寸法は出所URLと取得時点付き |

## 未解決の観測事項

Phase 3の作業中に、fixtureへpin済みのKiCadライブラリのファイルhashが、同一の版表記
（PPA `kicad-symbols`／`kicad-footprints` 10.0.5~ubuntu22.04.1）で再現しないことを
観測した。ライブラリを導入して`scripts/build_gd1_fixture.py`を実行すると、
`symbol_sha256`／`footprint_sha256`だけが差分として現れる。原因は未確定であり、
Phase 3では再生成結果を採用せずfixtureのpinを維持した。版表記だけでは出所が確定せず、
ファイルhashによる検証が停止条件として機能した事例である
（[`adr/ADR-0004-parts-catalog-provenance.md`](adr/ADR-0004-parts-catalog-provenance.md)）。

## Phase 4への持ち越し

1. 実データのECAD↔MCAD交換（`kicad-cli pcb export step`）と、高さ・keepoutの受け渡し。
   Phase 3で宣言値としたXY位置・部品高さを、電気レーンの投影から受け取る経路へ置き換える。
2. 上記ライブラリhash不一致の原因調査と、pin方式（版表記＋ファイルhash）の見直し要否判断。
3. 筐体形状の制約解除（`front`以外の面の開口、平板でない蓋、直方体近似でない占有体）を
   どこまでPhase 4で必要とするかの判断。
4. OCP関連の実測約355 MBがCI初回の`uv sync`に与える影響の継続観測と、CIで常時実行する
   範囲の切り分け（[`roadmap.md`](roadmap.md)の未決事項）。
5. Phase 2から継続中の実機Evidence（probe-rs書き込み、実機LED、実機シリアルログ、
   SHT40実測）は引き続き「実機Evidence待ち」として管理する。

## 教訓

- 「実測」と称する値が宣言値と一致するときは、測定が逆算になっていないかを疑う。
  体積のような集約量からの逆算は、局所欠陥を構造的に見逃す。
- negative testは「判定対象を壊す」ものでなければならない。全体パラメータを変えるだけの
  テストは、逆算実装でも通ってしまうため検出力の証明にならない。局所欠陥を注入して
  初めて測定方法の妥当性が示せる。
- in-processのライブラリ呼び出しも、外部CLIと同じenvelope（入力hash・config hash・
  版・出力hash）で包む必要がある。副作用の重複防止と再現性の契約はプロセス境界の
  有無とは独立である。
- 出力の正規化規則は、それを使う最も上流の層（本件では`acd-core`）に置く。層順序を
  無視して置くと、adapterとゲートで別実装に分岐する。
- 実行環境の差はツール版だけでは吸収できない。CIのロケール（ASCII既定）とVMの
  ロケールの差で読み込みが落ちた事例は、Phase 1のKiCad設定コンテキスト、Phase 2の
  `IDF_PYTHON_ENV_PATH`と同型である。
