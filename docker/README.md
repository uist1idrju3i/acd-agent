# ACDゲート用Dockerイメージ

## 位置づけ

このイメージは、ACDの決定論的pipelineとゲートだけをDockerWorkspaceで実行するための
base imageである。agentそのものをコンテナへ移すものではなく、ACD imageとして
再配布もしない。利用者が各自でDockerfileからbuildする。

Dockerはdeterminismを保証しない。時刻、locale、filesystem、CPU、外部サービスなど
の差は残るため、ToolEnvelope、出力hash、timestamp正規化、独立再読込、期待値と
ゲートの規則は引き続き必要である。

## build

```bash
docker build \
  --file docker/acd-tools.Dockerfile \
  --tag acd-tools-gates:local \
  .
```

Dockerfileでは次を固定または検証する。

- KiCad CLI: KiCad 9.0 PPAの9系をインストールし、build時に9系であることを検証
- FreeRouting: 2.1.0、GitHub release URL、SHA-256を検証し、`/usr/local/bin/freerouting`
  wrapperからPATH上で実行できることを検証
- OpenJDK: Ubuntu 24.04の`openjdk-21-jre-headless`
- ngspice: Ubuntu 24.04のパッケージと`ngspice --version`を検証
- Python: Ubuntu 24.04のPython 3.12
- uv: 0.7.12
- git: revision解決と差分確認のためUbuntu 24.04のパッケージを利用

APT由来のパッケージはUbuntuのrepository snapshotを別途固定しない限り、同じ
Dockerfileでも再解決される可能性がある。完全な再現性にはimage digestとAPT
repositoryの固定が必要である。

## OpenHands SDKからの利用

`DockerWorkspace(server_image="...@sha256:<digest>")`を決定論的ゲート実行の正とする。
`DockerDevWorkspace(base_image=...)`は、このDockerfileからagent-server imageをbuildする
準備経路に限定する。現行runnerは移行中であり、ホスト実行は合格側Evidenceを生成しない。

```python
from openhands.workspace.docker import DockerDevWorkspace

with DockerDevWorkspace(
    base_image="acd-tools-gates:local",
    volumes=["/absolute/repo/path:/workspace"],
    forward_env=["ACD_CONTAINER_IMAGE_DIGEST"],
) as workspace:
    result = workspace.execute_command(
        "uv run python scripts/run_gd1_enclosure_pipeline.py "
        "--out out/gd1-enclosure",
        cwd="/workspace",
    )
```

ホスト側の`ACD_CONTAINER_IMAGE_DIGEST`は、runnerが`docker image inspect`から解決
した値を設定する。`forward_env`で同名変数をコンテナへ渡し、ToolEnvelopeの
`execution_env`へ記録する。digestを解決できない場合はworkspaceを起動せず停止する。

## ライセンスとupstream

ACDはこのイメージを配布しない。KiCad（GPLv3）、FreeRouting（GPLv3）などの
GPL系ソフトウェアを含むイメージを配布すると、対応するソース提供やライセンス
義務が発生するためである。各利用者は自分の環境でbuildし、各upstreamの条件に
従うこと。

- KiCad: GPLv3、<https://www.kicad.org/>
- FreeRouting: GPLv3、<https://github.com/freerouting/freerouting>
- ngspice: BSD系ライセンス、<https://ngspice.sourceforge.io/>
- OpenJDK: GPLv2 with Classpath Exception、<https://openjdk.org/>
- Python: PSF License、<https://www.python.org/>
- uv: MIT License、<https://github.com/astral-sh/uv>

## 手動確認

```bash
docker image inspect --format='{{json .RepoDigests}}' acd-tools-gates:local
docker run --rm acd-tools-gates:local sh -lc \
  'command -v freerouting && freerouting --version && command -v ngspice && ngspice --version && command -v git'
ACD_CONTAINER_IMAGE=acd-tools-gates:local \
  uv run python scripts/run_in_workspace.py
```

ローカルbuild imageにはRepoDigestsが無いことがある。その場合runnerはimage ID
（`sha256:...`）を使う。どちらも解決できない場合は何も実行しない。
