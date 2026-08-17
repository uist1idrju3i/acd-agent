# インストール

## 前提

- Linux環境
- Python 3.12以上
- `uv`
- KiCad CLI
- JavaとFreeRouting
- （任意）Docker

OpenHands Software Agent SDKは`vendor/software-agent-sdk`のsubmodule v1.42.1を
workspace sourceとして使用する。Agent Canvasのソースは取得しない。OpenHands公開Skillsは
必要な場合だけ外部repositoryを参照する。

## cloneと依存関係

```bash
git clone --recurse-submodules <repository-url>
cd acd-agent
uv sync
```

submoduleの確認:

```bash
git submodule status
```

`vendor/software-agent-sdk`がv1.42.1のcommitを指していることを確認する。

Dockerでゲートを実行する場合は、[`docker/README.md`](../docker/README.md)に従って
`docker/acd-tools.Dockerfile`を各自buildする。通常のpipelineは引き続きホストで
実行する。

## 外部ツール

環境に次の実行ファイルが必要である。

```bash
command -v kicad-cli
command -v java
command -v freerouting
```

版と能力は次で記録する。

```bash
uv run python scripts/probe_tools.py
```

Docker workspace経路（任意）:

```bash
docker build -f docker/acd-tools.Dockerfile -t acd-tools-gates:local .
ACD_CONTAINER_IMAGE=acd-tools-gates:local uv run python scripts/run_in_workspace.py
```

image digestを解決できない場合、runnerはコマンドを実行せず非ゼロ終了する。

外部ツールが無い、版が不明、または出力を独立再読込できない場合、pipelineは
fail-closedで停止する。ツールの採否判断は[`research/tool-selection.md`](research/tool-selection.md)、
実測は[`tool-capability-probes.md`](tool-capability-probes.md)を参照する。

## plugin

OpenHands SDKから`plugins/acd`をpluginとして読み込む。pluginには7 Skill、4
AgentDefinition、`/acd:gates` command、SDK ToolDefinition、hooksが含まれる。
決定論的なACD入口は`acd_tools.sdk_tools`の明示的な登録関数からSDKへ登録する。

## 検証

```bash
uv run ruff check
uv run pyright
uv run pytest
uv run pytest plugins -q
uv run python scripts/verify_docs.py
uv run python scripts/run_gd1_enclosure_pipeline.py --out out/gd1-enclosure
uv run python scripts/probe_tools.py
git diff --check
```

GD1基板pipelineはERC、routing、SES import、DRC、fabrication出力、独立再読込、
silkscreen可読性ゲートまで通過する。外部ツールや入力が不正な場合は、ゲートを
緩めずfail-closedとして状態をそのまま記録する。

## トラブル時

- `uv sync`が失敗する場合はsubmoduleが初期化されているか確認する。
- 外部ツールが見つからない場合は`probe_tools.py`の結果を確認する。
- graphやfixtureが不正な場合は入力を修正し、エラーを成功扱いにしない。
- 秘密情報をログ、fixture、graph、commitへ書かない。
