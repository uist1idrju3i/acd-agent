# ADR-0050: ワイヤハーネス契約と結線検査

> ステータス: Accepted
> 日付: 2026-09-14
> 関連: [`ADR-0023-deterministic-gate-authority.md`](ADR-0023-deterministic-gate-authority.md)、[`ADR-0028-execution-provenance.md`](ADR-0028-execution-provenance.md)、[`../roadmap.md`](../roadmap.md)（マイルストーン16.6）

## コンテキスト

基板のDesign Graphは、基板上のコネクタ、ピン、ネットを正本として持つ。
基板外の電線ハーネスは、結線、電線種別、余長、電流、耐圧、耐熱を別途宣言しなければ、
ネットリストと製造用の切断長を同じrevisionへ結び付けられない。ハーネスをgraph nodeへ
混在させると、基板設計の正本と製造・組付け用の契約が不明確になる。

## 決定

1. ハーネスは`HarnessContract`として独立した宣言ファイルに置き、Design Graphのnode
   では表現しない。contractはgraphのコネクタcomponentとelectrical.netを参照し、
   `graph_id`と`revision`を一致させる。
2. graphのコネクタcomponent、pin、netlistを単一の正本とする。各wireの`from`／`to`
   connector pinは、宣言されたnetに属するgraph pinでなければならない。cavityを
   graph pinへ決定的に対応できない場合はunknownとする。
3. `electrical.net`の`off_board: true`はrequired rationaleの`net_class`属性とする。
   すべてのoff-board netは少なくとも1本のハーネスwireに現れなければならない。
4. `netlist_consistency`、`ampacity`、`voltage_drop`、`insulation_rating`、
   `bend_radius`をL1の決定論的gateとして実行する。欠落、矛盾、revision不一致は
   合格へ変換せず、入力エラーまたはunknown／failとして停止側へ集約する。
5. ハーネスSVG図と切断長表はL3 projectionであり、入力やL1判定権限へ逆流させない。
   projectionは入力hash、revision、tool versionをprovenance sidecarへ記録し、同じ入力から
   byte-identicalに再生成できるものとする。
6. 実測Evidenceの境界はmilestone 5の方式に従う。本ADRの実装では測定Evidenceを取り込まず、
   宣言値による決定論的検査だけを提供する。
7. shield、flex-cycle、mating回数・保持力、DFA linkageは次のPR以降へ延期する。

## 追補: 将来構想ワイヤハーネス第2段

第2段では、上記の独立contractとL1 fail-closed方針を維持したまま、次の任意宣言を
追加した。

1. wire typeのシールド種別とwireの撚り対groupにより、analog-sensitive／high-speed
   netのシールド要件を検査する。return wireを含む撚り対の宣言がない場合はfailとする。
2. 16.5で定義した信号クラス非互換表を再利用し、同一connectorまたは同一routeのwire束を
   検査する。既存の構造安全性predicateの定義は変更しない。
3. moving sectionのrouteに期待屈曲回数、wire typeの耐屈曲回数、動的最小曲げ半径を宣言し、
   不足または超過をfail／unknownとする。
4. harness service expectationに嵌合回数と保持力を宣言し、connector定格と比較する。
   同一housingのconnectorはdistinct keyingまたはpolarity guardを必須とする。
5. 16.5の`safety.redundant_group`が`harness`共有を禁じる場合、membersのnetが同一routeへ
   集約されていないことを検査する。harnessが未宣言の16.5 predicateの挙動は変更しない。
6. `check_harness.py`が返す`dfa_findings`は既存のDFA finding contractを使うL2所見であり、
   L1判定権限を持たない。keying未宣言と余長5%未満をassembly-order観点の観測として出力する。

第2段の追加フィールドはすべて任意であり、旧contractは既存5 checksを維持する。ただし、
判断に必要な宣言が存在する場合に欠落値をpassへ変換せず、unknownまたはfailとして停止側へ
集約する。

## 追補: 将来構想ワイヤハーネス第2段

第2段では、上記の独立contractとL1 fail-closed方針を維持したまま、次の任意宣言を
追加した。

1. wire typeのシールド種別とwireの撚り対groupにより、analog-sensitive／high-speed
   netのシールド要件を検査する。return wireを含む撚り対の宣言がない場合はfailとする。
2. 16.5で定義した信号クラス非互換表を再利用し、同一connectorまたは同一routeのwire束を
   検査する。既存の構造安全性predicateの定義は変更しない。
3. moving sectionのrouteに期待屈曲回数、wire typeの耐屈曲回数、動的最小曲げ半径を宣言し、
   不足または超過をfail／unknownとする。
4. harness service expectationに嵌合回数と保持力を宣言し、connector定格と比較する。
   同一housingのconnectorはdistinct keyingまたはpolarity guardを必須とする。
5. 16.5の`safety.redundant_group`が`harness`共有を禁じる場合、membersのnetが同一routeへ
   集約されていないことを検査する。harnessが未宣言の16.5 predicateの挙動は変更しない。
6. `check_harness.py`が返す`dfa_findings`は既存のDFA finding contractを使うL2所見であり、
   L1判定権限を持たない。keying未宣言と余長5%未満をassembly-order観点の観測として出力する。

第2段の追加フィールドはすべて任意であり、旧contractは既存5 checksを維持する。ただし、
判断に必要な宣言が存在する場合に欠落値をpassへ変換せず、unknownまたはfailとして停止側へ
集約する。

## 影響

ハーネスが未宣言のGD1や既存設計は、opt-in contractが存在しない限りハーネスgateの
対象にならず、既存のgate出力、Evidence、projectionを変更しない。contractを宣言した
設計では、graphとの結線不一致、電線の定格不足、電圧降下超過、絶縁定格不足、曲げ半径
不足をfailまたはunknownとして明示できる。切断長表は製造・組付けの観測資料であり、
それ自体は認証適合や規制認証を主張しない。
