# ADR-0028: 実行provenanceとauthoritative Evidence

- Status: Accepted
- Date: 2026-08-11

## Context

従来の`ToolEnvelope.execution_env`はhost/architectureの説明文字列に
container情報を埋め込んでいた。そのため、hostで決定論的ゲートが通った結果と、
digest固定containerで通った結果を型安全に区別できず、valid Evidenceが合格側へ
誤って昇格し得た。

## Decision

`ToolEnvelope`は`execution_context`（`container`、`host`、`unknown`）と
`container_image_digest`を持つ。containerはdigestまたは`unknown`を必須とし、
hostはdigestを持たない。矛盾した組合せはPydantic validatorで拒否する。
container identityの判定はtyped fieldから行い、`execution_env`の文字列をparseしない。
container markerがあるのにdigestを解決できない場合は
`execution_context="container"`、digest=`"unknown"`としてfail-closedにする。

`Evidence.supports_pass()`はrevision、status、既知provenanceの妥当性を表す従来の
意味を維持する。`supports_authoritative_pass()`はこれにdigest固定containerを
追加要求する。validだがauthoritative条件を満たさないEvidenceは
`is_provisional()`で表し、参考実行としてのみ扱う。

`evidence/`への昇格とEvidence check、git-backed gate checkは
`supports_authoritative_pass()`を要求する。host pipelineはゲートを実行してexit 0
を維持できるが、出力Evidenceをprovisionalと明示し、合格側へ昇格させない。
digest不明containerは既存のunknown fail-closed経路で停止する。

容器実行の再利用可能な入口は`src/acd/openhands/workspace.py`へ集約し、
CLIは`scripts/run_in_workspace.py`で引数と表示だけを担う。現行runnerはユーザーが
指定したbase imageからagent-server imageを準備するため、SDKの
`DockerDevWorkspace(base_image=...)`を採用する。SDKの実装とdocstringが示すとおり
これはon-the-fly buildの開発・テスト経路である。事前build済みagent-server imageを
配布する運用へ移行した時点で、`DockerWorkspace(server_image=...)`へ切り替える。
runnerは解決済みdigestとcontainer markerをforwardする。

## Consequences

- host CIの既存exit 0を壊さず、結果をprovisionalとして明示できる。
- 合格側Evidenceはimage digestへ結び付く。
- Dockerを使うCI jobは本変更では追加しない。CIのcontainer移行は別途受入条件を
  定義して実施する。
- timestamp、filesystem、外部tool版、入力・出力hashの正規化と決定論的gateは
  引き続き必要であり、container化だけでdeterminismを仮定しない。

## Verification

validatorの矛盾拒否、host provisional、digest固定container authoritative、
markerのみのunknown拒否、Evidence CLIのhost拒否を回帰試験に含める。
