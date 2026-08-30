# ADR-0045: FreeRouting実行JREのEclipse OpenJ9移行と`-mt`暗黙継承

> ステータス: Accepted
> 日付: 2026-08-25
> 関連: [`ADR-0023-deterministic-gate-authority.md`](ADR-0023-deterministic-gate-authority.md)、[`../operations.md`](../operations.md)、[`../../docker/README.md`](../../docker/README.md)、[`../vibebb-gap-analysis.md`](../vibebb-gap-analysis.md)

## コンテキスト

acd-tools imageのFreeRouting実行JREはapt導入の`openjdk-26-jre-headless`（HotSpot）
だった。FreeRoutingのbatch routingは約90〜100秒の短命プロセスで、実質single-threaded
であり、peak heapは数百MB規模である。この形状はHotSpotのwarmup前提と噛み合わず、
2コア・限RAMのVPSでは常駐RSSが1.1GBを超えていた。

同時に、GD1基板pipelineは`-mt 1`を常に明示していた（[`ADR-0023`](ADR-0023-deterministic-gate-authority.md)の
決定論方針および[`../vibebb-gap-analysis.md`](../vibebb-gap-analysis.md)のF-5）。この固定は
実行環境のCPU数をrouter条件へ持ち込まないための措置であり、高速化目的ではない。
一方で`-mt 0/1/2/4`のSES SHA-256が一致するという実測があり、多コアVPSへ移行しても
CPUを使えない制約だけが残る状態だった。

## 決定

1. acd-tools imageのFreeRouting実行JREをIBM Semeru Open JRE 26.0.2.10
   （Eclipse OpenJ9 0.61.0）へ置き換える。tarballはversionとSHA-256でpinし、
   `/opt/jre`へ展開して`JAVA_HOME`と`PATH`で解決させる。build時に
   `java -version`がEclipse OpenJ9とSemeru 26.0.2.10を示すことを検査する。
   aptの`openjdk-26-jre-headless`は削除する。
2. JVM tuningの既定は`-Xtune:footprint`とし、`FREEROUTING_JVM_TUNING`で上書き可能に
   する。`-Xsoftmx`は設定しない。2コア環境では`-Xsoftmx1g`併用が僅かに速いが
   （1.6秒、2%）、より大きな基板でheapを`-Xmx`まで伸ばせなくなる副作用を避ける。
   `-Xmx`の既定`2g`と`FREEROUTING_MAX_HEAP`による上書きは維持する。
3. shared class cache（SCC）とAOTはimage build時に生成し、runtimeは
   `-Xshareclasses:name=fr_scc,cacheDir=/opt/scc,readonly`で読み取り専用に再利用する。
   `nonfatal`は付けず、cache不在・破損時はJVM起動失敗（fail-closed）とする。
   コンテナではSCCが既定で無効化されるため、明示有効化が必須である。
4. `-XX:+UseContainerSupport`と`-XX:+AdaptiveGCThreading`をwrapperで明示する。
   どちらも既定有効だが、両VPS形状で意図した挙動を固定するために明示する。
   JVMのCPU認識は制限せず、`-XX:ActiveProcessorCount`は
   `FREEROUTING_ACTIVE_PROCESSORS`が明示された場合だけ付与する。
5. FreeRoutingの`-mt`をF-5の決定から部分的に撤回し、暗黙継承（FreeRouting既定の
   論理CPU数−1）へ変更する。`DEFAULT_FREEROUTING_THREADS`は`None`とし、
   `None`のときは`-mt`をcommandへ含めない。明示値は正のintだけを受け、
   `--freerouting-threads N`で従来どおり固定できる。
6. Evidenceの機械非依存性は、実行環境のCPU数を記録しないことで維持する。
   暗黙継承時の`measurement_conditions`は固定文字列
   `"implicit router threads (cpu_count-1)"`とし、`routing_config.freerouting_threads`は
   JSON `null`として残す。したがって`config_hash`は実行機のCPU数で変動しない。

## 根拠となる実測

2コアVM、digest固定image
`ghcr.io/uist1idrju3i/acd-tools@sha256:35313c1ddd1954122ad3f173ca557993e6ca0dc892c3f052521f83c8e4c5e36c`
へSemeru JREをmountし、`examples/sensor-node-20260820/board/gd1.dsn`を`-mp 10`、
`-mt`暗黙で実行した。全構成でSES SHA-256は
`45d620d0d86c05e860724fb1e0df49c6cda34b00c9dc921b552d2a0f071ddff0`に一致した
（HotSpot `-mt 1`のbaselineと同値）。3回反復の平均は次のとおりである。

| 構成 | wall（平均/最小〜最大） | peak RSS | peak heap |
|------|------------------------|----------|-----------|
| HotSpot `-Xmx2g` `-mt 1` | 98.3秒 / 96.4〜99.6 | 1139.9 MB | 425.9 MB |
| OpenJ9 `gencon` + SCC | 91.1秒 / 87.7〜95.9 | 622.9 MB | 330.1 MB |
| OpenJ9 `-Xtune:virtualized` + SCC | 94.2秒 / 88.5〜101.6 | 566.7 MB | 317.2 MB |
| OpenJ9 `-Xtune:footprint` + SCC | 77.3秒 / 76.1〜78.7 | 357.9 MB | 148.3 MB |
| OpenJ9 `-Xtune:footprint -Xsoftmx1g` + SCC | 75.7秒 / 74.6〜76.7 | 324.0 MB | 110.1 MB |

単発測定（n=1）では`gencon`（SCC無し）98.5秒、`-Xquickstart`+SCC 113.6秒、
`optthruput`+SCC 107.6秒、`balanced -Xnuma:none`+SCC 113.4秒／RSS 1333.6 MB、
`-Xtune:throughput`+SCC 104.0秒だった。いずれも`-Xtune:footprint`より遅い。
出荷するwrapperと同一のoption列（`-Xmx2g -Xtune:footprint` + readonly SCC +
`-XX:+UseContainerSupport -XX:+AdaptiveGCThreading`、`-mt`暗黙）での確認実行は
76.2秒／RSS 344.9 MB／peak heap 99.9 MBで、unrecognized option警告は出ず、
SES SHA-256も一致した。

SCC不在時の挙動も確認した。`readonly`および`readonly,fatal`のいずれでも
`JVMSHRC226E`／`JVMSHRC336E`／`JVMSHRC337E`／`JVMSHRC840E`で起動失敗し、
終了statusが非0になる。fail-closed契約は追加optionなしで満たされる。

## 未決定事項と制約

- 多コア・大RAMのVPS相当環境は本決定の測定に含まれない。2コア環境のみの実測であり、
  高性能VPS側は未測定として[`../operations.md`](../operations.md)へ明記する。
  `-Xtune:footprint`はメモリ使用量最小化を優先する設定であるため、多コア環境では
  `FREEROUTING_JVM_TUNING`の再評価が必要になり得る。
- `-mt`暗黙継承の出力非依存性はGD1 DSN・FreeRouting 2.3.0の事例で確認したものである。
  他の入力または版でSES SHA-256が一致しない場合は`-mt`固定へ戻す。
- Semeru／OpenJ9はEPL-2.0、Apache-2.0、GPL-2.0-with-classpath-exceptionであり、
  JRE実行環境としての同梱はACDへのGPL/AGPL import結合には当たらない。帰属は
  [`../../docker/README.md`](../../docker/README.md)へ記載する。
- image digestは publish job summaryの値を確認してから
  [`../../docker/image-digests.json`](../../docker/image-digests.json)へ転記する。
  本ADRの時点でlockのdigestとJava版文字列は旧HotSpot imageのままである。
