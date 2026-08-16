# ACDドキュメント索引

> ステータス: Draft  
> 対象: ACDコンセプト段階、OpenHands SDK v1.42.1、調査日 2026-08-11

本索引は`docs/`の文書一覧と読む順序を正とする。各文書は、冒頭の対象範囲と
関連文書へのリンクを基準に、個別の仕様・調査・運用方針を記述する。

## 読む順序

1. [`../README.md`](../README.md): ビジョン、原則、全体フロー。
2. [`glossary.md`](glossary.md): 用語と工程IDの定義。
3. [`installation.md`](installation.md): OpenHands Agent Canvasとacd-agentの導入手順。
4. [`architecture.md`](architecture.md): 入力ファイル、投影、レイヤ境界。
5. [`ecad-domain-notes.md`](ecad-domain-notes.md): ECAD領域知識と投影契約。
6. [`design-flow.md`](design-flow.md): 基板・筐体・FWの工程と第三レーン。
7. [`ai-physical-design.md`](ai-physical-design.md): AI主導の配置・回転・配線探索。
8. [`projection-review.md`](projection-review.md): 機械可読投影と視覚投影のレビュー。
9. [`tool-selection.md`](tool-selection.md): 実装で使う外部ツールの採否と設計根拠。
10. [`roadmap.md`](roadmap.md): マイルストーン、フェーズ境界、ゴールデンタスク。
11. [`golden-design-1.md`](golden-design-1.md): 第1マイルストーンの具体設計とfixture入力。
12. [`openhands-integration.md`](openhands-integration.md): SDKの利用範囲とACD側の実装境界。
13. [`dependency-notes.md`](dependency-notes.md): 依存更新時の一次情報、使用箇所、関連文書の対応表。
14. [`implementation-plan.md`](implementation-plan.md): リポジトリ構成、パッケージ・Skill・agent分割、CI。
15. [`reliability-practices.md`](reliability-practices.md): 信頼性・安全性。
16. [`qc-tools.md`](qc-tools.md): Q7/N7のAI作業手法と品質分析。
17. [`prior-art.md`](prior-art.md): 先行事例とライセンス境界。
18. [`future-outlook.md`](future-outlook.md): ローカル製造と将来展望。
19. [`../AGENTS.md`](../AGENTS.md): リポジトリ全体の作業契約。
20. [`../SECURITY.md`](../SECURITY.md): セキュリティポリシーと報告経路。
21. [`adr/ADR-0008-minimal-vibebb-scope.md`](adr/ADR-0008-minimal-vibebb-scope.md): VibeBBの最小構成とSDK優先の実装境界。

## 文書一覧

| 文書 | 目的 | ステータス |
|---|---|---|
| `../README.md` | 製品ビジョン、設計原則、全体フロー | Draft |
| `../AGENTS.md` | リポジトリ全体の作業契約 | Draft |
| `../SECURITY.md` | セキュリティポリシーと報告経路 | Draft |
| `adr/ADR-0008-minimal-vibebb-scope.md` | VibeBBの最小構成とSDK優先の実装境界 | Accepted |
| `README.md` | docs配下の文書索引と読む順序 | Draft |
| `glossary.md` | 用語と工程IDの定義 | Draft |
| `installation.md` | OpenHands Agent Canvasとacd-agentの導入手順 | Draft |
| `design-flow.md` | 電気・機械・FWレーンの入力・出力・ゲート | Draft |
| `ai-physical-design.md` | AI主導の配置・回転・配線探索 | Draft |
| `projection-review.md` | 機械可読投影と視覚投影のレビュー | Draft |
| `future-outlook.md` | ローカル製造、プリンテッドエレクトロニクス、将来展望 | Draft |
| `architecture.md` | 入力ファイル、投影、adapter設計 | Draft |
| `openhands-integration.md` | SDK v1.42.1との統合判断 | Draft |
| `dependency-notes.md` | 依存更新時の一次情報、使用箇所、関連文書の対応表（対応関係の正） | Draft |
| `implementation-plan.md` | 実装の構成正本（リポジトリ・パッケージ・Skill・agent・CI） | Draft |
| `qc-tools.md` | 将来の高信頼化に関する品質・計画分析 | Draft |
| `tool-selection.md` | 実装で使う外部ツールの採否と設計根拠 | Draft |
| `reliability-practices.md` | JAXA公開資料を根拠にした信頼性方針 | Draft |
| `prior-art.md` | 公開先行事例、API、ライセンス | Draft |
| `roadmap.md` | ACD固有のPhase 0〜11 | Draft |
| `golden-design-1.md` | 第1マイルストーンの具体設計とfixture入力 | Draft |
| `ecad-domain-notes.md` | ECAD領域知識と投影契約 | Draft |
| `review-checklist.md` | 機械可読投影と視覚投影のレビュー観点 | Draft |
| `tool-capability-probes.md` | 外部ツール能力プローブの測定結果と候補 | Draft |
| `adr/ADR-0001-monorepo-structure.md` | uv workspaceによるmonorepo構成（acd-schema、acd-core、acd-tools、acd-runtime、adapters） | Accepted |
| `adr/ADR-0002-json-schema-canonical.md` | JSON Schemaを契約の正本とする（ADR-0008により廃止） | Superseded by ADR-0008 |
| `adr/ADR-0003-sdk-feature-adoption.md` | Phase 0でのSDK機能の採否 | Accepted |
| `adr/ADR-0004-parts-catalog-provenance.md` | 部品カタログとライブラリ出所方針 | Accepted |
| `adr/ADR-0005-jlcpcb-pcba-preparation-contract.md` | JLCPCB PCBA準備契約 | Accepted |
| `adr/ADR-0006-vendor-submodule-policy.md` | vendor submoduleの対象と固定方針 | Accepted |
| `adr/ADR-0007-llm-guided-physical-design.md` | LLM主導の物理設計探索の三層分離 | Accepted |

`runtime.md`は後続の実装・設計決定で追加する。契約の正はPydanticモデル、
設計決定は`docs/adr/`にある。未作成の文書へリンクを張らず、必要な場合は本文で
「後続作業」と言及する。
