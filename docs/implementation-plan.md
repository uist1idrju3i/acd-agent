# 実装計画

> ステータス: Draft

本書は、入力ファイルを正とするACDの実装境界を定める。契約は
`packages/acd-schema`のPydanticモデル、工程は`docs/roadmap.md`、SDK境界は
[`openhands-integration.md`](openhands-integration.md)を参照する。

## リポジトリ構成

```text
acd-agent/
├── packages/
│   ├── acd-schema/       # Pydantic契約
│   └── adapters/         # KiCad、Gerber、router、CAD、slicer、fab
├── plugins/acd/          # Skill、AgentDefinition、MCP設定
├── fixtures/             # golden task入力
├── scripts/              # パイプライン、文書検証、能力プローブ
├── profiles/             # 安全境界の版管理設定
└── docs/adr/             # 設計決定
```

ACD独自の実行抽象は設けない。OpenHands SDKの
Conversation、workspace、subagent、vision、checkpoint／resume、予算機能、
`ConfirmationPolicy`、MCP、pluginを優先して使う。

## パイプラインとadapter

生成側は部品・回路・配置・筐体・FWの生成、候補の整合化、代理指標による順位付けを担当する。
判定側は外部router、ERC/DRC、干渉、FW検査、独立parser再読込を担当し、生成側の成功状態を
合格根拠にしない。各adapterは外部ツールの入出力を扱い、パイプラインスクリプトが工程順序を
組み立てる。

## SkillとAgentDefinition

| 資材 | 役割 |
|---|---|
| Skill | 工程のチェックリストとパイプライン実行手順 |
| `acd-electrical` | 電気設計と配置・回転・配線の提案 |
| `acd-mechanical` | 筐体設計の提案 |
| `acd-firmware` | FWの実装とスクリプト内検査 |
| `acd-reviewer` | 機械可読投影の自然文レビュー |
| `acd-visual-reviewer` | 視覚投影のvisionレビュー |

生成agentとレビューagentは分離する。レビューagentは入力ファイルを書き換えず、自然文の
所見を修正ループへ返す。

## ゲートと発注

最低限の合格条件はERC/DRC通過と独立parser再読込である。FWはビルド、静的解析、単体テスト、
ピン割当整合、ログ期待値照合を生成スクリプト内で検査する。発注スクリプトは上限額以内と
発注直前の全ゲート通過を確認し、価格・在庫の鮮度も直前に確認する。

## 設計決定

ADR一覧は[`../docs/README.md`](README.md)を参照する。ADR-0002はADR-0008により廃止され、
ADR-0007の探索方針は現在の小規模試作向けに縮小されている。ADR-0008の本文を本書へ複製しない。
