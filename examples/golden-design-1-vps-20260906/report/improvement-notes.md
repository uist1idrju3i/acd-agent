# 改善提案メモ（第7回検証と成果物回収で気づいた点）

`docs/vibebb-standalone-verification.md` 14.10と`docs/vibebb-gap-analysis.md` X節の提案を、
成果物回収時に判明した点で補強した。閾値・ゲート・fail-closed境界を緩める提案は含めない。

## X-1 plugin更新でpackage pinとversionが追従しない

installed pluginのrevisionは`f636c73…`へ進んだが`version`は`0.0.2`のままで、
`plugins/acd/skills/acd-package-ref.txt`のpackage pinは`b3e531b…`で本体より古い。
GUI経路のSkill subprocessがどのACD本体を実行したかを、この記録から確定できない。

**提案**: plugin資材を変更する変更ではpackage pinも同じ変更で更新することを、docs driftと同種の
機械検査で固定する。`/acd:init`のbootstrap recordへ「Skill subprocessが解決したACD本体revision」を
記録する。

## X-2 FW Evidenceの`input_hash`が常にunknownで、検証対象からも漏れていた

生成側は修正済みである。残るのは検証範囲の問題で、`container-gates`と文書例示が
基板・筐体の2 Evidenceしか検証していなかった。

**提案**: `container-gates`と文書例示を「loopが書いたEvidence全件」のglob検証へ広げる。
`examples/golden-design-1-vps-20260901/firmware/evidence-firmware.json`の`"unknown"`は
過去記録としてそのまま残し、READMEに拒否される旨を明記する（本ディレクトリの`prefix-run/`が
negative controlになる）。

## X-3 会話から`run_in_workspace.py`を起動する際の引数誤り

`--repo`にworkspaceではなく`/workspace`を渡す、`--download`を宣言しないまま既定の
`out/gd1/…`を取りに行く、の2回の誤りで会話は迂回した。loop本体は完走しており、
失敗はtransport側だけである。

**提案**: `plugins/acd/commands/vibebb-loop.md`のfallback節に、workspace pathを`--repo`へ、
`--out-root`配下の回収対象を`--download`へ渡す具体commandを書く。runnerが`--out-root`から
回収対象を導出できる`--download-out-root`のような経路があれば誤りにくい。transport失敗時は
loop本体のexit codeとtransportのexit codeを分けて報告する。

## X-4 `--source mounted`の起動overhead

起動ごとにcontainer内で依存同期が走り、loop外側に10秒台が乗る（`measure/runP.log`内の
`Installed 259 packages`まで。単独計測は未実施）。

**提案**: image同梱venvの再利用、または同期結果のcacheを実測して採否を決める。

## X-5 FreeRoutingと他laneのCPU競合

同じDSNの単独実行156〜163秒に対し、loop内`board[3/12]`は180〜183秒。競合分は約15%。

**提案**: FW laneのESP-IDF buildの並列度を`--jobs`から導出して抑える案を実測する。ただし
FW laneは基板laneの影に隠れているため、短縮は競合分（20〜25秒）が上限である。
router threadsとJVM tuningは効かないことが本回で確定したので、再測定は不要である。

## 反復実行のcache未使用

会話のfallback commandは`--cache-dir`／`--resume`を指定していない。DSN不変なら
`board[3/12]`の約180秒を省ける既存機能である。

**提案**: `vibebb-loop.md`のfallback commandに`--cache-dir`を既定で含める。

## 計測wrapper（V-8、未解消）

資源計測は今回も使い捨てshell（`measure/sampler.sh`）で行った。

**提案**: repository内にsampler scriptを置き、`run_in_workspace.py`から任意で起動できるようにする。
