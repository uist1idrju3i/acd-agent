# ADR-0030: Goal loopと中断・観測境界

> ステータス: Accepted
>
> 日付: 2026-08-18

## コンテキスト

SDKには目標達成を反復判定する`GoalController`、会話を中断する
`LocalConversation.interrupt()`、使用量を集計する`ConversationStats`がある。これらは
agentの操舵、停止、観測を支えるが、ACDの決定論的gateやauthoritative Evidenceの
代替ではない。

## 決定

- SDKの`GoalController`をACD固有driverから再利用し、SDKの`run_goal()`は使わない。
  ACD driverは各run後の`execution_status`を観測し、`PAUSED`ならjudgeを呼ばず
  `interrupted`で終了する。
- judgeの`GoalVerdict`は反復制御だけに使う。`gate_passed`と`authoritative`は
  注入されたACD決定論的判定からのみ導出し、判定未指定または例外時は
  `False`へ倒す。
- SIGINTは`LocalConversation.interrupt()`へ結線し、handlerはcontext manager終了時に
  元へ戻す。
- `goal_result`と`conversation_stats`は`pass_evidence=false`の観測成果物とする。
  `ConversationStats`はcombined metricsとusage別snapshotを記録する。

## 権限境界

Goal loop、judge、cancellationはL2の操舵・停止層、ConversationStatsはL3観測層である。
いずれもEvidenceを生成・昇格せず、digest固定containerで実行されたrevision一致の
決定論的gateとauthoritative EvidenceだけがL1合否を担う。中断時も決定論的再判定を
通らない結果を合格へ倒さない。

## 影響

SDKのcontrollerとconversation APIを再利用し、ACD側はI/O、停止観測、合否境界だけを
保持する。goal完了のjudge評決を合格とみなさないため、従来のEvidence authorityと
fail-closed契約を維持できる。

## 検証

complete、iteration cap、PAUSED中断、judgeとgate判定の分離、判定例外時のfail-closed、
Evidence非変更、成果物の`pass_evidence=false`、SIGINT復元、ネットワークを使わない
judge stubを回帰試験で固定する。
