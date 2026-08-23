# エージェント作業契約

> 対象: OpenHands Software Agent SDK v1.43.1、Python 3.12+

本書は本リポジトリでの実装・検証・文書化の作業契約である。READMEは製品概要、
`docs/`は仕様と運用方針、`docs/adr/`は設計決定、Pydanticモデルは契約の正とする。
README、docs、Issue、PR、コミットメッセージは日本語、コードのコメントと識別子は英語とする。

## 構成

```text
src/acd/
├── schema/
├── core/
├── pipeline/
├── openhands/
│   ├── session/
│   ├── safety/
│   ├── evidence/
│   ├── tools/
│   └── distribution/
└── adapters/
    ├── kicad/
    ├── freerouting/
    └── cad/
tests/
├── schema/
├── core/
├── pipeline/
├── openhands/
└── adapters/
plugins/acd/
├── skills/
├── agents/
├── commands/
├── hooks/
└── .plugin/plugin.json
vendor/software-agent-sdk/       # OpenHands SDK v1.43.1のみ
```

本リポジトリはOpenHands Software Agent SDK v1.43.1専用拡張であり、機能採否は
`docs/openhands-sdk-capabilities.json`を契約の正として管理する。Markdown表は
`scripts/verify_sdk_capabilities.py`で機械生成し、driftを検査する。
Accepted ADRの索引は`docs/README.md`を正とし、Superseded ADRは統合先を示すpointerだけを残す。
agent-serverは対象外であり、採用する場合は新規ADRを起票する。

## 不変条件

- 入力ファイルとgitを設計の正とし、投影を入力へ逆流させない。
- L1判定は決定論的ゲートとrevision一致のauthoritative Evidenceだけが担う。
- L2のcritic、Skill、agent、reviewerは操舵、L3のevent、metrics、telemetryは観測に限る。
- L2とL3は停止側にだけ作用でき、合格側へ作用させない。
- ツール不在、parse失敗、ゲート未実行、unknown、未検証はfail-closedにする。
- 閾値、期待値、evidence規則を成功のために緩めない。
- SkillのPython moduleをACD本体からimportしない。必要なCLIはsubprocessで実行する。
- 探索結果を設計入力へ確定した場合、Skill名とscript sha256をprovenanceへ記録する。
- evidence／provenanceには、出所、取得時点、版、入力hash、出力hash、ツール名・版を記録する。
- 判定対象を故意に壊すnegative testを用意し、壊した入力が不合格になることを確認する。
- API key、token、secretをログ、入力、commitに書かない。
- GPL/AGPLコードをACDへimport結合しない。

外部由来コードを含むファイルでは、元のライセンス表記と帰属を維持する。派生コードを
含むファイルにのみ必要な表記を追加し、新規自作ファイルへ無関係な第三者著作権表記を
追加しない。

## plugin境界

Skillsは工程手法、探索、FW作業、レビューを提供する。AgentDefinitionは電気、機械、
FW、レビューの役割を分ける。`/acd:gates` commandとSDK ToolDefinitionは既存の
決定論的入口だけを使う。独自tool、event、history、task、executor基盤は作らず、
OpenHands SDKへ委譲する。

Skillsのtriggerは`KeywordTrigger`を使う。`paths:`はmodel invocationを無効化し、
`inputs:`はTaskTriggerになるため現在は使わない。reviewerは合否権限を持たない。
SDK hooksはagent経路のfail-closed境界として採用する。agent-server packageとserver直接APIは
対象外であり、採用する場合は新規ADRで受入条件を定義する。CIの決定論的検証を置き換えない。
Conversationにはpinned SDKの`EnsembleSecurityAnalyzer`、`ConfirmRisky`、
`SecretRegistry`、`load_skills_from_dir`、`StuckDetector`を設定する。これらはL2の
操舵・停止・漏洩防止層であり、authoritative Evidenceを生成・昇格しない。既定の明示経路では
ACD Skillを`plugins/acd/skills`だけからロードし、事前検証・ロード数照合とfail-closed契約を
維持する。ADR-0036のambient install経路ではSDK installed-plugin自動読み込みのwarn-and-continue
意味論に従い、事前検証を行わない。public/userの自動読み込みは明示経路では無効とし、
MarketplaceRegistryは引き続き使用しない。Skill資材の読み込み失敗は明示経路ではfail-closedとし、
既存のorder guard、projection保護、
stop policy hookを置換しない。GoalControllerとconversation cancellationは同じL2停止境界で
再利用し、ConversationStatsはL3観測に限定する。goal結果やjudge評決をEvidenceへ昇格しない。
lane並列は`tool_concurrency_limit`を明示した場合だけ有効化し、資源宣言不能時は
SDKのmutexによる直列化へ倒す。task/delegateのsub-agentは親hookを継承しないため、
ACD AgentDefinitionへ必須hookを明記し、SDKロード結果を検査する。AgentDefinitionは
`skills:`を宣言せず、plugin同梱SkillのSKILL.mdをpromptからパス参照する（ADR-0039）。
browser_useは既定無効で、明示有効時だけChromiumの利用可能性を検査してL2探索補助として
登録する。browser由来の観測をEvidenceへ昇格させず、決定論的API取得を置き換えない。
workflowは任意Python scriptがhook境界の外で実行されうるため不採用（将来再検討）とする。

## 並列実行

CPUバウンドな処理は既定でマルチコアを使う。新規実装でも、要素間が独立なループと
独立stageは並列実行を前提に設計する。

- 並列度は`--jobs`や`--*-workers`のような明示引数で受け、既定は`min(os.cpu_count() or 1, N)`とする。
- 外部プロセス待ちとI/O待ちが主体の処理は`ThreadPoolExecutor`、Pythonの計算と
  ネイティブ拡張（OCP等）が主体の処理は`ProcessPoolExecutor`を使う。
- 並列度を成果物へ影響させない。reduceは宣言順またはID順で行い、worker数をhash入力、
  Evidence、provenanceへ入れない。
- 逐次（worker=1）と並列（worker=N）で正規化hashと判定が一致することを回帰テストで固定する。
- 失敗はfail-closedのまま扱い、部分成功を合格側へ昇格しない。
- 並列化で短縮を主張する場合は同一入力の逐次・並列比較を実測し、`docs/`へ記録する。
  外部ツールが支配項で短縮が測れない場合もその事実を記録する。

## 依存とsubmodule

Python依存、submodule、外部ツールを更新する場合は一次情報を確認し、
使用API、既定値、破壊的変更、採否を`docs/operations.md`へ記録する。
`vendor/software-agent-sdk`のsubmodule版を更新した場合は本書冒頭も同じ変更で更新する。
submodule版を更新する場合は、同じ変更で`pyproject.toml`のPyPI pinも同じ版へ更新する。
SDK機能の採否は`docs/openhands-sdk-capabilities.json`を単一の正とし、
`docs/openhands-sdk-capabilities.md`は機械生成ブロックを含む説明文書とする。

ファイルを削除・移動するときは、関連文書、索引、相対リンク、参照先を同じ変更で更新し、
旧パスへの参照を残さない。

## 検証

検証段階とコマンド列の正は`scripts/verify_all.py`である。定義は

```bash
uv run python scripts/verify_all.py --list
```

で機械可読に列挙できる。文書のみ、通常、フルの3段階を次で実行する。

```bash
uv run python scripts/verify_all.py --stage docs
uv run python scripts/verify_all.py --stage standard
uv run python scripts/verify_all.py --stage full
```

`verify_all.py`は`uv sync`を各段階の先頭で単独実行し、完走後にruff、pyright、
pytest、各`verify_*.py`、`git diff --check`を最大
`min(os.cpu_count() or 1, 4)`本まで並列実行する。`--jobs 1`は従来どおり宣言順に
実行して最初の失敗で停止し、`--jobs N`（N > 1）は起動済みの独立コマンドを完走させ、
宣言順に出力してから失敗したコマンドをすべて報告する。`--list`のJSONには各コマンドの
`requires_sync`と`requires_previous`も含める。

pytestは既定で`-n auto --dist loadgroup`を有効にする。単体デバッグなどで並列化を
無効にする場合は`uv run pytest -n 0`を使う。テストは固定パス、cwd、環境変数、
installed plugin storeの共有状態を避け、独立化できない共有資源だけを
`pytest.mark.xdist_group`で同一workerへ固定する。並列・逐次で収集件数、判定、
正規化hashを一致させ、短縮を記録する場合は同一入力のwall-clockを比較する。

Markdownのみの変更で実装資材を変更していない場合は`--stage docs`に絞ってよい。
GD1のゲート実行とEvidence生成はdigest固定containerを
正とし、ホスト実行は参考実行で合格側Evidenceを生成しない。runnerは
事前build済みdigest固定server imageを`DockerWorkspace`で実行する。
host経路はprovisional専用であり、authoritative Evidenceの生成経路には使わない。
GD1基板pipelineはsilkscreenゲートまで通過する前提で、
resolverと基板pipelineを実行して確認する。

CIの`container-gates` jobはlock済みserver imageをpullし、
`scripts/run_in_workspace.py`（SDKの`DockerWorkspace`）経由でsilkscreen resolver、
GD1基板pipeline、GD1筐体pipelineをcontainer内で実行する。その後、
`scripts/verify_authoritative_evidence.py`で両laneのEvidenceがrevision一致、
`status="valid"`、既知のcontainer provenance、digestを持つことを決定論的に検査する。
host実行のEvidenceはprovisionalであり、合格側へ昇格しない。image publishは
`.github/workflows/publish-acd-tools.yml`の手動起動またはmainの`docker/**`変更（lock file
`docker/image-digests.json`と`docker/README.md`は除外）で行い、
GHCR digestをjob summaryから運用記録へ転記する。publish済みdigestが無い間はlock fileの
placeholderを作らない。

graphへ設計判断属性を追加する機能変更では、同じ変更で属性を
`REQUIRED_RATIONALE_ATTRS`または`RATIONALE_EXEMPT_ATTRS`へ分類する。必須属性には
rationale recordを追加し、どちらにも分類されない属性はcoverageの`unclassified`として
fail-closedになる。免除する場合も、属性ごとの英語理由を免除表へ記録する。

## Git

日本語コミットを使い、`git add .`、amend、`--no-verify`、force push、mainへのpush、
`reset --hard`、`clean -fd`、`checkout -- file`、`stash drop`を使わない。
生成された`out/`、秘密情報、環境ファイルをcommitしない。作業branchへのpushとPR作成は
都度の依頼を待たずに行ってよい。mainへの直接pushは行わない。
