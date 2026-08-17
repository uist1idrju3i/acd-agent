# ADR-0019: pinned plugin配布とTestLLM回帰

## 状況

P6/P7でACDのpluginは開発checkoutのlocal pathから読み込めるようになった。
外部利用者が別のcheckoutを同じ版として読み込まないため、配布経路には不変な
provenanceが必要である。また、SDK Conversationの配線をネットワークやAPI keyなしで
回帰検証する必要がある。

## 決定

- 外部pluginは`github:uist1idrju3i/acd-agent`の`plugins/acd`を
  40桁commit SHAまたは`v<semver>` release tagで指定する。
- branch名、`None`、短縮SHA、空文字、不正なtagは`acd_tools.plugin_distribution`で
  fail-closedに拒否する。
- 開発時のlocal pathは従来どおり既定値として許可する。`build_acd_conversation`は
  local `PluginSource`とpinned external `PluginSource`の双方を受け取る。
- `sdk.marketplace`は採用しない。今回必要なのはMarketplace登録ではなく、既存repoの
  plugin部分木を不変refで取得する薄い配布契約だからである。
- `TestLLM`でbootstrap構成、台本応答、二値criticの未達・follow-up文面・反復上限を
  ネットワークなしで検証する。既存hook subprocess testは投影保護DENYを独立に検証する。

## 境界

TestLLMでSDKの実LLM呼び出しは検証しない。外部pluginのfetch、Docker workspace、
実tool callをConversationの完全な実行ループへ接続したE2E検証もP8の範囲では行わない。
これらを未検証のまま「回帰済み」と扱わない。合否は従来どおり決定論的ゲート、
Evidence、入力ファイル、git状態だけで決まる。

## 結果

同じplugin refを再取得する配布契約と、SDK wiringの安価な回帰経路を得る。一方、
profileのモデル設定はsecret/API keyを含む解決済み設定ではなく参照モデルのため、
電気・機械・FW・reviewerのACD宣言への採用は行わない。profile採否の詳細は
`docs/dependency-notes.md`に記録する。
