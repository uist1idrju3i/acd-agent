#!/bin/sh
# FreeRouting thread-count / JVM tuning benchmark inside the digest-pinned container (untracked helper).
set -u
cd /workspace/acd
DSN=tmp-bench/golden-design-1.dsn
nproc
run() {
  name="$1"; tuning="$2"; extra="$3"
  out=/tmp/bench-$name.ses; rm -f "$out"
  s=$(date +%s%N)
  FREEROUTING_MAX_HEAP=2g JDK_JAVA_OPTIONS=-Xmx2g FREEROUTING_JVM_TUNING="$tuning" freerouting -de "$DSN" -do "$out" -mp 100 $extra > /tmp/bench-$name.log 2>&1
  rc=$?
  e=$(date +%s%N)
  echo "cfg=$name rc=$rc wall_ms=$(( (e - s) / 1000000 )) ses_sha=$(sha256sum "$out" 2>/dev/null | cut -c1-64) unrouted=$(grep -o '([0-9]* unrouted' /tmp/bench-$name.log | tail -1)"
  grep -iE "optimiz|threads|pass" /tmp/bench-$name.log | tail -3 | cut -c1-200
}
run implicit-footprint -Xtune:footprint ""
run mt1-footprint -Xtune:footprint "-mt 1"
run implicit-virtualized -Xtune:virtualized ""
run mt1-virtualized -Xtune:virtualized "-mt 1"
