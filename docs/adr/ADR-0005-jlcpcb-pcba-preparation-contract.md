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
  3分類とする。能力違反はwaiver不可で常にfailとし、後2者は根拠付き
  `fab.process_allowance`がある場合のみ通す。宣言の有無と根拠はEvidenceに残す。
- Qualityを最優先とし、`quality_risk`の緩和には、設計上の必要性を示す要件nodeへの
  参照を必須とする。参照欠落、rule_id不整合、reason空はfail-closedとする。
- 判定の両辺は別出自から取得する。判定入力は生成済み成果物を独立parserで読み直した
  実測値、比較対象はfab profileの宣言値とし、graphの宣言値を合格根拠にしない。
- 実価格、実納期、在庫、JLCDFMのfab側レビュー結果はACDで判定せず、`unknown`として
  Phase 8/10へ送る。

## 影響

- `fab.order_intent`は対象profileとPCBA工程クラスを設計グラフへ明示する。
- `fab.process_allowance`は、追加影響を受け入れる工法と要件根拠を明示する。
- profileの`rule_id`は後続DFM findingの安定した識別子となる。
