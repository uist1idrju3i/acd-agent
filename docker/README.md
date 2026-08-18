# ACDゲート用Dockerイメージ

## 位置づけ

このイメージは、ACDの決定論的pipelineとゲートだけをDockerDevWorkspaceで実行するための
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

- Ubuntu: `ubuntu:26.04`
- KiCad CLI: KiCad 10.0 PPAの10系をインストールし、build時に10系であることを検証
- FreeRouting: 2.3.0、GitHub release URL、SHA-256を検証し、`/usr/local/bin/freerouting`
  wrapperからPATH上で実行できることを検証
- OpenJDK: Ubuntu 26.04の`openjdk-25-jre-headless`（25 LTS）
- ngspice: Ubuntu 26.04の45.2パッケージと`ngspice --version`を検証
- Python: Ubuntu 26.04のsystem Python 3.14（`python3.14`、`python3.14-venv`）
- uv: 0.12.3、配布tarballのSHA-256を検証
- git: revision解決と差分確認のためUbuntu 26.04のパッケージを利用

APT由来のパッケージはUbuntuのrepository snapshotを別途固定しない限り、同じ
Dockerfileでも再解決される可能性がある。完全な再現性にはimage digestとAPT
repositoryの固定が必要である。

## OpenHands SDKからの利用

`DockerDevWorkspace(base_image=...)`をSDK委譲の決定論的ゲート実行経路とする。
現行runnerはこのDockerfileからon-the-flyでserver imageをbuildする。事前build済みimageへ
移行した時点では`DockerWorkspace(server_image="...@sha256:<digest>")`へ切り替える。
ホスト実行は合格側Evidenceを生成しない。

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

`scripts/run_in_workspace.py`は上記workspace経路を使用し、image IDまたはRepoDigestを
解決できない場合は実行しない。

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
  'kicad-cli --version && freerouting --version && ngspice --version && git --version && uv --version && python3.14 --version'
ACD_CONTAINER_IMAGE=acd-tools-gates:local \
  uv run python scripts/run_in_workspace.py
```

ローカルbuild imageにはRepoDigestsが無いことがある。その場合runnerはimage ID
（`sha256:...`）を使う。どちらも解決できない場合は何も実行しない。
