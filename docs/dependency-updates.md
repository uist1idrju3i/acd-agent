# 依存更新記録

依存、submodule、外部ツールの更新確認手順と、更新時に使用API・既定値・破壊的変更・採否を
追記する記録である。運用手順は[`operations.md`](operations.md)、更新方針は
[`adr/ADR-0006-vendor-submodule-policy.md`](adr/ADR-0006-vendor-submodule-policy.md)を参照する。

## 依存アップデートの確認

### CalculiX（ccx）のtools image運用

機械解析のFEM経路で使うCalculiXはGPLツールのため、ACDへimportせず
`acd.core.runtime.process.run_tool`から`ccx` subprocessとしてだけ起動する。tools imageの
DockerfileにはUbuntu archiveの`calculix-ccx`を追加し、`scripts/measure_image_tools.py`
が`ccx -v`から版を抽出する。`ccx -v`はstdoutへ`This is Version 2.21`形式の
版バナーを出して終了コード201で終わるため、probe経路ではバナーが読めたときだけ
非ゼロ終了を成功として扱う（解析実行`ccx <jobname>`は正常終了で0）。現行の
digest lockにはまだccxの測定値が無いため、
`docker/image-digests.json`へ版を推測記入せず、依存更新レポートでは
`未計測（次回publishで記録）`として扱う。imageをpublishして実測した後にだけlockへ
転記する。

Ubuntu archiveのhost確認では`calculix-ccx`候補が`2.17-3`として観測されたが、
hostのarchive系列と将来のUbuntu 26.04 publish imageの実測値を同一視しない。
上流比較はLaunchpadの`calculix-ccx` sourceページを対象にし、lockの値が無い間も
checkerが例外で停止しないようにする。

FEMのdropは`v=sqrt(2gh)`と`a=v²/(2*crush_distance)`による等価静的近似であり、
完全な過渡衝撃解析ではない。`fixtures/fem/gd1-drop.dat`はreal ccxが利用できない
host向けのsynthetic parser fixtureで、CalculiX結果やauthoritative Evidenceではない。

### clang-tidyのtools image運用

FWのopt-in静的解析で使用する`clang-tidy`はGPL境界を越えてimportせず、
subprocessとして起動する。tools imageのapt package、`clang-tidy --version`測定、
LaunchpadのLLVM toolchain apt sourceを`measure_image_tools.py`と
`check_dependency_updates.py`で管理する。image lockへ実測値が無い場合は、値を推測して
追加せず`未計測（次回publishで記録）`として扱う。

clang-tidyのchecks listは
`plugins/acd/skills/acd-firmware-esp32c3/rules/clang_tidy_checks.json`に固定し、
compile commands、target、GCC toolchainの出所を解析入力に含める。warning、error、
malformed diagnostics、tool/version不一致はpassへ変換しない。結果はstatic-analysis
estimateであり、authoritative Evidenceではない。

### clang-tidyのtools image運用

FWのopt-in静的解析で使用する`clang-tidy`はGPL境界を越えてimportせず、
subprocessとして起動する。tools imageのapt package、`clang-tidy --version`測定、
LaunchpadのLLVM toolchain apt sourceを`measure_image_tools.py`と
`check_dependency_updates.py`で管理する。image lockへ実測値が無い場合は、値を推測して
追加せず`未計測（次回publishで記録）`として扱う。

clang-tidyのchecks listは
`plugins/acd/skills/acd-firmware-esp32c3/rules/clang_tidy_checks.json`に固定し、
compile commands、target、GCC toolchainの出所を解析入力に含める。warning、error、
malformed diagnostics、tool/version不一致はpassへ変換しない。結果はstatic-analysis
estimateであり、authoritative Evidenceではない。

### gcovrのtools image運用

FW coverageのhost-side parserは`gcovr --json`の出力だけをsubprocess境界で
読み取り、gcovr自体をACDへimportしない。tools imageでは`GCOVR_VERSION`を固定した
PyPI packageを`uv pip install --system --break-system-packages`で導入し
（Ubuntu 26.04のpython3.14はPEP 668のexternally managed環境で、`--system`だけでは
uvが導入を拒否する）、`measure_image_tools.py`が
`gcovr --version`を測定する。image lockに新しい測定値が無い間は
`docker/image-digests.json`へ推測値を追記せず、次回publishで記録する。
依存checkerはDocker ARGをPyPIのgcovr versionと照合する。

ESP-IDF/QEMUの実run dumpは`esp_gcov_dump()`をgenerated virtual-run end markerから
呼び出す方式を選択した。hostにESP-IDF/QEMUが無い場合はreal runをpassへ変換せず
unknownとし、synthetic gcovr JSON parser fixtureだけを検証する。

HILのGD1 plan/run/logはsynthetic fixtureであり、実機計測値ではない。ingest結果は
既存のmeasured PhysicalEvidence消費経路へ渡せるが、authoritative pass Evidenceには
昇格しない。feedback proposalの既存意味論は変更しない。

`libraries/README.md`のgit pinは、EspressifとCERNを含む全sourceを確認する。

[`.github/workflows/check-dependency-updates.yml`](../.github/workflows/check-dependency-updates.yml)は週次および手動で`scripts/check_dependency_updates.py`を実行し、更新候補をIssue「依存アップデート確認レポート」へ報告する。確認対象は、PyPIの直接依存と`uv.lock`間接依存、`vendor/software-agent-sdk` submoduleと`openhands-sdk`・`openhands-tools`・`openhands-workspace` pin、`.github/workflows/*.yml`の`uses:`とrelease download、Docker base imageとバージョンARG、`docker/image-digests.json`のtools上流版、Python版、`libraries/README.md`のgit pin、Semeruの新major、`src/acd/adapters/cad/viewer_assets/three/`のvendored three.jsである。ngspice、cmake、ninja、ccache、git、python3.14などapt管理のツールはLaunchpadのUbuntu archive版を比較し、上流版は注記として併記する。ローカル実行にはネットワークとuvが必要である。レポートは更新不要の項目も`最新`として掲載し、確認対象の漏れを目視できるようにする。互換性や移行検証で保留する項目は`scripts/dependency_update_deferrals.json`に対象版、理由、再確認期限を記録し、期限到来または新版出現時に再候補化する。

### 2026-09 更新記録

- **FreeRouting v2.4.1**（一次情報: [v2.4.1 release](https://github.com/freerouting/freerouting/releases/tag/v2.4.1)、[`command_line_arguments.md`](https://github.com/freerouting/freerouting/blob/v2.4.1/docs/command_line_arguments.md)）。Java 25 build baseline、routing pipeline統合、`.frb`廃止、DSN隣接`.rules`自動探索が変更・追加された。ACD adapterが使う`-de`、`-do`、`-mp`、`-mt`は不変。ACDは`.rules`を書き出さず、KiCadの`.kicad_dru`を生成するため、`.rules`自動探索の影響はない。採否: 採用。
- **uv 0.12.10**（一次情報: [0.12.10 release](https://github.com/astral-sh/uv/releases/tag/0.12.10)）。trusted publishing tokenの失効処理、lock/treeの改善、性能向上とバグ修正が含まれ、現行利用方法に対する破壊的変更はない。採否: 採用。
- **IBM Semeru 27**（一次情報: [semeru27-binaries releases](https://github.com/ibmruntimes/semeru27-binaries/releases)）。GA releaseがなくprereleaseのみのため、Semeru 26からの更新は保留。checkerもGA releaseがあるmajorだけを更新候補とし、prerelease-only majorは注記に留める。
- **ツール上流版**（ngspice、cmake、ccache、git、python3.14）。Ubuntu 26.04のapt由来ツールはLaunchpadのUbuntu archive版を比較し、image再publish時に追従する。上流版との差分は注記として確認するため、現行archive版と一致する項目は採否: 最新。
- **three.js 0.186.0**（一次情報: [npm package](https://www.npmjs.com/package/three) / [r186 release](https://github.com/mrdoob/three.js/releases/tag/r186)）。統合3Dモデル投影（11.4a）のHTMLビューア用に`three.module.js`・`three.core.js`・`OrbitControls.js`・`GLTFLoader.js`・`BufferGeometryUtils.js`・`SkeletonUtils.js`の6つのESM fileのみを`src/acd/adapters/cad/viewer_assets/three/`へ改変なしにvendoringした（MIT）。相対importはbundleせず、HTML生成時にimport mapのbare specifierへ書き換える。採否: 採用。

Docker ARG（FreeRouting 2.4.1、uv 0.12.10、Semeru 27）の判断は本節の該当項目で扱う。

```bash
uv run python scripts/check_dependency_updates.py --markdown out/dependency-updates.md
```

SemeruはJava majorごとに別repositoryを使うため、現在のARGのmajorに対応するrepositoryと新しいmajorの有無を確認する。apt由来のツールはinstall済みversionを`docker/image-digests.json`の`tools`へpublish時に記録し、LaunchpadのUbuntu archive版と照合する。KiCad（PPA由来）は`kicad-source-mirror` tag、ngspiceはSourceForge best releaseを上流版として注記する。versionを記録しないaptパッケージ（fonts、`libcairo2`等）は個別確認せず、Ubuntu base imageの確認に従う。ESP-IDFの`idf_tools.py`が解決するtoolchain binaryはESP-IDF tagで固定されるため個別確認しない。Skill scriptのPEP 723 `acd @ git+…@<sha>` refは`update-skill-package-ref.yml`が管理するため対象外とし、vendor内SDKのagent-server base imageも対象外とする。新しいimage toolを`docker/image-digests.json`の`tools`へ記録する場合は`TOOL_UPSTREAM_SPECS`へ上流取得元を追加する。更新候補が無くなると、対応するIssueはworkflowが自動でcloseする。自動更新PRは作成せず、更新時は本書と`AGENTS.md`の手順に従う。

### 2026-09 更新記録

- **pydantic 2.13.5**
  - 一次情報: [Pydantic v2.13.5 release](https://github.com/pydantic/pydantic/releases/tag/v2.13.5)
  - 破壊的変更/新機能: validator再利用、`pydantic-core`のGC traversal、smart unionの修正。破壊的変更は確認されなかった。
  - 採否: 採用。修正のみで、Pydanticモデル契約への変更はない。
- **ruff 0.16.6**
  - 一次情報: [Ruff 0.16.6 release](https://github.com/astral-sh/ruff/releases/tag/0.16.6)
  - 破壊的変更/新機能: preview rule分類、`PT020` autofix、`I001` pragma除外等。新しいMarkdown fenced Python code block format機能は、略記snippetを含む文書を変更するため不採用とした。
  - 採否: 採用。`pyproject.toml`の`include`をPythonと`pyproject.toml`に限定し、Markdownはformat対象外とする。
- **actions/cache v6.1.0**
  - 一次情報: [actions/cache v6.1.0 release](https://github.com/actions/cache/releases/tag/v6.1.0)、[README](https://github.com/actions/cache/blob/v6.1.0/README.md)
  - 破壊的変更/新機能: v5からNode 24 runtime、Actions Runner 2.327.1以上。v6はESM移行、v6.1.0はread-only cache access対応を含む。
  - 採否: 採用。GitHub-hosted runnerのためNode 24/runner 2.327.1以上の要件は充足する。
- **actionlint v1.7.12**
  - 一次情報: [actionlint v1.7.12 release](https://github.com/rhysd/actionlint/releases/tag/v1.7.12)
  - 破壊的変更/新機能: `on.schedule.timezone`のIANA timezone検証、environment deployment、macOS 26 Intel runner label対応。Go 1.24対応は終了した。
  - 採否: 採用。現行workflowはtimezone等を使わず、検査への影響はない。
- **uv.lock間接依存**
  - 一次情報: `uv lock --upgrade --dry-run`および各PyPI metadata。
  - 破壊的変更/新機能: 多数の更新に加え、fastmcp 4、mcp 2、protobuf 7のmajor候補がある。
  - 採否: 更新は採用するが、fastmcp/mcp/protobuf majorはOpenHands SDK 1.44.1がそれぞれ3/1系でリリースされMCP経路を検証していないため、`[tool.uv] constraint-dependencies`（`mcp<2`、`protobuf<7`）で保留する。fastmcp 4はmcp 2系を前提とするため`mcp<2`により3系に留まる。
- **cadquery-ocp 8.x**
  - 一次情報: [build123d PyPI metadata](https://pypi.org/pypi/build123d/json)、[cadquery-ocp PyPI metadata](https://pypi.org/pypi/cadquery-ocp/json)
  - 破壊的変更/新機能: build123d 0.11.1が`cadquery-ocp-novtk<8.0`を要求する。
  - 採否: 保留。build123d側に8.xを許可する新しいpre-releaseがないため、cadquery-ocpだけを8.xへ更新しない。`scripts/dependency_update_deferrals.json`へ2026-12-01の再確認期限付きで記録する。
- **Python 3.14**
  - 一次情報: [CPython releases](https://github.com/python/cpython/tags)
  - 破壊的変更/新機能: checkerでは新しいminor seriesを検出するが、SDK/pyproject targetはPython 3.12である。DockerのPython 3.14はtools用である。
  - 採否: 保留。SDKと`pyproject.toml`のtargetを3.14へ変更する別検証が必要。`scripts/dependency_update_deferrals.json`へ2026-12-01の再確認期限付きで記録する。
- **Ubuntu 26.10**
  - 一次情報: [Ubuntu Docker tags](https://hub.docker.com/_/ubuntu)
  - 破壊的変更/新機能: 26.10はLTSではなく、28.04はLTS seriesである。
  - 採否: 不採用。リポジトリ標準をLTSに限定し、checkerも偶数年の`YY.04`だけを比較する。

### 2026-09 更新記録（#332）

- **OpenHands SDK v1.47.0**
  - 一次情報: [v1.45.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.45.0)、[v1.46.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.46.0)、[v1.47.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.47.0)
  - 破壊的変更/新機能・採否: 「依存・版・破壊的変更の記録」節のv1.44.1→v1.47.0項に記録する。submodule、`openhands-sdk`・`openhands-tools`・`openhands-workspace` pin、`AGENTS.md`、`docs/openhands-sdk-capabilities.json`を同じ変更で更新した。
- **cairosvg 2.9.1**
  - 一次情報: [CairoSVG 2.9.1 release](https://github.com/Kozea/CairoSVG/releases/tag/2.9.1)
  - 破壊的変更/新機能: security update。特殊に細工された非常に長いpathで描画時間が指数的に増える問題を修正。`url`引数のpath-like対応、Windows path修正。
  - 採否: 採用。ACDは`svg2png(bytestring=…)`だけを使い、APIと既定値の変更はない。KiCad SVG視覚投影の入力は自生成物だが、security fixとして追従する。
- **ruff 0.16.7**
  - 一次情報: [Ruff 0.16.7 release](https://github.com/astral-sh/ruff/releases/tag/0.16.7)
  - 破壊的変更/新機能: preview rule `RUF077`追加、`ISC003`/`TID254`のfix安全性修正、`UP035`の`typing.no_type_check_decorator`推奨停止、性能改善。stable ruleの追加はなく破壊的変更はない。
  - 採否: 採用。`uv run ruff check`は変更なしで通過する。preview ruleは有効化しない。
- **pyright 1.1.414**
  - 一次情報: [1.1.412](https://github.com/microsoft/pyright/releases/tag/1.1.412)、[1.1.413](https://github.com/microsoft/pyright/releases/tag/1.1.413)、[1.1.414](https://github.com/microsoft/pyright/releases/tag/1.1.414)
  - 破壊的変更/新機能: 型推論の修正（Sentinel assignability、keyword-form assignability、comprehension iterable内walrusの診断等）、type equality fast pathの最適化。behavior changeの告知はない。
  - 採否: 採用。strict modeの`uv run pyright`は変更なしで通過する。
- **uv.lock間接依存**
  - 一次情報: `uv lock --upgrade`およびIssue #332の候補表。
  - 破壊的変更/新機能: alembic、boto3/botocore、caio、contourpy、cyclopts、fakeredis、filelock、fonttools、google-auth、huggingface-hub、jiter、litellm 1.100.1、matplotlib、mcp 1.30.0、multidict、numpy 2.5.3、platformdirs、posthog、pure-eval、pyjwt、pypdf、regex、scikit-learn、tqdmのminor/patch更新。`agent-client-protocol`はSDK v1.47.0の`<0.11.0`制約により0.12.1から0.10.1へ下がる。
  - 採否: 採用。`[tool.uv] constraint-dependencies`（`mcp<2`、`protobuf<7`）は維持し、fastmcp/mcp/protobuf majorは引き続き保留する。
- **astral-sh/setup-uv v10.1.0**
  - 一次情報: [setup-uv v10.1.0 release](https://github.com/astral-sh/setup-uv/releases/tag/v10.1.0)
  - 破壊的変更/新機能: `no_proxy`/`NO_PROXY`環境変数の尊重、`python-runtime-id` output追加、`astral-sh/versions` checksumによるdownload検証。破壊的変更はない。
  - 採否: 採用。全workflowのpinをcommit `bec219d24cd3e171d82865faccec33120bb574f4`へ更新した。`python-runtime-id`は現行workflowで使用しない。
- **uv 0.12.13（Docker ARG `UV_VERSION`）**
  - 一次情報: [0.12.11](https://github.com/astral-sh/uv/releases/tag/0.12.11)、[0.12.12](https://github.com/astral-sh/uv/releases/tag/0.12.12)、[0.12.13](https://github.com/astral-sh/uv/releases/tag/0.12.13)
  - 破壊的変更/新機能: `uv.lock`記録hashによるsource archive検証、PEP 658 metadata sidecarのhash検証、`exclude-newer`後にuploadされたdistributionのlock除外、install高速化。CLIと既定値の破壊的変更はない。
  - 採否: 採用。server image内のsync経路はhash検証強化の恩恵を受ける。image digest lockはpublish後に別変更で更新する。`UV_VERSION`を変更する際は`UV_SHA256`もrelease assetの`.sha256`から同じ変更で更新する（#399では未更新でpublishが`sha256sum --check`失敗した）。
- **ohwr/cern-kicad-libs `1c71207c558a9ea32d96f7b272ba4a1fa923ef14`**
  - 一次情報: upstream commit `39e5755`・`1c71207`（CERN KiCad Library Bot、2026-09-12）。差分は`CERN.sqlite`、`CHECKSUMS`、`SchLib/Analog & Interface.kicad_sym`・`SchLib/Crystals & Oscillators.kicad_sym`のsymbol追加、AMPHENOL/PEM/OHMITE footprint追加、TYCO THD footprintの再生成、conversion log。`LICENSE`・`LICENSES/`・`.reuse/dep5`に変更はない。
  - 破壊的変更/新機能: 既存部品の削除はなく、GD1 fixtureはCERN catalog部品を参照しないため`parts_catalog_sha256`を記録した既存Evidenceに影響しない。`CERN.sqlite`のhashは変わるため、以後の`catalog="cern"`選択は新しい`parts_catalog_sha256`を記録する。
  - 採否: 採用。`libraries/README.md`の取得commit・取得日を更新し、`tests/core/test_cern_submodule_pin.py`とcatalog testで整合を確認した。
- **保留継続**: cadquery-ocp 8.0.1.0.0（build123d 0.11.1が`cadquery-ocp-novtk<8.0`を要求）、Python 3.14（target 3.12、SDK v1.47.0 baseline）は`scripts/dependency_update_deferrals.json`の2026-12-01期限のまま据え置く。

#### 2026-09 更新記録（#517）

- **OpenHands SDK v1.49.2**
  - 一次情報: [v1.48.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.48.0)、[v1.49.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.49.0)、[v1.49.1](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.49.1)、[v1.49.2](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.49.2)
  - 破壊的変更/新機能・採否: 「依存・版・破壊的変更の記録」節のv1.47.0→v1.49.2項に記録する。submodule、`openhands-sdk`・`openhands-tools`・`openhands-workspace` pin、`AGENTS.md`、`docs/openhands-sdk-capabilities.json`を同じ変更で更新した。
- **ruff 0.16.8**
  - 一次情報: [Ruff 0.16.8 release](https://github.com/astral-sh/ruff/releases/tag/0.16.8)
  - 破壊的変更/新機能: bug fixのみ（`SIM117` nested async with、`SIM109` operand順、`UP040`の括弧保存とTypeVarTuple除外、`RUF043`の`\Z`検出、`__lazy_modules__`・PEP-728 TypedDict対応等）。破壊的変更と新規stable ruleの追加はない。
  - 採否: 採用。dev groupの`ruff>=0.16.8`へ更新し、`uv run ruff check`は変更なしで通過する。
- **uv.lock間接依存**
  - 一次情報: `uv lock --upgrade`およびIssue #517の候補表。
  - 破壊的変更/新機能: boto3/botocore 1.43.98、cachetools 7.2.0、cyclopts 4.25.3、filelock 4.0.1、fsspec 2026.9.0、google-api-core 2.38.0、greenlet 3.5.6、grpcio 1.84.0、huggingface-hub 1.32.0、idna 3.20、litellm 1.101.0、lmnr 0.7.63、multidict 6.9.0、platformdirs 4.11.11、posthog 7.58.0、propcache 0.5.4、py-key-value-aio 0.4.6、pypdf 6.19.0、sqlalchemy 2.0.54、threadpoolctl 3.7.0、urllib3 2.8.0、uvicorn 0.53.0、wcwidth 0.8.4、yarl 1.25.1のminor/patch更新と、macOS限定の新規間接依存`pyobjc-framework-pubsub` 12.2.2の追加。
  - 採否: 採用。`[tool.uv] constraint-dependencies`（`mcp<2`、`protobuf<7`）は維持する。SDK v1.49.2が`fastmcp>=3.2.0,<4`をpinするため、fastmcpは3.4.7に留まる。
- **uv 0.12.17（Docker ARG `UV_VERSION`）**
  - 一次情報: [0.12.14](https://github.com/astral-sh/uv/releases/tag/0.12.14)、[0.12.15](https://github.com/astral-sh/uv/releases/tag/0.12.15)、[0.12.16](https://github.com/astral-sh/uv/releases/tag/0.12.16)、[0.12.17](https://github.com/astral-sh/uv/releases/tag/0.12.17)
  - 破壊的変更/新機能: 0.12.14はdownload中断時のHTTP Range resume、エラー描画の`cause:`表示、package-operationのexit code分類（expected failure=1、operational/internal failure=2）。0.12.15は0.12.14のsymlink destination回帰修正。0.12.16はindex供給hashによるwheel/sdist検証、build-constraint-dependenciesのhash対応。0.12.17はlockfile内Git archive pathの明示拒否。CLIと既定値の破壊的変更はない。
  - 採否: 採用。`UV_VERSION`と`UV_SHA256`（release assetの`.sha256`から取得）を同じ変更で更新した。exit code分類は`uv sync`等の非ゼロ判定のみの現行scriptへ影響しない。
- **gcovr 8.6（Docker ARG `GCOVR_VERSION`）**
  - 一次情報: [gcovr 8.5](https://github.com/gcovr/gcovr/releases/tag/8.5)、[8.6](https://github.com/gcovr/gcovr/releases/tag/8.6)
  - 破壊的変更/新機能: 8.5は`--lcov-test-name`の空白禁止、`--lcov-format-1.x`のdeprecation、HTML templateのgrid layout化、`gcov-exclude-directory`等のconfig key改名（旧名はalias存続）。8.6はPython 3.9 support終了、Python 3.14対応、merge error対策の関数名line番号付与等。
  - 採否: 採用。ACDの利用は`gcovr --json --root <dir> <dir>`だけであり、変更対象のoptionとHTML出力を使用しない。image内Pythonは3.14のため8.6のPython要件を充足する。
- **IBM Semeru 27.0.0.0（Docker ARG `SEMERU_JRE_VERSION`）**
  - 一次情報: [jdk-27.0.0.0 release](https://github.com/ibmruntimes/semeru27-binaries/releases/tag/jdk-27.0.0.0)とrelease metadata JSON。
  - 破壊的変更/新機能: Java 27 GA（2026-09-16公開、Eclipse OpenJ9 0.62.0、build 27+35）。以前はprereleaseのみでmajor更新を保留していたが、GAが出たため採用へ転換する。download repositoryは`semeru26-binaries`から`semeru27-binaries`へ変わる。
  - 採否: 採用。`SEMERU_JRE_VERSION=27.0.0.0`、`SEMERU_JRE_SHA256=9e6d9c1131da124bd08eb4183f7787a9f90111fc3d62c1231976c2d37372d59e`、download URLのrepositoryを同じ変更で更新し、build時の`java -version`検査をSemeru 27.0.0.0へ合わせた。FreeRouting 2.4.1はJava 25+ baselineのためJRE 27上で動作する。image digest lockはpublish後に別変更で更新する。
- **ohwr/cern-kicad-libs `9dba1850616da7fb1a4834531a3a1f0fff7c8666`**
  - 一次情報: upstream commit `9dba185`（CERN KiCad Library Bot、2026-09-19）。`1c71207c`との差分は9ファイル追加・18ファイル変更・0削除で、`LICENSE`・`LICENSES/`・`.reuse/dep5`に変更はない。
  - 破壊的変更/新機能: 既存部品の削除はなく、GD1 fixtureはCERN catalog部品を参照しないため`parts_catalog_sha256`を記録した既存Evidenceに影響しない。`CERN.sqlite`のhashは変わるため、以後の`catalog="cern"`選択は新しい`parts_catalog_sha256`を記録する。
  - 採否: 採用。`libraries/README.md`の取得commit・取得日を更新し、`tests/core/test_cern_submodule_pin.py`とcatalog testで整合を確認した。
- **build123d 0.12.0**
  - 一次情報: [build123d 0.12.0 release](https://github.com/gumyr/build123d/releases/tag/0.12.0)、[PyPI metadata](https://pypi.org/pypi/build123d/json)
  - 破壊的変更/新機能: `threejs-materials>=1.2.1,<1.3.0`を要求し、同packageが`pillow<12.3.0`をpinする。`openhands-sdk`の`pillow>=12.3.0`と両立せず`uv lock`がunsatisfiableになる。
  - 採否: 保留。`src/acd/adapters/cad/visual_projection.py`は`add_layer`の0-255 RGB tuple指定等、0.12.0でdeprecateされたAPIを使うため、単独での更新はAPI差分吸収も必要になる。pillow競合が解消する新版かSDK側pin緩和を待ち、`scripts/dependency_update_deferrals.json`へ2026-12-01の再確認期限付きで記録する。
- **保留継続**: cadquery-ocp 8.0.1.0.0（build123d 0.11.1が`cadquery-ocp-novtk<8.0`を要求）、Python 3.14（target 3.12、SDK v1.49.2 baselineへ理由を更新）は`scripts/dependency_update_deferrals.json`の2026-12-01期限のまま据え置く。


## 依存・版・破壊的変更の記録

依存、submodule、外部ツールを更新した場合は、使用API、既定値、破壊的変更、
採否を本節へ追記する。現行の基準は次のとおりである。

- SDKは`vendor/software-agent-sdk`のv1.49.2、commit
  `d128a786ee2ee570eb23ff5862ec148b43cfad0b`に固定する。更新前にpinned checkoutの
  API、上流release tag、CHANGELOGまたは一次リリース情報を確認する。
- v1.42.1からv1.43.1への更新では、Agent Pluginsのmanifest loaderとclosed
  `plugin.json` schema、structured task outcome preset、shell semanticsの
  defense-in-depth、LLM provider connection/runtime metadata、cleanup LLM profile、
  `AgentSettingsBase.from_persisted()`、profile validate endpointが追加された。
  ACDはagent-serverを引き続き非対象とし、structured outcome、shell semantics、
  provider/runtime metadata、cleanup profile、provider connectionsは採用しない。
  これらで既存のfail-closed hook/security policy、L1の決定論的判定、authoritative
  Evidenceの規則を置換・緩和しない。Agent Pluginsのmanifest loaderもSDKの公開追加
  surfaceとして記録するが、既存のACD plugin format採用範囲を拡大しない。
- 同更新で、resume時のclient tool再登録、Conversation errorのstructured event、
  active LLM profile解決、terminal executable prefix重複防止、browser-useの自動
  Chromium install削除、v1 skills migration修正が行われた。ACDの既存利用箇所では
  公開APIのimportとsignatureに互換性問題はなく、追加された既定動作は既存の安全境界を
  変更しない。
- v1.43.1からv1.44.1への更新では、別LLM profile`oracle`へ第二意見を照会する`ask_oracle`
  toolがtoolsへ追加され、structured builtin tool specのremote解決、`AsyncExecutor.close()`の
  上限時間、subscription LLMでのcondenser有効化、workspace git cloneのprovider host尊重、
  conversationごとのbrowser `user_data_dir`分離が修正された。ACDは`ask_oracle`を不採用とし、
  非決定論的な助言経路を合否・Evidenceへ関与させない。browserの`user_data_dir`分離は明示
  有効時のSingletonLock衝突を避ける既定改善であり、既存のL2探索補助の境界を変更しない。
- 同更新のagent-server側変更（ACP providerのbuild argとlayer分離、conversation単位の
  lifecycle lock、streaming deltaの配信範囲修正、crash recovery、canvas extension manifest、
  ACP agentへのworkspace project skills注入禁止）はACDの対象外であり、採用しない。
- v1.44.1からv1.47.0への更新（一次情報: [v1.45.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.45.0)、
  [v1.46.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.46.0)、
  [v1.47.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.47.0)）では、
  次の既定動作改善をSDK経路を通じて採用する。いずれもL2の漏洩防止・停止境界を強化する
  方向の変更であり、L1判定、authoritative Evidence、approval規則を変更しない。
  - `SecretRegistry`によるmaskingが、durableな`MessageEvent`のmodel出力、全toolの
    observation（`ToolDefinition.__call__`の共通chokepoint）、streaming tokenへ拡張された
    （#4783、#4788）。ACDが`Conversation`へ設定する`SecretRegistry`の効果範囲が広がる。
  - `execute_command`のsubprocess envから`SESSION_API_KEY`、`OH_SECRET_KEY`、
    `OH_SESSION_API_KEYS_*`が除去される（#4801）。ACD hook・toolがsubprocessへ
    渡す環境変数には影響しない。
  - eventは購読callbackへ配信される前にpersistされ、`EventLog.append`・
    `ConversationState.append_event`は割り当てたsequence番号（`int`）を返す（#4806、#4697）。
    callback合成順は「visualizer → persist → user callbacks」へ変わる。ACDは
    `LocalConversation`へ独自callbackを渡さず、`append_event`の戻り値も使用しないため
    互換性問題はない。
  - `OH_PERSISTENCE_DIR`が`~/.openhands`配下の全経路（user memory、installed
    plugins/skills、cache、hooks、profiles）で尊重される（#4476）。ACDの
    `memory_context_observation`はSDKの`get_user_persistence_dir()`でuser memory
    indexを探索し、SDKの`load_memory`と同じ既定を共有するよう更新した。
    `acd-install-doctor`のinstalled plugin store検査はhostの`~/.openhands`のまま
    据え置く（標準libraryのみのscriptであり、環境変数による移設は現時点で運用していない）。
  - async stepの途中に到着したuser messageの拾い直し（#4194）、
    nested repo pathの祖先判定（#4767）、local extension sourceと`repo_path`の合成と
    subpath containment検査（#4839）、`fastmcp>=3.2.0`によるMCP OAuth token失効の
    修正（#4857）。ACDの`PluginSource(source="github:…", repo_path="plugins/acd")`は
    remote sourceであり、local source合成の変更による影響はない。
  - `StreamContext`がstream identityを一元管理し、streamを必ずcloseする（#4822、
    `sdk.agent.stream_context`）。SDK内部補助として`docs/openhands-sdk-capabilities.json`の
    `sdk.agent.internal`へ分類する。
  - Agent Pluginsのclient extensionが`dev.openhands` namespace配下へ写像される（#4496）。
    `AgentPluginsFormat`はupstreamでも未登録のため、ACDのplugin format採用範囲は変えない。
- 同更新の不採用項目: TypeScript clientのmonorepo移行、agent-serverのOpenAI Responses
  gateway、`INSTALL_CAPABILITIES` build arg、VNC/desktop stack削除、
  `/sockets/session/{id}`、ACP-less image fallback、ACP provider追加（Kimi Code、Pi、
  OpenCode）、Laminar instrument選択、GPT-6 Astra等のverified model追加、
  litellm_proxy alias pricing。agent-server・ACP・observability・model registryは
  ACDの対象外であり、非決定論的経路を合否へ関与させない。
- 同更新の破壊的変更: `agent-client-protocol`が`>=0.10.1,<0.11.0`へ制限され
  （0.11.0の`prompt()`引数順変更を回避）、lockは0.12.1から0.10.1へ下がる。ACDはACPを
  使用しないため影響はない。`AgentBase.model_dump_succint`（deprecated）が削除された。
  ACDは使用していない。
- v1.47.0からv1.49.2への更新（一次情報: [v1.48.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.48.0)、
  [v1.49.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.49.0)、
  [v1.49.1](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.49.1)、
  [v1.49.2](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.49.2)）では、
  次の既定動作改善をSDK経路を通じて採用する。いずれもL2の漏洩防止・停止境界を強化する
  方向の変更であり、L1判定、authoritative Evidence、approval規則を変更しない。
  - `SecretRegistry`のmasking対象にlibtmuxのlog出力が追加され（#4871）、API key
    パターンに`sk-oh-*`が追加された（#4947）。ACDが`Conversation`へ設定する
    `SecretRegistry`の効果範囲が広がる。
  - Agent Pluginsのpackage pathにcontainment検査が強制された（#5101）。
    fail-closed方向の既定強化であり、ACDのplugin境界を緩めない。
  - saved secretはlookup時にscopeで解決される（#5017）。ACDはSDKのsaved secret
    機構を利用しないため既定動作への影響はない。
  - hard quota exhaustion時にfallback LLMへ即時failoverする（#4917）。LLM既定
    動作の改善であり、ACDの判定経路を変更しない。
  - pluginのskill発見は`load_skills_from_dir`へ委譲された（#5086）。同関数の新規
    引数はoptionalであり、ACDの`PluginSource(source="github:…", repo_path="plugins/acd")`
    の既存利用に互換性問題はない。
  - Agent Pluginsへ`mcp.json` loaderが追加された（#5093）。SDKの公開追加surface
    として記録するが、upstreamの`AgentPluginsFormat`は引き続き未登録であり、ACDの
    plugin format採用範囲は変えない。
  - SDKが`fastmcp>=3.2.0,<4`でpinするようになり（#5153）、unlocked installでも
    fastmcp 4系へ上がらなくなった。ACDの`[tool.uv] constraint-dependencies`
    （`mcp<2`、`protobuf<7`）と整合する。
  - 新module `workspace.agent_sandbox`（Kubernetes agent-sandbox実行）を
    `docs/openhands-sdk-capabilities.json`へ不採用として登録した。
    `DockerWorkspace`以外の実行環境はOpenHands専用拡張の境界外である。
- 同更新の不採用項目: agent-serverのper-conversation Docker runtime mode、
  python-minimal image、Docker conversation metadata/catalog/proxy root/restart
  修正、deprecated desktop URL endpointの削除（いずれもagent-server側）。
  verified model listの最新2系統への整理と新model追加（model registryはACDの
  対象外）。cryptography 48→50のmajor bump（transitive、ACDの直接使用なし）。
- 同更新の破壊的変更: `LLM.modify_params`がv1.47.0のremoval deadlineどおり
  削除された（#4954）。ACDは使用していない。
- Python依存は`pyproject.toml`とlockを正とし、既定値・公開API・破壊的変更を確認して
  `docs/openhands-sdk-capabilities.json`の採否へ反映する。Markdown表は
  `scripts/verify_sdk_capabilities.py`で生成し、採否enumと代表APIの検査を通す。
- KiCad CLI、FreeRouting、QEMU、CMake、ESP-IDF等の外部ツールは、doctorと
  SessionStart hookではdigest固定server image内だけを観測する。image内で版不明、
  未実行、出力不整合があればゲートを緩めずfail-closedとする。`probe_tools.py`は
  hostのprovisionalな開発観測に限り、doctorやhookのauthoritativeな観測経路では
  使用しない。
- SDKのdev workspace経路からDockerWorkspaceへ移行する際はimage digest、Dockerfile、外部ツール版を同時に記録し、
  ホスト実行の結果を合格側Evidenceへ昇格しない。
- container toolchainの今回更新では、Semeru 26.0.2.10（OpenJ9 0.61.0、新機能追加なし）、
  uv 0.12.10、ESP-IDF v6.1（GD1 FWが使うGPIO／I2C／FreeRTOS APIは破壊的変更の対象外）、
  KiCad 10.0.6（PPA追従、pinしない）、CMake 4.2.3、Ninja 1.13.2へ更新した。
  以前のimage（ESP-IDF v6.0.2のimageを含む）はCMakeとNinjaを欠き、
  `To use idf.py, either the 'ninja' or 'GNU make' build tool must be available in the PATH`
  でcontainer FW laneが失敗していたため、今回imageへ同梱した。host provisional経路は
  `uv run --with cmake==3.31.6`によるCMake注入を維持する。FreeRouting 2.4.1と
  QEMU 9.2.2は据え置きである。lock値`docker/image-digests.json`はpublish後に別変更で更新する。
- KiCad 10.0.5は公式PPAから配布されなくなったため、現行環境を10.0.6へ追従させた。
  公式libraryでは`Device.kicad_sym`、`Regulator_Linear.kicad_sym`、
  `Switch.kicad_sym`の3ファイルの内容が変わり、実ファイルから再計算したpinを
  `graph.json`とparts catalogへ反映した。ホストとlocked containerで参照15ファイルの
  hashは全件一致した。fixture generator全体はmain由来のsilkscreen resolver不整合で
  再生成できなかったため、今回の変更はlibrary pin属性に限定し、歴史的記録は変更していない。

版と能力は次で記録する。

```bash
uv run python scripts/probe_tools.py
```

Docker workspace経路（ゲート実行の正）:

```bash
SERVER_REF="$(uv run python scripts/pull_locked_image.py --entry acd-server \
  --record out/container/pull-acd-server.json)"
uv run python scripts/run_in_workspace.py --image "$SERVER_REF"
```

`scripts/pull_locked_image.py`はlock済みdigestのpull入口の正である。`docker/image-digests.json`の
lock entryだけを受け付け、`image@sha256:...`のimmutable referenceでpullし、pull後に
localのdigestがlock値と一致することを`docker image inspect`で確認する。全体timeout
（既定900s）、有限回のbackoff retry（既定3回）、docker版・attempt・timeout・取得時刻を含む
provenanceの`--record`出力を持つ。pull失敗、retry上限到達、digest不一致、docker CLI
timeout、lock未設定はいずれもexit=2でfail-closedとし、Evidenceを生成しない。

container実行のtimeout境界は`run_in_workspace.py`の引数で明示する。既定値は
`--health-check-timeout 300`、`--command-timeout 3600`、`--docker-cli-timeout 300`、
`--memory-limit 8g`、`--platform linux/amd64`である。ACDは`DockerWorkspace`のlifecycleが
呼ぶdocker CLI（`docker version`、`docker run`、`docker inspect`、`docker logs`、
`docker stop`）へ同じdocker CLI timeoutとmemory上限（`--memory`／`--memory-swap`）を与え、
`resolve_image_digest()`の`docker image inspect`にも明示timeoutを与える。container起動が
失敗した場合は観測したcontainerを`docker stop`で後始末し、停止できないcontainer IDを
エラーへ含める。`WorkspaceResult`は失敗種別（`timeout`、`transport`、`command`）を保持し、
runnerは失敗種別を出力して非ゼロ終了する。retryはdigest固定pullとfile downloadに限り、
gate実行とEvidence生成は再試行しない。
commandが非ゼロで終了した場合も、runnerは宣言済み`--download`を1回ずつ試みて回収できた
成果物をhostへ置き、回収できなかったfileは`download_errors`（stderrの
`download not retrieved:`）へ記録する。exit codeと失敗種別`command`は維持され、downloadの
成否は判定へ影響しない。部分的な回収を成功として読まず、tarとexit 0で失敗を包む回避策も
使わない。transport失敗とtimeoutではdownloadを試みない。

`--graph`で指定したDesign Graphから、未指定のcommandとdownload pathを導出する。
commandを与えない既定実行では`fixtures/golden-design-1/graph.json`（GD1）を使う。
commandを明示した場合、graph由来の既定downloadが使われるのは`--graph`を明示し、
かつ`--download`・`--download-root`を指定しないときだけである。`--graph`無しの任意
commandでは`--download`／`--download-root`で指定したpathだけをdownloadし、指定が
無ければdownloadは行わない（成功したcommandをdownload不足で失敗扱いしない）。
graphのmissing、parse failure、または不正な`graph_id`ではGD1へfallbackせず停止する。
明示したdownload対象がcontainer内に存在しない場合は引き続きfail-closedとする。

生成物の既定pathとFW boot logはgraph_id由来であり、GD1 fixtureだけが互換値
（`out/gd1-*`および`ACD GD1 fw boot target_revision=%s`）を明示属性または
compatibility aliasで再現する。boot log messageのC string literal安全条件を含む
FW boot-log導出規則の規範は[`architecture.md`](architecture.md)に集約し、
coreとSkillは独立実装する。

imageへ同梱したACD本体・pipeline scripts・fixtureだけで実行する場合は`--source bundled`を
使う。この経路はリポジトリをマウントせず、image内`/opt/acd`のprebake済み環境で実行する。

```bash
uv run python scripts/run_in_workspace.py --image "$SERVER_REF" --source bundled \
  "uv run python scripts/run_enclosure_pipeline.py --fixture fixtures/golden-design-1 --out out/gd1-enclosure"
```

`--source bundled`は実行前に`/opt/acd`の`pyproject.toml`、`uv.lock`、`src/acd`、
`scripts`、`fixtures`、prebake済み`.venv`を検査し、欠落があればコマンドを実行せず停止する。
同梱資材を持つimageがpublishされてlockへ記録されるまで、既定は`--source mounted`のままとする。
bundled経路はhostのgit checkoutを持たないためsource provenanceは常に`unknown`と記録され、
そのEvidenceは`verify_authoritative_evidence.py`を通過できない。image同梱bundleがgit shaを
記録するまで、bundled実行の生成物はprovisionalとしてのみ使う。

`--source mounted`のrunnerは、container起動前に`--repo`のsource tree
（`src`・`scripts`・`plugins`・`contracts`・`libraries`・`docker`・`pyproject.toml`・
`uv.lock`）を`git status --porcelain`で検査し、結果を`ACD_SOURCE_GIT_SHA`・
`ACD_SOURCE_TREE_STATE`・`ACD_SOURCE_DIRTY_DIGEST`（dirty時のみ）としてcontainerへ
forwardする。ToolEnvelopeは`source_revision`・`source_tree_state`・`source_dirty_digest`
へ同じ値を記録する。dirtyなsource treeは`--allow-dirty`を与えてもcontainer起動前に
常に拒否する（AA-5）。sourceとcontractの変更はcommitしてpull requestとして提案する
必要があり、設計入力path（`fixtures/`・`evidence/`・`out/`）はsource provenanceの対象外で
遮断しない。`--allow-dirty`が許すのは非git checkout（`unknown`）とbootstrap recordの
revisionからの逸脱の記録だけであり、許容してもprovenanceは記録されるため、生成された
Evidenceは`verify_authoritative_evidence.py`が`source_tree_state`非clean、provenance欠落、
または`unknown`としてfail-closedで拒否する。`--source-revision <sha>`を与えると全envelopeの
`source_revision`一致も要求する。これにより検証checkout内の`src/`改変（dirty treeからの
Evidence生成）は検証側で必ず検出できる。

runnerとverifierは、観測したsource revisionがbootstrap時のrevisionから逸脱していないかも
照合する。`run_in_workspace.py --source-revision <sha>`は期待するsource git shaを指定し、
`--bootstrap-record <path>`はbootstrap record（既定では存在すれば
`<repo>/.openhands/bootstrap-record.json`）の`resolved_revision`を期待値として読む。
両方を指定した場合は一致を要求し、明示したrecord pathが存在しない場合は停止する。
`--source mounted`で観測revisionが期待値と異なる場合、`--allow-dirty`無しではimage digest
解決の前にcontainer起動を拒否する。`--allow-dirty`を許容した場合もenvelopeには実測
revisionが記録されるため、`verify_authoritative_evidence.py --source-revision`（または
`--bootstrap-record`）でfail-closedに拒否される。`--source bundled`では観測できる
provenanceが無いためこの照合は行わない。`--source-revision`と`--bootstrap-record`は
`--local-provisional`では使えない。

server imageがlockに未設定、image digestを解決できない、または経路がunknownの場合、
runnerはコマンドを実行せず非ゼロ終了する。
runnerは`ACD_CONTAINER_IMAGE_DIGEST`と`ACD_IN_CONTAINER`をcontainerへforwardする。
hostのToolEnvelopeは`execution_context="host"`、containerのToolEnvelopeは型付き
`container_image_digest`を持つ。`evidence/`へ昇格するCLIは
`supports_authoritative_pass()`を要求する。

host provisional経路（合格側Evidenceへ昇格しない参考実行）:

```bash
uv run python scripts/run_in_workspace.py --local-provisional --repo "$PWD" \
  "uv run python scripts/run_gd1_pipeline.py --out out/gd1-host"
```

この経路は`LocalWorkspace(working_dir=...)`を使用し、結果はhost/provisional型で返す。
`--image`との併用、container markerまたはdigest環境変数がある状態は拒否する。

外部ツールが無い、版が不明、または出力を独立再読込できない場合、pipelineは
fail-closedで停止する。ゲートの仕様とprobeの責務は[`gates.md`](gates.md)を参照する。
