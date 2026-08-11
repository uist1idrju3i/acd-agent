# OpenHands SDK統合

> ステータス: Draft  
> 対象バージョン: OpenHands Software Agent SDK v1.41.0  
> submodule commit: `ca46719d5e9a0b0af79f7de2da37067a5b94563c`（2026-08-06）  
> ライセンス: MIT、Python 3.12+

本書は、`vendor/software-agent-sdk`のソースと公式ドキュメントを一次情報として
調査した結果の要約である。代表的な根拠は、`openhands-sdk/openhands/sdk/agent/`、
`openhands-sdk/openhands/sdk/conversation/`、`openhands-sdk/openhands/sdk/event/`、
`openhands-sdk/openhands/sdk/tool/`、`openhands-sdk/openhands/sdk/security/`、
`openhands-workspace/openhands/workspace/`のリポジトリ相対パスにある。

## パッケージ構成

| package | 責務 | ACDでの使い方 |
|---|---|---|
| `openhands-sdk` | Agent、Conversation、Event、Tool、LLM、MCP、security、settings | 計画・型付きtool・会話・実行制御 |
| `openhands-tools` | terminal、browser、file/editor、delegate | 必要な汎用toolとサブエージェント |
| `openhands-workspace` | Local、Docker、Apptainer、cloud、remote workspace | CAD/EDA workerの隔離実行 |
| `openhands-agent-server` | FastAPI REST/WebSocket、会話、workspace、MCP | CLI以外のAPI入口、長時間会話の管理 |

## 実行モード

- `LocalWorkspace`: 開発と軽量なローカル検証。ホスト分離は自動保証されないため、
  外部CAD/EDAや製造CLIは専用環境と権限で実行する。
- `DockerWorkspace`: workerと依存ツールをimageへ固定し、CI・再現性を優先する。
- `APIRemoteWorkspace`＋agent-server: 長時間実行、遠隔worker、API入口に使う。

ユーザーとの対話インタフェースはOpenHands（CLIやagent-serverを含むクライアント）が
担う。ACDが提供するのは、OpenHandsへ登録するツール群、設計グラフ、決定論的ゲート、
Evidenceである。

## SDK機能とACD自前実装

| ACD要件 | SDKで使うもの | ACDが自前実装するもの |
|---|---|---|
| 型付きtool | `ToolDefinition`、Pydantic Action/Observation、annotations | 設計グラフschema、artifact contract、CAD/EDA意味論 |
| 決定論的gate | tool hooks、typed result、`readOnly`/`destructive`/`idempotent` annotations | gate policyの版、input/design hash、stale判定、fail-closed |
| 承認 | `ConfirmationPolicy`、`SecurityRisk`、confirmation state | approval IDの一回性、失効、ActionEventとの束縛、不可逆executor |
| 実行履歴 | EventLog、snapshot、resume、fork | 外部副作用journal、署名、idempotency、外部状態snapshot |
| 長時間実行 | condenser、memory、interrupt、max iteration、budget | ACD task ledger、checkpoint方針、予算の製造・機械統合 |
| 分業 | delegate/spawn、子Conversation、権限継承 | 電気・機械レーンのgraph merge、成果物契約、失敗因果 |
| LLM運用 | token/cost metrics、cache、retry | ACD retry budget、同一input hash、外部副作用の再実行防止 |
| 外部tool | MCP client、動的Pydantic schema、timeout、再接続 | adapterの意味検証、tool version固定、Evidence生成 |

ACDのtoolは`ToolDefinition`として登録し、Pydantic Action/Observationで入力と結果を
型付けする。annotationsはread-only、destructive、idempotentの宣言に使うが、
宣言だけで安全性は成立しない。共通executorが実際の副作用を分類・検査する。

## MCP接続

SDKのMCP統合は、外部CAD/EDA、sourcing、simulationを動的schemaで接続する候補である。
MCP toolの入力をPydantic Actionへ変換し、timeout、再接続、secret展開、出力maskingを
利用する。MCP serverが返す成功文字列を合格Evidenceとはせず、生成artifactを再読込し、
決定論的gateを別途実行する。

## ファームウェア開発とOpenHands

OpenHands SDKのソフトウェア開発能力（bash、ファイル編集、テスト実行、MCP client、
delegate）は、FWレーンの実装にそのまま利用できる。ACD側が用意するのは、設計グラフ
から投影する型付きFWパッケージ、ピン・ネット整合ゲート、ビルド・テスト・ログの
Evidence記録である。FW側の決定がピン割当やペリフェラル設定を変える場合は、S2へ
戻す双方向契約として扱う。

実機への書き込み、RTT等のログ取得、Blinkの実行を外部ツールまたはMCPサーバとして
OpenHandsから呼び出す構成は候補である。候補例として`FreeOCD/freeocd-vscode-extension`
（CMSIS-DAP、RTT、MCPサーバ）と`OpenBlink/openblink-vscode-extension`（mruby/c、
BLEによるBuild & Blink、MCPサーバ）がある。ただし、接続方法、提供ツール、ライセンスは
本リポジトリで一次情報による接続検証をしておらず、候補・要検証である。

## SDKが保証しないこと

- 外部副作用を含む決定論的replay。
- LocalWorkspaceでのホスト権限・ファイル・ネットワークの完全分離。
- 承認IDと不可逆操作の暗号学的または因果的な束縛。
- KiCad、FreeCAD、SPICE、slicerの設計意味論や製造妥当性。
- 外部サービスの価格、在庫、発注状態の永続的な正確性。
- FWの機能的正しさ、書き込み・実機ログの再現性、ターゲット固有の意味論。

したがって、OpenHandsは実行基盤であって、ACDのcanonical graph、gate、Evidence、
approval、side-effect journalを代替しない。

## 公開先行事例

`docs/prior-art.md`の調査では、OpenHands SDKを使った公開のハードウェア/CAD設計先行
事例は確認できなかった。OpenHandsからKiCad、FreeCAD、agentcad、slicerを呼ぶことは
ACDの統合案であり、既存事例の実績ではない。
