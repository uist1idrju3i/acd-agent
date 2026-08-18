# ADR-0028: 実行provenanceとauthoritative Evidence

> ステータス: Accepted
>
> 日付: 2026-08-17

## コンテキスト

従来の`ToolEnvelope.execution_env`はhost/architectureの説明文字列に
container情報を埋め込んでいた。そのため、hostで決定論的ゲートが通った結果と、
digest固定containerで通った結果を型安全に区別できず、valid Evidenceが合格側へ
誤って昇格し得た。

## 決定

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
CLIは`scripts/run_in_workspace.py`で引数と表示だけを担う。以前はSDKのdev workspace経路
（on-the-fly build）でbase imageからagent-server imageを準備していたが、6.3〜6.5で
移行を完了した。現在は事前build済みagent-server imageを
`DockerWorkspace(server_image=...)`へ渡し、runnerは実際のserver imageの解決済みdigestと
container markerをforwardする。

## 影響

- host CIの既存exit 0を壊さず、結果をprovisionalとして明示できる。
- 合格側Evidenceはimage digestへ結び付く。
- Dockerを使うCI jobは本変更では追加しない。CIのcontainer移行は別途受入条件を
  定義して実施する。
- timestamp、filesystem、外部tool版、入力・出力hashの正規化と決定論的gateは
  引き続き必要であり、container化だけでdeterminismを仮定しない。

## 検証

validatorの矛盾拒否、host provisional、digest固定container authoritative、
markerのみのunknown拒否、Evidence CLIのhost拒否を回帰試験に含める。

## CI authoritative gate

GD1基板pipelineは、ERC、routing、DRC、silkscreen、DFM、発注readinessの決定論的結果を
`evidence-electrical.json`へ記録する。CIの`container-gates` jobはlock済みserver imageを
pullし、`DockerWorkspace`を使う
`scripts/run_in_workspace.py`からresolver、基板pipeline、筐体pipelineを実行する。
続けて`verify_authoritative_evidence.py`で両Evidenceを決定論的に検査する。

`DockerWorkspace`のagent-serverは`/workspace`をconversation保存領域として使用する
ため、ホストrepositoryを`/workspace`へmountしない。repositoryは`/acd-src:ro`として
read-only mountし、container user所有の`/workspace/acd`へ複製してからpipelineを実行する。
生成物はSDKの`RemoteWorkspace.file_download()`でhostへ取得し、host上のverifierへ渡す。
commandの失敗やfile downloadの失敗はfail-closedとする。

`ACD_CONTAINER_IMAGE_DIGEST`には実際に実行したserver imageのcontent addressを記録する。
base tools imageとderived server imageのdigestは別 identityであり、同一とは主張しない。
server digestがlockへ記録される前は、`print_locked_image.py`とCIがpullを拒否して
fail-closedで停止する。

local build imageにRepoDigestが無い場合はimage IDをcontent addressとして記録する。
publish済みdigestが未確定の間は、偽のlock fileやplaceholder digestを作成しない。
