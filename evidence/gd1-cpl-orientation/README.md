# GD1 CPL 回転 Evidence

各 JSON は、部品の CPL 回転根拠を取得時点とともに記録する。

- `schema_version`: Evidence 文書のスキーマ版。
- `refdes`: 対象部品のリファレンス番号。
- `lcsc`: LCSC 部品番号。
- `url`: 応答を取得した URL。
- `retrieved_at`: 取得時刻。
- `response_sha256`: 保存した API 応答の raw bytes に対する SHA-256。
- `response_canonical_sha256`: JSON を parse し、キーをソートして区切り文字を固定した canonical JSON bytes に対する SHA-256。
- `response`: API 応答本体。形状とピン位置の原データを保持する。

`response` は削除・縮小しない。製造 adapter が package/pin の shape を参照し、canonical hash の検証にも同じ応答を使うためである。
