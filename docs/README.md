# ACDドキュメント索引

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.43.1

| 文書 | 内容 |
|---|---|
| [`../README.md`](../README.md) | 製品概要 |
| [`../AGENTS.md`](../AGENTS.md) | 作業契約 |
| [`glossary.md`](glossary.md) | 用語定義 |
| [`architecture.md`](architecture.md) | 責務境界 |
| [`openhands-sdk-capabilities.json`](openhands-sdk-capabilities.json) | SDK能力カタログの契約 |
| [`openhands-sdk-capabilities.md`](openhands-sdk-capabilities.md) | SDK能力カタログの説明表 |
| [`gates.md`](gates.md) | 投影と決定論的ゲート |
| [`operations.md`](operations.md) | 運用・インストール |
| [`golden-design-1.md`](golden-design-1.md) | GD1到達状況 |
| [`design-requirement-variation.md`](design-requirement-variation.md) | 要件変更の境界と設計動作の確認 |
| [`vibebb-gap-analysis.md`](vibebb-gap-analysis.md) | VibeBB単体化に向けた機能ギャップと改善提案 |
| [`vibebb-standalone-verification.md`](vibebb-standalone-verification.md) | VibeBB単体成立性の検証記録（M節の項目別） |
| [`vibebb-onpremise-verification.md`](vibebb-onpremise-verification.md) | VibeBB単体成立性の実機検証記録（新規設計・実機OpenHands） |
| [`roadmap.md`](roadmap.md) | 現在地と計画 |
| [`research/README.md`](research/README.md) | 研究結論 |

## ADR

主要な責務統合は[`adr/ADR-0026-openhands-delegation-contract.md`](adr/ADR-0026-openhands-delegation-contract.md)、
実行provenanceは[`adr/ADR-0028-execution-provenance.md`](adr/ADR-0028-execution-provenance.md)、
文書統治は[`adr/ADR-0034-document-governance.md`](adr/ADR-0034-document-governance.md)に記録する。
過去の決定を保持するADRは、各文書のSuperseded pointerから統合先を確認できる。

## Accepted ADR一覧

| ADR | 題 |
|---|---|
| [0005](adr/ADR-0005-jlcpcb-pcba-preparation-contract.md) | PCBA準備契約 |
| [0006](adr/ADR-0006-vendor-submodule-policy.md) | SDK submodule更新方針 |
| [0007](adr/ADR-0007-llm-guided-physical-design.md) | LLM物理設計境界 |
| [0008](adr/ADR-0008-minimal-vibebb-scope.md) | 最小VibeBB範囲 |
| [0021](adr/ADR-0021-design-rationale-records.md) | 設計根拠record |
| [0023](adr/ADR-0023-deterministic-gate-authority.md) | 三層分離と合否権限 |
| [0026](adr/ADR-0026-openhands-delegation-contract.md) | OpenHands委譲契約 |
| [0027](adr/ADR-0027-single-distribution.md) | 単一配布形態 |
| [0028](adr/ADR-0028-execution-provenance.md) | 実行provenanceとauthoritative Evidence |
| [0033](adr/ADR-0033-sdk-capability-adoption.md) | SDK能力の採否とbrowser_use境界 |
| [0034](adr/ADR-0034-document-governance.md) | 文書統治とSDK能力カタログ |
| [0035](adr/ADR-0035-standard-distribution.md) | SDK標準機構による配布とインストール |
| [0036](adr/ADR-0036-ambient-plugin-install.md) | installed plugin自動読み込みによるインストール |
| [0037](adr/ADR-0037-pep723-skill-scripts.md) | PEP 723によるSkill scriptの依存自己解決 |
| [0038](adr/ADR-0038-acd-install-doctor.md) | ACDインストール自己診断入口 |
| [0039](adr/ADR-0039-subagent-skill-reference.md) | sub-agentのSkill参照方式 |
| [0040](adr/ADR-0040-hook-plugin-root-resolution.md) | plugin hookのplugin root解決方式 |
| [0041](adr/ADR-0041-vision-proposals-as-design-candidates.md) | ビジョン出力の宣言層入力境界 |
| [0042](adr/ADR-0042-skill-package-ref-skew.md) | Skill package refのskew検出と事前導入 |
| [0043](adr/ADR-0043-functional-block-contract-registry.md) | 機能ブロック契約registryによる設計述語の適用条件 |
| [0044](adr/ADR-0044-design-freedom-declaration.md) | 探索対象とする設計自由度の宣言とstitch候補Evidence |

上記以外のADRは、統合先を示すSuperseded pointerである。
