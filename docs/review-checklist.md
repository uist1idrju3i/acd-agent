# レビュー観点チェックリスト（RV1／RV2）

> ステータス: Draft（Phase 0最小版）
> 対象: 投影レビュー。背景は[`docs/projection-review.md`](projection-review.md)を参照。

AIレビューは`ReviewFinding`（[`schemas/review-finding.schema.json`](../schemas/review-finding.schema.json)）
を提案するだけで、合否権限を持たない。高重大度（high）で未処分（open）のfindingが
ある間、`review_disposition`ゲートは合格しない。

## RV1: 機械可読投影レビュー

対象: 設計グラフから生成した機械可読投影（netlist、pin割当表、FWパッケージ等）。

- 投影の`source_revision`が現在のグラフrevisionと一致しているか。
- 要求（requirementノード)から導出されていない値（定数、部品定格）がないか。
- ネット・ピン・FW pin割当の相互整合が取れているか。
- 安全境界ノードに関わる値が境界内か、境界の判定がunknownでないか。
- 出所（部品、ライブラリ）のpinとhashが記録されているか。

## RV2: 視覚投影レビュー

対象: 人間可読の視覚投影（回路図画像、基板図、レポート）。

- 視覚投影が同じrevisionの機械可読投影と同一内容を表しているか。
- 描画依存の情報（重なり、非表示要素）で意味が欠落していないか。
- 注記・単位・軸・原点の表示が canonical グラフの定義と一致しているか。

## disposition運用

- `fixed`: 修正commitとrevisionを根拠に閉じる。
- `waived`: 期限・対象revision・理由付きのwaiverで閉じる。
- `assumption`: 前提として記録し、前提が崩れたらstale化する。
- `rejected`: 誤検出。理由を必須とする。
