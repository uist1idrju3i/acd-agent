# ACDドキュメント索引

> ステータス: Draft
> 対象: OpenHands SDK v1.42.1

本索引は`docs/`の文書一覧と読む順序を正とする。各文書は、冒頭の対象範囲と
関連文書へのリンクを基準に、個別の仕様・調査・運用方針を記述する。
表は上から順に読む前提で並べる。

## 文書一覧

| 文書 | 目的 | 位置づけ |
|---|---|---|
| [`../README.md`](../README.md) | 製品ビジョン、設計原則、全体フロー | ビジョンの正 |
| [`glossary.md`](glossary.md) | 用語と工程IDの定義 | 規範 |
| [`adr/ADR-0008-minimal-vibebb-scope.md`](adr/ADR-0008-minimal-vibebb-scope.md) | VibeBBの最小構成とSDK優先の実装境界 | 現行方針の正 |
| [`installation.md`](installation.md) | OpenHandsとacd-agentの導入手順 | 運用 |
| [`architecture.md`](architecture.md) | 入力ファイル、投影、レイヤ境界 | 規範 |
| [`design-flow.md`](design-flow.md) | 電気・機械・FWレーンの工程とゲート | 規範 |
| [`projection-review.md`](projection-review.md) | 機械可読投影と視覚投影のレビュー | 規範 |
| [`ai-physical-design.md`](ai-physical-design.md) | AI主導の配置・回転・配線探索 | 規範 |
| [`ecad-domain-notes.md`](ecad-domain-notes.md) | ECAD領域知識と投影契約 | 調査 |
| [`tool-selection.md`](tool-selection.md) | 外部ツールの採否と設計根拠 | 調査 |
| [`tool-capability-probes.md`](tool-capability-probes.md) | 外部ツール能力プローブの測定結果 | 実測記録 |
| [`roadmap.md`](roadmap.md) | フェーズ境界と到達状況 | 規範 |
| [`golden-design-1.md`](golden-design-1.md) | Golden Design #1の具体設計とfixture入力 | 規範 |
| [`openhands-integration.md`](openhands-integration.md) | SDKの利用範囲とACD側の実装境界 | 規範 |
| [`implementation-plan.md`](implementation-plan.md) | リポジトリ構成、パッケージ分割、CI | 規範 |
| [`dependency-notes.md`](dependency-notes.md) | 依存更新時の一次情報と関連文書の対応表 | 対応関係の正 |
| [`qc-tools.md`](qc-tools.md) | Q7/N7の作業手法 | 将来調査 |
| [`reliability-practices.md`](reliability-practices.md) | JAXA公開資料を根拠にした信頼性方針 | 将来調査 |
| [`prior-art.md`](prior-art.md) | 公開先行事例、API、ライセンス境界 | 調査 |
| [`future-outlook.md`](future-outlook.md) | ローカル製造と将来展望 | 将来調査 |
| [`../AGENTS.md`](../AGENTS.md) | リポジトリ全体の作業契約 | 規範 |
| [`../SECURITY.md`](../SECURITY.md) | セキュリティポリシーと報告経路 | 規範 |
| [`adr/`](adr) | 設計決定の記録（ADR） | 決定の正 |

「将来調査」の文書は現行の要求ではなく、将来の高信頼化・拡張に向けた調査記録である。
現行仕様として読まない。

## ADR一覧

| ADR | 決定 | 状態 |
|---|---|---|
| [`adr/ADR-0001-monorepo-structure.md`](adr/ADR-0001-monorepo-structure.md) | uv workspaceによるmonorepo構成 | Accepted |
| [`adr/ADR-0002-json-schema-canonical.md`](adr/ADR-0002-json-schema-canonical.md) | JSON Schemaを契約の正本とする | Superseded by ADR-0008 |
| [`adr/ADR-0003-sdk-feature-adoption.md`](adr/ADR-0003-sdk-feature-adoption.md) | SDK機能の採否 | Accepted |
| [`adr/ADR-0004-parts-catalog-provenance.md`](adr/ADR-0004-parts-catalog-provenance.md) | 部品カタログとライブラリ出所方針 | Accepted |
| [`adr/ADR-0005-jlcpcb-pcba-preparation-contract.md`](adr/ADR-0005-jlcpcb-pcba-preparation-contract.md) | JLCPCB PCBA準備契約 | Accepted |
| [`adr/ADR-0006-vendor-submodule-policy.md`](adr/ADR-0006-vendor-submodule-policy.md) | vendor submoduleの対象と固定方針 | Accepted |
| [`adr/ADR-0007-llm-guided-physical-design.md`](adr/ADR-0007-llm-guided-physical-design.md) | LLM主導の物理設計探索の三層分離 | Accepted |
| [`adr/ADR-0008-minimal-vibebb-scope.md`](adr/ADR-0008-minimal-vibebb-scope.md) | VibeBBの最小構成とSDK優先 | Accepted |

契約の正はPydanticモデルであり、設計決定は`docs/adr/`にある。
未作成の文書へリンクを張らず、必要な場合は本文で「後続作業」と言及する。
