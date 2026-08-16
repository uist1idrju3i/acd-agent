# OpenHands SDK統合

> ステータス: Draft

ACDはOpenHands SDKを実行基盤として優先利用する。会話履歴、workspace、Skill、
`AgentDefinition`、subagent、vision、checkpoint／resume、予算機能、`ConfirmationPolicy`、
MCPをACD独自実装で置き換えない。

## SDKへ寄せる責務

- 会話履歴を設計判断の文脈として保持する。
- 生成agentとレビューagentを`AgentDefinition`で分離する。
- 機械可読投影と視覚投影をsubagent／visionへ渡す。
- 観点別レビューの並列化に`WorkflowTool`のmap/reduceを使う。
- 長時間処理はcheckpoint／resume、停止判定は`StuckDetector`、予算はSDKの機能を使う。
- 不可逆な発注確認は`ConfirmationPolicy`へ委ねる。

## ACDに残す責務

ACDはadapters、パイプラインスクリプト、決定論的ゲート、投影生成、発注ガードを保持する。
外部router、ERC/DRC、干渉検査、FW検査、独立parser再読込の結果だけが合否を決める。
LLMの応答、subagentの成功状態、visionの所見は合格根拠にしない。

## レビュー経路

機械可読投影はテキストまたは構造化データとしてagentへ渡す。視覚投影は
`ImageContent`または`inspect_image_with_vision`で渡す。所見は自然文で修正ループへ返し、
入力ファイルを修正した後に投影と全ゲートを再生成する。

## 探索と実測

LLMは探索方針を提案できるが、座標・回転角を直接出力しない。候補生成・整合化・代理指標は
決定論的スクリプトで行い、実測は少数候補に限定する。代理指標やSDKのgoal判定は合格根拠にしない。

## 関連文書

- [`architecture.md`](architecture.md)：実装レイヤ
- [`projection-review.md`](projection-review.md)：投影レビュー
- [`roadmap.md`](roadmap.md)：フェーズ境界
