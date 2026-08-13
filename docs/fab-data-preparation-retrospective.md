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
7. SW1とSW2は同じLCSC・MPN・footprintだったが、graph投影のvalue（`RESET`／`BOOT`）が異なるため
   発注用BOMで分割された。export format側の同一性キーをfab部品番号へ分離し、`SW1,SW2`を1行へ
   まとめ、value不一致時はMPNをCommentへ使い、生成後のBOMをグラフと再照合するようにした。
8. GD1では配置アンカーをfootprint幾何とグラフ宣言から導出せず、`J1`と`U1`の位置を
   マジックナンバーで固定していた。そのため板端との関係を誰も検証できず、DRC 0・DFM 0でも
   誤配置が通った。生成物の3Dレンダを人が目視するのは最初に異常へ気付ける安価な手段であり、
   今回もユーザの目視指摘が起点になった。今後はアンカーを幾何と宣言から導出し、意図した
   板端はみ出しを宣言して独立実測と照合する。
9. 発注用exportの行識別キーはgraph投影の同一性キーと分ける。fab部品番号によるBOM統合と
   value差異の扱いを混同せず、生成後のDesignator集合を独立照合する。
10. KiCadの回転規約を思い込みで実装したため、90°/270°の非対称部品で実測pad座標が
    180°ずれた。0°/180°だけでは符号誤りが露見しないため、SOT-223のtabやUSB-C shield
    のような非対称形状を90°/270°でテストし、Gerber銅、3Dレンダ、KiCad自身の出力と
    突き合わせる独立ゲートを必須にする。DRC 0でも実測層の座標変換が誤っていれば、
    DFM判定自体が無意味になる。
11. CPLのfootprint原点と部品centroidを混同した。生成物と独立測定が同じfootprint原点を
    共有していると、その基準自体の誤りは検出できない。fabが要求する位置・回転基準は
    一次情報で確認する。JLCPCB公式はcomponent centroidと定義するが算出方法を明記して
    いないため、GD1のU1/J1でpad bbox中心を採用した結論は推定として記録し、confirmed
    とは扱わない。ビューワ実測との差の符号と大きさが一致することは傍証であり、第三者の
    補正テーブルは一次情報の出所として採用しない。estimatedな基準はfab側プレビューの
    目視確認が必要で、自動発注合格にしない。製造データ生成と発注可否は分離し、
    Gerber、CPL、BOM、DFM、fab-packageを生成した後にorder-readinessゲートで発注可否を
    判定する。未確認の位置・回転基準が残る間は製造データを確認用に出力するが、
    `order-readiness.json`を`not_order_ready`として発注を停止する。
    グラフの出所時点は`cpl_position_evidence_at`／`cpl_rotation_evidence_at`で記録し、
    人によるconfirmed宣言には確認手段、対象revision、根拠メモも必須とする。
    fab側ライブラリの番号付きパッド配置は取得可能な照合対象であり、保存した応答のURL、
    取得時刻、hashをEvidenceとして固定し、KiCad側パッドとピン機能・座標を再計算する。
    パッド番号はライブラリ間で意味が異なり得るため照合キーにせず、D1のような極性部品で
    番号照合が逆実装を導くことを防ぐ。一意な幾何解も正しさの証明とはせず、機能を1:1
    対応できない場合はfail-closedとする。無極性・対称部品だけは極性影響なしの根拠を
    Evidenceへ残して幾何照合する。
    照合の優先順位はピン機能が第一であり、機能対応を省略する幾何例外には機構的な向き
    または仕様上の機能対称性の出所付き宣言を必須とする。左右反転は回転では解消できない
    ため、幾何的一意性だけでなく左右の電気的機能対称性も確認する。
    ただしこれはメーカーのtape&reel図そのものではないため、ライブラリ由来である限界を
    `fab_library_footprint`として明示する。JLCPCB公式FAQの「0°は包装内の部品向きと
    一致すべき」という要件を補助する再現可能な照合であり、公式の部品別テープ表とは
    扱わない。

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
- 発注用BOMの行同一性キーをgraph投影の同一性キーと混同しない。fabの部品番号（LCSC、MPN、
  footprint）とexport formatの列契約をprofile側で宣言し、valueの差異で同一発注部品を分割しない。
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
