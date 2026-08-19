# ACDエージェント定義

OpenHands SDKで読み込むACDサブエージェント定義を配置する。

- `acd-electrical.md`: 電気レーンの投影、ERC/DRC、失敗原因の調査
- `acd-mechanical.md`: 筐体投影、機械ゲート、CAD決定性
- `acd-firmware.md`: ESP32-C3ファームウェアの開発・検証
- `acd-reviewer.md`: 投影所見とQC・信頼性レビューの整理
- `acd-search.md`: 決定論的探索CLIの実行と候補provenanceの返却

AIとSkillは候補・所見を提供するだけで、合否を決定しない。合否は決定論的ゲートが
判定し、unknown、parse失敗、ツール不在、未検証状態はfail-closedとして扱う。
sub-agentは親conversationのhookを継承しないため、各AgentDefinitionに
`protect-derived-projections`、`require-order-evidence`、
`require-gate-after-input-change`を明記する。SDKロード後のHookConfigを試験で照合し、
hook drift時はtask/delegate経路を受け入れない。workflowの採否は別途判断する。
AgentDefinitionは`skills:`を宣言せず、plugin同梱SkillのSKILL.mdをpromptの
`## Skill references`節でパス参照する（ADR-0039）。SDKのsub-agent解決は
plugin同梱Skillを探索しないため、宣言すると会話生成が失敗する。
