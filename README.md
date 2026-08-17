# ACD — Autonomous Computer Design

> ステータス: 開発中。投影・決定論的ゲート・plugin委譲・SDK tools公開まで実装済みです。
> 実機測定、発注、silkscreen再配置ループは未実装です。

ACDは、基板・筐体・ファームウェアをOpenHandsと決定論的な投影・ゲートで扱う
AIファーストCADです。入力ファイルとgitを設計の正とし、AIとSkillは候補を提案し、
ERC/DRC、独立再読込、機械測定などの決定論的ゲートが合否を判定します。

## 製品ビジョン

ACDは、要件から基板・筐体・ファームウェアを設計し、製造データを生成し、検証結果を
次の設計入力へ戻す最小の縦断を目指します。VibeBB（Vibe BreadBoarding）として、
人間は要件のオーナーとフィードバックの提供者に集中し、OpenHandsが対話、Skill、
subagentを使って候補と修正案を整理します。重い検証を人間の手作業から隠すことは
目標ですが、合否は常に決定論的ゲートが担います。

設計は次の3レーンを同じ入力ファイルとgitの履歴から扱います。

- **基板レーン**: 部品、回路意図、配置・配線、ERC/DRC、製造出力。
- **筐体レーン**: 外形、部品高さ、締結、干渉、clearance、肉厚、CAD出力。
- **FWレーン**: OpenHandsへ委譲する実装、ビルド、静的検査、仮想実行。

製造・実機フィードバックを次の入力へ反映するループ、実機測定、発注、量産対応は
将来範囲です。現在の実装状況は、この節ではなく「現在の状態」と
[`docs/roadmap.md`](docs/roadmap.md)に分けて記録します。

## 現在の状態

Golden Design #1の筐体pipelineは通過します。基板pipelineは次の段階まで通過します。

```text
ERC
routing収束
SES import
DRC
fabrication出力
独立再読込
```

その後のsilkscreen可読性ゲートは、Skillが投影前のlibrary由来geometryを使い、
ゲートが生成後Gerber実測を使う判定基準の不一致によりfail-closedとなります。
これは既知の未解決課題であり、今回の実装で閾値・検査・期待値を緩めていません。
解決方向は投影→実測→再配置の反復ループですが、未実装です。

## 構成

```text
acd-schema → acd-core → acd-pipeline → adapters/*
                                      └→ acd-tools (probe / SDK tools)

plugins/acd/
├── skills/       # 7つの探索・FW・レビュー手法
├── agents/       # 電気、機械、FW、レビュー
├── commands/     # /acd:gates
└── hooks/        # SDK fail-closed hooks
```

Python側は契約、投影、adapter、決定論的ゲートに限定する。OpenHands pluginは
Skill、AgentDefinition、command、hooksを配布する。Skill結果は合否根拠ではない。

## 実行

```bash
uv sync
uv run python scripts/run_gd1_enclosure_pipeline.py --out out/gd1-enclosure
uv run python scripts/run_gd1_pipeline.py
uv run python scripts/probe_tools.py
```

基板pipelineのsilkscreen fail-closedは現在の既知状態です。詳細は
[`docs/golden-design-1.md`](docs/golden-design-1.md)、
[`docs/adr/ADR-0011-search-results-as-design-input.md`](docs/adr/ADR-0011-search-results-as-design-input.md)
を参照してください。

## 文書

| 文書 | 内容 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | 作業契約と検証規約 |
| [`docs/README.md`](docs/README.md) | 文書索引 |
| [`docs/architecture.md`](docs/architecture.md) | 実装境界 |
| [`docs/openhands-integration.md`](docs/openhands-integration.md) | OpenHands統合 |
| [`docs/roadmap.md`](docs/roadmap.md) | 現行計画と将来構想 |
| [`docs/research/`](docs/research/) | 調査記録 |
| [`docs/adr/`](docs/adr/) | 設計決定 |

## ライセンス

BSD 3-Clause。Copyright (c) Y. Yamashiro。
