# ACD — Autonomous Computer Design

> ステータス: 開発中。決定論的ゲート、OpenHands plugin、Conversation経路を実装済みです。
> DockerWorkspace一本化とagent-server受け入れ条件は次フェーズです。

ACDは、基板・筐体・ファームウェアをOpenHandsと決定論的な投影・ゲートで扱う
AIファーストCADです。AIとSkillは候補を提案し、ERC/DRC、独立再読込、機械測定などの
決定論的ゲートが合否を判定します。

## 構成

```text
acd-schema → acd-core → acd-pipeline → adapters/*
                                      └→ acd-tools
plugins/acd/ → Skill / AgentDefinition / command / hooks
vendor/software-agent-sdk/ → OpenHands SDK v1.42.1
```

本リポジトリはOpenHands専用拡張です。MCP互換層、ACP、Agent Canvas、Apptainer、remote_api、
cloud workspaceは提供しません。境界は[`docs/architecture.md`](docs/architecture.md)、SDKの
採否は[`docs/openhands-sdk-capabilities.md`](docs/openhands-sdk-capabilities.md)を参照してください。

## 実行

```bash
uv sync
uv run python scripts/run_gd1_enclosure_pipeline.py --out out/gd1-enclosure
uv run python scripts/run_gd1_pipeline.py
uv run python scripts/probe_tools.py
```

決定論的ゲートの正はdigest固定のDockerWorkspaceです。現行runnerは移行中で、DockerDevWorkspace
によるbuild準備とホスト実行が残っています。digest不明またはホスト実行のEvidenceは合格側に
使用しません。

## 文書

- [`AGENTS.md`](AGENTS.md): 作業契約
- [`docs/README.md`](docs/README.md): 文書索引
- [`docs/architecture.md`](docs/architecture.md): 境界の単一の正
- [`docs/roadmap.md`](docs/roadmap.md): 現在地と計画
- [`docs/adr/`](docs/adr/): 設計決定
