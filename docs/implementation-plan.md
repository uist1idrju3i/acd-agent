# 直近の実装計画

> ステータス: 現行作業の分解。長期計画は[`roadmap.md`](roadmap.md)を参照する。

## 作業単位

1. **契約と入力**
   - `acd-schema`でgraph、profile、evidenceを検証する。
   - 欠落、不正、unknownをfail-closedにする。
2. **投影とadapter**
   - `acd-core`からレーンを抽出する。
   - `acd-pipeline`がKiCad、FreeRouting、CAD adapterを呼ぶ。
   - 生成物を独立parserで再読込する。
3. **plugin委譲**
   - Skillは探索・FW作業・レビュー手法を提供する。
   - AgentDefinitionは電気、機械、FW、レビューの役割を分離する。
   - commandとMCPは既存の決定論的入口だけを公開する。
4. **検証**
   - `uv run ruff check`
   - `uv run pyright`
   - `uv run pytest`
   - `uv run pytest plugins -q`
   - `uv run python scripts/verify_docs.py`
   - `git diff --check`

## 作業境界

Python側へ新しいagent executor、独自event、history、task基盤を追加しない。
SkillのPython moduleをACD本体からimportしない。探索結果を採用する場合はgraph.jsonへ
確定し、Skill名とscript sha256を記録する。合否はSkillの出力ではなく決定論的
pipelineと独立測定で判定する。

## 未着手の作業

- 投影後Gerber実測を使ったsilkscreen再配置ループ
- 実機の製造・組立・測定Evidence
- sourcing、価格・在庫・納期、発注guard
- SecretRegistry、DockerWorkspace、agent-server、Conversation実行経路

これらを実装する場合は、既存ADRとロードマップを先に更新し、fail-closed境界を
維持する。
