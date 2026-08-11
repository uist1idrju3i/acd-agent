# Phase 0 振り返り

> ステータス: Draft  
> 対象: Phase 0実装（PR #19、W1〜W6）  
> 日付: 2026-08-11

[`phase0-plan.md`](phase0-plan.md)のW1〜W6に対する実施結果、逸脱、残課題、教訓を
記録する。Phase 1の前提条件はここを起点に確認する。

## 達成事項

| 作業単位 | 結果 |
| --- | --- |
| W1 | uv workspace（`packages/*`5パッケージ）、ruff／pyright strict／pytest、CI、`scripts/verify_docs.py`、ADR-0001／0002 |
| W2 | `schemas/`8契約とacd-schema Pydanticモデル、golden／negative fixtureによる往復検証（55テスト中26） |
| W3 | acd-core（revision／patch／影響・stale導出）、acd-events（SDK `Event`統合、未知kindは`ValueError`） |
| W4 | acd-runtime（SessionStart検証・deny、tool envelope executor、`TestLLM`回帰）、`plugins/acd/`骨組み、ADR-0003 |
| W5 | acd-toolsプローブ（版・不在検出）、`scripts/probe_tools.py`、`docs/tool-capability-probes.md` |
| W6 | `ReviewFinding`契約、`docs/review-checklist.md`（RV1/RV2）、ADR-0004 |

## 計画からの逸脱

- W5の能力プローブのうち、実ツールを要する項目（派生状態再計算、原点・単位・軸、
  ライブラリ参照解決、variant／DNP等）は、実装環境に`kicad-cli`／freerouting／
  CAD kernelが不在だったため**未実測**。`unknown`として
  [`tool-capability-probes.md`](tool-capability-probes.md)に記録した。
  fail-closed原則どおり成功扱いはしていないが、Phase 0完了条件の
  「非決定性の実測と正規化規則の確定」は**実測残**である。
- SessionStart hook CLIは現在`tool_versions={}`・`actual_mcp_config_hash=None`で
  呼んでおり、`acd_tools.probe_all()`と実MCP設定hash計算の接続が未了。

## Phase 1への持ち越し

1. `kicad-cli`／freerouting／JREを導入した環境での能力プローブ実測と
   `tool-capability-probes.md`の更新（Phase 1の最初に実施）。
2. SessionStart hookへの`probe_all()`とMCP hash計算の接続。
3. ADR-0004のカタログ契約（catalog schema）の具体化（Phase 1のライブラリpinで必要）。
4. Golden Design #1（[`golden-design-1.md`](golden-design-1.md)）のfixture化。

## 教訓

- pyright strictでは`Field(default_factory=list)`が`list[Unknown]`になるため、
  `default_factory=list[T]`と各パッケージの`py.typed`を最初から入れる。
- SDKのevent discriminatorは入力dictを破壊的に消費するため、
  読み戻し時は必ずコピー（`dict(data)`）を渡す。
- 用語集など意図的なID再掲がある文書は、検証器側でセクションを区別しないと
  誤検出する。検証器自体にもnegative意図の確認が要る。
- Markdownの行末2スペース（hard break）は`git diff --check`と衝突する。
  本リポジトリでは行末空白を使わない。
