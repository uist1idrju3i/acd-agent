# インストール

## 前提

Linux、Python 3.12以上、`uv`、KiCad CLI、Java、FreeRoutingを必要とする。Dockerは
決定論的ゲート実行に必須である。

```bash
git clone --recurse-submodules <repository-url>
cd acd-agent
uv sync
git submodule status
```

`vendor/software-agent-sdk`がv1.42.1のcommitを指すことを確認する。

## 外部ツール

```bash
command -v kicad-cli
command -v java
command -v freerouting
uv run python scripts/probe_tools.py
```

## Dockerゲート

現行runnerは移行中で、次フェーズに`DockerWorkspace`とdigest固定をゲートの正にする。
現在のbuild準備経路は次の通りである。

```bash
docker build -f docker/acd-tools.Dockerfile -t acd-tools-gates:local .
ACD_CONTAINER_IMAGE=acd-tools-gates:local uv run python scripts/run_in_workspace.py
```

digestを解決できない場合はrunnerが実行せず非ゼロ終了する。ホスト実行は参考実行であり、
合格側Evidenceを生成しない。

## pluginと検証

pluginは`plugins/acd`から読み込む。外部配布では40桁commit SHAまたは`v<semver>` tagを使い、
branch、短縮SHA、未指定refは拒否する。文書のみの変更では次を実行する。

```bash
uv run python scripts/verify_docs.py
git diff --check
```
