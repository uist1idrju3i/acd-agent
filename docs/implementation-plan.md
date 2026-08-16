# 実装計画

> ステータス: Draft
> 対象: ACD実装の構成正本（リポジトリ構成、Pydantic契約、adapters、Skill、agent、テスト、CI）

本書は、実装のリポジトリ構成、パッケージ分割、配布資材（Skill／plugin／AgentDefinition）、
テスト・CI戦略の具体名を正とする。分割の**原則**（レイヤ境界、1 adapter = 1ツール、
生成と判定の分離、ツール版の固定）は[`architecture.md`](architecture.md)を正とし、本書は
その原則をディレクトリとパッケージ名へ具体化する。フェーズ境界と完了条件は
[`roadmap.md`](roadmap.md)、Phase 0の作業単位は[`phase0-plan.md`](phase0-plan.md)、
SDKの責務境界は[`openhands-integration.md`](openhands-integration.md)を参照する。

## 1. リポジトリ構成

単一リポジトリ（uv workspaceによるmonorepo）とする。Python 3.12+、uv、ruff、pyrightを
標準とし、ソースコードの識別子とコメントは英語、文書・コミット・PRは日本語とする
（[`../AGENTS.md`](../AGENTS.md)）。

```text
acd-agent/
├── pyproject.toml          # uv workspaceルート
├── packages/               # Pythonパッケージ（レイヤ境界単位）
│   ├── acd-schema/         # Pydantic契約
│   └── adapters/
│       ├── acd-adapter-kicad/        # kicad-cli（ERC/DRC/Gerber/STEP export）
│       ├── acd-adapter-freerouting/  # freerouting（DSN/SES）
│       ├── acd-adapter-cad/          # build123d/OCP（筐体生成・干渉・肉厚）
│       └── （以降、simulation、slicer、fw等をフェーズ着手時に追加）
├── plugins/acd/            # OpenHands plugin（Skill・agents・hooks・MCP設定の配布単位）
│   ├── .plugin/plugin.json
│   ├── skills/
│   ├── agents/
│   └── hooks/hooks.json
├── fixtures/               # golden task入力（tracked、hash付き）
├── scripts/                # golden task実行、文書検証、能力プローブ
├── docs/
│   └── adr/                # 設計決定記録（Phase 0で開始）
└── vendor/
    ├── openhands/
    └── software-agent-sdk/
```

- `acd-schema`はPydanticモデルを契約として持ち、各adapterは合否判定を持たない。
- adapterは1外部ツール・1形式版系列につき1パッケージとし、ツール版と形式版を固定する。
- OpenHands SDKの`Conversation`／workspace／plugin登録を優先し、同等のACD独自実行層を作らない。

依存方向はPydantic契約 → adapters → pipeline scriptsの一方向とする。

## 2. パイプラインとadapterの分割

初期パイプラインは次の処理を持つ。

| tool | 副作用クラス | 概要 |
|---|---|---|
- 入力ファイルからの投影生成。
- 独立parserによる再読込。
- ERC/DRC、geometry、干渉、FW検査などの決定論的ゲート。
- 発注直前の全ゲート実行と上限額確認。

## 3. Skill・plugin・AgentDefinitionの分割

配布資材は`plugins/acd/`の単一pluginへまとめ、解決済みSHAで固定する
（[`openhands-integration.md`](openhands-integration.md)）。

### Skill（工程チェックリスト・手法は1 Skill = 1工程観点）

| Skill | 内容の出所 | trigger |
|---|---|---|
| `e1-circuit-review` | E1レビュー観点（[`design-flow.md`](design-flow.md)） | TaskTrigger |
| `e2-artwork-review` | E2レビュー観点、アンテナ・strapping等 | TaskTrigger |
| `m1-m2-enclosure-review` | 筐体観点（干渉・肉厚・締結・公差） | TaskTrigger |
| `s2-manufacturing-output` | 製造出力・面付け手順 | TaskTrigger |
| `ecad-pitfalls` | [`ecad-domain-notes.md`](ecad-domain-notes.md)の落とし穴 | PathTrigger（ECAD投影パス） |
| `projection-review` | [`projection-review.md`](projection-review.md)のレビュー観点 | KeywordTrigger |
| `fw-lane-procedure` | FWレーン手順・ピン整合の確認手順 | TaskTrigger |

Skillはプロンプト資材であり、triggerの発火を適用可否の最終判定にしない
（[`knowledge-base.md`](knowledge-base.md)）。

### AgentDefinition（1 agent = 1役割、生成と判定は別）

| agent | 役割 | 主なtools |
|---|---|---|
| `acd-requirements` | S1要件対話・構造化 | workspace shell、file editor、パイプラインスクリプト |
| `acd-electrical` | E1/E2生成。配置・回転・配線の探索と設計根拠を確認する | workspace shell、file editor、パイプラインスクリプト |
| `acd-mechanical` | M1/M2生成 | workspace shell、file editor、パイプラインスクリプト |
| `acd-firmware` | FWレーン実装 | projection系、terminal、file editor |
| `acd-reviewer` | 機械可読投影のレビュー（入力ファイルへの書込み不可） | file editor、`inspect_image_with_vision`、workspace shell |
| `acd-visual-reviewer` | 視覚投影レビュー（vision profile、書込み不可） | `inspect_image_with_vision` |

リポジトリ探索・テスト実行等の汎用作業はSDK builtinサブエージェント
（`code-explorer`、`bash-runner`等）を再利用し、自作しない。

## 4. テスト・CI戦略

- 単体テスト: パッケージごとに`pytest`。Pydanticモデルの検証を必須とする。
- 決定論的AI回帰: SDKの`TestLLM`で応答・例外を固定する。実LLMのgolden taskは適格性の
  定期再測定として分離する（[`../AGENTS.md`](../AGENTS.md)）。
- golden task: `scripts/`の単一コマンドでfixtureから実行し、negative testを必ず対にする。
  完了条件の5要素は[`roadmap.md`](roadmap.md)の書式に従う。
- 文書検証: 相対リンク、アンカー、Mermaid、コードフェンス、見出し階層、用語集整合、
  `git diff --check`を`scripts/verify_docs.py`で機械検証し、CIとローカルで同一入力とする。
- CI: `uv sync` → `uv run ruff check` → `uv run pyright` → `uv run pytest` → 文書検証 →
  golden task（CIで回す範囲は[`roadmap.md`](roadmap.md)未決事項の切り分けに従う）。
- fixture・scriptはtrackedとし、typecheck／lint対象へ含める（フェーズ横断検証要件4）。

## 5. 設計決定の記録

`docs/adr/`をPhase 0で開始し、以後の構成変更はADRを先に起こす。最初に記録するADR:

1. monorepo（uv workspace）とパッケージ境界の採用。
2. Pydanticモデルを契約の正とし、モデルの検証を行う方式。
3. 最小ACDドメインeventをSDK `EventLog`へ載せ、ドメイン記録の正をcommit済み
   Evidence artifactへ置く方式。
4. 部品カタログ・ライブラリの出所方針（Phase 0で確定）。
5. AI主導の配置・回転・配線探索の三層分離と、探索ハーネスをリポジトリへcommitする方針
   （[`ADR-0007`](adr/ADR-0007-llm-guided-physical-design.md)）。

探索器・整合化器・代理指標の生成側と、実測・ゲートの判定側は別モジュールとして実装する。
探索ハーネスは`scripts/`または`packages/`へcommitし、使い捨ての外部スクリプトへ依存しない。

## 6. 実装順序

実装はマイルストーン・フェーズ順（[`roadmap.md`](roadmap.md)）に従い、各フェーズ着手時に
`docs/phaseN-plan.md`で作業単位を管理する。最初の対象はPhase 0であり、その作業単位・
順序・撤退条件は[`phase0-plan.md`](phase0-plan.md)を正とする。Phase 1〜2は
[`golden-design-1.md`](golden-design-1.md)を対象実物とする。

## 7. 未決事項

- adapterパッケージへのsimulation／slicer／fw追加時の命名と、二次候補ツールの持ち方。
- pluginをリポジトリ内サブディレクトリのまま配布するか、別リポジトリへ分離するか。
- golden taskのCI実行範囲と頻度（[`roadmap.md`](roadmap.md)未決事項と同一）。
