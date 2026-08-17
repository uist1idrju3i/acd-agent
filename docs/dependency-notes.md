SDK v1.42.1の`HookConfig`、`HookMatcher`、command hookを使用する。command hookは
`hooks.json`から読み込まれ、stdinのHookEvent JSONを受け取る。exit code 0は許可、
2はブロック、その他の非0は非ブロッキングエラーである。SessionStartとPostToolUseは
ブロックできないため常に0で返す。

SDK側はhooks.jsonのcommandで`${CLAUDE_PLUGIN_ROOT}`や`${SKILL_ROOT}`を展開しない。
そのため`${ACD_PLUGIN_ROOT:-$OPENHANDS_PROJECT_DIR/plugins/acd}`を使い、別配置時だけ
`ACD_PLUGIN_ROOT`で上書きする。git不能、policy欠落、unknown、Evidence不一致は
停止側へ集約し、gate実行または変更をcommitしてからEvidenceを生成する。
# 依存関係ノート

> ステータス: Draft
> 対象: acd-agentのPython依存、submodule、外部ツール、GitHub Actions、調査日 2026-08-16

本書は、依存関係を更新するときに確認する一次情報、ACD内の使用箇所、影響する関連文書の
対応表である。依存更新の手順と合否条件は [`../AGENTS.md`](../AGENTS.md) の
「依存関係更新契約」を正とする。採否理由、設計境界、ライセンス評価は各関連文書を正とし、
本書では二重管理しない。

## 対応表

| 依存 | 役割・ACD内の使用箇所 | 現行採用版 | 固定方法 | 一次情報 | 更新時に確認する観点 | 更新する関連文書 |
|---|---|---:|---|---|---|---|
| OpenHands Software Agent SDK | subagent、視覚投影、Skill、plugin、workspace shell、`EventLog`、agent-server等を使用 | 1.42.1 | `vendor/software-agent-sdk`のsubmodule SHA、`uv.lock` | [v1.42.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.42.0)、[v1.42.1](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.42.1)、[commit比較](https://github.com/OpenHands/software-agent-sdk/compare/v1.41.0...v1.42.1) | ACDのimport API、LLM設定、plugin／agent-serverの挙動 | [`openhands-integration.md`](openhands-integration.md)、[`agent-server-runbook.md`](agent-server-runbook.md)、必要時は [`ADR-0023`](adr/ADR-0023-deterministic-gate-authority.md)／[`ADR-0024`](adr/ADR-0024-openhands-only-scope.md) |
| OpenHands SDK hooks | `HookConfig`、`HookMatcher`、command hookでagent経路のfail-closed境界を実装 | 1.42.1 | `plugins/acd/hooks/hooks.json`、SDK submodule SHA | [hooks API](https://github.com/OpenHands/software-agent-sdk/tree/v1.42.1/openhands-sdk/openhands/sdk/hooks) | HookEvent、exit code 2、command環境変数、ブロック可能なevent | [`ADR-0013`](adr/ADR-0013-openhands-sdk-runtime-adoption.md)、[`architecture.md`](architecture.md) |
| pydantic | ACDの契約モデル、`Field`、validation | 2.13.4 | `uv.lock`。範囲指定は各packageの`pyproject.toml` | [releases](https://github.com/pydantic/pydantic/releases)、[migration guide](https://docs.pydantic.dev/latest/migration/) | model validation、serialization、strict mode、既定値と非推奨 | [`architecture.md`](architecture.md)、[`installation.md`](installation.md) |
| build123d | `acd_adapter_cad`の投影と機械ゲートでCAD形状生成・STEP／3MF出力 | 0.11.1 | `uv.lock`、`pyproject.toml`で完全固定 | [releases](https://github.com/gumyr/build123d/releases) | kernel互換性、形状演算、exportの決定性、測定値とhash | [`tool-capability-probes.md`](tool-capability-probes.md)、[`design-flow.md`](design-flow.md) |
| cadquery-ocp | build123dが使用するOCP CAD kernel。`acd_adapter_cad`で使用し、`acd_tools.probe`で版を取得 | 7.9.3.1.1 | `uv.lock`、`pyproject.toml`で完全固定 | [releases](https://github.com/CadQuery/OCP/releases) | Python／OCP ABI、STEP／3MF出力、kernelの幾何演算 | [`tool-capability-probes.md`](tool-capability-probes.md)、[`research/prior-art.md`](research/prior-art.md) |
| sexpdata | `acd_core.sexpr`、KiCad adapterでS-expressionの読み書き | 1.0.2 | `uv.lock`、adapterの範囲指定 | [PyPI](https://pypi.org/project/sexpdata/) | parse／emitの型、quote、KiCad／Specctra形式の互換性 | [`research/tool-selection.md`](research/tool-selection.md)、[`installation.md`](installation.md) |
| gerbonara | KiCad adapterでGerber／Excellonを生成・再読込・検証 | 1.6.3 | `uv.lock`、adapterの範囲指定 | [PyPI](https://pypi.org/project/gerbonara/)、[repository](https://github.com/jaseg/gerbonara) | Gerber／Excellon parse、M02、座標・単位、fail-closed検証 | [`research/tool-selection.md`](research/tool-selection.md)、[`installation.md`](installation.md) |
| OpenHands SDK ToolDefinition | `acd-tools`の決定論的入口をAction、Observation、Executorとして公開 | 1.42.1 | `vendor/software-agent-sdk`、`uv.lock` | [v1.42.1](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.42.1) | `ToolDefinition`、`ToolAnnotations`、`register_tool`、Action schema、冪等登録 | [`openhands-integration.md`](openhands-integration.md)、[`ADR-0014`](adr/ADR-0014-sdk-tool-definitions.md) |
| pytest | `packages/`以下の全テストを実行するCI・開発用test runner | 9.1.1 | `uv.lock`、dev dependencyの範囲指定 | [releases](https://github.com/pytest-dev/pytest/releases)、[CHANGELOG](https://docs.pytest.org/en/stable/changelog.html) | collection、fixture、warning、plugin API、Python 3.12互換性 | [`installation.md`](installation.md) |
| ruff | CIのlint。`pyproject.toml`のE/F/W/I/UP/B/SIM/RUFを検査 | 0.16.3 | `uv.lock`、dev dependencyの範囲指定 | [0.16.3 release notes](https://github.com/astral-sh/ruff/releases/tag/0.16.3) | ルール追加・変更、fix、出力形式、Python／Markdown解析 | [`AGENTS.md`](../AGENTS.md)、[`installation.md`](installation.md) |
| pyright | CIのstrict型検査。`packages`、`scripts`、`fixtures`を検査 | 1.1.411 | `uv.lock`、dev dependencyの範囲指定 | [releases](https://github.com/microsoft/pyright/releases) | 型推論、strict diagnostics、Python 3.12、stub変更 | [`AGENTS.md`](../AGENTS.md)、[`installation.md`](installation.md) |
| uv | workspace同期・lock生成・CIでのPython／依存導入 | CIはsetup-uv v10.0.1、ローカル版は環境依存 | workflowのsetup-uv SHA pin、`uv.lock` | [uv releases](https://github.com/astral-sh/uv/releases)、[setup-uv v10.0.1](https://github.com/astral-sh/setup-uv/releases/tag/v10.0.1) | resolver、lock format、workspace、Python取得、cache、Node runtime | [`AGENTS.md`](../AGENTS.md)、[`installation.md`](installation.md) |
| actions/checkout | CIでsubmoduleを含むrepositoryをcheckout | v7.0.1 | GitHub公式actionのタグ参照 | [v7.0.1 release](https://github.com/actions/checkout/releases/tag/v7.0.1) | `submodules`、`persist-credentials`、runner／Node runtime | [`installation.md`](installation.md) |
| astral-sh/setup-uv | CIでuvとPythonを導入 | v10.0.1 | commit SHA `20cfd1bf945f4377ade1205e4dbc17946fc9a30d`、コメントで版を併記 | [v10.0.1 release](https://github.com/astral-sh/setup-uv/releases/tag/v10.0.1) | Node 24 runner互換性、`python-version`、cache、uvの取得 | [`installation.md`](installation.md)、[`AGENTS.md`](../AGENTS.md) |
| CodeQL | `Analyze (python)`、`Analyze (actions)`のcheck-runを確認。いずれもappは`github-actions`で、repository内に対応するworkflowファイルはない | GitHub側のCodeQL default setupと推定（版表記なし） | リポジトリ設定で管理。action SHAのpin対象外 | [GitHub CodeQL](https://codeql.github.com/docs/) | check-run名、対象言語、結果、権限を確認。`code-scanning/default-setup` APIは権限不足の403で直接確認できず、default setupという管理形態は推定 | リポジトリ設定、必要時は関連するセキュリティ文書 |
| `update-uv-graph` | `update-uv-graph`のcheck-runを確認。appは`github-actions`で、repository内に対応するworkflowファイルはない | GitHub側の依存グラフ送信設定と推定（版表記なし） | リポジトリ設定で管理。action SHAのpin対象外 | [GitHub dependency graph](https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependency-graph) | `uv.lock`更新後のcheck-run結果と依存グラフへの反映を確認。設定の詳細は権限不足のため未確認 | リポジトリ設定、`uv.lock`、必要時は依存更新文書 |
| kicad-cli | KiCad adapterでERC／DRC、netlist、Gerber／drill出力。`scripts/run_gd1_pipeline.py`でも使用 | 10.0.5を一次情報とGD1期待値の基準にする。Dockerfileは9系pinで次フェーズ是正 | 実行環境で版をprobeしEvidenceへ記録 | [KiCad 10.0 CLI docs](https://docs.kicad.org/10.0/en/cli/cli.html) | CLI引数、ERC／DRC、出力形式、ライブラリとproject format | [`research/tool-selection.md`](research/tool-selection.md)、[`tool-capability-probes.md`](tool-capability-probes.md) |
| FreeRouting | `acd_adapter_freerouting`でDSN→SES外部routing | 環境プローブで検出（CI固定なし） | 実行環境で版をprobeしEvidenceへ記録 | [FreeRouting releases](https://github.com/freerouting/freerouting/releases) | DSN／SES形式、収束、幅・clearance、終了コード | [`research/tool-selection.md`](research/tool-selection.md)、[`tool-capability-probes.md`](tool-capability-probes.md) |
| ESP-IDF | acd-firmware-esp32c3 Skillが`idf.py`を呼ぶ。ACD本体のゲートではなくSkill側の作業 | 固定なし（要probe） | `IDF_PATH`と`idf.py --version`を実行時検証 | [ESP-IDF releases](https://github.com/espressif/esp-idf/releases) | toolchain／target、build output、merge-bin、ログ、再現性 | [`design-flow.md`](design-flow.md)、[`installation.md`](installation.md) |
| QEMU | acd-firmware-esp32c3 Skillが`qemu-system-riscv32`で仮想実行しログを照合する | 固定なし（要probe） | 実行時にversionをprobeしSkillのsummaryへ記録 | [QEMU releases](https://www.qemu.org/download/) | target、machine、serial log、timeout、exit status | [`design-flow.md`](design-flow.md)、[`tool-capability-probes.md`](tool-capability-probes.md) |
| `vendor/software-agent-sdk` | OpenHands SDKのsource submodule | v1.42.1 | submodule SHA `167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497` | [release](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.42.1) | source差分、API、submodule版表記、lock再生成 | [`openhands-integration.md`](openhands-integration.md)、[`installation.md`](installation.md) |

CodeQLと`update-uv-graph`はリポジトリ設定側で動くcheck-runであり、workflowのaction pin管理外である。
依存更新PRではこれらをworkflow変更として管理せず、check-runの結果と依存グラフへの反映だけを確認する。

間接依存である`charset-normalizer`、`filelock`、`lmnr`、`platformdirs`、
`python-json-logger`、`typing-inspection`、`uvicorn`は、今回の`uv lock --upgrade`で
更新されたが、acd-agentのsourceから直接importしていない。更新時は同じlock解決結果を
記録し、依存元（SDK、LiteLLM、agent-server等）のリリースノートとCI・テスト結果を確認する。

## 今回の更新で確認した変更点

今回のlock更新で変更された11件は以下であり、現行採用版は`uv.lock`を正とする。

| 依存 | 変更 | 一次情報で確認した内容と結論 |
|---|---:|---|
| `charset-normalizer`、`filelock`、`lmnr`、`platformdirs`、`python-json-logger`、`typing-inspection`、`uvicorn` | 3.4.9→3.5.1、3.32.2→3.32.3、0.7.58→0.7.59、4.11.2→4.11.3、4.1.0→4.2.0、0.4.3→0.4.4、0.52.1→0.52.3 | 直接importはなく、今回の作業ではACD固有APIへの変更は確認していない。依存元の解決・CI・pytestで回帰を確認する対象とした |
| `ruff` | 0.16.2→0.16.3 | [一次リリースノート](https://github.com/astral-sh/ruff/releases/tag/0.16.3)で新しいpreview rule、rule修正、性能・CLI改善を確認。ACDの選択ruleへの影響は`uv run ruff check`で確認し、追加採用はしていない |
| `litellm` | 1.96.0→1.97.0 | [一次リリース](https://github.com/BerriAI/litellm/releases/tag/v1.97.0)と[差分](https://github.com/BerriAI/litellm/compare/v1.96.0...v1.97.0)を確認。ACDはSDK経由でLLM呼び出しを使うため回帰対象だが、新しいprovider／挙動の採用判断はしていない |
| `openai` | 2.53.0→2.54.0 | [一次CHANGELOG](https://github.com/openai/openai-python/blob/main/CHANGELOG.md)でResponses model identifiers追加とaudio upload metadataの説明修正を確認。ACDはOpenAI SDKを直接importせず、SDK／LiteLLM経由のため新APIは採用していない |
| `orjson` | 3.11.9→3.12.0 | [一次CHANGELOG](https://github.com/ijl/orjson/blob/master/CHANGELOG.md)を確認したが、3.12.0専用releaseページは有効な変更説明を取得できなかった。ACDの直接importはなく、serializationのbyte表現・ABI・Python 3.12 wheelを未確認の回帰リスクとして扱い、追加機能は採用していない |

確認日: 2026-08-16。一次情報で確認できない変更は推測せず、未確認の採否を合格扱いにしない。

### SDK ToolDefinition API

OpenHands SDK v1.42.1の`ToolDefinition`、`Action`、`Observation`、
`ToolAnnotations`、`ToolExecutor`、`register_tool`を一次情報で確認し、
`acd_tools.sdk_tools.register_acd_tools()`から明示的に登録する。登録はSDK registryの
重複登録挙動を踏まえて冪等にし、import副作用を持たせない。SDKのexample実装を写経せず、
vendorのMIT Licenseに基づく帰属が必要な派生コードも追加していない。
### Docker workspace API

OpenHands SDK v1.42.1の一次情報として、次のvendor sourceを確認した。

- `vendor/software-agent-sdk/openhands-workspace/openhands/workspace/docker/workspace.py`
- `vendor/software-agent-sdk/openhands-workspace/openhands/workspace/docker/dev_workspace.py`
- `vendor/software-agent-sdk/openhands-workspace/openhands/workspace/AGENTS.md`

`DockerWorkspace`は既成のagent-server imageを受け取り、
`DockerDevWorkspace`は`base_image`からagent-server imageをbuildする。P5は利用者が
buildしたACD tools imageをbase imageとして渡すため`DockerDevWorkspace`を選ぶ。
API上の既定値は`platform="linux/amd64"`、container起動は`--rm`、health checkを
行い、`volumes`は`/host/path:/workspace`の文字列形式である。環境変数は
`forward_env`に名前を渡す方式であり、runnerは`ACD_CONTAINER_IMAGE_DIGEST`を
forwardする。

docker CLI側は`docker image inspect --format`でRepoDigestsを優先し、ローカルbuild
でRepoDigestsが無い場合は`.Id`のimage IDを使う。いずれもsha256 digestが得られ
なければ実行しない。Docker daemonが利用できない場合も同じfail-closedである。

### OpenHands SDK critic API

OpenHands SDK v1.42.1の
`vendor/software-agent-sdk/openhands-sdk/openhands/sdk/critic/base.py`、
`result.py`を確認した。`CriticBase.evaluate(events, git_patch)`は
`CriticResult`を返し、`IterativeRefinementConfig`の
`success_threshold`と`max_iterations`が反復制御に使われる。
ACDは`AcdGateCritic`でこれを利用するが、eventsとgit patchは評価に使わず、
Design Graph、Evidence、製造manifestだけを読む。既定値は
`success_threshold=1.0`、`max_iterations=3`である。

### OpenHands SDK workflow境界

SDK v1.42.1のworkflow実装を確認し、`run_agent`、`map_agents`、
`reduce_agent`、`pipeline`、`flatten`はいずれもLLM subagent orchestrationの
APIであることを確認した。workflow scriptはshell実行やファイル読み書きを行わない
契約のため、KiCadなどの決定論的CLI探索には採用しない。ACD側のwidth arm並列化は
`ThreadPoolExecutor`で実装し、外部subprocessを独立に待機する。

### OpenHands SDK Conversation API

現行のLocalConversation経路ではSDK v1.42.1の`Agent`、`LocalConversation`、`PluginSource`、
`HookConfig.load()`、`LLMSummarizingCondenser`、`LocalWorkspace.git_changes()`、
`ConversationStats.get_combined_metrics()`を使用する。
既定の`out/agent-sessions`は生成物であり設計入力ではない。SDKのloop、history、
persistence、metricsは採用し、ACD独自実装は採用しない。metricsは
`pass_evidence: false`で保存し、合否判定には使わない。

### OpenHands SDK plugin配布・TestLLM API

次フェーズでは`PluginSource`の`source`、`repo_path`、`ref`を使用する。外部配布の`ref`は
`acd_tools.plugin_distribution`で40桁commit SHAまたは`v<semver>` tagに限定し、
branch名や未指定refをfail-closedで拒否する。開発時local pathは従来どおり許可する。
`sdk.marketplace`は既存repoのplugin部分木をpinned fetchする要件を超えるため採用しない。

`sdk.testing.TestLLM`は台本応答を提供し、bootstrap構成とcritic反復方針の回帰に使う。
hookの投影保護DENYは既存のsubprocess testで確認する。外部fetch、完全なConversation
tool-call E2E、実LLM、Dockerは次フェーズの回帰対象外である。

`sdk.profiles`の`AgentProfile` / `AgentProfileStore`はsecret-freeなLLM profile参照を
保持するが、ACDの役割別モデル設定へは採用しない。resolved LLMやAPI keyを宣言へ
持ち込まず、profileのライフサイクル契約が必要になるためである。

### OpenHands agent-server API

v1.42.1の`openhands-agent-server/openhands/agent_server/`を読み、
`api.py`のREST router登録、`conversation_router.py`、`event_router.py`、
`sockets.py`、`openai/router.py`、`config.py`、`conversation_service.py`、
`event_service.py`を確認した。ACDはREST/WebSocket、filesystem persistence、
`/v1` OpenAI互換APIの運搬機構だけを採用候補とし、serverのevent、state、metrics、
agent応答をpass evidenceには使わない。

既定保存先は`workspace/conversations`、`workspace/project`、
`workspace/bash_events`である。session keyは任意設定で、`OH_SECRET_KEY`はsecretの
再起動後復元に必要である。`docker/Dockerfile`と`docker/build.py`のtarget・既定image名
も確認したが、registry imageの存在、digest、ACD server E2Eは未確認である。
`sdk.marketplace`やagent-serverの独自改修は採用しない。運用手順と未実測範囲は
[`agent-server-runbook.md`](agent-server-runbook.md)と
[`ADR-0020`](adr/ADR-0020-agent-server-operations.md)を正とする。

### OpenHands SDK hooks

SDK v1.42.1の`HookConfig`、`HookMatcher`、command hookを使用する。command hookは
`hooks.json`から読み込まれ、stdinのHookEvent JSONを受け取る。exit code 0は許可、
2はブロック、その他の非0は非ブロッキングエラーである。SessionStartとPostToolUseは
ブロックできないため常に0で返す。

SDK側はhooks.jsonのcommandで`${CLAUDE_PLUGIN_ROOT}`や`${SKILL_ROOT}`を展開しない。
そのため`${ACD_PLUGIN_ROOT:-$OPENHANDS_PROJECT_DIR/plugins/acd}`を使い、別配置時だけ
`ACD_PLUGIN_ROOT`で上書きする。policy欠落、unknown、Evidence不一致は停止側へ集約する。
