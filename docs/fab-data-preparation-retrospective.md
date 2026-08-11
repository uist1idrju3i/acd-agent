# 製造データ先行実装の振り返り

> ステータス: Draft  
> 対象: GD1のJLCPCB製造データ準備と、Phase 8のfab非依存化計画

## 範囲と契約

今回の先行実装は、設計グラフを正としてJLCPCB向け製造データを決定論的に生成し、
独立測定とゲート結果を製造パッケージへまとめるものである。契約上の根拠は
[`ADR-0005`](adr/ADR-0005-jlcpcb-pcba-preparation-contract.md)であり、本書は実装結果と
一般化対象を記録する。Phaseの境界は[`roadmap.md`](roadmap.md)だけを正とする。

## 先行実装したもの

- JLCPCBへ渡すGerber/drillのzip。
- JLCPCB形式のBOMとCPL、位置CSV。
- 生成物を独立parserで再読込して測定するDFM report。
- J1のPTHアニュラリングを補正するLibraryOverlay。公式footprintを変更せず、overlay後の
  geometryを下流投影で共有した。
- Gerber/drill、BOM/CPL、DFM、profileとoverlayのprovenance、member hash、gate結果、
  unknown項目を含むmanufacturing package。

## 有効だった設計判断

能力値をfab profileに置き、推奨値や工程選択をpreferencesとして分離した。DFM findingは
`capability_violation`、`cost_or_lead_time_adder`、`quality_risk`、`unused_allowance`に分類し、
capability violationにはallowanceを適用しない。

判定は生成器の自己申告ではなく、生成されたGerber、drill、BOM、CPLを独立に再読込して測定した。
比較の優先順位はQuality、Cost、Deliveryであり、価格や納期が未取得なら既知の値として補完しない。

## 実際に起きた失敗と修正

1. KiCad 10で生成した`.kicad_dru`は期待した実効性を持たず、DRU有無で同じ42件の違反が出た。
   誤解を招くDRU出力を避け、未測定項目は`checks_not_implemented`へ記録する方針に変えた。
2. overlay適用前geometryで配線し、適用後geometryで最終boardを作ったため、配線と検証がずれた。
   overlay後geometryをDSN、routing、最終board、DRC、DFMで共有する形に統一した。
3. via外径とpadの重なりでvia-in-padを判定し、TP1、TP4、TP7を誤検出した。
   drill穴円と回転考慮したSMD pad矩形の交差だけを判定し、異ネット銅clearanceはDRCの責務とした。
4. zipの生バイトhashは、KiCadがGerberへ`TF.CreationDate`を書き込むため決定論の根拠にならなかった。
   メンバごとの正規化hashからcontent hashを導出し、Gerber/drillを2回生成して9メンバ全一致を実測した。
5. 配置がSW2で不能になったため、残部品をcourtyard面積の降順（同面積はrefdes順）で走査した。
   大物部品が最後に残らなくなり解消し、制約は緩和していない。
6. レビューで見つかったDFM閾値のハードコード、`unused_allowance`の分類誤り、Economic判定の
   色・表面処理・組合せ表・assembly sides不足、oval drillの計算、overlay内rule ID literalを修正した。

## 残るリスクとunknown

`checks_not_implemented`には次の13項目が残る。未検査は合格扱いにしない。

`pth-to-track-prefer-035`、`via_hole_to_hole`、`routed_edge_copper_clearance`、`pad_to_silk`、
`min_via_diameter`、`min_plated_slot_width`、`min_nonplated_slot_width`、`slot_length_width_ratio`、
`soldermask_bridge`、`pad_to_track_clearance`、`min_package`、`min_ic_pitch`、`min_bga_pitch`。

価格、在庫、lead time、total order amount、fab側DFM reviewは`unknown`である。Gerbonaraには
`"G90" header statement found after end of header`というExcellon警告が残るが、parseと独立reloadは
成功している。FreeRoutingの観測最小幅は`0.1124 mm`で、SES取り込み時に宣言DFM幅`0.15 mm`へ
正規化している。この差は隠さず、測定条件として記録する。

## JLCPCB KiCad pluginの位置づけ

JLCPCB KiCad pluginは将来の任意adapterとして二次保持する。既定経路は現在の決定論的な自前生成で
あり、採用前にライセンス、公式性、版固定可否、ヘッドレス実行可否を確認する。採用しても出力は
独立parser、DFM、hash、ToolEnvelope、target revision検証を通す。GUI専用または非決定論的なplugin
出力を、そのまま合否Evidenceにはしない。

## Phase 8で一般化するfab固有箇所

以下は現実装で確認した一般化対象であり、現状がfab非依存であるという主張ではない。

- `packages/acd-core/src/acd_core/bom.py`と`electrical.py`の`jlcpcb_class`属性名・BOM列名。
  fab非依存名へ改め、設計グラフ属性、schema、fixtureを連動させる。
- `schemas/fab-profile.schema.json`の`assembly_classes`固定（`economic`／`standard`）を任意の
  class ID配列へ一般化し、graphの`pcba_class_target`をprofile class ID参照にする。
- `packages/adapters/acd-adapter-kicad/src/acd_adapter_kicad/fab.py`のBOM/CPL列名・列順、
  座標符号、回転規約をprofileのexport format宣言へ移す。
- `packages/adapters/acd-adapter-kicad/src/acd_adapter_kicad/project.py`の`.kicad_dru` rule名に
  ある`jlcpcb-` prefixを一般化する。
- `packages/acd-core/src/acd_core/fab.py`のassembly class literal検証をprofile由来にする。
- capability値とpreferenceの`rule_id`はfab依存である。profileに出所、取得時刻、hashを付ける
  共通原則を維持し、未確認値は追加しない。

## Evidence参照

数値と成果物はGD1の次の生成物・記録を出所とする。

- `out/gd1/fab/dfm-report.json`
- `out/gd1/fab/fab-package.json`
- `out/gd1/routing-summary.json`
- `out/gd1/fab/`配下のGerber/drill、BOM、CPL、hash manifest
- JLCPCB capability profile `jlcpcb-fr4-2l-1oz`（profileのsource、fetched_at、hash）
