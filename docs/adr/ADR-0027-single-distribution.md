# ADR-0027: 単一配布パッケージ

> ステータス: Accepted
>
> 日付: 2026-08-17

## 決定

ACDの配布単位を7本のworkspace packageから、ルートの単一配布パッケージ
`acd`へ統合する。実装は`src/acd/`配下のschema、core、pipeline、openhands、
および各adapterで構成し、テストはルートの`tests/`へ集約する。

旧OpenHands統合moduleは、その責務を明示するため`acd.openhands`へ改名する。
OpenHands SDKの標準toolをAgentDefinitionから使用するため、`openhands-tools`をpath
依存として追加する。`openhands-agent-server`は将来構想であり、今回の依存には含めない。

ruffとpyrightの対象は単一の`src`レイアウトへ統合し、pyrightのsrc系実行環境も
SDKの3パッケージを参照する1環境へ統合する。既存の処理、契約、合否権限、テストの
意味は変更せず、公開moduleのimport pathだけを変更する。

## 理由

配布単位と型検査環境の重複をなくし、実装変更時の依存宣言・module path・検証設定の
同期漏れを減らす。単一配布の責務境界はADR-0026の委譲契約を維持する。

## 関連

[`ADR-0001-monorepo-structure.md`](ADR-0001-monorepo-structure.md)を置き換える。
