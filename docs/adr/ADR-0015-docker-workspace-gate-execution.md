# ADR-0015: DockerWorkspaceによるゲート実行

> ステータス: Accepted
> 日付: 2026-08-18

## 決定

ACDはホスト実行を既定のまま維持し、決定論的pipelineとゲートだけを任意に
Docker workspace内で実行できる経路を追加する。agentそのものをコンテナへ
移すことは今回の範囲外である。

配布用ACD imageは作らない。KiCad、FreeRoutingなどGPL系ライセンスのソフトウェアを
含むimageを配布すると、対応するソース提供その他の頒布義務が発生するため、Dockerfile
を公開し利用者が各自buildする。

## Workspaceの選択

`DockerWorkspace`は既成のagent-server imageを起動する経路である。一方、
`DockerDevWorkspace`は`base_image`からagent-server imageをbuildできるため、
利用者がbuildした`docker/acd-tools.Dockerfile`を渡すP5の経路には後者を選択した。
workspaceはrepoを`volumes`で`/workspace`へmountし、出力とevidenceをホストへ残す。
DockerfileはFreeRouting JARを`/usr/local/bin/freerouting` wrapperからPATH上で実行可能にし、
ngspiceの版をbuild時に検証する。revision解決と差分確認のためgitもimageへ含める。
SDK v1.42.1のworkspace実装は`--rm`、`linux/amd64`、health check、
`forward_env`を提供する。

## Container記録とfail-closed

`execution_env()`のcontainer値は次の決定論的規則で記録する。

1. `ACD_CONTAINER_IMAGE_DIGEST`が`sha256:`と64桁hexで始まる妥当な値なら、その値を
   `container=`へそのまま記録する。
2. `/.dockerenv`または`ACD_IN_CONTAINER`の真値からコンテナ内と判定できるがdigestが
   未設定・空・不正なら`container=unknown`とする。ToolEnvelopeのunknownは
   `has_unknown()`を真にし、Evidenceの`supports_pass()`を通さない。
3. それ以外は`container=none`とする。

runnerは`docker image inspect`でRepoDigestsを優先し、ローカルbuildでそれが無い
場合はimage IDを使う。いずれも`sha256:` digestを解決できなければworkspaceを
起動せず非ゼロ終了する。docker CLI不在も同じ扱いとする。

## Determinismの境界

Dockerは実行環境の隔離を補助するが、determinismを保証しない。timestamp、locale、
filesystem、CPU、APT repositoryなどの差は残るため、ToolEnvelope、入力・出力hash、
timestamp正規化、独立再読込、決定論的期待値とゲートを緩めない。
runnerはpipelineの終了コード、stdout/stderr、生成物の場所を報告するだけで、
pipelineに追加の合否判定を行わない。

## 将来課題

agentごとのコンテナ実行、配布済みACD image、実機測定を含む運用は将来課題であり、
本ADRの決定には含めない。
