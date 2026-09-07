# 実行例: dual-beacon-tag（2026-09-07／roadmap 14.22反映後の同一要件再検証・不合格）

第9回VibeBB検証（`docs/vibebb-standalone-verification.md` 16節）で実際に生成された成果物、
会話の一次記録、対照run（pristine main・同digest）、修正branch再実行の記録を収録した
実行例である。本例は**不合格の実例**であり、authoritativeな合格Evidenceは存在しない。
閾値、ゲート挙動、fail-closed境界は変更していない。

## 条件

| 項目 | 値 |
|---|---|
| 対象graph | `dual-beacon-tag`（revision `r1`、GD1とは無関係の新規設計） |
| `origin/main`／plugin revision | `180b628f5da100292e520c7cd2a5c1a3ddf5ea53`（`e45f1ec…`からPOST `/api/plugins/install`、`ref=main`・`force=true`で更新） |
| server image | `ghcr.io/uist1idrju3i/acd-server@sha256:3fb0e216e5aee4ad727792bc8b762b9eb0bc4141d911eafbc23c18bb340f8c26` |
| tools image | `ghcr.io/uist1idrju3i/acd-tools@sha256:732842927293447e96a75c03b67d92d72ddb668bfb351f688ea175c61f21be6f` |
| OpenHands workspace | `/home/openhands/acd-workspace-verify-20260907`（本検証で新規作成） |
| 会話ID | init `3406573f-c4d7-4cbe-883c-de5243dc7cc1`、loop `4d203304-1acb-44c0-a261-af5ab1bbeb57` |
| host | 実機OpenHands VPS 195.154.107.160（OpenHands Local GUI） |
| 実行日 | 2026-09-07（UTC） |
| 投入要件 | `conversation/prompt.md`の自然文のみ（第8回と同一文言。agentがspec.jsonを自力生成） |
| 介入 | 初期prompt1回と、`MaxIterationsReached`後の自然文re-prompt1回（`conversation/reprompt.md`） |

## 権限

- **authoritative（L1）**: 存在しない。GUI経路の最終実行は`board-pipeline`が
  `GateError: router convergence_state='not_converged' (fail-closed)`
  （`final_unrouted: 3`、`open_nets: ["+3V3", "GND"]`）で停止した。ただしこの到達段は
  agentが検証checkoutの`src/acd/core/rationale.py`へ免除を追加した（gate緩和）うえで、
  `run_in_workspace.py`を経ない生`docker run`で得たものであり、pristine `180b628`の
  対照runでは同じ入力がrationale coverage（`unclassified=3`）で`board-pipeline`到達前に
  停止する。
- **唯一存在するEvidence（合格を意味しない）**:
  - GUI経路: `loop/raw-container/evidence-firmware.truncated.txt`（会話observationからの
    転記、途中まで）。`status: "valid"`、`target_revision: "r1"`だが
    `container_image_digest: "unknown"`・`source_revision: "unknown"`で
    `verify_authoritative_evidence.py`は受理しない。
  - 対照run: `control/control-a/evidence-firmware.json`・`control/control-b/evidence-firmware.json`。
    `status: "valid"`、`target_revision: "r1"`、`container_image_digest`が上記lockと一致、
    `source_revision: 180b628…`・`source_tree_state: clean`。QEMU仮想実行であり実機Evidence
    ではない。単独ではauthoritative passを構成しない。
- **検証commandの結果（fail-closedの確認）**:

  ```text
  $ uv run python scripts/verify_authoritative_evidence.py \
      --revision-from fixtures/dual-beacon-tag/graph.json --out-root <out root> \
      --require-lane electrical --require-lane mechanical --require-lane firmware
  FAIL: required lane Evidence missing: electrical
  （終了コード 1。GUI経路は会話内で同結果、対照runは control/verify-control-*.txt）
  ```

- **L3観測**: `loop-summary.json`・`timing-record.json`・`router_diagnostics`・
  hook発火ログ・会話digestはいずれも観測記録であり合格側権限を持たない。

## 収録内容

| path | 内容 |
|---|---|
| `conversation/prompt.md`、`conversation/reprompt.md` | 投入した自然文要件と、停止後の再prompt（各1回） |
| `conversation/init-events-digest.jsonl`、`conversation/vibebb-events-digest.jsonl` | `/acd:init`・`/acd:vibebb-loop`会話のevent digest（各eventを300文字へ切り詰め、system promptは省略。secret・session keyを含まない） |
| `conversation/agent-final-report.md` | 再promptに対するagent最終報告の全文（`src/`変更なし・R4／R6誤配線の記述は一次資料と矛盾する。16.3節参照） |
| `fixture/` | agentが生成した最終設計入力（`spec.json`・`graph.json`・`rationale.json`・`requirements.json`・`graph-overwrite-report.json`）。Espressif KiCad libraryとmini-blink由来overlayは第三者資材のため収録しない |
| `loop/raw-container/` | 生container経路（`/tmp/out`）の最終`loop-summary.json`・`timing-record.json`とfirmware Evidence（会話observationからの転記） |
| `loop/host-provisional/` | host（provisional）実行の`loop-summary.json`（`silkscreen-resolve`のlibrary不在）・`timing-record.json`・`lane-preflight` |
| `loop/tool-availability.json` | 会話経路のtool可用性記録 |
| `hooks/hook-log-init.txt`、`hooks/hook-log-loop.txt` | HookExecutionEvent全件（PreToolUse 505件中deny 17件、理由文付き） |
| `hooks/matcher-matrix.txt` | 会話で観測したcommandを本VMの`protect_projections._terminal_allowed`で再現した表（empty poll・`find -exec grep`・read-only `python3 -c`・heredoc・`mv out/…`・`docker exec`包み・base64 `exec`・`docker run`） |
| `control/control-a/`、`control/control-b/` | pristine `180b628`・同digest containerでagent最終fixtureを実行した対照run（a: `--design-only`、b: `--explore-board`付き）の`loop-summary`・`timing-record`・`lane-preflight`・`rationale-coverage`・`firmware-coverage`・firmware Evidence |
| `control/verify-control-*.txt` | 対照runの`verify_authoritative_evidence.py`出力 |
| `control/defect-repro-*.log` | `run_in_workspace.py`が任意commandで既定GD1 downloadを必須扱いし終了コード2を返す再現（Z-5） |
| `repair/` | `design_loop.py`の`spec_dir`未伝播（Z-13）の再現と修正branch再実行。`README.txt`は対照専用specの編集内容、`main-host.log`はpristine mainのhost再現、`repair-branch-host.log`は修正branchのhost実行、`repair-container.log`・`container-*.json`は修正branchのdigest固定container実行（provenance `3e13c80 clean`、`silkscreen-resolve`で`net 'BOOT': manufacturing margin is required`のfail-closed） |
| `report/notes.md` | 実測中の一次記録（時刻・観測・Z候補） |
| `report/workspace-git-commits.json`、`report/workspace-git-delta-files.txt`、`report/workspace-src-diffs/` | 検証workspaceのcommit一覧（bootstrap `180b628`以降にagentが`src/`・`scripts/`へ加えた2 commit）、変更file一覧、source差分 |

## 注意

- `out/`生成物そのものはcommitしない。本例の`loop/`・`control/`・`repair/`は必要な
  fileだけをコピーしたものである。
- 本例の設計入力（`fixture/`）はagentがgate緩和と要件削除（`net.en`）を伴って到達した
  最終状態であり、参照設計として使ってはならない。
- secret、API key、SSH key、GUI session key、`.env`は含まない。
