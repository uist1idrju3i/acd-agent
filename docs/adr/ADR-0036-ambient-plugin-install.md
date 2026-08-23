# ADR-0036: installed plugin自動読み込みによるインストール

> ステータス: Accepted
> 日付: 2026-08-18

## コンテキスト

ADR-0035はclone不要のSDK標準配布（pip git install＋`Plugin.fetch()`）を定めたが、
利用者は依然として設定コードでpluginを明示ロードする必要がある。pinned SDK v1.43.1は
拡張の標準インストール機構として、installed plugin store
（`install_plugin()`／`~/.openhands/plugins/installed`）と、`LocalConversation`が
起動時に行うambient自動読み込み（installed・user・project pluginの自動merge）を提供する。
自前のmarketplaceリポジトリは作らない。`MarketplaceRegistry`は登録対象が存在しないため
引き続き使用しない。

本ADRの採用にあたり、次の従来契約を配布経路について放棄することを決定済みである。

- ACD pluginだけを明示ロードする境界。
- 各SKILL.mdの事前検証とロード数照合。
- plugin資材読み込み失敗のfail-closed停止（SDK標準loaderはwarningで継続する）。

放棄により、Skillの無音欠落、同名Skillの上書きを含む意図しないpluginの混入、
資材版の環境依存化、部分ロードの検出不能という具体的な後退を受け入れる。

## 決定

インストール経路として、SDKのinstalled plugin自動読み込みを採用する。

1. Pythonパッケージ`acd`をgit経由で導入する（ADR-0035と同じ）。

   ```bash
   uv pip install "git+https://github.com/uist1idrju3i/acd-agent@<tag or SHA>"
   ```

2. pluginをSDK標準の`install_plugin()`で一度installする。以後の
   `LocalConversation`はambient自動読み込みでACD pluginを取得する。

   ```python
   from openhands.sdk.plugin.installed import install_plugin

   install_plugin(
       "github:uist1idrju3i/acd-agent",
       ref="<tag or SHA>",
       repo_path="plugins/acd",
   )
   ```

これを成立させるため、次を実施する。

- `build_acd_conversation()`へambient経路（明示pluginを渡さず、Skill・hooks・agentを
  ambient自動読み込みへ委ねるmode）を追加する。従来の明示ロード経路は開発・CI用に
  維持し、既定とする。
- ambient経路では、明示pluginの`validate_pinned_ref()`検査、SKILL.md事前検証、
  ロード数照合、hook資材の事前検証を行わない。SDK標準の
  warn-and-continue意味論に従う。
- AGENTS.mdのplugin境界（明示ロード限定・自動読み込み無効）とADR-0026の
  marketplace系不採用記述を、本ADRを参照する形へ改訂する。
- `docs/openhands-sdk-capabilities.json`のsdk.plugin／sdk.skillsの根拠を
  両経路（明示＋ambient）へ更新する。`sdk.marketplace`（`MarketplaceRegistry`）は
  引き続き不採用とする。

## 影響

- L1判定は変更しない。ゲート実行の正はlock記録済みdigest固定server image
  （`DockerWorkspace(server_image=...)`）であり、authoritative Evidence契約
  （ADR-0026／ADR-0028）のrevision一致・provenance・digest検査は従来どおり
  fail-closedである。誤った合格は本ADRによって発生しない。
- ambient経路はL2資材の完全性・再現性・注入耐性を弱める。具体的には、
  壊れたSKILL.mdの無音スキップ、`~/.agents/plugins`等からの同名Skill上書き、
  実行ごとの資材版の環境依存、部分ロードの黙認が起こりうる。
  探索結果を設計入力へ確定する際のSkill名とscript sha256のprovenance記録は
  維持し、事後検出の手段とする。
- installの`ref`には不変ref（tagまたは40桁SHA）を推奨するが、ambient経路では
  強制しない。強制が必要な用途は従来の明示ロード経路を使う。
- installed-plugin経路は、将来のGUIからのMarketplace installが到達する同じSDK機構でもある。

## 検証

- ambient経路の`build_acd_conversation()`が明示pluginなしで会話を構築し、
  Skill事前検証・ロード数照合を行わないことをテストする。
- 明示ロード経路の既存fail-closed試験（壊れたSKILL.md、可変ref拒否）を維持する。
- 文書・capability表のdrift検査（`verify_docs.py`、`verify_sdk_capabilities.py`）を通す。
