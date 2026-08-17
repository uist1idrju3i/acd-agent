# ADR-0012: OpenHands SDKランタイム機能の段階採用

- **状態**: Accepted
- **日付**: 2026-08-17

## 決定

SDKの宣言的利用に加えて、ランタイム機能を段階的に採用する。第1段として、
fail-closed境界をSDK hooksで機構化する。hookは既存の決定論的判定を呼ぶだけで、
新しい閾値・ゲートを作らない。

hookのDENYはagent経路にしか効かないため、CI側の検証を唯一の防壁から降ろさず、
二重に持つ。SDKの契約に従い、exit code 2のみがブロックする。

## 範囲

本ADRの第1段では、派生投影への直接書き込み、ゲート未通過の発注・外部送信、
設計入力変更後の未検証終了をhooksで拒否する。また、SessionStartで外部ツールprobeを
注入し、Markdown変更後に既存の文書検証を実行する。判定の閾値とEvidence契約は
既存のPydanticモデルを正とする。

orderガードは、transmission commandがリポジトリ内の`out/`またはartifact globに一致する
製造成果物に触れる場合、または明示的なorder commandの場合だけ作動する。transmissionと
orderは実行ファイルのtoken単位で検出し、URL tokenはartifact判定から除外する。通常の
source push、文書取得、供給者データ取得は対象外である。order policyのEvidence globで
解決した各ファイルをCLIへ渡し、`required_evidence_ids`に指定された各Evidence IDについて
現revisionの`supports_pass()`を要求する。GD1基板pipelineは現状Evidenceを生成しないため、
基板fabrication成果物の送信はdenyする。

Stopガードには出口を設ける。order policyのEvidence globで解決したファイルのうち、
dirtyな設計入力すべてより新しいmtimeのvalidかつunknownなしEvidenceがあればallowするが、
これはorderガードより弱い。CLIの`--valid-only`はこのStopガード専用の新しさ確認であり、
mtimeの新しさはpassの根拠ではない。`supports_pass()`はcommit済みrevision一致を要求し続け、
`--valid-only`と`--revision`または`--require-id`は併用しない。

以降の段では各段でADRを追加する。

- P2: `ToolDefinition`化とFastMCP server廃止
- P5: `DockerWorkspace`
- P3: critic
- P4: workflow探索並列化
- P6/P7: EventLog・Metrics
- P8: 配布・TestLLM
- P9: agent-server runbook

## 既存ADRとの関係

ADR-0003およびADR-0010の過去の決定は削除しない。本ADRがランタイム機能の採用範囲を
優先して定めるが、契約の正、決定論的ゲート、plugin境界に関する既存方針は維持する。
