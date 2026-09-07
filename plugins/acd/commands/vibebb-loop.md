---
description: 要件から設計反復と発注可否までを固定順序で実行するVibeBB loop。
argument-hint: "--fixture PATH [--order-total PATH | --quote-record PATH... --order-scope PATH --fab-profile PATH] [--policy PATH] [--out-root PATH] [--cache-dir PATH] [--resume] [--jobs N] [--requirement PATH] [--fixture-spec PATH] [--fixture-overwrite] [--design-only] [--explore-board | --recover-lanes] [--max-exploration-candidates N] [--max-exploration-rounds N]"
allowed-tools:
  - acd_aggregate_order_total
  - acd_register_parts_catalog_entry
  - acd_compile_requirement_change
  - acd_build_design_fixture
  - acd_validate_design_graph
  - acd_run_design_loop
  - acd_diagnose_gate_failure
  - acd_explore_board_candidates
  - acd_check_order_readiness
---

# VibeBB設計loop

会話で受け取った要件を、次の順序で設計入力へ反映してから実行する。
生のshellや任意のPython moduleを使わず、宣言された`acd_*` toolだけを使う。

0. 宣言された`acd_*` toolがこの会話に無い場合（ambient install経路など）は、
   任意のshell作業へ退避せず、次のcommandで不在をfail-closedに確認する。

   ```bash
   uv run python scripts/verify_acd_tool_registration.py \
       --command plugins/acd/commands/vibebb-loop.md --available <この会話のtool名>...
   ```

   `status`が`pass`でない場合、報告された`fallbacks`の決定論的CLI入口だけを使い、
   CLI入口を持たないtoolの段は実行せずfail-closedとして報告する。この判定はL3観測であり、
   合否権限もauthoritative Evidenceも持たない。結果は既定で
   `out/tool-availability/<command名>.json`へ機械可読JSONとして保存され（`--record`で
   変更可）、判定不能の場合も`status: unknown`として同じ場所へ残す。会話exportに依らず、
   この一次記録からtool不在を第三者が確認できるようにする。

   この会話からloopをlock済みcontainer内で実行しなければならない場合は、次のcommandを
   使う。`--repo`には`/workspace`ではなくhostのrepository絶対pathを渡し、回収対象は
   `--download-root`でout rootごと宣言する。downloadされたfileはhost側の
   `out/container/<out_root>`配下へ置かれる。

   ```bash
   uv run python scripts/run_in_workspace.py \
       --image <lock済みserver image ref> \
       --repo <この会話のworkspaceの絶対path（/workspaceではなくhostのrepository path）> \
       --download-root <out_root> \
       'uv sync && uv run python scripts/run_design_loop.py --fixture <fixture> --out-root <out_root>'
   ```

   要件が発注入力を含まない場合は`--design-only`を付けて実行する。この場合
   order-readiness段は未実行として記録されloopはfail-closedのままとなる。
   不足する発注入力を補うためにorder-totalやquote documentを捏造してはならない。
1. 要件差分は`acd_run_design_loop`の`requirement`へ渡す。新規fixtureは
   `fixture_spec`へ渡す。どちらも省略した場合は既存fixtureを使う。
2. `acd_run_design_loop`は次の段を必ずこの順序で実行する。
   - fixture生成（spec指定時のみ）
   - 要件compile（更新record指定時のみ）
   - 要件入口整合検査（常時のdesign-loop stage）
   - silkscreen resolver（基板pipelineの前提となるbarrier）
   - 基板pipeline、筐体pipeline、FW pipeline（Skill CLI subprocess）
   - order-total集計（quote record、scope、fab profile指定時のみ）
   - 発注可否のpre-order gate

   発注入力（order-total documentまたは集計入力）が要件から除外される場合は、
   `design_only`（CLIの`--design-only`）で実行し、order-readinessは未実行かつ
   fail-closedとして記録される。order-totalやquote documentを作成して穴埋めしない。
3. 既存fixtureをspecから作り直す場合は`fixture_overwrite`を明示する。既存graphは
   backupと差分reportを残し、暗黙の上書きはfail-closedである。
4. 失敗した場合は後続段を実行せず、`acd_diagnose_gate_failure`で出力を調べる。
   `explore_board`を明示した場合、board-pipelineのfail-closed却下に限ってloopが
   `explore_board_candidates`を自動実行し、候補予算とround上限の範囲でgraph検証から
   loopを再実行する。enclosure、FW、silkscreenの失敗では自動探索しない。
   自動探索を使わない場合、または探索結果の診断が必要な場合は
   `acd_explore_board_candidates`を手動で使い、修正後はgraph検証からloopを再実行する。
   却下応答には`recovery_rerun`として機械可読な再実行引数、宣言された復帰次元、
   復帰不能laneの次手が含まれる。laneごとの宣言由来復帰は`recover_lanes`を明示した
   場合に有効になり、詳細な手順は`/acd:vibebb-recover`を使う。
   board-pipelineまたはboard-explorationで失敗した場合、`loop-summary.json`の
   `router_diagnostics`にrouterの収束状態、`unrouted`数のpassごとの推移、最終
   未配線数、plateau pass数、`status: "fail"`のnet一覧（10件上限）がL3診断として
   記録される。探索候補を評価したroundがある場合は候補ごとの
   `candidate_router_diagnostics`も記録される（12件上限）。plateau（末尾3 pass以上
   同一値）なら宣言済み制約内で候補軸（外形サイズ、層数、部品間隔・配置）を広げるか
   設計入力へ制約を明示し、減少継続なら`--max-passes`を先に引き上げ、timeoutなら
   `--router-timeout-s`を引き上げるか配線負荷を下げる。いずれもDRCや配線規則を
   緩めない。これらの診断と`next_step_action`へのhint追記はL3観測であり、
   合否権限を持たない。
5. 発注可否はloopが返すorder-readiness結果と、必要なら
   `acd_check_order_readiness`で確認する。発注実行はこのcommandの責務ではない。
6. 各roundの終了後、run出力のL3 recordを会話へ返して進行を可視化する。

   ```bash
   uv run python scripts/report_progress.py --out <out_root>
   ```

   digestはtiming recordと探索reportの`status`、`termination_reason`、
   評価候補数、残予算、勝者候補を返す。timing recordではstage duration合計と
   loop全体の`wall_clock_seconds`を別値として示す（並列laneでは合計がwall-clockを
   上回りうる）。読めないrecordは`unknown`として報告され、digestは非零終了する。
   digestはL3観測であり、合否やEvidenceを変更しない。digestは常に
   「authoritative Evidence: unverified」の行を含み、この行はdigestがEvidenceを
   検査していないことを示す。
7. 「合格」「発注可」を会話へ報告する前に、authoritative Evidenceの検証を実行し、
   その結果を報告へ含める。

   ```bash
   uv run python scripts/verify_authoritative_evidence.py \
       --revision-from <fixture>/graph.json --out-root <out_root> \
       --require-lane electrical --require-lane mechanical --require-lane firmware
   ```

   `--out-root`は`evidence-*.json`を再帰的に集め（`.stage-cache`配下は除外）、
   `--require-lane`は指定laneのEvidenceが1件も無い場合にfail-closedで失敗する。
   「合格」の報告には基板・筐体・FWの3 laneすべてのEvidenceが必須であり、FW Evidenceが
   欠けたままの報告は認めない。報告には必ず次を含める。(a) 上記コマンドの終了コードと出力、(b) 各Evidenceの
   `target_revision`がgraph revisionと一致すること、(c) `status="valid"`と
   container provenance（digest）、(d) order-readiness段の結果。これらのいずれかが
   欠ける、unknown、または未実行の間は、timing record、loop summary、探索report、
   進行digest、preflightの`declarations_complete`を根拠に「合格」「order-ready」と
   述べてはならず、「Evidence未検証」と明記する。host実行のprovisional Evidenceは
   この検証を通過しない。

`acd_run_design_loop`は、必要に応じて入力hash単位のstage cache（`cache_dir`）、
失敗からのresume（`resume`）、stageごとの所要時間記録、基板・筐体・FW laneの
bounded並列（`jobs`）を利用できる。`resume`で`cache_dir`を省略した場合は
`out_root/.stage-cache`を使う。cacheから復元するのは決定論的な生成物だけであり、
判定、verdict、Evidenceは復元せず毎回再実行する。timing recordとcache reportは
L3観測であり、合否を変更しない。tool経路の`jobs`既定値は1であり、並列化は
明示指定時だけ有効になる。CLIの既定値は`min(os.cpu_count() or 1, 3)`である。
`explore_board`は既定で無効であり、`max_exploration_candidates`と
`max_exploration_rounds`を正整数で明示する。探索はL2の操舵とL3の観測であり、
候補report、L1閾値、判定権限、authoritative Evidenceを変更しない。候補が見つかっても
graphのIDとrevisionが探索前と一致し、正規化content hashが変化したこと、および探索reportの
`target_revision`がgraph revisionと一致することを検証してからloopを再実行し、L1ゲートと
Evidenceを毎回生成する。
入口整合検査のmissing、parse失敗、graph IDまたはrevision不一致、graph-anchored要件の
text不一致はfail-closedで停止する。unknownや未回答の要件は推測しない。この入口検査は
L1ゲートやauthoritative Evidenceの代替ではない。order-total集計は決定論的なL2
集計であり、既存の`--order-total` document modeと同時に指定してはならない。
集計結果はL1合格権限もauthoritative Evidenceも持たない。

各段はfail-closedであり、`ok: false`、`fail_closed: true`、失敗段ID、そこまでの
段結果を含むJSONを返す。段を黙って省略したり順序を入れ替えたりしてはならない。
gate、閾値、期待値、revision一致、authoritative Evidenceの規則を緩めない。
Skill出力、AI review、host上のprovisional実行、会話上の判断は合格Evidenceではない。
ESP-IDF、QEMU、外部toolの不在や検証不能は「問題なし」ではなくfail-closedとして報告する。
生成物の出力先とprefixはgraph_idから導出され、GD1の既存互換名以外を新たに固定しない。
FW boot logの既定文言もgraph_idから導出する（規範は
[`docs/architecture.md`](../../../docs/architecture.md)）。GD1の従来文言はfixtureの
`firmware.module.boot_log_message`明示属性で再現する。graphが不明な場合は既定値を
推測せずfail-closedにする。

FW laneは`firmware.sequence_step`・`firmware.state_transition`・`firmware.pin_assignment`と
capability registry（`contracts/firmware-capability-registry.json`）の被覆検査を、
Skill起動前にfail-closedで行う。`led_indicator: true`を宣言した電気部品はいずれかの
`firmware.sequence_step`の`target`でなければならず、sequence stepの`action`は登録済み
capabilityの`actions`に含まれていなければならない。`firmware.state_transition`の
`trigger`は、sequenceが使うcapabilityの`emits_triggers`のいずれかで発火できなければ
ならない。`firmware.pin_assignment`のnet（`net.`接頭辞を除くrole）は`pin_role_order`か
使用capabilityの`required_pin_roles`に含まれていなければならない。違反時は
`firmware coverage failed`で停止し、修正はsequence stepの追加、
`acd-firmware-capability-entry`（`scripts/register_firmware_capability.py`）での
capability登録（`emits_triggers`宣言付き）、または登録済みpin roleへのnet改名で行う。
宣言を削って検査を回避しない。検査結果はlane出力の`firmware-coverage.json`と
preflightの`firmware_coverage`へL3診断として残る。

2個目のLEDとボタン入力は登録済みcapabilityで宣言する。第2 LEDはnetを`net.led2`として
`firmware.pin_assignment`を追加し、部品へ`led_indicator: true`と`led_drive_net: "net.led2"`を
宣言したうえでsequence stepへ`toggle_led2`（capability `led2_blink`、targetはそのLED部品）を
追加する。生成FWは`led`と`led2`を交互に点滅させる。ボタン入力はnetを`net.button`として
pinを割り当て、`read_button`（capability `button_input`）をsequenceへ追加する。
`button_pressed`は`button_input`の`emits_triggers`に登録済みで、`read_button`がsequenceに
あるときだけ`button_pressed`をtriggerとする`firmware.state_transition`が被覆検査を通る。
buttonは内部pull-up付きactive-low入力として射影され、押下で点滅をpause／resumeする。
どちらのcapabilityも`led_blink`の存在を前提とし、単独では射影できない。

機能blockのトポロジは`contracts/topology-templates.json`から検証・合成され、部品の
追加は`acd_register_parts_catalog_entry`でlibrary provenanceを検証してから行う。
共通railは`shared_nets`へ宣言し、template-localなrefdes／net IDと分離する。template
間の重複は代替blockのため許可するが、pad参照は自templateのlocal netまたはshared net
に閉じ、同時選択時の異なる定義はfail-closedにする。catalog登録は宣言操作であり、
合否やEvidenceを与えない。USB-Cを宣言しない設計は
`usb_cc`をnot_applicableとして扱えるが、電池の充電・保護回路を暗黙に規範化しない。
その範囲はロードマップ16.2／16.3へ委譲する。
