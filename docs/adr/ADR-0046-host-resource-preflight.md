# ADR-0046: container起動前のホスト資源検査とJVM heap宣言

> ステータス: Accepted
> 日付: 2026-08-26
> 関連: [`ADR-0023-deterministic-gate-authority.md`](ADR-0023-deterministic-gate-authority.md)、[`ADR-0045-openj9-freerouting-runtime.md`](ADR-0045-openj9-freerouting-runtime.md)、[`../operations.md`](../operations.md)

## コンテキスト

container gateは既定で8 GiBのmemory limitを要求するが、Dockerの
`--memory-swap`をmemory limitと同値にしているため、swapを物理メモリの代替として
扱えない。実機ではMemTotal 1641 MiB、swap 5116 MiB、CPU 3コアのホストでFreeRouting
のJVM 2プロセスがglobal OOMによりkillされ、host processも巻き込まれた。

## 決定

1. container起動前に、MemTotal、MemAvailable、swap、CPU、repositoryの空きディスクを
   `check_host_resources()`で検査する。物理メモリの判定にはswapを加算せず、MemTotalから
   512 MiBのheadroomを差し引く。8 GiB上限、2コア、8 GiB空きディスクを既定要件とする。
2. 読み取り不能・parse不能・不足は全findingを集約し、containerを起動せず
   `HostResourceReport`と`failure_kind="resources"`を返す。これはcontainer起動の前提条件
   検査であり、L3 observation、lane gate pass、authoritative Evidenceではない。
3. FreeRoutingの最大heapは既定`2g`として、container wrapperへ
   `FREEROUTING_MAX_HEAP`を渡し、host launcherへ`JDK_JAVA_OPTIONS=-Xmx2g`を渡す。
   heapに加えて1 GiBのnon-heap reserveを確保し、合計がcontainer memory limitを超える
   設定は拒否する。
4. `/acd:doctor`の同じ資源値はoptional checkとして報告し、不足やunknownで`degraded`に
   するがexit code 0を維持する。container実行時のfail-closed境界をdoctorへ移さない。

## 結果

資源不足をDocker起動前に決定論的に報告でき、O-2のglobal OOM再発を実行前に阻止する。
`HostResourceReport`は観測値とfindingの機械可読な記録を残す一方、合否権限を持たない。
