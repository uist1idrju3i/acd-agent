# ADR-0032 CIにおけるauthoritative gate

> ステータス: Accepted
> 日付: 2026-08-18

## 文脈

ACDはrevision一致の決定論的Evidenceを合否の正とするが、host実行では
`Evidence.supports_authoritative_pass()`を満たせない。さらに、基板pipelineは
Evidence recordを生成していなかったため、基板と筐体の両laneをauthoritative条件で
検査するCI経路が存在しなかった。

## 決定

GD1基板pipelineは、ERC、routing、DRC、silkscreen、DFM、発注readinessの決定論的結果を
`evidence-electrical.json`へ記録する。Evidenceのenvelopeはlane内の決定論的DRC実行を
代表し、host実行時はprovisionalのまま保持する。

CIには`container-gates` jobを追加する。buildxで`docker/acd-tools.Dockerfile`をbuildして
localへloadし、SDKの`DockerDevWorkspace`を使う`scripts/run_in_workspace.py`からresolver、
基板pipeline、筐体pipelineを実行する。続けて決定論のみの
`verify_authoritative_evidence.py`で両Evidenceを検査する。

`DockerDevWorkspace`のagent-serverは`/workspace`を自身のconversation保存領域として
使用するため、ホストrepositoryを`/workspace`へmountしない。repositoryは`/acd-src:ro`
としてread-only mountし、container user所有の`/workspace/acd`へ複製してからpipelineを
実行する。生成物はSDKの`RemoteWorkspace.file_download()`でhostへ取得し、host上の
verifierへ渡す。commandの失敗やfile downloadの失敗はfail-closedとする。

`DockerDevWorkspace`は`base_image`からpinned SDK v1.42.1の
`openhands-agent-server` imageを派生buildする。実際の実行imageはderived imageだが、
provenanceへ記録する`ACD_CONTAINER_IMAGE_DIGEST`は指定されたbase imageのcontent
addressである。Evidenceではbase digestとSDK版を組み合わせた派生経路を明示し、
base imageとderived imageが同一だとは主張しない。

local build imageには通常RepoDigestが無いため、runnerはimage IDをcontent addressとして
記録する。publish workflowはmainのDockerfile変更または手動起動でGHCRへpublishし、
digestをjob summaryへ出す。publish済みdigestが未確定の間は、偽のlock fileやplaceholder
digestを作成しない。

## 結果

host実行は引き続きprovisionalであり、SDKのL2機能やLLM判断はEvidence authorityを
変更しない。container内でもrevision不一致、status不正、unknown、digest不在は
`verify_authoritative_evidence.py`がfail-closedで拒否する。Dockerは完全なdeterminismを
保証しないため、ToolEnvelopeの版、hash、収束状態、image content addressを継続して
記録する。
