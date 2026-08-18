# ADR-0005: JLCPCB PCBA発注準備の契約と宣言データ

> ステータス: Accepted
> 日付: 2026-08-11

## コンテキスト

JLCPCB PCBAに必要な製造データと、品質を最優先にしたDFM／コスト・納期
リスクゲートを、roadmapのPhase 5/7/10に先行して発注準備へ利用する。
ただし実発注、価格・在庫・納期取得、総発注額計算はACDの責務ではない。

## 決定

- CPL生成、JLCPCB投入形式BOM、DFM照合、製造データパッケージを先行実装する。
  実発注、価格・在庫・納期の取得、総発注額計算は実装せず、値は`unknown`とする。
- fab能力値とコスト／納期ドライバはコードへハードコードせず、版管理されたfab
  profileとして保持する。各値には出所URL、確認日時、一次情報か推論かの区分を持たせる。
- DFM判定は`capability_violation`、`cost_or_lead_time_adder`、`quality_risk`の
  3分類とする。能力違反は常にfailとし、後2者は根拠付き
  `fab.process_allowance`がある場合のみ通す。宣言の有無と根拠はEvidenceに残す。

ADR-0008によりwaiver機構は廃止し、能力違反は常にfailとする。
- Qualityを最優先とし、`quality_risk`の緩和には、設計上の必要性を示す要件nodeへの
  参照を必須とする。参照欠落、rule_id不整合、reason空はfail-closedとする。
- 判定の両辺は別出自から取得する。判定入力は生成済み成果物を独立parserで読み直した
  実測値、比較対象はfab profileの宣言値とし、graphの宣言値を合格根拠にしない。
- 実価格、実納期、在庫、JLCDFMのfab側レビュー結果はACDで判定せず、`unknown`として
  Phase 9/11へ送る。
- 部品カタログは設計グラフの`electrical.component`ノードにMPN、メーカー、出所URL、
  取得時点、ライセンスを保持する。footprint、3D model、symbolのライブラリは取得元URLと
  commit、版、またはhashをpinし、解決した実パスと取得日時をEvidenceへ記録する。
- pinのないライブラリ参照、出所不明のfootprint、hash未記録の3D modelは`unknown`として
  fail-closedで扱い、照合Evidenceなしに合格根拠にしない。ライブラリ記述と実部品の照合は
  datasheetとpin mappingを独立に検証し、ライブラリ更新時はstale化して再照合する。
- KiCad公式ライブラリを第一候補とし、ライセンスは
  [`docs/research/README.md`](../research/README.md)の境界に従って確認する。

## 影響

- `fab.order_intent`は対象profileとPCBA工程クラスを設計グラフへ明示する。
- `fab.process_allowance`は、追加影響を受け入れる工法と要件根拠を明示する。
- profileの`rule_id`は後続DFM findingの安定した識別子となる。

## silkscreen観測範囲とevidence要約

silkscreenゲートは、silkと同面のpad、mask開口、body、courtyardだけを衝突対象
とする。through-hole padは両面の対象とし、boardレベル参照にはnearest-component
制約を適用しない。文字寸法はKiCad stroke fontの実測に基づく上界モデルをゲート側の
単一の出所とし、文字ごとのadvance係数、stroke余裕、descender係数をcontext経由で
Skillへ配布する。帰属範囲を広げた場合は、実測text-local範囲が上界をstroke幅以上
超えたとき`attribution_overflow`でfail-closedにする。

placement evidenceは、採用位置・回転、拒否理由別件数、各理由の先頭例、および完全な
evidence JSONのsha256をgraphへ保存する。完全な候補列挙は`out/`へ出力し、canonical
graphには保存しない。

GD1の観測で、裏面silkと表面部品を衝突扱いすること、およびboard参照をrefdes向け
nearest-component判定へ入れることは物理的に成立しない判定だった。KiCad stroke fontの
advanceは約`0.868 × height`であり、上界`0.95 × height`とstroke余裕を採用した。
descender文字`g/j/p/q/y`は、実測直交方向幅`1.483 mm`（height 1.0、stroke 0.15、
stroke除外で`1.333 × height`）に対して係数`1.45`を上界とした。これは閾値を緩めた
のではなく、同面性と測定モデルの誤りを是正したものである。

F面ラベルは上界モデルで解が存在する高さ1.0 mmへ変更し、`RESET`は解が存在しない
ため`RST`へ変更した。投影・実測・再配置後、GD1基板pipelineはsilkscreenゲートまで
通過する。evidence要約は設計入力のサイズを抑えつつ、完全データをhashで追跡できる。
