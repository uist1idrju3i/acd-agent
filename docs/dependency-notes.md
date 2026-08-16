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
| OpenHands Software Agent SDK | `acd_events.events`、`acd_runtime.review`、`acd_runtime.session_start_hook`、`acd_runtime.startup`がEvent、HookDecision、LLM、TestLLM、InstallationInfo／Metadataを使用 | 1.42.1 | `vendor/software-agent-sdk`のsubmodule SHA、`uv.lock` | [v1.42.0](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.42.0)、[v1.42.1](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.42.1)、[commit比較](https://github.com/OpenHands/software-agent-sdk/compare/v1.41.0...v1.42.1) | ACDのimport API、Event復元、hookのdeny、LLM設定、plugin／agent-serverの挙動。詳細は既存文書へ委譲 | [`openhands-integration.md`](openhands-integration.md)、必要時は [`ADR-0003`](adr/ADR-0003-sdk-feature-adoption.md) |
| pydantic | ACD schema・event・runtimeのモデル、`Field`、validation | 2.13.4 | `uv.lock`。範囲指定は各packageの`pyproject.toml` | [releases](https://github.com/pydantic/pydantic/releases)、[migration guide](https://docs.pydantic.dev/latest/migration/) | model validation、serialization、JSON Schema、strict mode、既定値と非推奨 | [`architecture.md`](architecture.md)、[`installation.md`](installation.md) |
| jsonschema | `acd_core.fab`でFab profileのJSON Schema検証 | 4.26.0 | `uv.lock` | [CHANGELOG](https://github.com/python-jsonschema/jsonschema/blob/main/CHANGELOG.rst) | Draft 2020-12、validator API、format／type検証の既定挙動 | [`architecture.md`](architecture.md)、[`installation.md`](installation.md) |
| build123d | `acd_adapter_cad`、`acd_runtime.mechanical`、`acd_tools.probe`でCAD形状生成・STEP／3MF出力 | 0.11.1 | `uv.lock`、`pyproject.toml`で完全固定 | [releases](https://github.com/gumyr/build123d/releases) | kernel互換性、形状演算、exportの決定性、測定値とhash | [`tool-capability-probes.md`](tool-capability-probes.md)、[`design-flow.md`](design-flow.md) |
| cadquery-ocp | build123dが使用するOCP CAD kernel。`acd_adapter_cad`と`acd_tools.probe`で版を取得 | 7.9.3.1.1 | `uv.lock`、`pyproject.toml`で完全固定 | [releases](https://github.com/CadQuery/OCP/releases) | Python／OCP ABI、STEP／3MF出力、kernelの幾何演算 | [`tool-capability-probes.md`](tool-capability-probes.md)、[`prior-art.md`](prior-art.md) |
| sexpdata | `acd_core.sexpr`、KiCad adapterでS-expressionの読み書き | 1.0.2 | `uv.lock`、adapterの範囲指定 | [PyPI](https://pypi.org/project/sexpdata/) | parse／emitの型、quote、KiCad／Specctra形式の互換性 | [`tool-selection.md`](tool-selection.md)、[`installation.md`](installation.md) |
| gerbonara | KiCad adapterでGerber／Excellonを生成・再読込・検証 | 1.6.3 | `uv.lock`、adapterの範囲指定 | [PyPI](https://pypi.org/project/gerbonara/)、[repository](https://github.com/jaseg/gerbonara) | Gerber／Excellon parse、M02、座標・単位、fail-closed検証 | [`tool-selection.md`](tool-selection.md)、[`fab-data-preparation-retrospective.md`](fab-data-preparation-retrospective.md) |
| pytest | `packages/`以下の全テストを実行するCI・開発用test runner | 9.1.1 | `uv.lock`、dev dependencyの範囲指定 | [releases](https://github.com/pytest-dev/pytest/releases)、[CHANGELOG](https://docs.pytest.org/en/stable/changelog.html) | collection、fixture、warning、plugin API、Python 3.12互換性 | [`installation.md`](installation.md) |
| ruff | CIのlint。`pyproject.toml`のE/F/W/I/UP/B/SIM/RUFを検査 | 0.16.3 | `uv.lock`、dev dependencyの範囲指定 | [0.16.3 release notes](https://github.com/astral-sh/ruff/releases/tag/0.16.3) | ルール追加・変更、fix、出力形式、Python／Markdown解析 | [`AGENTS.md`](../AGENTS.md)、[`installation.md`](installation.md) |
| pyright | CIのstrict型検査。`packages`、`scripts`、`fixtures`を検査 | 1.1.411 | `uv.lock`、dev dependencyの範囲指定 | [releases](https://github.com/microsoft/pyright/releases) | 型推論、strict diagnostics、Python 3.12、stub変更 | [`AGENTS.md`](../AGENTS.md)、[`installation.md`](installation.md) |
| uv | workspace同期・lock生成・CIでのPython／依存導入 | CIはsetup-uv v10.0.1、ローカル版は環境依存 | workflowのsetup-uv SHA pin、`uv.lock` | [uv releases](https://github.com/astral-sh/uv/releases)、[setup-uv v10.0.1](https://github.com/astral-sh/setup-uv/releases/tag/v10.0.1) | resolver、lock format、workspace、Python取得、cache、Node runtime | [`AGENTS.md`](../AGENTS.md)、[`installation.md`](installation.md) |
| actions/checkout | CIでsubmoduleを含むrepositoryをcheckout | v7.0.1 | GitHub公式actionのタグ参照 | [v7.0.1 release](https://github.com/actions/checkout/releases/tag/v7.0.1) | `submodules`、`persist-credentials`、runner／Node runtime | [`installation.md`](installation.md) |
| astral-sh/setup-uv | CIでuvとPythonを導入 | v10.0.1 | commit SHA `20cfd1bf945f4377ade1205e4dbc17946fc9a30d`、コメントで版を併記 | [v10.0.1 release](https://github.com/astral-sh/setup-uv/releases/tag/v10.0.1) | Node 24 runner互換性、`python-version`、cache、uvの取得 | [`installation.md`](installation.md)、[`AGENTS.md`](../AGENTS.md) |
| CodeQL | workflowでの利用は確認できず | 該当なし | 該当なし | [GitHub CodeQL](https://codeql.github.com/docs/) | workflowに追加する場合のみaction SHA、言語、権限、解析対象を確認 | `.github/workflows/`と関連するセキュリティ文書 |
| kicad-cli | KiCad adapterでERC／DRC、netlist、Gerber／drill出力。`scripts/run_gd1_pipeline.py`でも使用 | 環境プローブで検出（CI固定なし） | 実行環境で版をprobeしEvidenceへ記録 | [KiCad CLI docs](https://docs.kicad.org/cli/9.0/) | CLI引数、ERC／DRC、出力形式、ライブラリとproject format | [`tool-selection.md`](tool-selection.md)、[`tool-capability-probes.md`](tool-capability-probes.md) |
| FreeRouting | `acd_adapter_freerouting`でDSN→SES外部routing | 環境プローブで検出（CI固定なし） | 実行環境で版をprobeしEvidenceへ記録 | [FreeRouting releases](https://github.com/freerouting/freerouting/releases) | DSN／SES形式、収束、幅・clearance、終了コード | [`tool-selection.md`](tool-selection.md)、[`tool-capability-probes.md`](tool-capability-probes.md) |
| ESP-IDF | `acd_adapter_espidf.build`が`idf.py`を呼ぶ。現行CI workflowでの実行は確認できず | 固定なし（要probe） | `IDF_PATH`と`idf.py --version`を実行時検証 | [ESP-IDF releases](https://github.com/espressif/esp-idf/releases) | toolchain／target、build output、merge-bin、ログ、再現性 | [`design-flow.md`](design-flow.md)、[`installation.md`](installation.md) |
| QEMU | `acd_adapter_espidf.qemu`が`qemu-system-riscv32`で仮想実行・serial log gate | 固定なし（要probe） | 実行時にversionをprobeしEvidenceへ記録 | [QEMU releases](https://www.qemu.org/download/) | target、machine、serial log、timeout、exit status | [`design-flow.md`](design-flow.md)、[`tool-capability-probes.md`](tool-capability-probes.md) |
| `vendor/software-agent-sdk` | OpenHands SDKのsource submodule | v1.42.1 | submodule SHA `167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497` | [release](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.42.1) | source差分、API、submodule版表記、lock再生成 | [`openhands-integration.md`](openhands-integration.md)、[`installation.md`](installation.md) |
| `vendor/openhands` | Agent Canvas sourceを参照するsubmodule。acd-agentのSDK実行基盤ではない | v1.13.0 | submodule SHA `4f465f3ccada5271a3bbe4a0148941b0c40d243b` | [repository](https://github.com/All-Hands-AI/OpenHands) | Canvas source API、実行版との差異、過去の実測値 | [`installation.md`](installation.md)、[`prior-art.md`](prior-art.md) |

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
