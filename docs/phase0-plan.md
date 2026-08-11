# Phase 0実施計画

> ステータス: Draft  
> 対象: Phase 0「契約とツール能力確認」の作業単位・順序・撤退条件

本書は、Phase 0の作業単位・順序・撤退条件を正とする。Phase 0の内容・やらないこと・
完了条件（ゴールデンタスク）は[`roadmap.md`](roadmap.md)を正とし、ここで二重管理しない。
リポジトリ構成・パッケージ名は[`implementation-plan.md`](implementation-plan.md)、
能力プローブの項目詳細は[`ecad-domain-notes.md`](ecad-domain-notes.md)を参照する。

## 作業単位と順序

作業単位は依存順に並べる。各単位は、成果物、検証方法、完了の観測点を持つ。

### W1 リポジトリ骨組みと検証基盤

- uv workspace、`packages/`、`schemas/`、`scripts/`、`docs/adr/`の初期化。
- ruff、pyright、pytest、CIパイプラインの設定。
- `scripts/verify_docs.py`（文書検証契約の機械化）を実装し、既存全文書が通ることを確認する。
- ADR-0001（monorepo構成）、ADR-0002（schema正本方式）を起こす。

### W2 schema正本（Phase 1〜2に必要な範囲のみ）

- `schemas/`にdesign-graph（電気・FW・Evidence・安全境界の最小domain）、tool-envelope、
  gate-matrix、error-taxonomy、event-payload、review-finding、evidenceを定義する。
- FWパッケージschemaをこの時点で含める（後付けによるEvidence一斉失効を避けるため）。
- `acd-schema`パッケージでPydanticモデルを実装し、JSON Schemaとの往復検証テストを付ける。
- Phase 1〜2で不要なdomain（製造・発注・機械詳細）は作り込まない。

### W3 core最小実装

- `acd-core`: graphのrevision管理、patch適用、影響node・再実行gate・失効Evidenceの導出。
- `acd-events`: 最小ACDドメインevent型（gate結果・承認・commit側receipt参照）と
  `EventLog`読み戻しのfail-closedテスト（未import時の`ValueError`確認）。
- 手書きの最小グラフfixtureがschema検証を通り、patchから影響導出できることを
  golden taskとして固定する（negative test: 未知field、revision不一致で停止）。

### W4 SDK統合骨組み

- `acd-runtime`: `SessionStart` hookでのimport・版プローブ・resolved SHA・MCP設定hash
  検証（失敗時deny）、共通executorの骨組み、tool envelopeの強制点。
- `plugins/acd/`の初期plugin（空に近いSkill・agents骨組み）を作り、
  `InstallationInfo.resolved_ref`／`.installed.json`の取得を確認する。
- `TestLLM`による決定論的回帰の実行経路を1本通す。
- Phase 0で骨組みだけ作る機能と後段へ送る機能の一覧をADRへ記録する。

### W5 外部ツール能力プローブ

- `kicad-cli`、freerouting、CAD kernel（build123d/OCP）の版検出・不在検出・非決定性の
  実測と正規化規則の確定。結果は環境プローブEvidenceとして第一級成果物にする。
- [`ecad-domain-notes.md`](ecad-domain-notes.md)のPhase 0能力プローブ候補
  （派生状態再計算、原点・単位・軸、ライブラリ参照解決、variant／DNP、面付け、
  内部接続ピン、ルール重大度・除外、機械可読レポート、形式版更新、設定隔離、
  描画依存、plugin／backend互換、シミュレーションpin／node対応、ロック検出）を実測する。
- 未確認項目は`unknown`のまま記録し、成功扱いしない。

### W6 投影レビュー契約と部品カタログ方針

- `ReviewFinding` schema、レビュー観点チェックリスト、処分状態、`RV1`／`RV2`定義の
  最小確定（W2のschemaへ反映）。
- 部品カタログとライブラリ出所方針の確定とADR化。

W1→W2→W3→W4は直列、W5はW1完了後に並行可能、W6はW2完了後に並行可能とする。

## 完了の観測点

Phase 0の完了条件（ゴールデンタスク）は[`roadmap.md`](roadmap.md)の定義に従う。
本計画では、全作業単位のgolden taskがCIとローカルの同一コマンドで再実行でき、
negative testが対になっていることを完了の観測点とする。

## 撤退条件

[`roadmap.md`](roadmap.md)の撤退・見直し条件に加え、Phase 0固有として次を置く。

- W5で一次採用ツールの非決定性が正規化規則で閉じない場合、
  [`tool-selection.md`](tool-selection.md)の二次候補評価へ戻る。
- W2のschemaがPhase 1〜2に不要な作り込みへ膨らみ、最短経路を遅延させる場合、
  該当domainを削って後段へ送る。
- SDKの前提（`SessionStart` hookでのdeny、`resolved_ref`取得、`TestLLM`回帰）が
  実測で成立しない場合、[`openhands-integration.md`](openhands-integration.md)の
  該当方針を見直してから続行する。
