# インストール

> ステータス: Draft

## 前提

- Python 3.12以上
- `uv`
- OpenHands Software Agent SDK
- KiCad CLIと対象工程の外部ツール

## セットアップ

```bash
uv sync
uv run python scripts/probe_tools.py
uv run python scripts/verify_docs.py
```

能力プローブで不在または版不明のツールがあれば、その工程を合格にしない。外部ツールは
パイプラインスクリプトまたはadapterから呼び、設定ディレクトリを明示する。

## OpenHands plugin

`plugins/acd/`のSkill、`AgentDefinition`、MCP設定をOpenHandsへ登録する。会話履歴、
subagent、vision、checkpoint／resume、予算、`ConfirmationPolicy`はSDK機能を使う。
ACD独自tool層や共通executorを追加しない。

## 最小実行

1. 入力ファイルを作成しgitへ記録する。
2. パイプラインで機械可読投影と視覚投影を生成する。
3. subagent／visionの自然文レビューを修正へ反映する。
4. ERC/DRCと独立parser再読込を実行する。
5. 発注する場合は、設定上限額以内であることと発注直前の全ゲート通過を確認する。

ツール不在、parse失敗、ゲート未実行、安全境界の`unknown`はfail-closedで停止する。
