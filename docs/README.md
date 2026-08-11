# ACDドキュメント索引

> ステータス: Draft  
> 対象: ACDコンセプト段階、OpenHands SDK v1.41.0、調査日 2026-08-11

本索引は`docs/`の文書一覧と読む順序を正とする。各文書は、冒頭の対象範囲と
関連文書へのリンクを基準に、個別の仕様・調査・運用方針を記述する。

## 読む順序

1. [`../README.md`](../README.md): ビジョン、原則、全体フロー。
2. [`glossary.md`](glossary.md): 用語と工程IDの定義。
3. [`architecture.md`](architecture.md): 設計グラフ、投影、レイヤ境界。
4. [`ecad-domain-notes.md`](ecad-domain-notes.md): ECAD領域知識と投影契約。
5. [`design-flow.md`](design-flow.md): 基板・筐体・FWの工程と第三レーン。
6. [`projection-review.md`](projection-review.md): 投影レビューとPDCAループ。
7. [`tool-selection.md`](tool-selection.md): 実装で使う外部ツールの採否と設計根拠。
8. [`roadmap.md`](roadmap.md): マイルストーン、フェーズ境界、ゴールデンタスク。
9. [`golden-design-1.md`](golden-design-1.md): 第1マイルストーンの具体設計とfixture入力。
10. [`openhands-integration.md`](openhands-integration.md): SDKの利用範囲とACD側の実装境界。
11. [`implementation-plan.md`](implementation-plan.md): リポジトリ構成、パッケージ・Skill・agent分割、CI。
12. [`phase0-plan.md`](phase0-plan.md): Phase 0の作業単位・順序・撤退条件。
13. [`knowledge-base.md`](knowledge-base.md): 知識の構造化と設計への還流。
14. [`reliability-practices.md`](reliability-practices.md): 信頼性・安全性。
15. [`qc-tools.md`](qc-tools.md): Q7/N7分析器。
16. [`prior-art.md`](prior-art.md): 先行事例とライセンス境界。
17. [`future-outlook.md`](future-outlook.md): ローカル製造と将来展望。
18. [`../AGENTS.md`](../AGENTS.md): リポジトリ全体の作業契約。
19. [`../SECURITY.md`](../SECURITY.md): セキュリティポリシーと報告経路。

## 文書一覧

| 文書 | 目的 | ステータス |
|---|---|---|
| `../README.md` | 製品ビジョン、設計原則、全体フロー | Draft |
| `../AGENTS.md` | リポジトリ全体の作業契約 | Draft |
| `../SECURITY.md` | セキュリティポリシーと報告経路 | Draft |
| `README.md` | docs配下の文書索引と読む順序 | Draft |
| `glossary.md` | 用語と工程IDの定義 | Draft |
| `design-flow.md` | 電気・機械・FWレーンの入力・出力・ゲート | Draft |
| `projection-review.md` | 投影レビューとPDCAループ | Draft |
| `knowledge-base.md` | 知識の構造化、スコープ、実測、還流 | Draft |
| `future-outlook.md` | ローカル製造、プリンテッドエレクトロニクス、将来展望 | Draft |
| `architecture.md` | 型付き設計グラフとadapter設計 | Draft |
| `openhands-integration.md` | SDK v1.41.0との統合判断 | Draft |
| `implementation-plan.md` | 実装の構成正本（リポジトリ・パッケージ・Skill・agent・CI） | Draft |
| `phase0-plan.md` | Phase 0の作業単位・順序・撤退条件 | Draft |
| `qc-tools.md` | Q7/N7を使う品質・計画分析 | Draft |
| `tool-selection.md` | 実装で使う外部ツールの採否と設計根拠 | Draft |
| `reliability-practices.md` | JAXA公開資料を根拠にした信頼性方針 | Draft |
| `prior-art.md` | 公開先行事例、API、ライセンス | Draft |
| `roadmap.md` | ACD固有のPhase 0〜11 | Draft |
| `golden-design-1.md` | 第1マイルストーンの具体設計とfixture入力 | Draft |
| `ecad-domain-notes.md` | ECAD領域知識と投影契約 | Draft |
| `review-checklist.md` | RV1/RV2レビュー観点とdisposition運用 | Draft |
| `tool-capability-probes.md` | 外部ツール能力プローブの測定結果と候補 | Draft |
| `adr/ADR-0001-monorepo-structure.md` | uv workspaceによるmonorepo構成 | Accepted |
| `adr/ADR-0002-json-schema-canonical.md` | JSON Schemaを契約の正本とする | Accepted |
| `adr/ADR-0003-sdk-feature-adoption.md` | Phase 0でのSDK機能の採否 | Accepted |
| `adr/ADR-0004-parts-catalog-provenance.md` | 部品カタログとライブラリ出所方針 | Accepted |

`runtime.md`は後続の実装・設計決定で追加する。機械可読契約の正本は`schemas/`、
設計決定は`docs/adr/`にある。未作成の文書へリンクを張らず、必要な場合は本文で
「後続作業」と言及する。
