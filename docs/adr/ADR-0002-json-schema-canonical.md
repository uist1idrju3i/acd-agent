# ADR-0002: JSON Schemaを契約の正本とする

> 本決定はADR-0008により廃止され、現在の契約の正はPydanticモデルとする。本文は過去の決定履歴として保持する。

> ステータス: Accepted
> 日付: 2026-08-11

## コンテキスト

設計グラフ、tool envelope、gate matrix、error taxonomy、event payload、
ReviewFinding、Evidence、FWパッケージの契約は、Python実装と独立に版管理・
レビュー可能な形式で固定する必要がある。

## 決定

- `schemas/*.schema.json`（JSON Schema draft 2020-12）を機械可読契約の正本とする。
- `packages/acd-schema`のPydanticモデルは正本の実装であり、両者の整合は
  往復検証テスト（golden fixtureが両方で受理され、negative fixtureが両方で
  拒否されること）で担保する。
- 共有語彙（revision、hash、unknown、timestamp等）は`common.schema.json`に置き、
  各契約から`$ref`で参照する。
- すべての契約は`schema_version`を持ち、`additionalProperties: false`
  （Pydantic側は`extra="forbid"`）で未知フィールドを拒否する。
- `unknown`は明示的な値として許容するが、fail-closedで扱い、合格根拠にしない。

## 影響

- 契約変更はJSON Schemaの差分としてレビューでき、他言語実装も同じ正本を参照できる。
- Pydanticモデルと正本が乖離した場合、往復検証テストが失敗して検出される。
- 未知フィールドの読み飛ばしによる暗黙のデータ損失が起きない。
