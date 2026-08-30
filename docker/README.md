# ACDゲート用Dockerイメージ

## 位置づけ

このイメージは、ACDの決定論的pipelineとゲートを構築するためのtools imageである。
agent-server imageのbaseとして使用し、tools imageとagent-server imageをGHCRへpublishする。

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
- FreeRouting wrapperはJVM最大heapを既定`-Xmx2g`として明示し、
  `FREEROUTING_MAX_HEAP`で上書きできる。active processor countは既定では宣言せず、
  必要な場合だけ`FREEROUTING_ACTIVE_PROCESSORS`で`-XX:ActiveProcessorCount=`を
  追加できる。OpenJ9のJVM tuningは既定`-Xtune:footprint`で、
  `FREEROUTING_JVM_TUNING`で上書きできる（選定根拠は
  [`../docs/adr/ADR-0045-openj9-freerouting-runtime.md`](../docs/adr/ADR-0045-openj9-freerouting-runtime.md)）。
  AWTは`-Djava.awt.headless=true`をwrapperへ固定し、ambientな`DISPLAY`やX serverの
  有無にFreeRoutingの実行結果を依存させない
- Java: IBM Semeru Runtime Open Edition 26.0.2.10（Eclipse OpenJ9 0.61.0）を
  `/opt/jre`へ展開し、`JAVA_HOME=/opt/jre`とPATH上の`java`をbuild時に検証する。
  FreeRoutingの共有class cache（SCC+AOT）は`/opt/scc`へbuild時に生成し、実行時は
  read-onlyで再利用する
- ngspice: Ubuntu 26.04の45.2パッケージと`ngspice --version`を検証
- Python: Ubuntu 26.04のsystem Python 3.14（`python3.14`、`python3.14-venv`）
- uv: 0.12.7、配布tarballのSHA-256を検証
- git: revision解決と差分確認のためUbuntu 26.04のパッケージを利用
- CJKフォント: `fonts-noto-cjk`を同梱し、`fc-list`でNoto Sans CJKの存在を検証
- ccache: ESP-IDF再ビルド高速化のため同梱し、`ccache --version`を検証。`CCACHE_DIR`と
  `IDF_CCACHE_ENABLE`をimageで宣言する
- FW build tool: Ubuntu 26.04のCMake 4.2.3（`cmake --version`）とNinja 1.13.2
  （`ninja --version`）を同梱し、container経路でhost側のbuild tool準備を不要にする
- QEMU: Espressif QEMU 9.2.2（`esp-develop-9.2.2-20260417`のriscv32 softmmu tarball）を
  SHA-256検証のうえ`/opt/qemu-esp`へ展開し、`qemu-system-riscv32 --version`が9.2.2で
  あることを検証。`libslirp0`とSDL2共有ライブラリの解決も検証する
- ESP-IDF: v6.1をsubmodule込みでcloneし、esp32c3向けtoolchainとPython環境を
  build時に導入する。ESP-IDFのPython環境はuvが導入した3.12を使い、ACD本体が使う
  system Python 3.14とは分離する。`export.sh`経由の`idf.py --version`が
  `v6.1`であることを検証する
- ACD本体: `pyproject.toml`、`uv.lock`、`src`、`scripts`、`fixtures`、`contracts`、
  `plugins`、vendored SDKを`/opt/acd`へ同梱し、authoritative実行時のリポジトリcloneを
  不要にする
- Python依存のprebake: `/opt/acd`でbuild時に`uv sync --frozen --compile-bytecode`を
  実行し、実行時の依存解決とダウンロードを不要にする。`UV_FROZEN=1`をimageで宣言する
- PEP 723依存のprebake: 同梱する全acd-importing Skill scriptと
  `scripts/probe_pinned_acd_graph.py`のmetadata blockが同一であることをbuild時に検証し、
  probeをonlineで1回、`uv --offline`で1回実行する。これによりpinned `acd`とその
  isolated environmentをimage build時にcacheへ導入し、FW laneの実行時git・ネットワーク
  依存を除く。ホストで新規の`UV_CACHE_DIR`を作成し、同じprobeをonlineで実行して
  `du -sh`した実測値は2.2 GBだった（PEP 723 probe環境のみの測定であり、既存の
  uv cache全体は含めない）。その後、同じcacheを使って`uv run --offline`でprobeが
  成功することも確認した。imageごとの追加容量はbuild後に`docker image inspect`で
  測定する。
- bytecodeキャッシュ: `PYTHONPYCACHEPREFIX=/tmp/acd-pycache`をimageで宣言する。
  `/opt/acd/src`配下へ`__pycache__`が書かれるとeditable installが無効化され、
  実行時にビルドバックエンドのダウンロード（ネットワーク）が発生するため、
  実行時の書き込みをsource treeの外へ退避する

同梱資材の版はDockerfileの`ARG`で固定し、tarballはSHA-256で検証する。build時の検証に
失敗した場合はimageを生成しない。ESP-IDFはgit tagで固定するが、Espressifのtoolchain
downloadはupstreamの配布に依存するため、完全な再現性はimage digestで担保する。

APT由来のパッケージはUbuntuのrepository snapshotを別途固定しない限り、同じ
Dockerfileでも再解決される可能性がある。完全な再現性にはimage digestとAPT
repositoryの固定が必要である。

`docker/**`（lock fileの`docker/image-digests.json`とこのREADMEを除く）または
build contextを決める`.dockerignore`をmainへ変更すると、
`.github/workflows/publish-acd-images.yml`がtools imageとagent-server imageを同一jobで
直列にpublishする。publish結果は`docker/image-digests.json`へ1つの更新PRとして記録する。
lock更新PRはpublish triggerの対象外であり、digest lockと`latest`が再帰的に更新されることはない。

## 事前build済みagent-server image

`docker/image-digests.json`に記録したACD tools image digestをbaseとして、
`vendor/software-agent-sdk/openhands-agent-server/openhands/agent_server/docker/build.py`
がagent-server imageを生成する。toolsを同一jobで再buildした場合も、lock更新PRがまだ
merge前でlockが1世代前を指すため、publish直後の`acd-tools:latest`のdigestをbaseにする。
解決できない場合はfail-closedで停止する。`skip_tools`指定時はlockのdigestをbaseにする。
publishは`publish-acd-images.yml`の手動起動で行い、`skip_tools`を指定した場合はtools imageを
再buildせず、lock済みtools imageをbaseにserverだけを再buildする。job summaryへbase digestと
derived server digestを別々に記録する。derived imageが
publishされるまでlockの`acd_server` entryは未設定であり、未設定のimageをpullしてはならない。

## OpenHands SDKからの利用

`DockerWorkspace(server_image="...@sha256:<digest>")`をSDK委譲の決定論的ゲート実行経路とする。
host経路はprovisional専用であり、合格側Evidenceを生成しない。server digestがlockへ
記録されていない場合は、CLIとCIがfail-closedで停止する。

同梱資材だけで実行する場合は、リポジトリをマウントせずimage内の`/opt/acd`を作業
ディレクトリにする。

```bash
ACD_CONTAINER_IMAGE=ghcr.io/uist1idrju3i/acd-server@sha256:<digest> \
  uv run python scripts/run_in_workspace.py --source bundled \
  uv run python scripts/run_enclosure_pipeline.py --fixture fixtures/golden-design-1 --out out/gd1-enclosure
```

`--source bundled`は`/opt/acd`の`pyproject.toml`、`uv.lock`、`src/acd`、`scripts`、
`fixtures`、`contracts`、prebake済み`.venv`の存在を実行前に検査し、いずれかが欠ける
場合はfail-closedで停止する。開発中の変更を実行する場合は既定の`--source mounted`を
使う。
同梱資材を持つimageがpublishされてlockへ記録されるまで、CIとrunnerの既定経路は
マウント方式のままとする。

```python
from openhands.workspace import DockerWorkspace

with DockerWorkspace(
    server_image="ghcr.io/uist1idrju3i/acd-server@sha256:<digest>",
    volumes=["/absolute/repo/path:/acd-src:ro"],
    forward_env=["ACD_CONTAINER_IMAGE_DIGEST", "ACD_IN_CONTAINER"],
) as workspace:
    result = workspace.execute_command(
        "cd /workspace/acd && uv run python scripts/run_enclosure_pipeline.py "
        "--fixture fixtures/golden-design-1 "
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

ACDはtools imageとagent-server imageをGHCRへ配布する。イメージに含まれる
KiCad（GPLv3）とFreeRouting（GPLv3）のソースおよび対応するソースは各upstreamで
公開されており、このリポジトリではDockerfileに使用版、取得元、取得物のSHA-256を
固定している。配布物の対応関係は、イメージのDockerfile pinと次のupstream source
を組み合わせて確認できる。

- KiCad: GPLv3、sourceと対応するソースは<https://www.kicad.org/>で提供
- FreeRouting: GPLv3、sourceと対応するソースは<https://github.com/freerouting/freerouting>で提供
- ngspice: BSD系ライセンス、<https://ngspice.sourceforge.io/>
- IBM Semeru/OpenJ9: GPLv2 with Classpath Exception、<https://www.ibm.com/semeru-runtimes/>
  および<https://openj9.org/>
- Python: PSF License、<https://www.python.org/>
- uv: MIT License、<https://github.com/astral-sh/uv>

## 手動確認

```bash
docker image inspect --format='{{json .RepoDigests}}' acd-tools-gates:local
docker run --rm acd-tools-gates:local sh -lc \
  'command -v java && java -version 2>&1 && ls -l /opt/scc && freerouting --version && ngspice --version && git --version && uv --version && python3.14 --version'
ACD_CONTAINER_IMAGE=acd-tools-gates:local \
  uv run python scripts/run_in_workspace.py
```

ローカルbuild imageにはRepoDigestsが無いことがある。その場合runnerはimage ID
（`sha256:...`）を使う。どちらも解決できない場合は何も実行しない。
