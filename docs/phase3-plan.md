# Phase 3実施計画

> ステータス: Draft
> 対象: Phase 3「機械レーン最小縦切り」の作業単位・順序・撤退条件

フェーズ境界と完了条件は[`roadmap.md`](roadmap.md)のPhase 3行を正とする。本書は
作業単位の管理だけを行い、完了条件を二重管理しない。

## 対象範囲

設計グラフの機械レーン入力（外形・部品占有体・connector開口・筐体制約）を抽出し、
build123d/OCPで筐体を生成する。生成したSTEP/3MFを再読込可能な投影として出力し、
CAD kernel妥当性、干渉、clearance、肉厚を機械的に検証する。同一入力の再実行で、
実測し確定した正規化後成果物hashが一致することを確認する。

やらないこと: レーン統合、知識ベース、自然言語入力、自動発注、Phase 4以降の
ECAD↔MCAD交換、汎用routerや独自CAD kernelの実装。

## 作業単位と順序

| # | 作業単位 | 主な成果物 |
|---|---|---|
| P3-1 | CAD kernel能力プローブと正規化規則の確定 | build123d/OCP導入、STEP/3MFの非決定性実測、`acd-core`の正規化規則、`docs/tool-capability-probes.md`更新 |
| P3-2 | Phase 3実施計画 | 本書、`docs/README.md`索引 |
| P3-3 | 設計グラフ契約の機械レーン拡張 | `schemas/design-graph.schema.json`へ機械レーンnode kind追加、`acd-schema`更新、往復検証 |
| P3-4 | 機械レーン抽出 | `acd-core`側の機械レーンview（電気レーンview`acd_core/electrical.py`に相当するもの） |
| P3-5 | CAD adapter新設 | `packages/adapters/acd-adapter-cad`、筐体生成とSTEP/3MF投影（判定を持たない） |
| P3-6 | 機械ゲート | `acd-runtime`側のCAD kernel妥当性・干渉・clearance・肉厚ゲート |
| P3-7 | fixtureと単一コマンド | `fixtures/golden-design-1`の機械レーンnode、`scripts/run_gd1_enclosure_pipeline.py`、envelope一致時skipとhash再現 |
| P3-8 | negative test | 干渉・肉厚不足・CAD kernel不在の注入で停止 |

依存方向は`acd-schema` → `acd-core` → adapters → `acd-tools` → `acd-runtime`を維持し、
adapterは合否判定を持たない。ゲート判定はruntime側で行う。正規化規則は`acd-core`を
正本とし、probeと後続adapterは同じ実装を利用する。

## 外部ツール（実測済み）

| ツール | 版 | 出所・測定 |
|---|---|---|
| build123d | 0.11.1 | PyPI固定版。10 mm角箱のSTEP/3MFを2回出力して測定 |
| cadquery-ocp（OCP） | 7.9.3.1.1 | PyPI固定版。build123dのCAD kernel |
| lib3mf | 2.5.0 | build123d/Mesher経由の3MF writer依存 |

OCP関連のインストール済み容量は実測約355 MB（OCP 159 MB、native libraries
101 MB＋95 MB）である。STEPのtimestampと3MFのUUIDを正規化した結果、今回の箱では
正規化後hashが一致した。実測と正規化の詳細は[`tool-capability-probes.md`](tool-capability-probes.md)
に記録する。

## 撤退条件

- STEP/3MFの非決定性が実測した正規化規則で閉じない場合は停止し、成果物とCAD kernelを
  `unknown`として扱う。規則外の差分を無視して合格扱いしない。
- OCPのインストール容量（実測約355 MB）またはCI所要時間がgolden taskの日常実行を
  妨げる場合、CIで常時実行する範囲と定期実測する範囲の切り分けを見直す。
- OCCの妥当性・干渉判定が本fixtureで安定しない場合、判定条件（tolerance）をfixtureへ
  固定して再測する。安定しない状態は合格扱いしない。
- build123d/OCPの版不明、CAD kernel不在、出力の再読込失敗はfail-closedで停止する。
