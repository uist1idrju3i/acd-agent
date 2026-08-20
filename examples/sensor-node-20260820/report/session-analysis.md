# セッション分析（2026-08-20 実行例作成〜リリース〜レビュー）

対象は次の2つの作業全体である。

1. OpenHands実装セッション: GD1を参考にしたsensor-node設計・製造データ生成
   （会話ログ: [`../conversation/`](../conversation/)、1,288イベント、08:49〜13:00 UTC）
2. Devinセッション: 実行例のリポジトリ整理、PR #136、v0.0.1リリース対応、
   成果物レビュー（[`review-notes.md`](review-notes.md)）、docs反映

## 1. OpenHands実装セッションの分析

### 定量観測

- イベント総数 1,288: ActionEvent 240 / ObservationEvent 223 /
  HookExecutionEvent 493 / UserRejectObservation 17 / Condensation 3 / MessageEvent 7
- ActionEvent内訳: terminal 183 / file_editor 44 / task_tracker 6 / finish 5 / think 2
- トークン使用量: 入力 32,717,982 / 出力 104,427（比率 約313:1）、
  コンテキストウィンドウ 163,140、チャット生成 252リクエスト

### 所見

- **terminal偏重**: 全pipeline実行・検証がscripts経由のterminal実行であり、
  ACDのToolDefinition群（`acd_validate_design_graph`等）は本会話にSDKツールとして
  登録されていなかった。結果は同等だが、tool経路（Pydantic契約による型付き入出力）の
  検証機会を逃した。tool登録条件の文書化とdoctor診断化が望ましい。
- **入力トークン比率が極端に大きい**: 長大なログ・ファイル内容の再取り込みが
  繰り返された可能性が高い。Condensationは3回のみで、コンテキスト管理は概ね健全だが、
  pipelineログの要約出力（tail既定化等）で入力量を削減できる余地がある。
- **fail-closed境界は実際に機能した**: hookによる遮断17件（`out/`配下への書き込み等）は
  すべて妥当であり、副作用境界の設計が実運用で有効だった。遮断理由の自動集計があると
  振り返りが容易になる。
- **SKILL活性化はKeywordTriggerのみ**: acd-qc-seven-tools / acd-reliability-review は
  一度も活性化されず、`/acd:gates` も未使用。trigger語彙の見直し、または
  pipeline完了時にレビュー系SKILLを促す手順の追加が望ましい。
- **環境セットアップの試行錯誤が大きい**: QEMUのPATH・`libslirp0`・SDL2系の解消に
  複数回の編集・再実行を要した。locked imageへの同梱が最も効果的な改善である。

## 2. Devinセッションの分析

### うまくいった点

- コミット前検証でコピー元との全ファイルsha256一致を確認し、改変・取りこぼしなく
  実行例を取り込めた（FW `build/` 除外はライセンス上の判断として文書化済み）。
- ライセンス確認（CC-BY-SA 4.0帰属維持、Apache-2.0由来物の除外・注記）を
  取り込み前に実施し、帰属READMEを維持した。
- レビューで視覚投影SVGのfont-size欠落など、ゲートでは検出されない
  「表示品質」の問題を発見できた（決定論的ゲートはSVGの機械可読性を照合するが、
  人間可読性は対象外である）。

### 問題点と根本原因

- **CI回帰の見逃し（重要）**: PR #136マージ後、mainの`verify`ジョブが
  会話ログmd（生成artifact、未クローズのコードフェンス・存在しない相対リンクを含む）の
  docs検証で失敗した。根本原因は2つある。
  1. `verify_docs.py`はgit追跡済みMarkdownのみを検査するため、
     コミット前検証を実行した時点（ファイルが未追跡）では検出されなかった。
  2. マージ確認時にCIがまだ実行中だったにもかかわらず完了と誤認した。
  対策: (a) 会話ログ等の生成artifactをdocs検証の対象定義から除外する
  （検証自体は弱めない。除外は「人間が保守する文書ではないbyte-exact成果物」に限定）、
  (b) 実行例取り込み時は`git add`後に`verify_all --stage docs`を実行する手順を
  operations.mdへ明記する。
- **タグ作成のruleset制限**: `v0.0.1`タグのpushがGH013で拒否され、ユーザーの手動作成が
  必要になった。リリース手順（タグ作成権限・ruleset・リリースノート方針）が
  docsに存在しない。
- **リリースノートの手戻り**: assets添付と実行例詳細の記載がユーザー方針
  （assetsなし・実行例はリンクのみ）と食い違い、2回の修正を要した。
  リリースノートの記載方針を文書化しておくと再発しない。

## 3. ドキュメントへの反映

本分析に基づく反映は次のとおり（詳細は[`roadmap.md`](../../../docs/roadmap.md)の
改善バックログを参照）。

- `scripts/verify_docs.py`: `examples/*/conversation/` 配下の会話ログartifactを
  検査対象から除外（mainのCI回帰の修正）
- `docs/operations.md`: 実行例取り込み手順（追跡後のdocs検証、生成artifactの扱い）、
  リリース手順の注意（タグ作成ruleset、リリースノート方針）を追記
- `docs/roadmap.md` 改善バックログ: pipelineログの要約出力、hook遮断の要約集計、
  ToolDefinition登録のdoctor診断化、SKILL trigger見直し等（反映済み項目を含む）
