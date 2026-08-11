# 外部ツール能力プローブ（Phase 0）

> ステータス: Draft
> 測定日: 2026-08-11

プローブ実装は`packages/acd-tools`、実行は`uv run python scripts/probe_tools.py`。
不在・版不明は`unknown`として構造化記録し、成功扱いしない（fail-closed）。
能力プローブ候補の背景は[`docs/ecad-domain-notes.md`](ecad-domain-notes.md)を参照。

## 本環境での測定結果

| ツール | 検出 | 版 | 備考 |
| --- | --- | --- | --- |
| kicad-cli | 不在 | `unknown` | PATH上に実行ファイルなし |
| freerouting | 不在 | `unknown` | PATH上に実行ファイルなし |
| CAD kernel（build123d/OCP） | 不在 | `unknown` | Python distribution未インストール |

上記が`unknown`である間、これらのツールを要求するゲートは合格しない。
版が確認できた環境で再測定し、本表を更新する。

## 正規化規則（版が確認でき次第、実測で確定する）

- 版はsemver部分（`X.Y.Z`）のみを比較に使い、ビルドメタデータは`detail`に保持する。
- 実行は隔離した設定ディレクトリで行い、ユーザー設定の影響を排除する。
- 同一入力・同一版での出力hash差（タイムスタンプ埋め込み等）は非決定性として
  記録し、正規化（該当フィールドの除去）後のhashをEvidenceに使う。

## Phase 1前に実測すべき能力プローブ候補

以下は[`docs/ecad-domain-notes.md`](ecad-domain-notes.md)の候補一覧の転記であり、
kicad-cli等が利用可能な環境で実測し、結果をEvidence（版、形式版、設定hash、
入力hash、出力hash、実行環境、測定条件）として記録する。

- 派生状態（ratsnest等）の再計算の有無と契機
- 原点・単位・軸の既定と設定依存性
- ライブラリ参照解決の規則と失敗モード
- variant／DNPの表現と投影への影響
- 面付けの表現
- 内部接続ピンの扱い
- ルール重大度・除外（waiver相当）の機械可読性
- レポートの機械可読形式（JSON等)の有無
- ファイル形式版の更新タイミング
- 設定ディレクトリの隔離可否
- 描画依存機能（画像出力等）のheadless動作
- plugin／backend互換性
- simulationのpin/node対応
- ファイルロック検出とハンドル解放の確認方法
