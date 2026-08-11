# 将来展望 — 家庭で基板を「印刷」する時代へ

> ステータス: Draft  
> 対象: プリンテッドエレクトロニクス、ローカル製造、構造エレクトロニクス、個人適合ウェアラブル

本書は、ACDの将来展望とPhase 9以降の製造拡張を扱います。現在の設計フローは
[`design-flow.md`](design-flow.md)、フェーズの完了条件は [`roadmap.md`](roadmap.md)を正とします。

VibeBBの前提である「製造の安さと速さ」は、さらに先へ進む可能性があります。
プリンテッドエレクトロニクス技術が成熟すれば、家庭用3Dプリンタのように、各家庭・
各デスクで基板がその場で製造される未来が考えられます。ループの「作って試す」が
数日から数十分に短縮され、VibeBBは真にブレッドボードの速度に到達します。

この前提は基板だけでなく、筐体・ブラケット・機械部品にも広がります。
[DMM.make 3Dプリント](https://make.dmm.com/print/)、[JLC3DP](https://jlc3dp.com/)、
[PCBWay 3Dプリント／CNC](https://www.pcbway.com/rapid-prototyping/cnc-faq.html)、
[Xometry](https://www.xometry.com/machine-learning-for-manufacturing/)、
[Craftcloud](https://craftcloud3d.com/)、[Protolabs Network](https://www.hubs.com/)などの
見積・DFM・発注サービスは、STEP/STL/3MF等から基板fabに並ぶ機械部品の調達経路になります。
ACDは基板と筐体を協調設計し、合算した総発注額、納期、製造能力を同じ発注前ゲートで扱います。
家庭の3Dプリンタや卓上CNCは、[Phase 9のローカル製造経路](roadmap.md)としてこれらの
サービスに対応します。

## 現状の技術動向

2026年時点の調査結果です。

| カテゴリ | 代表例 | 現状 |
|---|---|---|
| 卓上切削（サブトラクティブ） | [サンハヤト MDP-10Mk2](https://shop.sunhayato.co.jp/products/mdp-10mk2)、[Bantam Tools](https://bantamtools.com/products/bantam-tools-desktop-cnc-milling-machine)、[LPKF ProtoMat](https://www.lpkf.com/en/industries-technologies/research-in-house-pcb-prototyping/about-research-in-house-pcb-prototyping) | 銅張基板の彫刻・穴あけ。薬品不要で1〜2層試作が可能。ビア・多層は手作業 |
| 導電性インク印刷（アディティブ） | [Voltera V-One](https://store.voltera.io/products/v-one)（公式EUストア表示は2026年8月時点で€3,137.95、リードタイム1〜2週。地域・構成により異なる）、BotFactory SV2（2026年の調査時点で公開されていた構成価格：Starter $19,999／Enhanced $29,999／Professional $34,999。ただし現在は公式サイトへ到達できず未確認） | 1時間以内で動作基板を作れる例も。2層はリベット接続。銀インクは銅箔より高抵抗で、大電流用途には制約 |
| 研究・産業用 | [Voltera NOVA](https://www.voltera.io/products/nova)（フレキシブル/ストレッチャブル材料研究）、Nano DimensionのAME／Fabrica製品ライン（DragonFly関連資産を含み、[2026年4月7日の報道](https://3dprint.com/325057/analysis-nano-dimension-sells-additive-manufactured-electronics-business/)に記載のとおりInspira Technologiesへ売却）、[Optomec Aerosol Jet](https://www.optomec.com/printed-electronics/) | DragonFly IVをNano Dimensionの現行製品とは断定しない。多層・立体面・柔軟基材への印刷は産業用途が中心。LPKF ProtoMat、Bantam Tools、Optomecの2026年価格・在庫は公開情報で未確認 |
| 材料技術 | 銀ナノ粒子インク、銅焼結（フォトニック/レーザー）、粒子フリーMODインク、スクリーン印刷、インモールドエレクトロニクス | 導電率・はんだ付け性・信頼性のギャップが継続的に縮小中 |
| 導電性フィラメント／FDM | [Multi3D Electrifi](https://www.multi3dllc.com/product/electrifi/)（1.75／2.85mm、200g／500g、公称1,000または10,000 S/m）、[Protopasta Conductive PLA](https://proto-pasta.com/products/conductive-pla)（入手可能） | 筐体と配線を一体印刷できる可能性がある。Electrifiでも銅より大幅に低導電率で、電流容量、層間抵抗、接触抵抗、曲げ・摩耗・環境耐久を個別検証する必要がある |
| 導電性ペースト／直接実装 | [日油 CP-602AA](https://www.nof.co.jp/contents/electronicsdevicematerial/conductivepaste/cp-602aa.html)、[Henkel conductive adhesives](https://next.henkel-adhesives.com/pk/en/applications/electronic-component-bonding-solutions/electrically-conductive-adhesives.html)、[NovaCentrix](https://novacentrix.com/conductive-inks-faq/) | 低温硬化による樹脂・フレキ基板への配線、はんだを使わない部品接続が可能。ただし接触抵抗、硬化条件、熱サイクル、吸湿、再加工性を検証する |
| 3D-MID／LDS／IME | [LPKF LDS](https://www.lpkf.com/en/industries-technologies/electronics-manufacturing/3d-mids-with-laser-direct-structuring-lds)、[Fraunhofer MID Lab](https://www.iem.fraunhofer.de/en/about-us/labs-and-testing-facilities/mid-lab.html)、[TactoTek IMSE](https://www.tactotek.com/technology) | 回路を成形品や筐体表面へ置く構造エレクトロニクス。平面PCBと筐体の境界を曖昧にするが、量産工程・専用材料・検査が必要 |
| 導電性材料・ハイブリッドAM | J.A.M.E.S（2026年8月時点でサイト到達不可）、Nano DimensionのAME／Fabrica製品ライン（2026年4月にInspira Technologiesへ売却）、[Aerosol Jet](https://optomec.com/printed-electronics/aerosol-jet-printers/aerosol-jet-5x-system/) | 導電体・誘電体・構造材を組み合わせた多層／立体回路。将来の非平面設計候補だが、Phase 1の要件には含めない |

冷静な見立てとしては、単純な1〜2層基板の宅内製造はすでに現実であり、数年内には
「印刷＋穴あけ＋ペースト＋リフロー＋検査」を統合したアプライアンス的な卓上
ハイブリッド機が有望です。一方、高密度多層・メッキスルーホール・大電流・認証が
必要な量産は当面プロのfabが優位です（詳細な調査ノートは別途）。

## ACDが織り込む項目

- **プリンタ・材料プロファイル対応DRC：** 最小配線幅／間隔、工具径、インクまたはフィラメントの抵抗率・異方性・電流容量、最小層厚、ビア方式（リベット/手動/印刷）、基材、密着性、硬化／焼結温度、熱サイクル耐久など、手元の製造機と材料ごとのルールで検証します。fab向けDRCと同じ枠組みの別プロファイルです。
- **材料を考慮した電気解析：** 銅箔前提ではなく、実測の材料データから配線抵抗・電圧降下・温度上昇を見積もります。
- **ハイブリッド製造の自動判断：** ローカルで作れる部分は即座に印刷し、密度や電流が要求を超える基板は従来のfabへ自動的に振り分けます。同じ設計グラフから、ローカル試作版とFR-4量産版の両方を生成できます。
- **クローズドループ検査と知識蓄積：** カメラによる位置合わせ、導通・抵抗チェックの結果を設計グラフへ戻し、インクロットや機体ごとの癖も知識として蓄積します。
- **構造エレクトロニクスへの余地：** 筐体表面・成形品・埋め込み配線を含む非平面回路を将来方向として検討します。現時点では`Layout`を平面PCBに固定せず、材料・工程・測定証拠を制約と根拠として保持できる設計グラフを優先します。

## 個人適合ウェアラブル

その先には、個人に合わせたウェアラブルがあります。手首、耳、頭部などを3Dスキャンし、
個人形状を設計グラフの機械制約として取り込み、非平面・伸縮回路を生成し、その場で
印刷する流れです。補聴器のカスタムシェルは、耳のスキャンから個別形状を作り3D製造する
実用化済みの先例です。[OptomecのAerosol Jet](https://optomec.com/printed-electronics/aerosol-jet-technology/)
や皮膚に追従するepidermal electronics研究（[Rogers group](https://doi.org/10.1126/science.1206157)）
は、曲面・身体表面への回路形成の技術的基盤を示しています。VibeBBは「その人の要件」
から「その人が装着して動くデバイス」までの最短経路を目指しますが、これはvision-levelの
将来方向であり、Phase 1の約束ではありません。設計グラフは平面の硬い基板を前提に固定せず、
構造エレクトロニクスの将来拡張を妨げないものとします。

個人適合ウェアラブルを志向すると、個人ごとに形状が変わるため、従来の回路図や
アートワーク図を正とする設計では限界があります。個別の図面を正とすれば、形状ごとに
作り直す図面が設計の根拠になってしまいます。ACDでは、設計原則どおり要件・制約・
設計根拠を含む型付き設計グラフを正とし、個人形状ごとにガーバーなどの製造データまで
一気通貫で再生成します。何をテストすべきかも根拠から導出でき、万一NGになっても結果を
根拠へ遡ってその場で修正し、次のリビジョンを再印刷できます。

家庭での基板製造が普及するほど、「対話 → 設計 → その場で印刷 → 実機テスト → 知識蓄積」
というVibeBBのループは短く強力になります。ACDはそのときの標準ツールとなることを目指します。
