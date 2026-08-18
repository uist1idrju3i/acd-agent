# ACDドキュメント索引

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.42.1

| 文書 | 内容 |
|---|---|
| [`../README.md`](../README.md) | 製品概要 |
| [`glossary.md`](glossary.md) | 用語定義 |
| [`architecture.md`](architecture.md) | 責務境界 |
| [`openhands-sdk-capabilities.json`](openhands-sdk-capabilities.json) | SDK能力カタログの契約 |
| [`openhands-sdk-capabilities.md`](openhands-sdk-capabilities.md) | SDK能力カタログの説明表 |
| [`gates.md`](gates.md) | 投影と決定論的ゲート |
| [`operations.md`](operations.md) | 運用・インストール |
| [`golden-design-1.md`](golden-design-1.md) | GD1到達状況 |
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

上記以外のADRは、統合先を示すSuperseded pointerである。
