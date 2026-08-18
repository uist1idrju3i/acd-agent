# 運用・インストール

## 前提

- Linux環境
- Python 3.12以上
- `uv`
- KiCad CLI
- JavaとFreeRouting
- Docker（ゲート実行の正）

OpenHands Software Agent SDKは`vendor/software-agent-sdk`のsubmodule v1.42.1
（commit `167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497`）をworkspace sourceとして使用する。
agent-serverはACDの対象外であり、採用する場合は新規ADRで受入条件を定義する。現行の
実行形は`LocalConversation`と`DockerDevWorkspace` runnerを基点とする。事前build済み
digest固定imageへの移行後は`DockerWorkspace`を使う。

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
`docker/acd-tools.Dockerfile`を各自buildする。現行runnerは
`DockerDevWorkspace(base_image=...)`でagent-server imageを準備する。これはSDK実装上の
on-the-fly build経路であり、事前build済みserver imageを配布する運用へ移行したら
`DockerWorkspace(server_image=...)`へ切り替える。ホスト経路は移行中の参考実行であり、
合格側Evidenceを生成しない。

CIでは`container-gates` jobがbuildxでACD tools imageをbuildし、SDKの
`DockerDevWorkspace`を経由する`scripts/run_in_workspace.py`でresolver、基板pipeline、
筐体pipelineを実行する。agent-serverの`/workspace`を占有させるため、host repositoryは
`/acd-src:ro`へmountし、container内の`/workspace/acd`へ複製する。container内で生成された
`out/gd1/evidence-electrical.json`と`out/gd1-enclosure/evidence-mechanical.json`は、
SDKの`RemoteWorkspace.file_download()`でhostへ取り出してから
`verify_authoritative_evidence.py`へ渡す。revision不一致、host実行、digest不在、
unknown、parse失敗、file不在はすべて非ゼロ終了となる。

`DockerDevWorkspace`の実行imageはbase imageからpinned SDK v1.42.1で派生buildされる。
runnerはderived imageそのものではなく、入力base imageのcontent addressを
`ACD_CONTAINER_IMAGE_DIGEST`へforwardする。これは派生imageの同一性を偽装せず、base
digestとSDK版による再現可能な派生経路をEvidenceへ記録するためである。

`publish-acd-tools.yml`は`workflow_dispatch`またはmainへの`docker/**`変更pushで起動する。
GHCRのpublish job summaryに表示されたdigestを、利用するimage refとともに運用記録へ
転記する。publish済みdigestを持たない間はplaceholderのlock fileを作成せず、local build
のimage IDを実行時のcontent addressとして扱う。

将来、GHCRのpublish済みdigestを運用記録へ固定した後は、CIで毎回buildせず、そのdigestを
pullして`DockerDevWorkspace`へ渡す方式へ移行する。digest記録前に条件分岐でpull/buildを
切り替える実装は入れず、移行時に明示的な運用変更として扱う。

browser_useは`build_acd_conversation(enable_browser=True)`を明示したL2探索時だけ使用する。
Chromiumが利用できない場合は例外で停止し、browser由来の観測はEvidenceへ昇格させない。
EasyEDA APIの決定論的取得経路は維持し、設計入力へ確定する資材は既存経路で再取得して
hashを記録する。SDKのworkflowはfail-closed境界を保てないため不採用（将来再検討）とし、
agent-server系能力は対象外とし、採用判断は新規ADRの起票後に行う。

## 外部ツール

環境に次の実行ファイルが必要である。

```bash
command -v kicad-cli
command -v java
command -v freerouting
```

## 検証

検証段階とコマンド列は`uv run python scripts/verify_all.py --list`で確認できる
`verify_all.py`を正とする。文書のみ、通常、フルの段階を次で実行する。

```bash
uv run python scripts/verify_all.py --stage docs
uv run python scripts/verify_all.py --stage standard
uv run python scripts/verify_all.py --stage full
```

`full`には`pytest plugins`、silkscreen resolver、基板・筐体pipeline、外部ツールprobeを
含む。authoritative container gateはCI固有の`container-gates` jobで実行するため、
`verify_all.py`には含めない。

## 製造・組立受領の取り込み

送付manifestとfabまたは実装業者の受領recordを決定論的に突合する。manifest自身の
canonical JSON SHA-256を受領recordの`manifest_reference.manifest_hash`と比較し、
成果物の相対pathとcontent hash、対象revision、manifestの`unknowns`を検査する。
成果物の同一性に関係する構造不備、`status: "fail"`、不一致、受領record契約違反は
非ゼロ終了となる。manifestの`unknowns`は価格・納期などの追跡情報としてsortedキーを
reportへ記録するが、それ自体では突合を停止しない。出力Evidenceは合格側へ昇格しない。

```bash
uv run python scripts/ingest_receipt.py \
  --manifest fixtures/contracts/valid/fab-package-receipt.json \
  --receipt fixtures/contracts/valid/receipt.json \
  --evidence out/receipt-evidence.json \
  --report out/receipt-reconciliation.json
```

同一のmanifestとreceiptを再実行した場合、reportとEvidenceは同じバイト列になる。
受領recordの`recorded_by`は記録者 provenance としてEvidenceの測定機器operatorへ引き継がれる。
入力のJSON parse失敗、契約違反、manifest構造不備でもCLIはexit code 2を返し、
`status="unknown"`のreportを可能な限り出力する。
出力Evidenceは`execution_context="host"`で、`PhysicalEvidence.supports_authoritative_pass()`
は常に`False`である。

## 依存・版・破壊的変更の記録

依存、submodule、外部ツールを更新した場合は、使用API、既定値、破壊的変更、
採否を本節へ追記する。現行の基準は次のとおりである。

- SDKは`vendor/software-agent-sdk`のv1.42.1、commit
  `167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497`に固定する。更新前にpinned checkoutの
  API、上流release tag、CHANGELOGまたは一次リリース情報を確認する。
- Python依存は`pyproject.toml`とlockを正とし、既定値・公開API・破壊的変更を確認して
  `docs/openhands-sdk-capabilities.json`の採否へ反映する。Markdown表は
  `scripts/verify_sdk_capabilities.py`で生成し、採否enumと代表APIの検査を通す。
- KiCad CLI、Java、FreeRouting等の外部ツールは`command -v`と
  `uv run python scripts/probe_tools.py`で版と能力を記録する。版不明、未実行、
  出力不整合はゲートを緩めずfail-closedとする。
- DockerDevWorkspaceからDockerWorkspaceへ移行する際はimage digest、Dockerfile、外部ツール版を同時に記録し、
  ホスト実行の結果を合格側Evidenceへ昇格しない。

版と能力は次で記録する。

```bash
uv run python scripts/probe_tools.py
```

Docker workspace経路（ゲート実行の正）:

```bash
docker build -f docker/acd-tools.Dockerfile -t acd-tools-gates:local .
ACD_CONTAINER_IMAGE=acd-tools-gates:local uv run python scripts/run_in_workspace.py
```

image digestを解決できない場合、runnerはコマンドを実行せず非ゼロ終了する。
runnerは`ACD_CONTAINER_IMAGE_DIGEST`と`ACD_IN_CONTAINER`をcontainerへforwardする。
hostのToolEnvelopeは`execution_context="host"`、containerのToolEnvelopeは型付き
`container_image_digest`を持つ。`evidence/`へ昇格するCLIは
`supports_authoritative_pass()`を要求する。

外部ツールが無い、版が不明、または出力を独立再読込できない場合、pipelineは
fail-closedで停止する。ゲートの仕様とprobeの責務は[`gates.md`](gates.md)を参照する。

## plugin

OpenHands SDKから`plugins/acd`をpluginとして読み込む。pluginには8 Skill、5
AgentDefinition、`/acd:gates` command、SDK ToolDefinition、hooksが含まれる。
決定論的なACD入口は`acd.openhands.tools.definitions`の`register_acd_tools()`からSDKへ登録する。
Conversationの安全設定は`EnsembleSecurityAnalyzer`、`ConfirmRisky`、allowlist付き
`SecretRegistry`、ローカルSkill loader、`StuckDetector`を使用する。ACD analyzerと
Pattern analyzerのensembleは具体的riskの最大値を採用し、全て`UNKNOWN`なら
`UNKNOWN`、`propagate_unknown=True`なら任意の`UNKNOWN`を伝播する。これらはL2であり、
hostの参考実行をauthoritative Evidenceへ変えることはない。

Skill loaderはpinned SDKの
`load_skills_from_dir(skill_dir: str | Path) -> tuple[dict[str, Skill], dict[str, Skill], dict[str, Skill]]`
を使う。SDKは個別エラーを警告して継続する実装だが、ACD wrapperは各`SKILL.md`を
SDK `Skill.load()`で事前検証し、ロード数も照合して壊れた・欠落した資材をfail-closedにする。
public/user/marketplace自動読み込みは無効である。pinned SDKの`SecretValue`注釈には
callableの説明もあるが、実装の`_wrap_secret()`は`str | SecretSource`以外を拒否する。
そのためACDは環境変数をlazy `SecretSource`でラップする。secretの値はログ、
ToolEnvelope、Evidenceへ出さず、SDK registryのmaskingだけを出力境界に使う。

Goal loopはSDK `GoalController`をACD側のdriverから再利用する。SIGINTは
`LocalConversation.interrupt()`へ結線し、goalの中断結果は`status="interrupted"`として
記録する。`goal_result`と`conversation_stats`は`pass_evidence=false`の観測成果物であり、
judgeのcomplete評決や統計値を合否へ使わない。

lane並列は`tool_concurrency_limit`で設定し、既定値は1（直列）とする。2以上を指定する
場合は、ACD toolの`declared_resources()`が返す資源keyを経由して共有入力・出力を
直列化する。資源宣言やpath解決に失敗したtoolは宣言不能としてtool単位のmutexへ
fail-closedに倒す。task/delegateはhook付きAgentDefinitionに限定し、sub-agentの結果を
Evidenceへ昇格しない。workflowは任意scriptがhook境界を外れるため不採用（将来再検討）とする。

外部利用者が配布版を読み込む場合は、branch名ではなく不変refを指定する。
commit SHAは40桁で、release tagは`v<semver>`形式にする。

```python
from acd.openhands.distribution.plugin import acd_plugin_source

plugin = acd_plugin_source("v1.2.3")
```

`ref=None`、branch名、短縮SHA、空文字、不正なtagはfail-closedで拒否される。
開発checkoutでは`build_acd_conversation()`の既定local pathを使用できる。

## 検証

文書のみの変更は`uv run python scripts/verify_docs.py`と`git diff --check`で確認する。
通常のコード変更は`uv run ruff check`、`uv run pyright`、`uv run pytest`と文書検査を行い、
フル検証では`uv run pytest plugins -q`、GD1基板・筐体pipeline、`probe_tools.py`も実行する。

GD1基板pipelineはERC、routing、SES import、DRC、fabrication出力、独立再読込、
silkscreen可読性ゲートまで通過する。外部ツールや入力が不正な場合は、ゲートを
緩めずfail-closedとして状態をそのまま記録する。

`verify_authoritative_evidence.py`はLLMやSDKの判定を使わず、
`Evidence.supports_authoritative_pass()`とその構成要素だけを検査する。引数なし、
parse失敗、file不在、revision不一致、status不正、host実行、digest不在、unknown混入は
成功扱いにしない。

## トラブル時

- `uv sync`が失敗する場合はsubmoduleが初期化されているか確認する。
- 外部ツールが見つからない場合は`probe_tools.py`の結果を確認する。
- graphやfixtureが不正な場合は入力を修正し、エラーを成功扱いにしない。
- 秘密情報をログ、fixture、graph、commitへ書かない。
