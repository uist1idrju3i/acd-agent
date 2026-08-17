# 実装ロードマップ

> ステータス: 現行実装と近い順の計画

## 現在地

H1/H1b/H2を実装済み。OpenHands plugin、7 Skill、4 AgentDefinition、`/acd:gates`、
ACD MCP server、GD1基板・筐体pipelineを提供する。GD1基板はERC、routing収束、
SES import、DRC、fabrication出力、独立再読込まで通過するが、既知のsilkscreen可読性
ゲートでfail-closedになる。これは未解決課題であり、ゲートを緩めない。筐体pipelineは
決定論的ゲートを通過する。実機測定、発注、価格・在庫取得は未実装である。

## 現行実装計画

| 順 | マイルストーン | 達成条件 | 現状 |
|---|---|---|---|
| 1 | 契約と再現可能な投影 | graphをPydanticで検証し、同一入力から投影・provenance・hashを再生成できる | 達成 |
| 2 | 電気レーンの独立検証 | ERC、routing収束、SES import、DRC、Gerber/drill生成、独立再読込を通す | silkscreenを除き達成 |
| 3 | 機械レーンの決定論的検証 | STEP/3MF生成、CAD再読込、干渉・clearance・肉厚を通す | 達成 |
| 4 | plugin委譲とMCP境界 | Skill/agent/commandをSDKでloadし、MCPが既存gateをfail-closedで公開する | 達成 |
| 5 | 実機フィードバック | 製造・組立・測定結果をEvidenceとして取り込み、次の入力へ反映する | 未着手 |

各マイルストーンの完了条件は、(1)入力と出所、(2)実装、(3)正常系、(4)negative/
fail-closed、(5)再現性の5要素で確認する。SkillやAIの所見だけでは完了としない。

## 将来構想

旧Phase 8〜13に相当する機能は、現行実装へ混ぜず次の構想として保持する。

- 投影・実測・再配置の反復によるsilkscreen解決と電気・機械協調修復
- 複数fab profile、製造データ契約、価格・在庫・納期の期限付きsourcing
- OpenHands SDKのcheckpoint/resume、長時間運用、予算監視
- 実機Evidenceを使う知識ループとローカル製造
- 全ゲート通過後だけの自働発注
- 高密度基板、認証設計、熱・SIなどの拡張

## 検証要件

変更ごとに、契約・投影・独立再読込・決定論的ゲートを実行する。ツール不在、
parse失敗、未実行、unknownはfail-closedとする。Markdownのみの変更は
`verify_docs.py`と`git diff --check`で検証し、それ以外は`AGENTS.md`の全検証を行う。

## 見直し条件

外部ツールの非決定性が正規化できない、一次情報とライセンス境界が合わない、
negative testなしでしか完了条件を満たせない場合は、その機能を止めてADRと本書を
更新する。閾値・期待値を変更して成功に見せない。
