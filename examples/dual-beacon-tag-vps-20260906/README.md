# 実行例: dual-beacon-tag（2026-09-06／自然文要件のみ・GD1非依存の新規設計・不合格）

第8回VibeBB検証（`docs/vibebb-standalone-verification.md` 15節）で実際に生成された成果物、
会話の一次記録、対照run（pristine main）と修正branch再実行の記録を収録した実行例である。
本例は**不合格の実例**であり、authoritativeな合格Evidenceは存在しない。
閾値、ゲート挙動、fail-closed境界は変更していない。

## 条件

| 項目 | 値 |
|---|---|
| 対象graph | `dual-beacon-tag`（revision `r1`、GD1とは無関係の新規設計） |
| plugin revision | `f636c73…` → `e45f1ec…`（`origin/main`一致、POST `/api/plugins/install`で`force`・`ref=main`） |
| server image | `ghcr.io/uist1idrju3i/acd-server@sha256:d68c12409ff2e967b17d8899f4b5159029f1e1a0b5ed8a686c005cf2e501f8e2` |
| OpenHands workspace | `/home/openhands/acd-workspace-verify-20260906b`（本検証で新規作成） |
| 会話ID | init `c068c3e3-6134-4058-a82a-a9534465c2a0`、loop `fea3f2cf-fc26-4a68-b833-acbef76a1e3a` |
| host | 実機OpenHands VPS 195.154.107.160（OpenHands Local GUI） |
| 実行日 | 2026-09-06（UTC） |
| 投入要件 | `conversation/prompt.md`の自然文のみ（fixtureテンプレート無し。agentがspec.jsonを自力生成） |

## 権限

- **authoritative（L1）**: 存在しない。`board-pipeline`が
  `GateError: router convergence_state='not_converged' (fail-closed)`で停止し、
  探索は`status='exhausted'`（評価5候補／生成28候補、writable candidateなし）で終了した。
  筐体laneも`unsupported connector opening face: right`でfail-closedしている。
- **唯一存在するEvidence（合格を意味しない）**: `firmware/evidence-firmware.json`は
  `status: "valid"`、`target_revision: "r1"`、`container_image_digest`が上記lockと一致する
  QEMU仮想実行の記録である。単独ではauthoritative passを構成しない。
- **検証commandの結果（fail-closedの確認）**:

  ```text
  $ uv run python scripts/verify_authoritative_evidence.py \
      --revision-from <生成graph.json> --out-root <v5 out root> \
      --require-lane electrical --require-lane mechanical --require-lane firmware
  FAIL: required lane Evidence missing: electrical
  （終了コード 1、実出力は `report/verify-v5.txt`）
  ```

- **L3観測（合否権限なし）**: `loop/`、`control/`、`repair/`のsummary・timing・gate証跡。
  いずれも`pass_evidence: false`である。
- **L2観測（合否権限なし）**: `conversation/`の一次記録。`report/workspace-git-delta.patch`は
  検証checkoutでagentが行った`src/`改変の差分であり、検証者向けの一次資料であって
  採用された変更ではない。

## ディレクトリ

| path | 内容 |
|---|---|
| `fixture/spec.json` | agentが自然文要件から生成したDesign Fixture Spec（そのまま。修正なし） |
| `fixture/order-total.rejected.json` | agentが要件の禁止に反して捏造した発注document（合計USD 0、`quote_id: dummy-quote-1`）。**negative artefactであり、決して使用しない**。再現や検証のためにだけ収録する |
| `conversation/` | 投入prompt、1回だけ許したre-prompt、agentの最終報告、2会話のevent digest（`*-events-digest.jsonl`、timestamp／source／tool／本文300字切詰） |
| `loop/v5/` | 最終loopの`loop-summary.json`・`timing-record.json`・`exploration-report.json`・gate証跡（`design-predicates.json`・`routing-connectivity.json`） |
| `firmware/` | `evidence-firmware.json`・`qemu-serial.log`・`summary.json` |
| `control/` | pristine `e45f1ec`による対照runの`loop-summary.json`・`timing-record.json`（A: order-total省略、B: 捏造document付与） |
| `repair/` | 修正branch（strapping_pinのLED駆動net一般化等）での`--design-only`再実行のsummary・timing・述語結果と検証出力 |
| `report/` | 観測メモ（`notes.md`）、v5の検証出力、workspace差分patch |

`spec.json`が参照するEspressif KiCad library（`libraries/Espressif.pretty`・
`Espressif.kicad_sym`）は第三者資材のため収録していない。
pinは`espressif/kicad-libraries` commit `dd76561812ab300351234ba6e0ec1295641796f0`であり、
再現時は同commitを別途取得してfixtureの`libraries/`へ配置する。

## 結果

最終loop（v5）は`failed_stage: "board-pipeline"`、`ok: false`で停止した。
FreeRouting 2.4.1（100 pass、heap 2 GiB）は`unrouted`が22→21で plateauし、
探索は`candidate_budget_exhausted`で終了した。`strapping_pin`等の設計述語と
silkscreen resolverは通過し、FW laneはQEMU仮想Evidenceを生成したが、
要件の「緑・橙500 ms交互点滅」と「ボタン一時停止」はFW capability契約に無く、
agentは`fw.sequence`から`toggle_led comp.d2`と`read_button`を削除してD1のみの
点滅へ設計を縮小した（要件drift。`conversation/agent-final-report.md`も参照）。

pristine `e45f1ec`での対照run（control-a／control-b）は同じ2箇所で停止し、
agentの`src/`改変は最終失敗に対して荷重を持たなかった。修正branchでの
`--design-only`再実行（repair-a、container wall-clock 152秒）は
発注入力なしで全設計stageへ到達したが、同じrouter／筐体の壁で停止した。
修正はagent向けの罠（見分けづらいorder-total要件、単一「LED」net固定、
init scriptのpath）を除くものであり、dual-beacon-tagを合格させるものではない。
router収束の壁・非front筐体開口・FW capability契約は未解消として残る。
