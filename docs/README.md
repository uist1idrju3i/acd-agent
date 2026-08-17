# ACDドキュメント索引

> ステータス: Draft
> 対象: OpenHands Software Agent SDK v1.42.1

## 読む順序

| 文書 | 内容 | 位置づけ |
|---|---|---|
| [`../README.md`](../README.md) | 製品概要と現状 | 入口 |
| [`glossary.md`](glossary.md) | 用語と工程ID | 規範 |
| [`architecture.md`](architecture.md) | パッケージ、plugin、責務境界 | 規範 |
| [`design-flow.md`](design-flow.md) | 電気・機械・FWレーン | 規範 |
| [`openhands-integration.md`](openhands-integration.md) | SDK統合面と未実装境界 | 規範 |
| [`openhands-sdk-adoption.md`](openhands-sdk-adoption.md) | SDK活用分析と段階計画 | 計画 |
| [`roadmap.md`](roadmap.md) | 近い順の実装計画と将来構想 | 計画 |
| [`implementation-plan.md`](implementation-plan.md) | 直近作業の分解 | 計画 |
| [`installation.md`](installation.md) | 現行ツールチェーンの導入 | 運用 |
| [`golden-design-1.md`](golden-design-1.md) | GD1 fixtureと到達状況 | 規範 |
| [`projection-review.md`](projection-review.md) | 投影レビュー | 規範 |
| [`dependency-notes.md`](dependency-notes.md) | 依存と一次情報 | 対応関係の正 |
| [`tool-capability-probes.md`](tool-capability-probes.md) | 外部ツール能力の実測 | 記録 |

## 調査記録

大型の調査文書は[`research/`](research)へ移設した。現行仕様と混同しないが、
他文書から参照される要求・採否判断・出典は保持する。

| 文書 | 内容 |
|---|---|
| [`research/prior-art.md`](research/prior-art.md) | 先行事例とライセンス境界 |
| [`research/tool-selection.md`](research/tool-selection.md) | 外部ツールの採否判断 |
| [`research/ecad-domain-notes.md`](research/ecad-domain-notes.md) | ECAD領域知識 |
| [`research/ai-physical-design.md`](research/ai-physical-design.md) | AI主導の物理設計 |
| [`research/qc-tools.md`](research/qc-tools.md) | Q7/N7手法 |
| [`research/reliability-practices.md`](research/reliability-practices.md) | 信頼性・ディレーティング |
| [`research/future-outlook.md`](research/future-outlook.md) | 将来展望 |

## ADR

設計決定は[`adr/`](adr)に記録する。現行の重要な決定は次のとおり。

- [`ADR-0008-minimal-vibebb-scope.md`](adr/ADR-0008-minimal-vibebb-scope.md): 最小構成
- [`ADR-0009-openhands-delegation-and-skills.md`](adr/ADR-0009-openhands-delegation-and-skills.md): Skill委譲
- [`ADR-0010-plugin-first-openhands-integration.md`](adr/ADR-0010-plugin-first-openhands-integration.md): plugin-first
- [`ADR-0011-search-results-as-design-input.md`](adr/ADR-0011-search-results-as-design-input.md): 探索結果の設計入力化
- [`ADR-0012-design-rationale-records.md`](adr/ADR-0012-design-rationale-records.md): 設計根拠record
- [`ADR-0012-silkscreen-observation-boundary.md`](adr/ADR-0012-silkscreen-observation-boundary.md): silkscreen観測範囲とevidence要約
- [`ADR-0013-openhands-sdk-runtime-adoption.md`](adr/ADR-0013-openhands-sdk-runtime-adoption.md): SDKランタイム機能の段階採用
- [`ADR-0013-rationale-coverage-scope.md`](adr/ADR-0013-rationale-coverage-scope.md): 設計根拠coverageの必須範囲と免除分類
- [`ADR-0014-sdk-tool-definitions.md`](adr/ADR-0014-sdk-tool-definitions.md): SDK ToolDefinitionへの一本化
- [`ADR-0015-docker-workspace-gate-execution.md`](adr/ADR-0015-docker-workspace-gate-execution.md): Docker workspaceによるゲート実行

Skillの実行結果は合否根拠ではない。合否は入力ファイルと決定論的ゲートだけが決める。
