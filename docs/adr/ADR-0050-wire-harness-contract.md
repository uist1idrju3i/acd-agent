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

## 影響

ハーネスが未宣言のGD1や既存設計は、opt-in contractが存在しない限りハーネスgateの
対象にならず、既存のgate出力、Evidence、projectionを変更しない。contractを宣言した
設計では、graphとの結線不一致、電線の定格不足、電圧降下超過、絶縁定格不足、曲げ半径
不足をfailまたはunknownとして明示できる。切断長表は製造・組付けの観測資料であり、
それ自体は認証適合や規制認証を主張しない。
