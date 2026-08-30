# ADR-0047: install doctorのdigest固定server image前提

> ステータス: Accepted
> 日付: 2026-08-30
> 関連: [`ADR-0023-deterministic-gate-authority.md`](ADR-0023-deterministic-gate-authority.md)、[`ADR-0038-acd-install-doctor.md`](ADR-0038-acd-install-doctor.md)、[`../operations.md`](../operations.md)

## コンテキスト

install doctorはこれまで、ホスト上のKiCad、FreeRouting、ESP-IDF、QEMU、
CMakeを観測していた。しかしauthoritativeなゲートの正はdigest固定server imageであり、
ホスト環境の版や構成をdoctorの成功判断へ混ぜると、実際のゲート実行環境と異なる
診断結果になる。`acd_tools`はserver imageのbuild baseに過ぎず、ゲートを実行する
runtime imageではない。

また、`--source mounted`はホストcheckoutをdigest固定server imageへmountして実行する
authoritative経路として既に採用している。imageに同梱されたbundled資材をauthoritative
経路へ切り替えると、publish triggerが`src/**`を含まないため、古いbundleでゲートが
実行される危険がある。

## 決定

1. doctorのDocker capabilityとdigest固定server image availabilityをrequired checkへ
   格上げする。server imageは`docker/image-digests.json`の`acd_server` entryから解決し、
   不在時は既定でpullする。`--no-pull`指定時はpullせず、local image不在をfailとする。
2. ホストのKiCad、FreeRouting、ESP-IDF、QEMU、CMakeは観測しない。EDA capabilityと
   firmware prerequisiteは、`docker run --rm --entrypoint "" <image>@<digest> sh -lc ...`
   でdigest固定server image内を観測する。EDAの欠落はoptionalな`degraded`とし、
   firmwareの欠落はrequiredな`failed`とする。
3. server image内でdoctorを実行するcontainer modeではDocker-in-Dockerを要求せず、
   PATH上のツールを直接観測する。`/.dockerenv`または`ACD_HOME`でこのmodeを判定する。
4. workspace digest checkの対象を`acd_tools`から`acd_server`へ変更する。`acd_tools`の
   digestはdoctorでは検査しない。
5. authoritative Evidenceの実行経路は`--source mounted`のまま維持する。bundledを
   authoritativeにしない。initializeのclone軽量化とsession start hookは後続変更で扱う。
6. initializeはrepository clone、revision fetch、recursive submoduleをshallow
   (`--depth 1`)で取得する。ホストの`uv sync`は行わず、doctorがpullするlocked
   server imageの依存とEDA/FWツールを使用する。bootstrap recordには
   `source: "mounted"`と`server_image_digest`を記録する。
7. SessionStart hookはprojectのlockから解決したserver imageをpullせずに
   `docker run --rm --entrypoint "" ... sh -lc`でprobeする。4ツールの版をすべて取得
   できない場合はhost probeへfallbackせず、fail-closed contextをL3観測として注入する。

## 結果

doctorのツール観測対象とauthoritative gateのruntimeがdigest固定server imageへ一致し、
ホストEDA/FW環境の差による誤った診断を防止できる。image内EDA欠落はoptional観測として
報告される一方、Docker、server image、firmware前提はfail-closedで扱われる。
doctorは引き続きL3 observationであり、authoritative Evidenceやゲート合格を生成・昇格しない。
initializeとSessionStart hookもこの境界を維持し、初期化記録やツール版のcontextを
authoritative Evidenceへ昇格しない。image未取得時のpullはdoctorの責務とし、hookは
独立したpullやhost依存解決を行わない。
