# ADR-0012: silkscreen観測範囲とevidence要約

> ステータス: Accepted
> 日付: 2026-08-16
> 関連: [`ADR-0011-search-results-as-design-input.md`](ADR-0011-search-results-as-design-input.md)

## 決定

silkscreenゲートは、silkと同面のpad、mask開口、body、courtyardだけを衝突対象
とする。through-hole padは両面の対象とし、boardレベル参照にはnearest-component
制約を適用しない。文字寸法はKiCad stroke fontの実測に基づく上界モデルをゲート側の
単一の出所とし、文字ごとのadvance係数、stroke余裕、descender係数をcontext経由で
Skillへ配布する。帰属範囲を広げた場合は、実測text-local範囲が上界をstroke幅以上
超えたとき`attribution_overflow`でfail-closedにする。

placement evidenceは、採用位置・回転、拒否理由別件数、各理由の先頭例、および完全な
evidence JSONのsha256をgraphへ保存する。完全な候補列挙は`out/`へ出力し、canonical
graphには保存しない。

## 根拠

GD1の観測で、裏面silkと表面部品を衝突扱いすること、およびboard参照をrefdes向け
nearest-component判定へ入れることは物理的に成立しない判定だった。さらにKiCad stroke
fontのadvanceは約`0.868 × height`であり、上界`0.95 × height`とstroke余裕を採用した。
descender文字`g/j/p/q/y`は、実測直交方向幅`1.483 mm`（height 1.0、stroke 0.15、
stroke除外で`1.333 × height`）に対して係数`1.45`を上界とした。これは閾値を緩めた
のではなく、同面性と測定モデルの誤りを是正したものである。

## 結果

F面ラベルは上界モデルで解が存在する高さ1.0 mmへ変更し、`RESET`は解が存在しない
ため`RST`へ変更した。投影・実測・再配置後、GD1基板pipelineはsilkscreenゲートまで
通過する。evidence要約は設計入力のサイズを抑えつつ、完全データをhashで追跡できる。
