# ADR-0025: agent-serverとConversationの実運用化

> ステータス: Accepted
> 日付: 2026-08-19

## 決定

agent-serverとLocal/Remote Conversationを実運用前提の実行経路とする。運用単位は
単一instanceとDockerWorkspaceである。serverのevent、state、metrics、agent応答、
OpenAI互換応答はL3観測であり、合格側へ作用しない。forkやresumeの後も決定論的
ゲートを再実行する。

## 受け入れ条件

実装は次フェーズで行い、各項目にfail-closedのnegative testを1件設ける。

- V1: agent-serverを起動しhealth応答を確認する。
- V2: RESTでconversation作成、message送信、run、event取得を確認する。
- V3: WebSocketでイベントを購読し受信する。
- V4: agent-server imageをbuildしdigestを記録する。
- V5: DockerWorkspaceでGD1基板・筐体pipelineを実行し、出力差を正規化規則へ記録する。
- V6: fork/resume後にゲートを再実行し、判定がゲートだけで決まることを確認する。
- V7: file、git、bash routerとOpenAI互換gatewayへのhook適用を実測する。適用されない
  経路はsession key、network、workspace分離で閉じる。
- V8: token、money、wall-clock、外部process回数をMetricsと実行記録から取得する。

CIにはgates-container（V4、V5）とagent-e2e（V1〜V3、V6）を追加する。Docker不可は
skipではなく失敗とし、unknownを合格に見せない。秘密情報なしで実行できる構成にする。

## 境界

合否は常に決定論的ゲートの再実行で決める。`hooks_router`と`hooks_service`が提供する
`POST /api/hooks`はworkspaceの`.openhands/hooks.json`を読み込むAPIであり、server直接
API全体へhookを自動適用することはソース確認だけでは断定しない。V7で実測する。
