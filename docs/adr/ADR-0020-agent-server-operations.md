# ADR-0020: agent-serverの運用境界

- 状態: Accepted for documentation, not production adoption
- 対象: OpenHands Software Agent SDK v1.42.1
- 日付: 2026-08-17

## 決定

`openhands-agent-server`は、ACDにとって会話、agent実行、event、workspace、
永続化を運ぶruntime層として扱う。ACD独自のserver、history、event、metrics基盤は
追加しない。

agent-server経由のREST、WebSocket、conversation state、event、metrics、agent出力、
OpenAI互換応答は経過情報であり、合否Evidenceではない。合否は従来どおり設計入力、
git commit、Evidence、決定論的gateだけで決める。CIまたは`run_in_workspace`の
決定論的pipelineが判定を担い、agent-serverを判定器にしない。

## 採用範囲

- SDK v1.42.1の`agent-server` entry pointとREST/WebSocket transportの運用文書化
- SDKが提供するconversation/eventのfilesystem persistenceの利用方針
- serverのpause、interrupt、resume、fork、deleteを使う場合の手順
- `run_in_workspace`のDocker workspaceとserverを、運搬層と決定論的gate実行層に
  分ける境界
- server metricsやP6/P7のmetrics JSONを経過観測として扱う方針

一次情報は`vendor/software-agent-sdk/openhands-agent-server/`の
`README.md`、`config.py`、`api.py`、conversation/event router、
`openai/`、`sockets.py`、`conversation_service.py`、`event_service.py`、
`docker/Dockerfile`、`docker/build.py`である。

## 非採用範囲

- agent-serverをACDのpass/fail判定器にすること
- event、state、metrics、condenser、agent応答をEvidenceへ昇格すること
- agent-serverを実運用済みと主張すること
- server直接APIに対してagent hookが常に適用されると仮定すること
- ACD独自のserver起動script、remote persistence、multi-server lease基盤を追加すること
- imageの存在、registry tag、digestをsource inspectionだけで保証すること

## 安全とfail-closed

session key未設定時のserverはREADMEと`Config`上、未認証になるため、networkへ公開
しない。`OH_SECRET_KEY`なしではsecretを含むpersisted stateを再起動後に完全復元できない。
API key、token、secretは文書・commit・ログへ記録しない。

P1 hooksはagent経路のfail-closed境界であり、serverのfile、git、bash、OpenAI互換
直接経路へ自動的に同じ適用範囲を持つことは未確認である。発注・外部送信・生成物回収
では、serverの応答ではなく既存のEvidenceと決定論的gateを再確認する。

## 検証状態

本ADRとrunbookはvendor source inspectionに基づく。ACD repositoryでagent-serverを
起動した実測、REST/WebSocket E2E、resume/fork、Docker image build、registry pullは
未実施である。したがって本ADRは採用済みruntime実装の宣言ではなく、将来のstaging
検証に先立つ運用契約である。
