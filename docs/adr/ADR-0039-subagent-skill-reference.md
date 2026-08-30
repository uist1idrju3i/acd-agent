# ADR-0039: sub-agentのSkill参照方式

> ステータス: Accepted
> 日付: 2026-08-19

## コンテキスト

ADR-0036のambient install経路（Local GUIのplugin install）では、plugin資材が
`~/.openhands/plugins/installed/acd/`へコピーされ、`LocalConversation`起動時に
Skill・hooks・AgentDefinitionが自動読み込みされる。

pinned SDK v1.44.1の`openhands.sdk.subagent.registry.agent_definition_to_factory()`は、
AgentDefinitionの`skills:`をfactory生成時に`load_available_skills(include_user=True,
include_project=True)`だけで解決する。この探索範囲は`~/.agents/skills`、
`~/.openhands/skills`（installed standalone skillを含む）、`~/.openhands/microagents`と
workspaceのproject skillであり、plugin同梱Skillのディレクトリ
（`plugins/installed/<plugin>/skills/`）は含まれない。名前が解決できない場合は

```text
ValueError: Skill '<name>' not found but was given to agent '<agent>'.
```

で`register_plugin_agents()`が例外を上げ、会話生成そのものが失敗する。plugin skillは
親conversationのAgentContextへはmergeされるが、sub-agent解決には使われない。

実機のLocal GUI（source `github:uist1idrju3i/acd-agent`、path `plugins/acd`）で、この
挙動により`/acd:doctor`と`/acd:gates`が実行前に失敗することを確認した。plugin資材と
install doctorの直接実行はいずれも健全で、原因はACDのAgentDefinitionが同梱Skill名を
`skills:`へ宣言していた点にある。同じ失敗は、installed plugin storeが存在するホストでの
`pytest`でも再現していた。

`skills:`は名前解決だけを受け付けるため、pluginの外にSkillを二重配置しない限り
ambient経路で解決させる方法はない。二重配置はADR-0027の単一配布形態と、
利用者環境の手動変更禁止に反する。

## 決定

ACDのAgentDefinitionはSDKの`skills:`を宣言しない。plugin同梱Skillは、各agent
promptの`## Skill references`節でSKILL.mdのパスを明示して参照する。plugin rootは
ADR-0040のhook commandと同じ候補順（`$ACD_PLUGIN_ROOT`、
`$OPENHANDS_PROJECT_DIR/plugins/acd`、`$HOME/.openhands/plugins/installed/acd`）で
解決し、明示経路とambient経路の双方で参照できる形にする。読み取り不能なSkill資材は
fail-closedとして扱う。

回帰防止として次を追加する。

- `acd.openhands.safety.validate_acd_agent_skills()`が`plugins/acd/agents/acd-*.md`を
  SDKの`AgentDefinition.load()`で読み、`skills:`宣言があれば`ValueError`で拒否する。
  既定の明示経路の`build_acd_conversation()`はhook検査と同じ位置でこれを実行する。
- install doctorへrequired check「agent skill declarations」を追加し、GUI install後の
  ツリーでも宣言の再発を検出する。requiredのため`unknown`もfail-closedとする。

親conversationのAgentContextには従来どおりplugin Skillがmergeされるため、
`/acd:doctor`などのcommandとmodel invocationは影響を受けない。

## 影響

- ambient install経路でACD AgentDefinitionを含む会話が起動できるようになり、
  `/acd:doctor`と`/acd:gates`がGUIから到達可能になる。
- sub-agentはSkillのprogressive disclosureを受け取らず、必要なSKILL.mdを明示的に
  読む。Skill出力は従来どおり合否権限を持たない観測であり、L1判定は変更しない。
- 利用者環境へSkillを二重配置する回避策（`~/.openhands/skills/installed`への複製）は
  採らない。単一配布形態と手動変更禁止を維持する。
- SDK側で`register_plugin_agents()`がplugin同梱Skillを解決できるようになった場合は、
  新規ADRで`skills:`宣言の再採用を判断する。

## 検証

- `plugins/acd/agents/*.md`が`skills:`を宣言せず、参照するSKILL.mdが実在することを
  テストする。
- `skills:`を宣言する壊した定義を`validate_acd_agent_skills()`とinstall doctorが
  それぞれfail-closedで拒否することをnegative testで確認する。
- prompt manifestを再生成し、`scripts/verify_agent_prompts.py --check`のdriftを解消する。
- `uv run python scripts/verify_all.py --stage standard`を通す。
