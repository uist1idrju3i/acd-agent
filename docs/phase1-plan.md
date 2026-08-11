# Phase 1実施計画

> ステータス: Draft
> 対象: Phase 1「電気レーン最小縦切り」の作業単位・順序・撤退条件

フェーズ境界と完了条件は[`roadmap.md`](roadmap.md)を正とし、対象実物は
[`golden-design-1.md`](golden-design-1.md)を正とする。本書は作業単位の管理だけを行い、
完了条件を二重管理しない。

## 対象範囲

fixture要件→固定部品→netlist/BOM→決定論的配置→外部router（freerouting DSN/SES）→
`kicad-cli` ERC/DRC→Gerber/drillを単一コマンドで通し、`kicad-cli`と独立parser
（sexpdata系＋gerbonara）の二重再読込、同一入力再実行のhash一致、negative test
（配線不能・ERC違反・router不在）による停止を実証する。

やらないこと: 筐体、知識ベース、FW実装、自然言語入力、自動発注、汎用router自作。

## 作業単位と順序

| # | 作業単位 | 主な成果物 |
|---|---|---|
| P1-1 | 設計グラフ契約の拡張 | `schemas/design-graph.schema.json`へ`electrical.board`ノードkind追加、`acd-schema`更新 |
| P1-2 | Golden Design #1 fixture | `fixtures/golden-design-1/graph.json`（部品・ネット・ピン割当・基板制約・ライブラリpin） |
| P1-3 | KiCadライブラリpin解決 | `acd-adapter-kicad`: pinされたシンボル・footprintの解決とhash記録 |
| P1-4 | 回路図投影とERC | `.kicad_sch`生成（決定論的配置・グローバルラベル接続）、`kicad-cli sch erc` |
| P1-5 | netlist/BOM投影 | `kicad-cli sch export netlist`＋グラフ由来BOM（決定論的順序） |
| P1-6 | 基板投影と決定論的配置 | `.kicad_pcb`生成（外形・取付穴・アンテナキープアウト・グリッド配置） |
| P1-7 | freerouting DSN/SES連携 | `acd-adapter-freerouting`: DSN書き出し→外部process→SES読み戻し→配線注入 |
| P1-8 | DRC・Gerber/drill | `kicad-cli pcb drc`、`pcb export gerbers`/`drill` |
| P1-9 | 二重再読込・hash再現性 | sexpdata系＋gerbonaraによる独立再読込、正規化後hash比較 |
| P1-10 | 単一コマンドとnegative test | `scripts/run_gd1_pipeline.py`、配線不能・ERC違反・router不在の停止確認 |

依存方向は`acd-schema` → `acd-core` → adapters → `acd-tools` → `acd-runtime`を維持し、
adapterは合否判定を持たない。ゲート判定はpipeline側（`acd-runtime`）で行う。

## 外部ツール（実測済み）

| ツール | 版 | 出所 |
|---|---|---|
| kicad-cli | 10.0.5 | ppa:kicad/kicad-10.0-releases |
| freerouting | 2.3.0 | GitHub releases v2.3.0（OpenJDK 25） |
| KiCad公式ライブラリ | kicad 10.0.5同梱 | `/usr/share/kicad/symbols`・`footprints`（CC-BY-SA 4.0＋例外） |
| Espressif kicad-libraries | commit pin | ESP32-C3-MINI-1のシンボル・footprint（CC-BY-SA 4.0＋例外） |

ライブラリは出所URL・commit（または版）・ファイルhashをpinし、pinのない参照は
`unknown`として停止する（[`adr/ADR-0004-parts-catalog-provenance.md`](adr/ADR-0004-parts-catalog-provenance.md)）。

## 撤退条件

- `kicad-cli` 10系の形式版で再読込・ERC/DRCが安定しない場合、9系へpinを戻し
  実測を取り直す。
- freeroutingが本fixtureで収束しない場合、配線パラメータ（pass数・via条件）を
  fixtureへ固定して再測する。収束しない状態は`unknown`として停止し、合格扱いしない。
- 回路図投影のERCがKiCad版依存で不安定な場合、ERC対象を最小構成（電源・未接続・
  ピン方向）へ絞り、除外はwaiverとして期限・根拠付きで記録する。
