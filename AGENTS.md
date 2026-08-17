# エージェント作業契約

> 対象: OpenHands Software Agent SDK v1.42.1、Python 3.12+

本書は本リポジトリでの実装・検証・文書化の作業契約である。READMEは製品概要、
`docs/`は仕様と運用方針、`docs/adr/`は設計決定、Pydanticモデルは契約の正とする。
README、docs、Issue、PR、コミットメッセージは日本語、コードのコメントと識別子は英語とする。

## 構成

```text
packages/
├── acd-schema/
├── acd-core/
├── acd-pipeline/
├── acd-tools/
└── adapters/
    ├── acd-adapter-kicad/
    ├── acd-adapter-freerouting/
    └── acd-adapter-cad/
plugins/acd/
├── skills/
├── agents/
├── commands/
├── hooks/
├── .plugin/plugin.json
└── .mcp.json
vendor/software-agent-sdk/       # OpenHands SDK v1.42.1のみ
```

Agent Canvasのsubmoduleは削除済みであり、追加しない。OpenHands公開Skills repository
（<https://github.com/OpenHands/extensions>）もsubmoduleにしない。

## 不変条件

- 入力ファイルとgitを設計の正とし、投影を入力へ逆流させない。
- AIとSkillは提案し、決定論的ゲートが合否を判定する。
- Skill結果、代理指標、自然文レビューを合否根拠にしない。
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
FW、レビューの役割を分ける。`/acd:gates` commandと`acd-mcp` MCP serverは既存の
決定論的入口だけを使う。独自tool、event、history、task、executor基盤は作らず、
OpenHands SDKへ委譲する。

Skillsのtriggerは`KeywordTrigger`を使う。`paths:`はmodel invocationを無効化し、
`inputs:`はTaskTriggerになるため現在は使わない。reviewerは合否権限を持たない。
SDK hooksはagent経路のfail-closed境界として採用するが、CIの決定論的検証を置き換えず、
既存判定を呼び出すだけとする。

## 依存とsubmodule

Python依存、submodule、外部ツールを更新する場合は一次情報を確認し、
使用API、既定値、破壊的変更、採否を`docs/dependency-notes.md`へ記録する。
`vendor/software-agent-sdk`のsubmodule版を更新した場合は本書冒頭も同じ変更で更新する。

ファイルを削除・移動するときは、関連文書、索引、相対リンク、参照先を同じ変更で更新し、
旧パスへの参照を残さない。

## 検証

通常は次をすべて実行する。

```bash
uv sync
uv run ruff check
uv run pyright
uv run pytest
uv run pytest plugins -q
uv run python scripts/verify_docs.py
uv run python scripts/run_gd1_enclosure_pipeline.py --out out/gd1-enclosure
uv run python scripts/probe_tools.py
git diff --check
```

Markdownのみの変更で実装資材を変更していない場合は`verify_docs.py`と
`git diff --check`に絞ってよい。GD1基板pipelineのsilkscreen fail-closedは既知状態で
あり、silkscreen以前の各段階を確認して報告する。

## Git

日本語コミットを使い、`git add .`、amend、`--no-verify`、force push、mainへのpush、
`reset --hard`、`clean -fd`、`checkout -- file`、`stash drop`を使わない。
生成された`out/`、秘密情報、環境ファイルをcommitしない。PR作成・pushは依頼がある
場合だけ行う。
