# ACD — Autonomous Computer Design

> ステータス: 開発中。決定論的ゲート、OpenHands plugin、Conversation経路を実装済みです。
> runnerは事前build済みdigest固定DockerWorkspaceへ移行済みです。
> 実機測定、価格・在庫・納期取得、発注は未実装です。計画とフェーズは
> [`docs/roadmap.md`](docs/roadmap.md)を参照してください。

ACDは、基板・筐体・ファームウェアをOpenHandsと決定論的な投影・ゲートで扱う
AIファーストCADです。AIとSkillは候補を提案し、ERC/DRC、独立再読込、機械測定などの
決定論的ゲートが合否を判定します。

## 構成

```text
acd.schema → acd.core → acd.pipeline → acd.adapters.*
                                    └→ acd.openhands
plugins/acd/ → Skill / AgentDefinition / command / hooks
vendor/software-agent-sdk/ → OpenHands SDK v1.42.1
```

本リポジトリはOpenHands専用拡張です。境界と不採用機能は
[`docs/adr/ADR-0026-openhands-delegation-contract.md`](docs/adr/ADR-0026-openhands-delegation-contract.md)、
SDKの採否は[`docs/openhands-sdk-capabilities.json`](docs/openhands-sdk-capabilities.json)を正とし、
説明表は[`docs/openhands-sdk-capabilities.md`](docs/openhands-sdk-capabilities.md)で確認できます。
文書統治は[`docs/adr/ADR-0034-document-governance.md`](docs/adr/ADR-0034-document-governance.md)に従い、
agent-serverは対象外です。

Python配布物はルートの単一パッケージ`acd`であり、実装は`src/acd/`、テストは
`tests/`に配置します。

## インストール

OpenHands環境へは、Pythonパッケージ`acd`のgitインストールと、SDK標準の
installed plugin storeへのplugin installで導入できます。

```bash
uv pip install "git+https://github.com/uist1idrju3i/acd-agent@<tag or SHA>"
```

pluginはOpenHandsのLocal GUI（Agent Canvas）の「カスタマイズ → Plugins →
プラグインを追加」から、ソース`github:uist1idrju3i/acd-agent`、パス`plugins/acd`で
インストールできます。CLI手順と詳細は
[`docs/operations.md`](docs/operations.md)を参照してください。

## 実行

```bash
uv sync
uv run python scripts/run_gd1_enclosure_pipeline.py --out out/gd1-enclosure
uv run python scripts/run_gd1_pipeline.py
uv run python scripts/probe_tools.py
```

決定論的ゲートの正はdigest固定containerです。runnerはlockから解決したserver imageを
DockerWorkspaceへ渡します。digest不明またはホスト実行のEvidenceは合格側に使用しません。
ホスト経路はprovisional専用であり、経路がunknownの場合はfail-closedです。OpenHands固有の境界と
不採用機能は[`docs/adr/ADR-0026-openhands-delegation-contract.md`](docs/adr/ADR-0026-openhands-delegation-contract.md)
を参照してください。

## 文書

- [`AGENTS.md`](AGENTS.md): 作業契約
- [`docs/README.md`](docs/README.md): 文書索引
- [`docs/architecture.md`](docs/architecture.md): 境界の単一の正
- [`docs/roadmap.md`](docs/roadmap.md): 現在地と計画
- [`docs/adr/`](docs/adr/): 設計決定
