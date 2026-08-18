# ACD — Autonomous Computer Design

ACDは、基板・筐体・ファームウェアをOpenHandsと決定論的な投影・ゲートで扱う
AIファーストCADです。AIとSkillは候補を提案し、ERC/DRC、独立再読込、機械測定などの
決定論的ゲートが合否を判定します。

## 構成

```text
acd.schema → acd.core → acd.pipeline → acd.adapters.*
                                    └→ acd.openhands
plugins/acd/ → Skill / AgentDefinition / command / hooks
vendor/software-agent-sdk/ → OpenHands SDK v1.42.1
```

本リポジトリはOpenHands専用拡張です。境界と不採用機能は
[`docs/adr/ADR-0026-openhands-delegation-contract.md`](docs/adr/ADR-0026-openhands-delegation-contract.md)、
SDKの採否は[`docs/openhands-sdk-capabilities.json`](docs/openhands-sdk-capabilities.json)を正とし、
説明表は[`docs/openhands-sdk-capabilities.md`](docs/openhands-sdk-capabilities.md)で確認できます。
文書統治は[`docs/adr/ADR-0034-document-governance.md`](docs/adr/ADR-0034-document-governance.md)に従い、
agent-serverは対象外です。

## インストール

OpenHandsのLocal GUI（Agent Canvas）の「カスタマイズ → Plugins →
プラグインを追加」から、ソース`github:uist1idrju3i/acd-agent`、パス`plugins/acd`で
インストールできます。
パスは必須で、省略するとACDのSkill／AgentDefinition／command／hooksは読み込まれません。

通常の最新化（default branchの先頭への更新）は、同じPlugins画面の「更新」ボタンだけで
行えます。アンインストールは不要で、有効・無効の状態も維持されます。特定のtagまたは
40桁commit SHAへ固定・切替・ダウングレードする場合は、更新ボタンでrefを指定できないため、
いったんアンインストールして新しいrefで再インストールします。

その他の運用手順は[`docs/operations.md`](docs/operations.md)を参照してください。

## 文書索引

文書の一覧とAccepted ADRの索引は[`docs/README.md`](docs/README.md)を参照してください。
