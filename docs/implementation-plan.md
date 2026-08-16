# 実装計画

> ステータス: Draft  
> 対象: ACD実装の構成正本（リポジトリ構成、パッケージ、schema正本、tool、Skill、agent、テスト、CI）

本書は、実装のリポジトリ構成、パッケージ分割、配布資材（Skill／plugin／AgentDefinition）、
テスト・CI戦略の具体名を正とする。分割の**原則**（レイヤ境界、1 adapter = 1ツール、
生成と判定の分離、版とstale境界）は[`architecture.md`](architecture.md)を正とし、本書は
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
├── schemas/                # 機械可読契約の正本（JSON Schema）
├── packages/               # Pythonパッケージ（レイヤ境界単位）
│   ├── acd-schema/         # schema層: schemas/と1対1のPydanticモデル
│   ├── acd-core/           # core層: graph、rationale、impact、gate、knowledge
│   ├── acd-events/         # 最小ACDドメインevent型（gate結果・承認・receipt参照）
│   ├── acd-tools/          # agent tools層: ToolDefinition、tool envelope、共通executor
│   ├── acd-runtime/        # 合成ルート: SessionStart hook、agent登録、profile、会話構成
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

- `schemas/`は契約ごとに1ファイルとする: `design-graph`、`tool-envelope`、`gate-matrix`、
  `error-taxonomy`、`event-payload`、`review-finding`、`evidence`。文書と実装はこの正本
  から導き、二重管理しない。
- `acd-schema`は`schemas/`のJSON Schemaと相互検証されるPydanticモデルだけを持ち、
  ロジックを持たない。
- `acd-core`は外部ツール固有の型を参照せず、`acd-tools`と各adapterは合否判定を持たない。
- adapterは1外部ツール・1形式版系列につき1パッケージとし、ツール版・形式版の独立した
  変動をパッケージ境界（＝stale境界）と一致させる。
- `acd-runtime`だけがSDKの`Conversation`／workspace／plugin登録へ依存する合成ルートで
  あり、`acd-core`はSDKへ依存しない（`acd-events`と`acd-tools`はSDKの型のみ参照可）。

依存方向は`schemas/` → `acd-schema` → `acd-core` → adapters → `acd-tools` → `acd-runtime`
の一方向とする。

## 2. agent toolsの分割

1 toolは1副作用クラスに対応させる（[`architecture.md`](architecture.md)）。初期tool群:

| tool | 副作用クラス | 概要 |
|---|---|---|
| `graph_query` | read | 設計グラフの照会・述語評価 |
| `graph_patch` | 可逆 | patch適用と新revision生成、影響導出の起動 |
| `projection_generate` | 可逆 | 対象revisionからの投影生成（adapter経由） |
| `projection_reload` | read | 生成artifactの独立再読込・照合 |
| `placement_search` | 可逆 | 探索仕様に基づく決定論的候補生成・幾何整合化・代理指標順位付け |
| `gate_run` | read | 決定論的ゲート実行とEvidence生成 |
| `evidence_query` | read | Evidence・stale状態の照会 |
| `commit_receipt` | 可逆 | commit実行とcommit receipt生成 |
| `order_execute` | 不可逆 | 発注実行（Phase 11。`hobby`は上限額と直前全ゲート、`small-production`以上は裁量枠・最終ゲート・承認確認付き） |

全toolは共通executorを経由し、`hobby`では版と入力・出力hashを記録する。
idempotency key、副作用分類、`unknown`意味論を含む量産品質のtool envelopeは
`small-production`以上で有効化する。readと不可逆操作を同一toolへ混ぜない。

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
| `q7n7-methods` | [`qc-tools.md`](qc-tools.md)の作業手法 | KeywordTrigger |
| `fw-lane-procedure` | FWレーン手順・ピン整合の確認手順 | TaskTrigger |

Skillはプロンプト資材であり、triggerの発火を適用可否の最終判定にしない
（[`knowledge-base.md`](knowledge-base.md)）。

### AgentDefinition（1 agent = 1役割、生成と判定は別）

| agent | 役割 | 主なtools |
|---|---|---|
| `acd-requirements` | S1要件対話・構造化 | `graph_query`、`graph_patch` |
| `acd-electrical` | E1/E2生成。配置・回転・配線の探索仕様と設計根拠を宣言する | graph系、projection系、`placement_search`、`gate_run` |
| `acd-mechanical` | M1/M2生成 | graph系、projection系、`gate_run` |
| `acd-firmware` | FWレーン実装 | projection系、terminal、file editor |
| `acd-reviewer` | RV1機械可読レビュー（グラフ書込み不可） | `graph_query`、`projection_reload` |
| `acd-visual-reviewer` | 視覚投影レビュー（vision profile、書込み不可） | `inspect_image_with_vision` |

リポジトリ探索・テスト実行等の汎用作業はSDK builtinサブエージェント
（`code-explorer`、`bash-runner`等）を再利用し、自作しない。

## 4. テスト・CI戦略

- 単体テスト: パッケージごとに`pytest`。schemaはJSON Schema⇔Pydanticの往復検証を必須とする。
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
2. schema正本をJSON Schemaとし、Pydanticモデルと相互検証する方式。
3. 最小ACDドメインeventをSDK `EventLog`へ載せ、ドメイン記録の正をcommit済み
   Evidence artifactへ置く方式。
4. 部品カタログ・ライブラリの出所方針（Phase 0で確定）。
5. AI主導の配置・回転・配線探索の三層分離と、探索ハーネスをリポジトリへcommitする方針
   （[`ADR-0007`](adr/ADR-0007-llm-guided-physical-design.md)）。
6. VibeBBの最小構成とprofileによる機構の段階有効化（[`ADR-0008`](adr/ADR-0008-minimal-vibebb-scope.md)）。

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
