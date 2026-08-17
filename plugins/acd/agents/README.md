# ACDエージェント定義

OpenHands SDKで読み込むACDサブエージェント定義を配置する。

- `acd-electrical.md`: 電気レーンの投影、ERC/DRC、失敗原因の調査
- `acd-mechanical.md`: 筐体投影、機械ゲート、CAD決定性
- `acd-firmware.md`: ESP32-C3ファームウェアの開発・検証
- `acd-reviewer.md`: 投影所見とQC・信頼性レビューの整理

AIとSkillは候補・所見を提供するだけで、合否を決定しない。合否は決定論的ゲートが
判定し、unknown、parse失敗、ツール不在、未検証状態はfail-closedとして扱う。
