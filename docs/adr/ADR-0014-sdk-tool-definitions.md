# ADR-0014: SDK ToolDefinitionによるACD入口の一本化

- **状態**: Accepted
- **日付**: 2026-08-18

## 決定

ACDの決定論的エントリポイントは、OpenHands SDKの`ToolDefinition`、`Action`、
`Observation`、`ToolExecutor`、`ToolAnnotations`で公開する。FastMCP serverは互換層
として残さず廃止する。この決定はユーザーに明示的に承認された。

MCP client経由の外部利用は当面サポートしない。将来必要になった場合は、SDK側のMCP
機構を使って再導入を検討する。

## 契約

`acd_probe_tools`、`acd_validate_design_graph`、`acd_run_board_pipeline`、
`acd_run_enclosure_pipeline`は、既存入口と同じ入力妥当性、返却キー、
`ToolEnvelope`列挙、`Evidence`の意味、fail-closed契約を保つ。入力不備や例外を成功に
変換しない。fail-closedのObservationをLLMへ伝える場合は失敗理由と「これはpass
evidenceではない」ことを含める。

`ToolAnnotations`はLLMと実行器への助言であり、強制制約ではない。実際の書き込み制約、
派生投影保護、発注・送信境界はP1のPreToolUse hookとCIが担う。pipeline toolの
`readOnlyHint=False`、`destructiveHint=False`、`idempotentHint=True`、
`openWorldHint=False`は、その既存の決定論的性質を表す。

## 依存削減

本決定によりFastMCPとそれに伴うMCP依存スタックをACDの直接依存から削除する。
なお、vendorするOpenHands SDK v1.42.1自身がSDK全体のMCP機能のために持つ依存は、
SDKのlock解決に残るが、ACDのentrypointや互換serverとしては利用しない。SDK registry
への登録はimport副作用にせず、`register_acd_tools()`を明示的に呼ぶ。
重複登録を許容するSDK registryの挙動を前提に、関数自体は冪等にする。

## 既存ADRとの関係

ADR-0003とADR-0010は過去時点の決定として保存する。本ADRが現在の公開方式を上書き
参照する。契約の正、決定論的ゲート、plugin境界、fail-closed方針は変更しない。
