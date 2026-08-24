---
description: 要件から設計反復と発注可否までを固定順序で実行するVibeBB loop。
argument-hint: "--fixture PATH --order-total PATH [--policy PATH] [--out-root PATH] [--cache-dir PATH] [--resume] [--jobs N] [--explore-board --max-exploration-candidates N --max-exploration-rounds N]"
allowed-tools:
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

1. `acd_compile_requirement_change`で要件と変更対象を記録し、必要なら
   `acd_build_design_fixture`でgraphとfixtureを生成する。
2. graphを編集または生成した後、`acd_validate_design_graph`でcanonical graphを検証する。
3. `acd_run_design_loop`を実行する。このtoolは次の段を必ずこの順序で実行する。
   - silkscreen resolver（基板pipelineの前提となるbarrier）
   - 基板pipeline
   - 筐体pipeline
   - FW pipeline（Skill CLI subprocess）
   - 発注可否のpre-order gate
4. 失敗した場合は後続段を実行せず、`acd_diagnose_gate_failure`で出力を調べる。
   `explore_board`を明示した場合、board-pipelineのfail-closed却下に限ってloopが
   `explore_board_candidates`を自動実行し、候補予算とround上限の範囲でgraph検証から
   loopを再実行する。enclosure、FW、silkscreenの失敗では自動探索しない。
   自動探索を使わない場合、または探索結果の診断が必要な場合は
   `acd_explore_board_candidates`を手動で使い、修正後はgraph検証からloopを再実行する。
5. 発注可否はloopが返すorder-readiness結果と、必要なら
   `acd_check_order_readiness`で確認する。発注実行はこのcommandの責務ではない。

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

各段はfail-closedであり、`ok: false`、`fail_closed: true`、失敗段ID、そこまでの
段結果を含むJSONを返す。段を黙って省略したり順序を入れ替えたりしてはならない。
gate、閾値、期待値、revision一致、authoritative Evidenceの規則を緩めない。
Skill出力、AI review、host上のprovisional実行、会話上の判断は合格Evidenceではない。
ESP-IDF、QEMU、外部toolの不在や検証不能は「問題なし」ではなくfail-closedとして報告する。
生成物の出力先とprefixはgraph_idから導出され、GD1の既存互換名以外を新たに固定しない。
