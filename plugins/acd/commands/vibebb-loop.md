---
description: 要件から設計反復と発注可否までを固定順序で実行するVibeBB loop。
argument-hint: "--fixture PATH --order-total PATH [--policy PATH] [--out-root PATH]"
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
   基板候補を探索する必要がある場合だけ`acd_explore_board_candidates`を使い、
   修正後はgraph検証からloopを再実行する。
5. 発注可否はloopが返すorder-readiness結果と、必要なら
   `acd_check_order_readiness`で確認する。発注実行はこのcommandの責務ではない。

各段はfail-closedであり、`ok: false`、`fail_closed: true`、失敗段ID、そこまでの
段結果を含むJSONを返す。段を黙って省略したり順序を入れ替えたりしてはならない。
gate、閾値、期待値、revision一致、authoritative Evidenceの規則を緩めない。
Skill出力、AI review、host上のprovisional実行、会話上の判断は合格Evidenceではない。
ESP-IDF、QEMU、外部toolの不在や検証不能は「問題なし」ではなくfail-closedとして報告する。
生成物の出力先とprefixはgraph_idから導出され、GD1の既存互換名以外を新たに固定しない。
