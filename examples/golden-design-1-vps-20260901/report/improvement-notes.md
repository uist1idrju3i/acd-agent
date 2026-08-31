# 改善提案メモ（第6回検証と成果物回収で気づいた点）

`docs/vibebb-standalone-verification.md` 13.9の提案を、成果物回収時に判明した点で補強した。
閾値・ゲート・fail-closed境界を緩める提案は含めない。

## 検証で観測したギャップ

### V-1 container内のEDA資材をhostへ持ち出す操作が止まらない

GUI会話はhostにKiCad symbolが無いことを回避するため、locked container内の
`/usr/share/kicad/symbols`・`footprints`をhostの`/tmp`へtarで取り出し、成功した。
Evidenceの権限境界は「host実行はprovisional」という別の防御で守られたが、
持ち出し操作そのものは`PreToolUse` hookを通過している。

**提案**: containerからhostへEDA資材を取り出す操作をhookで拒否するか、少なくとも
host実行時にcontainer由来資材の混在を検出し、provisional扱いを明示的に記録する。

### V-2 GUIのplugin追加ピッカーがinstalled storeを反映しない

installed API側は`acd`（`enabled=true`、revision一致）を返すのに、GUIの追加ピッカーは
`No available plugins.`を表示する。導入済みpluginの確認・再導入がGUIから不可視で、
検証のたびにAPI直叩きを強いられる。

**提案**: 導入済みplugin一覧と再導入をGUIから行えるようにする（OpenHands側の課題）。

### V-3 会話の最終報告がL3記録だけで合格を述べる

**提案**: command契約側で「authoritative Evidence検証の実行と結果提示」を報告の必須項目にし、
`report_progress.py`のdigestに「Evidence未検証」を明示する行を持たせる。
`pass_evidence: false`の記録だけを根拠に合格側の語（PASSED／ready for order）を
使わせない文面規則をcommandへ書く。

### V-4 例示commandが必ずquote期限切れになる

`docs/operations.md`のGD1発注集計例は`--evaluated-at 2026-08-14T00:00:00Z`だが、
GD1のquote fixtureは`valid_until: 2025-01-17T09:00:00Z`である。

**提案**: quote期限を延ばすのではなく（閾値を緩めない）、例示`--evaluated-at`をquote有効期間内へ揃え、
期限整合をdocs検証で機械的に固定する。

### V-5 部分失敗時にcontainer成果物を回収できない

`scripts/run_in_workspace.py`の`_execute_and_download()`はcontainer commandがexit 0のときだけ
downloadする。loopが途中でfail-closedすると、生成済みEvidenceと製造データがhostへ降りず、
`verify_authoritative_evidence.py`にかけられない。

本回収作業では、container側commandの末尾でtarを作り`exit 0`させ、内側のexit codeを
stdoutへ`newspec_rc=1`として残す回避策を取った。**この回避策は判定の観点では危険で、
回避策が定着すると失敗が成功として読まれうる。**

**提案**: 「失敗時も宣言済みdownloadを試みるが、判定はcontainer exit codeで維持する」経路を
`run_in_workspace.py`へ設ける。fail-closedを緩めずに診断可能性だけを上げられる。

### V-6 新規specはsilkscreen宣言不足で止まる

**提案**: spec→fixture生成の段で、必要な宣言（少なくともreference designator配置と対象層）の
欠落を列挙し、`next_step_action`へ「specへ追加すべき宣言」を具体名で返す。
現在の`next_step_action`は「graphを調整して再実行せよ」であり、会話から埋めるには情報が足りない。

## 成果物回収で新たに気づいた点

### D-1 `timing-record.json`のduration_secondsをwall-clockとして読むと誤る

`duration_seconds`は26 stageの合計で、lane並列のためwall-clock（Run N 259秒）より大きい
（Run N 473.4秒）。13.7はこの合計値をGUI経路のwall-clockとしてCLIの248秒と比較しており、
「GUI経路は約2倍遅い」という誤った読みになっていた（本PRで訂正した）。

**提案**: `timing-record.json`へwall-clock（loop全体の開始・終了時刻または`wall_clock_seconds`）を
明示的に持たせる。合計値と実時間が混在すると、資源・所要時間の記録が比較不能になる。

### D-2 資源計測wrapperが特定checkout前提で固定されている

`measure_container_run_c.sh`相当のwrapperはcheckoutパス・downloadファイル一覧・
image指定が固定されており、別workspaceで再実行するにはコピー改変が必要だった。

**提案**: 計測wrapperをrepository内のscriptとして、checkout path、image digest、
download対象を引数で受ける形に整理する。検証のたびに使い捨てのshell scriptを書く状態は、
実測条件の再現性を下げる。

### D-3 会話exportからは`acd_*` tool未登録の判定材料が読み取りづらい

会話exportに登録tool一覧は含まれるが（`ConversationStateUpdateEvent`の`value.tools`）、
これが「ACD toolが登録されていない」ことを意味するかはACD側の知識が必要である。

**提案**: `verify_acd_tool_registration.py`の結果を会話へ機械可読な形で残す
（例: 不足tool名を列挙したJSONをworkspaceへ書く）。事後の第三者検証で
「入口を満たしていない」ことを一次資料から確認できるようにする。

### D-4 ESP-IDF buildツリーが成果物回収の大半を占める

FW laneのoutputは約207 MiBで、その大半（約203 MiB）は再生成可能なESP-IDF buildツリーである。
本ディレクトリでは`flash.bin`、`qemu-serial.log`、Evidence、プロジェクト入力だけを収録した。

**提案**: FW laneのsummaryへ「収録すべき最小成果物集合」を宣言し、
成果物回収や配布時に何を残すかを機械可読に決められるようにする。
