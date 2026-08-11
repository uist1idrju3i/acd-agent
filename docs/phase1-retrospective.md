# Phase 1 振り返り

> ステータス: Draft  
> 対象: Phase 1実装（PR #20、電気レーン最小縦切り）  
> 日付: 2026-08-11

[`phase1-plan.md`](phase1-plan.md)に対する実施結果、逸脱、残課題、教訓を記録する。
Phase 2の前提条件はここを起点に確認する。

## 達成事項

| 項目 | 結果 |
| --- | --- |
| fixture | Golden Design #1を180ノードの設計グラフとして固定（部品MPN／LCSC、ピン割当、基板制約、出所・hash付きライブラリpin）。再生成はbyte一致 |
| 投影 | netlist／BOM（CSV）、KiCad回路図・基板・プロジェクト（決定論的UUID、生成順固定） |
| 配置 | 決定論的グリッド走査＋接続性アトラクション（配置済み接続部品をアンカーにManhattanコスト最小化）。配置不能はfail-closed |
| 配線 | Specctra DSN出力→freerouting 2.3.0→SES取り込み（µm→mm、Y軸反転）→route注入。未収束・router不在はfail-closed |
| ゲート | kicad-cli ERC（0 error）、DRC（0 error・0 unconnected、graph由来制約を`.kicad_pro`経由で適用） |
| 製造出力 | Gerber 8層＋Excellon drill |
| 二重再読込 | sexpdata（回路図・基板）とgerbonara（Gerber／drill）による独立parser再読込 |
| 再現性 | 正規化hash manifest（G04／`;`コメント行のみ除去）。再実行でhash一致、外部process副作用の重複なし（envelope一致時skip） |
| 単一コマンド | `uv run python scripts/run_gd1_pipeline.py --out out/gd1` |
| negative test | router不在、未収束、ERC／DRC違反、unconnected、未知単位、SES不正、配置不能、出力欠落、入力変更によるenvelope無効化 |

## 計画からの逸脱

- CAD kernelプローブは引き続き`unknown`（Phase 1では不要のため未導入）。
- Freerouting呼び出しはCLIバッチ（`-de`/`-do`/`-mp`）であり、収束状態はログの
  `(N unrouted ...)`行から導出した。API連携は行っていない。
- ルート済み基板のDRCは、生成した`.kicad_pro`を隣接コピーして実行する方式とした。
  kicad-cliが基板単体では設計制約を読まないためであり、graph由来制約の適用を
  優先した判断である。
- Excellon出力にgerbonaraが`G90 header statement found after end of header`の
  SyntaxWarningを出す（kicad-cli 10.0.5の出力形式に起因）。解析は成功しており
  ゲートには影響しないが、既知事項として記録する。

## Phase 2への持ち越し

1. FWパッケージ投影（fw-package契約はPhase 0で確定済み）と、設計グラフの
   ピン割当を唯一の出所とするFW生成。
2. ピン割当整合ゲート（FW側定義と設計グラフの照合。故意にずらすと不合格になる
   negative test）。
3. ESP-IDF環境プローブと版のpin（ビルドEvidence）。
4. 仮想実機（Renode一次候補）のESP32-C3対応可否の実測と、仮想検証Evidenceの
   条件・版付き分類。
5. 実機書き込み（probe-rs一次候補）とシリアルログの実測Evidence化（実機到達は
   追加の到達条件）。

## 教訓

- 決定論的配置は「制約で絞る」より「候補を全列挙し決定論的コストで選ぶ」方が
  fail-closedと両立しやすい。マージン増加による配置不能が複数回発生し、候補
  スコアリング方式へ変更して解消した。
- 外部ツールの設定コンテキスト（KiCadのproject設定）は出力ファイルの隣接配置で
  しか適用されない場合があり、投影は「ファイル一式」を単位に扱う必要がある。
- ライブラリの旧形式（`fp_text reference`）と新形式（`property "Reference"`）の
  併存のように、独立parserによる再読込は生成側の想定漏れを実際に検出した。
  二重再読込はコストに見合う。
- freeroutingのログ形式は版依存であり、収束判定regexは版prove時に再確認する。
