#!/bin/bash
# 1s host + docker resource sampler. Output: TSV lines.
OUT="$1"
mkdir -p "$(dirname "$OUT")"
read -r _ u1 n1 s1 i1 w1 q1 sq1 st1 _ < /proc/stat
echo -e "ts\tcpu_cores_busy\tmem_used_kib\tmem_avail_kib\tswap_used_kib\tload1\tdocker" > "$OUT"
while true; do
  sleep 1
  read -r _ u2 n2 s2 i2 w2 q2 sq2 st2 _ < /proc/stat
  busy=$(( (u2+n2+s2+q2+sq2+st2) - (u1+n1+s1+q1+sq1+st1) ))
  idle=$(( (i2+w2) - (i1+w1) ))
  total=$(( busy + idle ))
  ncpu=$(nproc)
  cores=$(awk -v b="$busy" -v t="$total" -v n="$ncpu" 'BEGIN{ if (t>0) printf "%.2f", b/t*n; else print "0" }')
  u1=$u2; n1=$n2; s1=$s2; i1=$i2; w1=$w2; q1=$q2; sq1=$sq2; st1=$st2
  mt=$(awk '/MemTotal/{print $2}' /proc/meminfo)
  ma=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
  swt=$(awk '/SwapTotal/{print $2}' /proc/meminfo)
  swf=$(awk '/SwapFree/{print $2}' /proc/meminfo)
  load=$(cut -d' ' -f1 /proc/loadavg)
  dk=$(timeout 2 docker stats --no-stream --format '{{.Name}}={{.CPUPerc}}/{{.MemUsage}}' 2>/dev/null | tr '\n' ';')
  echo -e "$(date -u +%FT%T)\t$cores\t$((mt-ma))\t$ma\t$((swt-swf))\t$load\t$dk" >> "$OUT"
done
