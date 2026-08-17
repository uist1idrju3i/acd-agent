# ACDゲート用Dockerイメージ

## 位置づけ

このimageはACDの決定論的pipelineとゲートを実行するため、利用者が各自buildする。
ACDはimageを再配布しない。Dockerはdeterminismを保証しないため、ToolEnvelope、出力hash、
timestamp正規化、独立再読込、決定論的ゲートは引き続き必要である。

## build

```bash
docker build --file docker/acd-tools.Dockerfile --tag acd-tools-gates:local .
```

Dockerfileの現行pinはKiCad 9系、FreeRouting 2.1.0、OpenJDK 21、ngspice、Python 3.12、
uv 0.7.12である。DockerWorkspace一本化に伴い、次フェーズでKiCadを10系へ更新する。
GD1の期待値はKiCad 10.0.5を基準とする。

## SDK workspace

`DockerWorkspace(server_image=...)`をdigest固定のゲート実行の正とする。現行の
`DockerDevWorkspace(base_image=...)`はACD tools imageからagent-server imageをbuildする準備
経路に限る。

```python
from openhands.workspace.docker import DockerWorkspace

with DockerWorkspace(
    server_image="ghcr.io/openhands/agent-server:tag@sha256:<digest>",
    volumes=["/absolute/repo/path:/workspace"],
) as workspace:
    result = workspace.execute_command("uv run python scripts/run_gd1_pipeline.py", cwd="/workspace")
```

SDKの`server_image`は文字列をDocker runへ渡すためdigest参照を受け取れる構造だが、SDKが
digest固定を自動検証するわけではない。runner側で解決・記録し、digest不明は停止する。
