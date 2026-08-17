# OpenHands agent-server運用runbook

> ステータス: 実運用手順（受け入れ条件追跡中）
> 対象: OpenHands Software Agent SDK v1.42.1

## 目的と前提

このrunbookは、OpenHands Software Agent SDK v1.42.1に含まれる
`openhands-agent-server`をACDからどう扱うかを定める。対象コードは
`vendor/software-agent-sdk/openhands-agent-server/`であり、ACD独自のserver起動
scriptやCLIを追加しない。

agent-serverは会話、agent実行、event、workspaceへのアクセスを運ぶ層である。
ACDの合否は従来どおり、設計入力、git commit、Evidence、決定論的ゲートだけで決める。
serverのevent、conversation state、metrics、agent出力、OpenAI互換応答は経過情報であり、
pass evidenceには使わない。

## 一次情報で確認した実像

以下はv1.42.1の次の一次情報で確認できた範囲である。

- `openhands-agent-server/pyproject.toml`
  - package versionは`1.42.1`
  - `agent-server = "openhands.agent_server.__main__:main"`を提供する
  - FastAPI、Uvicorn、WebSocket、OpenAI client互換の依存を宣言する
- `openhands-agent-server/openhands/agent_server/api.py`
  - FastAPI applicationに`/api`配下のconversation、event、workspace、git、
    file、bash等のrouterを登録する
  - `/v1`のOpenAI互換routerと`/sockets`のWebSocket routerも登録する
- `openhands-agent-server/openhands/agent_server/conversation_router.py`
  - `POST /api/conversations`でconversationを作成する
  - `POST /api/conversations/{id}/run`、`/pause`、`/interrupt`、`/fork`、
    `/navigate`、`DELETE /api/conversations/{id}`を提供する
  - `POST /api/conversations/{id}/events`でmessageを送信する
- `openhands-agent-server/openhands/agent_server/event_router.py`
  - conversation eventの一覧、検索、件数取得、単体取得、message送信を提供する
- `openhands-agent-server/openhands/agent_server/sockets.py`
  - WebSocketでconversation eventを購読し、messageやbash関連の通信を行う
  - 認証設定がある場合、first-message auth、`X-Session-API-Key` header、
    互換用query parameterを扱う。first-message authが推奨されている
- `openhands-agent-server/openhands/agent_server/openai/router.py`と`openai/service.py`
  - `GET /v1/models`と`POST /v1/chat/completions`を提供する
  - `X-Session-API-Key`または`Authorization: Bearer`を既存session keyとして検証する
  - `stream=true`のchat completionは未対応である
- `openhands-agent-server/openhands/agent_server/config.py`
  - conversationとeventの保存先既定値は`workspace/conversations`
  - default workspaceは`workspace/project`
  - bash event保存先は`workspace/bash_events`
  - `SESSION_API_KEY`等でsession keyを設定でき、未設定時はserver APIが未認証になる
  - `OH_SECRET_KEY`は保存データ中のsecret暗号化に使われ、無い場合は再起動を
    またぐsecret復元ができない
  - `deferred_init=true`では、初期化APIが呼ばれるまでconversation、event、bash
    routerが503になる
- `openhands-agent-server/openhands/agent_server/conversation_service.py`と
  `event_service.py`
  - conversation metadata、event、stateをlocal filesystemへ保存し、必要時に
    persisted conversationを再ロードする
  - `fork`はevent historyをdeep-copyし、新しいconversationとして開始する

### Docker資材とimage

確認したDocker資材は
`vendor/software-agent-sdk/openhands-agent-server/openhands/agent_server/docker/`の
`Dockerfile`と`build.py`である。Dockerfileは`source`、`source-minimal`、`binary`、
`binary-minimal`等のtargetを持ち、`build.py`の既定image名は
`ghcr.io/openhands/agent-server`である。minimal targetはheadless向けで、full targetは
VSCode等の追加資材を含む。既定の公開imageが実際にregistryへ存在することや、その
digestはこの調査では確認していない。ACDではdigestを確認できないimageを決定論的
ゲート実行の根拠にしない。

## ACDでの位置づけ

```text
client / agent
      ↓
agent-server（REST / WebSocket / persistenceの運搬）
      ↓
workspace上のACD入力・生成物
      ↓
CIまたはrun_in_workspaceの決定論的pipelineとgate
```

agent-server経由のevent、state、metrics、condenser出力、agent最終応答、
OpenAI互換応答は、実行の進捗・観測・表示のための情報である。これらをEvidenceへ
変換して合格側へ倒してはならない。合否はCIまたはDockerWorkspaceの
`scripts/run_in_workspace.py`によるDocker workspace側で決定論的gateを再実行して決める。
agent-serverはこの経路を置き換えない。

fork、resume、server再起動でstateやeventの枝が変わっても、合否は同じ設計入力と
git状態に対するgateの再実行で決める。LocalConversationの`write_conversation_metrics`が出力する
metrics JSONも`pass_evidence: false`を持つ経過情報であり、serverのtelemetryやmetrics
と同様にpass evidenceではない。

## 運用手順

### 1. 起動前

1. `vendor/software-agent-sdk`がv1.42.1であることを確認する。
2. serverの作業ディレクトリを決め、`workspace/conversations`、
   `workspace/project`、`workspace/bash_events`をその配下に置く。
3. conversation/eventを再起動後も復元する場合は、`OH_SECRET_KEY`をsecret manager
   から注入する。secret値をshell history、文書、commit、ログへ出さない。
4. networkへbindする場合は`SESSION_API_KEY`または設定ファイルのsession keyを必ず
   設定する。READMEの既定hostは`0.0.0.0`だが、`__main__.py`は認証未設定時に
   loopbackを既定にする実装を含むため、実際のbind値を起動ログで確認する。

確認した起動入口は次のとおりである。

```bash
uv run python -m openhands.agent_server --host 127.0.0.1 --port 8000
```

このrunbookでは実serverの起動・接続・再起動を実測していない。上記は一次READMEと
entry pointに基づく手順例であり、ACDの検証済みE2E手順ではない。

### 2. conversationの作成・実行

native RESTを使う場合は、`POST /api/conversations`で作成し、返されたidに対して
message送信と`POST /api/conversations/{id}/run`を行う。進捗はevent endpointまたは
WebSocketで観測する。OpenAI互換経路では`POST /v1/chat/completions`を使えるが、
`stream=true`はv1.42.1で未対応である。

serverから返されたagent応答をACDの合格判定へ渡さない。生成物が必要な場合は、
workspace上の入力・出力を回収し、独立parserと既存gateをCIまたは
`run_in_workspace`側で実行する。

### 3. 永続化、resume、fork

`Config.conversations_path`を会話とeventの保存先として専用の永続volumeへ割り当てる。
`workspace_path`と会話ごとのworkspaceも同じ運用境界で管理し、設計入力と生成された
`out/`を混在させない。server再起動後のresumeはpersisted metadata/stateを再ロードする
SDK経路に委譲する。forkは`POST /api/conversations/{id}/fork`で行い、fork後も必ず
決定論的gateを再実行する。

同じ保存領域を複数serverで共有する場合、configのconversation leaseを確認する。
複数instanceでの所有権や同時実行をこのrunbookでは実測していないため、単一instanceを
既定の運用単位とする。shared storageが必要な場合は別途負荷・lease検証を実施する。

### 4. 停止、ログ、metrics

- 実行を止めるには`pause`または即時`interrupt`を使い、停止後の状態をeventとstateで
  観測する。
- 不要なconversationは`DELETE /api/conversations/{id}`で削除し、専用の保存volumeと
  bash eventの保持方針に従って後片付けする。
- server標準ログ、event API、WebSocketは経過観測であり、Evidenceではない。
- LocalConversationのlocal SDK経路では`conversation_stats`から
  `write_conversation_metrics(metrics, path)`を呼び出してJSONを保存する。
  server経由のmetricsをこの関数へ無理に接続する実装は本本手順では追加しない。

### 5. `out/`成果物とDocker workspace

`out/`、`evidence/`、fabrication成果物は専用volumeまたはhost mountへ明示的に回収する。
containerの一時filesystemにだけ置いた成果物は、container停止・削除で失われる。
DockerWorkspaceの`run_in_workspace`を併用する場合、agent-serverは会話とagent操作の運搬層、
Docker workspaceは決定論的pipelineとgateの実行層とする。image digestが解決できない、
toolが無い、gateが未実行、parse失敗、unknownの場合は成功扱いにしない。

## 安全境界と禁止事項

- API key、token、`OH_SECRET_KEY`、webhook headerを文書、commit、command line、
  ログへ書かない。
- session key未設定のserverをネットワークへ公開しない。認証が設定されていてもTLS、
  reverse proxy、network policyは別途運用で確保する。
- ACD hooksはSDK agent経路のpre-tool boundaryとして保護投影、Evidence要求、
  order/stop条件を適用する。ただし、serverのfile API、git API、bash API、OpenAI
  gatewayなどをagent hookを経由せず直接呼ぶ場合、その呼び出し全体に同じhookが自動で
  適用されることは確認していない。直接経路は決定論的gateと権限境界で別途制限する。
- server経由でも発注・外部送信ガードを緩めない。必要Evidenceが現revisionに一致しない、
  unknown、stale、未検証のときはfail-closedで拒否する。
- event、state、metrics、agent出力、OpenAI互換応答をpass evidenceとして保存・転記
  しない。

## 実測済み・未実測

### 実測済み（source inspection）

- v1.42.1のpackage version、entry point、REST/WebSocket/OpenAI routerの構成
- configの保存先既定値、session key、secret key、deferred init
- conversationのpause、interrupt、fork、delete、event取得API
- Dockerfileのtargetと`build.py`のimage名既定値

### ADR-0025受け入れ条件（未実測）

- **V1**: agent-server起動とhealth応答。
- **V2**: RESTでconversation作成、message送信、run、event取得。
- **V3**: WebSocketでイベント購読と受信。
- **V4**: agent-server imageのDocker buildとdigest記録。
- **V5**: DockerWorkspaceでGD1基板・筐体pipelineを実行し、出力差を記録。
- **V6**: fork/resume後のゲート再実行と、ゲートだけによる合否判定。
- **V7**: file、git、bash router、OpenAI互換gatewayへのhook適用可否。
- **V8**: token、money、wall-clock、外部process回数の予算実測。

V1〜V8を実測し、各項目にfail-closed negative testを付けるまで、実運用済み・検証済みと表現しない。実運用へ進む場合は、まずsecretを
含まないstagingでREST/WebSocket、再起動resume、fork、生成物回収、決定論的gate再実行を
別途記録する。
