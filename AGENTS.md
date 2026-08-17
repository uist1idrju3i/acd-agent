# エージェント作業契約

> 対象: OpenHands Software Agent SDK v1.42.1、Python 3.12+

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
vendor/software-agent-sdk/       # OpenHands SDK v1.42.1のみ
```

本リポジトリはOpenHands Software Agent SDK v1.42.1専用拡張であり、機能採否は
`docs/openhands-sdk-capabilities.md`で管理する。

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
SDK hooksはagent経路のfail-closed境界として採用する。agent-serverのhooks APIは設定ロードを
担うが、server直接API全体への自動適用は未確認である。CIの決定論的検証を置き換えない。
Conversationにはpinned SDKの`EnsembleSecurityAnalyzer`、`ConfirmRisky`、
`SecretRegistry`、`load_skills_from_dir`、`StuckDetector`を設定する。これらはL2の
操舵・停止・漏洩防止層であり、authoritative Evidenceを生成・昇格しない。ACD Skillは
`plugins/acd/skills`だけを明示ロードし、public/user/marketplaceの自動読み込みを無効にする。
Skill資材の読み込み失敗はfail-closedとし、既存のorder guard、projection保護、
stop policy hookを置換しない。GoalControllerとconversation cancellationは同じL2停止境界で
再利用し、ConversationStatsはL3観測に限定する。goal結果やjudge評決をEvidenceへ昇格しない。
lane並列は`tool_concurrency_limit`を明示した場合だけ有効化し、資源宣言不能時は
SDKのmutexによる直列化へ倒す。task/delegateのsub-agentは親hookを継承しないため、
ACD AgentDefinitionへ必須hookを明記し、SDKロード結果を検査する。

## 依存とsubmodule

Python依存、submodule、外部ツールを更新する場合は一次情報を確認し、
使用API、既定値、破壊的変更、採否を`docs/operations.md`へ記録する。
`vendor/software-agent-sdk`のsubmodule版を更新した場合は本書冒頭も同じ変更で更新する。
SDK機能の採否は`docs/openhands-sdk-capabilities.md`を単一の正とする。

ファイルを削除・移動するときは、関連文書、索引、相対リンク、参照先を同じ変更で更新し、
旧パスへの参照を残さない。

## 検証

文書のみ:

```bash
uv run python scripts/verify_docs.py
git diff --check
```

通常:

```bash
uv sync
uv run ruff check
uv run pyright
uv run pytest
uv run python scripts/verify_docs.py
```

フル:

```bash
uv sync
uv run ruff check
uv run pyright
uv run pytest
uv run pytest plugins -q
uv run python scripts/verify_docs.py
uv run python scripts/resolve_gd1_silkscreen.py
uv run python scripts/run_gd1_pipeline.py
uv run python scripts/run_gd1_enclosure_pipeline.py --out out/gd1-enclosure
uv run python scripts/probe_tools.py
git diff --check
```

Markdownのみの変更で実装資材を変更していない場合は`verify_docs.py`と
`git diff --check`に絞ってよい。GD1のゲート実行とEvidence生成はdigest固定containerを
正とし、ホスト実行は参考実行で合格側Evidenceを生成しない。現行runnerは
`DockerDevWorkspace`でbase imageからserver imageを準備する移行中の経路である。
GD1基板pipelineはsilkscreenゲートまで通過する前提で、
resolverと基板pipelineを実行して確認する。

graphへ設計判断属性を追加する機能変更では、同じ変更で属性を
`REQUIRED_RATIONALE_ATTRS`または`RATIONALE_EXEMPT_ATTRS`へ分類する。必須属性には
rationale recordを追加し、どちらにも分類されない属性はcoverageの`unclassified`として
fail-closedになる。免除する場合も、属性ごとの英語理由を免除表へ記録する。

## Git

日本語コミットを使い、`git add .`、amend、`--no-verify`、force push、mainへのpush、
`reset --hard`、`clean -fd`、`checkout -- file`、`stash drop`を使わない。
生成された`out/`、秘密情報、環境ファイルをcommitしない。PR作成・pushは依頼がある
場合だけ行う。
