---
description: 却下されたlaneを宣言由来の復帰次元でbounded反復するVibeBB復帰loop。
argument-hint: "--fixture PATH [--order-total PATH] [--policy PATH] [--out-root PATH] --recover-lanes [--max-exploration-candidates N] [--max-exploration-rounds N] [--fixture-overwrite --fixture-spec PATH] [--requirement PATH]"
allowed-tools:
  - acd_run_design_loop
  - acd_diagnose_gate_failure
  - acd_explore_board_candidates
  - acd_explore_enclosure_candidates
  - acd_compile_requirement_change
  - acd_build_design_fixture
  - acd_register_firmware_capability
  - acd_validate_design_graph
  - acd_check_order_readiness
---

# VibeBB復帰loop

`/acd:vibebb-loop`がfail-closedで停止した後、設計入力を決定論的に修正して反復する
経路である。生のshellや任意のPython moduleを使わず、宣言された`acd_*` toolだけを使う。
反復回数は必ず明示上限で囲み、上限に達したら停止して不足を報告する。

0. 宣言された`acd_*` toolがこの会話に無い場合（ambient install経路など）は、
   任意のshell作業へ退避せず、次のcommandで不在をfail-closedに確認する。

   ```bash
   uv run python scripts/verify_acd_tool_registration.py \
       --command plugins/acd/commands/vibebb-recover.md --available <この会話のtool名>...
   ```

   `status`が`pass`でない場合、報告された`fallbacks`の決定論的CLI入口だけを使い、
   CLI入口を持たないtoolの段は実行せずfail-closedとして報告する。この判定はL3観測であり、
   合否権限もauthoritative Evidenceも持たない。

1. `acd_diagnose_gate_failure`で失敗laneの診断を取る。診断は失敗述語、機械可読な
   失敗subject、変更次元、rationale coverage、lane preflight、必要な宣言、
   復帰可能性（`contracts/lane-recovery-declaration.json`由来）を返す。
2. 診断が`recovery_supported: true`のlaneを示した場合は、`acd_run_design_loop`へ
   `recover_lanes`と`max_exploration_candidates`・`max_exploration_rounds`を明示して
   再実行する。loopは却下predicateの`remediation`を候補生成へ渡し、宣言された次元に
   限定して候補を作る。remediationが無い却下では候補予算を消費せずunknownで停止する。
3. 診断が`recovery_supported: false`を示した場合は探索を主張しない。返される
   `next_step_action`に従って不足宣言を埋める。
   - 未登録のfirmware actionやcapability fragmentは`acd_register_firmware_capability`で
     provenance検証付きに追記する。未宣言actionのcode生成は行わない。
   - 要件の追加・削除・更新は`acd_compile_requirement_change`の`mode`で行う。graph、
     requirements、rationaleは同一transactionで更新される。
   - fixture specからの作り直しは`acd_build_design_fixture`の`overwrite`、または
     `acd_run_design_loop`の`fixture_overwrite`を明示した場合だけ許可される。既存graphは
     backupと差分reportを残す。暗黙の上書きはfail-closedである。
4. 候補が採用された場合も合否は再実行したL1ゲートだけが決める。loopはgraphのIDと
   revisionが探索前と一致し、正規化content hashが変化し、探索reportの`target_revision`が
   graph revisionと一致することを検証してから、該当laneの決定論的段を再実行する。
   採用時は変更subjectのrationaleを決定論的に更新し、更新できない場合は候補を採用しない。
5. 上限に達しても通過しない場合は、最後の診断と再実行引数を提示して停止する。
   閾値、期待値、revision一致、authoritative Evidenceの規則を緩めない。

`scripts/run_acd_goal.py`（`src/acd/openhands/goal_cli.py`）はhost側で同じboundsを持つ
bounded反復harnessであり、`GoalController`とgate evaluatorで`max_iterations`付きの反復を
回す。goalの評決、判断、探索report、診断はいずれもL2の操舵とL3の観測であり、
`pass_evidence`はrevision一致したL1ゲートのauthoritative Evidenceに限る。QEMUの仮想実行と
host上のprovisional実行は実機測定として扱わない。
