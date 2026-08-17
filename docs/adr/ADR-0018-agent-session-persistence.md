# ADR-0018: SDK Conversationによるagent session persistence

> ステータス: Accepted
> 日付: 2026-08-17

## 状況

現行のLocalConversation経路では、ACDのagent経路をOpenHands SDKの`LocalConversation`へ宣言的に接続する。
ACD側でloop、history、persistence、metricsを再実装しない。

## 決定

`acd_tools.agent_session.build_acd_conversation()`は、`plugins/acd`、
`register_acd_tools()`、`hooks/hooks.json`、`AcdGateCritic`、
`LLMSummarizingCondenser`、workspace、`LocalConversation.persistence_dir`を
SDKの構成要素として接続する。stateとEventLogの永続化、反復、metricsの収集はSDKへ
委譲する。metricsを書き出す場合も`pass_evidence: false`を付ける。

EventLog、conversation state、metrics、condenser outputは経過であり、合否Evidence
ではない。合否の正は入力ファイル、git commit、Evidence、決定論的ゲートである。
fork/resumeでstateが分岐しても、最終的には決定論的ゲートを再実行する。

SDK gitの変更情報は設計入力のstale判定に使う入力であり、Evidence意味論そのもの
ではない。`Evidence.supports_pass(revision)`だけがEvidenceの判定手段である。
`target_revision`はDesign Graphの`graph.revision`（`rN`）であり、git SHAではない。
非repo、不正ref、SDK git例外、malformed Evidence、revision不一致、設計入力の変更は
fail-closedとする。

## 結果

SDKのConversation機構を採用することで、ACD独自の実行基盤を増やさずにsessionの
state、event、resume、metricsを利用できる。一方、それらをpass evidenceへ昇格させる
境界は設けない。
