# 実装ロードマップ

> ステータス: 現行実装と近い順の計画

## 現在地

OpenHands plugin、7 Skill、4 AgentDefinition、`/acd:gates`、SDK ToolDefinition、
GD1基板・筐体pipelineを提供する。GD1基板はERC、routing収束、SES import、DRC、
fabrication出力、独立再読込、silkscreen可読性ゲートまで通過する。
SDK hooksによるfail-closed境界も提供する。筐体pipelineは決定論的ゲートを通過する。
実機測定、発注、価格・在庫取得は未実装である。
P5として、ホスト実行を既定にした任意のDockerDevWorkspaceゲート実行経路を追加し、
image digest未解決時は停止する。
P3aとして、`AcdGateCritic`による決定論的ゲート結果駆動の反復を追加する。
SDKへ委譲するのは反復制御だけであり、criticはpass evidenceではない。
P4として、GD1の独立したwidth positive-control armをACD側で並列化し、
探索候補を返す`acd-search` AgentDefinitionを追加する。SDK workflowは採用しない。

## 現行実装計画

| 順 | マイルストーン | 達成条件 | 現状 |
|---|---|---|---|
| 1 | 契約と再現可能な投影 | graphをPydanticで検証し、同一入力から投影・provenance・hashを再生成できる | 達成 |
| 2 | 電気レーンの独立検証 | ERC、routing収束、SES import、DRC、Gerber/drill生成、独立再読込、silkscreenゲートを通す | 達成 |
| 3 | 機械レーンの決定論的検証 | STEP/3MF生成、CAD再読込、干渉・clearance・肉厚を通す | 達成 |
| 4 | plugin委譲とSDK tool境界 | Skill/agent/command/toolをSDKでloadし、既存gateをfail-closedで公開する | 達成 |
| 4.1 | SDK hooks境界 | 投影保護、Evidence発注ガード、Stop、probe、文書検証を既存判定の呼出しとして実装する | 達成 |
| 4.2 | 決定論的gate critic | Design Graph revision、Evidence、製造manifestだけで二値criticを評価し、SDK反復を操舵する | 実装済み |
| 4.3 | 決定論的探索lane | 独立width armを固定順で並列集約し、探索AgentDefinitionは候補とprovenanceだけを返す | 実装済み |
| 5 | 実機フィードバック | 製造・組立・測定結果をEvidenceとして取り込み、次の入力へ反映する | 未着手 |

各マイルストーンの完了条件は、(1)入力と出所、(2)実装、(3)正常系、(4)negative/
fail-closed、(5)再現性の5要素で確認する。SkillやAIの所見だけでは完了としない。

## 将来構想

現行実装の次に残る機能は、次の構想として保持する。

- routing後のvia mask開口を含む投影・実測・再配置の反復
- 複数fab profile、製造データ契約、価格・在庫・納期の期限付きsourcing
- OpenHands SDKのcheckpoint/resume、長時間運用、予算監視
- 実機Evidenceを使う知識ループとローカル製造
- 全ゲート通過後だけの自働発注
- 高密度基板、認証設計、熱・SIなどの拡張
- agent自体のコンテナ化と配布済みACD image

## 検証要件

変更ごとに、契約・投影・独立再読込・決定論的ゲートを実行する。ツール不在、
parse失敗、未実行、unknownはfail-closedとする。Markdownのみの変更は
`verify_docs.py`と`git diff --check`で検証し、それ以外は`AGENTS.md`の全検証を行う。

## フェーズ横断の検証要件

以下は全マイルストーンの完了条件に共通して要求する。固有の達成条件が満たされても、
ここに反する実装は合格にしない。これらは実際の欠陥類型に基づく設計判断であり、
外部リポジトリの記述を権威として引くものではない。

| # | 要件 | 禁止する構造 |
|---|---|---|
| 1 | 判定の両辺は別の出自から取る | 自分が生成した成果物の存在を自分の合格根拠にする（自己証明）。replay結果同士、生成器同士の比較 |
| 2 | 導出できない入力は`unknown`として停止側へ集約する | `continue`・早期return・既定値補完でskipを合格に見せる。宣言の欠如を0や空と同一視する |
| 3 | 実行中のstageを入場時に宣言し、失敗はその宣言から帰属させる | 直前の成功結果や末尾要素を失敗の帰属先にする |
| 4 | CIが読み込む入力・fixture・scriptはtrackedにし、typecheck／lintの対象に含める | 検査対象外の領域を「検査済み」と扱う。gitignore下のデータに依存する回帰 |
| 5 | 外部ツールの保存バイト列を設計状態の権威にしない。非決定な出力は正規化規則を契約に書き、規則外の差異は停止条件とする | 外部ツールの決定論性を説明で仮定する（timestamp、再保存時のセグメント構成差など） |
| 6 | 契約はPydanticモデルから導く | runnerと文書でgate番号・状態を二重管理する |
| 7 | 安全条件・保護対象は書き換わる部分木で判断する | pathの完全一致だけで許可・却下を決める |
| 8 | 予算（token、money、wall-clock、外部process回数）を各ゴールデンタスクで実測して記録する。SDK `Metrics`／`MetricsSnapshot`と外部ツールの実行記録を使う | 予算次元を不明のまま次の作業へ渡す |
| 9 | 探索を含む工程では、代理指標スコアを合格根拠にせず、停止理由と実行結果を記録する | 代理指標だけで合格させる。停止理由を記録しない |

## 見直し条件

外部ツールの非決定性が正規化できない、一次情報とライセンス境界が合わない、
negative testなしでしか完了条件を満たせない場合は、その機能を止めてADRと本書を
更新する。閾値・期待値を変更して成功に見せない。
