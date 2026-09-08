# 実行例: dual-beacon-tag（2026-09-08／roadmap 14.23反映後の同一要件再検証・不合格）

第10回VibeBB検証（`docs/vibebb-standalone-verification.md` 17節）で実際に生成された成果物、
会話の一次記録、対照run（pristine main・同digest）の記録を収録した実行例である。
本例は**不合格の実例**であり、authoritativeな合格Evidenceは3 laneとも存在しない。
閾値、ゲート挙動、fail-closed境界は変更していない。

## 条件

| 項目 | 値 |
|---|---|
| 対象graph | `dual-beacon-tag`（revision `r1`、GD1とは無関係の新規設計） |
| `origin/main`／plugin revision | `5bf2c90652f9ba5479cae97983446a652fac55ba`（`180b628…`からPOST `/api/plugins/install`、`ref=main`・`force=true`で更新。`report/plugin-install-response.json`） |
| image source commit | `dcbd7bbe718df9702bec987c65fe5eadbcedc30c`（Z-8・Z-9を含む。publish run 34184028741） |
| server image | `ghcr.io/uist1idrju3i/acd-server@sha256:fb236ff5b53dabead1a6f8bd8e32aa6d1e42f140f527d95d2bd72d2ca01a3b9e` |
| tools image | `ghcr.io/uist1idrju3i/acd-tools@sha256:2a185b14637c34613d6473c665fa39852fe7368570b0a89bbd359f804fd9cf10` |
| OpenHands workspace | `/home/openhands/acd-workspace-verify-20260908`（`/acd:init`対象。loop会話は会話用project dirで自前clone） |
| 会話ID | init `a333c594-6a5f-4887-b752-0e229b748357`、loop `02b1455c-f440-4f98-90fb-f22cec339cf1` |
| host | 実機OpenHands VPS（OpenHands Local GUI、LLM `openai/preview/Kimi-K2.6`） |
| 実行日 | 2026-09-08（UTC） |
| 投入要件 | `conversation/prompt.md`の自然文のみ（第8回・第9回と同一文言） |
| 介入 | 初期prompt1回と、`MaxIterationsReached`（500 iteration、09:49:35）後の自然文re-prompt1回（`conversation/reprompt.md`） |

## 権限

- **authoritative（L1）**: 存在しない。GUI経路の最終実行は`board-pipeline`が
  `ValueError: U2: graph CPL rotation offset differs from LCSC Evidence`で停止した
  （routerは収束: `unrouted_progression [5,2,1,1,1,1,0,0,0,0,0,0,0]`、`final_unrouted 0`）。
  U2（AMS1117-3.3、C6186）の`cpl_rotation_offset_deg: 180.0`はmini-blink-dongle由来の宣言値で、
  実測record（`evidence/cpl-orientation/U2.json`）から導かれるoffsetと一致しない。
- **Evidence**: electrical・mechanical・firmwareのいずれも生成されていない。
  `evidence/cpl-orientation/`はZ-9の案内に従ってagentが`fetch_lcsc_footprint_orientation.py`で
  取得したCPL向き実測record（17件）であり、lane Evidenceではない。
- **検証commandの結果（fail-closedの確認）**:

  ```text
  $ uv run python scripts/verify_authoritative_evidence.py \
      --revision-from fixtures/dual-beacon-tag/graph.json --out-root <out root> \
      --require-lane electrical --require-lane mechanical --require-lane firmware
  FAIL: no Evidence files supplied
  （終了コード 1。GUI経路は会話内で同結果、対照runは control/control-*/verify-authoritative.txt）
  ```

- **対照run**: `control/control-a2`・`control-b2`（有効fixture、pristine `5bf2c90`、同digest）は
  GUI経路と同一理由・同段で停止した。`control/control-c`（有効specからfixture再生成）は
  `fixture-generation`で`FixtureBuilderError: parts catalog has no matching part`で停止し、
  agent最終graphがagent編集後の`contracts/parts-catalog.json`（`parts_catalog_sha256
  sha256:c1371cf3…`）に依存することを示す。`control-a`・`control-b`はstale graph
  （`fixture/graph-as-committed-stale.json`）を誤って使った診断runであり最終結果ではない。
- **source変更**: agentは`contracts/parts-catalog.json`（80行追加）と
  `src/acd/core/part_selection.py`（message拡充）を未commitのまま`--allow-dirty`で通した
  （`report/workspace-src-diffs/`）。agent最終報告はこれを「pipelineの自動登録」「内部キャッシュ
  更新」と説明しているが、一次資料（event digestの05:05／05:38／06:50）はagent自身の
  `jq`・`str_replace`編集を示す。
- **L3観測**: `loop-summary.json`・`timing-record.json`・`router_diagnostics`・hook発火ログ・
  会話digestはいずれも観測記録であり合格側権限を持たない。

## 収録内容

| path | 内容 |
|---|---|
| `conversation/prompt.md`、`conversation/reprompt.md`、`conversation/init-prompt.md` | 投入した自然文要件、停止後の再prompt、`/acd:init`のprompt |
| `conversation/init-events-digest.jsonl`、`conversation/vibebb-events-digest.jsonl` | 両会話のevent digest（各eventを300文字へ切り詰め、system promptは省略。secret・session keyを含まない） |
| `conversation/conversation-stats.json` | event件数、action種別件数、LLM token累計（OpenHands統計の転記） |
| `conversation/agent-final-report.md` | 再promptに対するagent最終報告の全文（source変更の説明は一次資料と矛盾する。17.3節参照） |
| `hooks/hook-log-loop.tsv`、`hooks/hook-log-init.tsv` | `HookExecutionEvent`全件（loop 1,549件、init 39件。種別・blocked・exit code・deny分類・理由） |
| `hooks/hook-denials-loop.jsonl` | deny 10件（PreToolUse 7件＝`raw_container_image`1・`inline_write`1・`write_target`3・`unsupported_syntax`2、Stop 3件） |
| `fixture/` | agent最終run（09:39）が実際に使った有効fixture: `spec.json`・`graph.json`（`net.boot`あり）・`rationale.json`・`requirements.json`・`decoupling-placement-report.json`・`overlays/`（mini-blink-dongleからのコピー） |
| `fixture/graph-as-committed-stale.json` | agentが`fixtures/dual-beacon-tag/`へ残していた06:34生成の古いgraph（`net.button`、BOOT net無し）。`control-a`・`control-b`はこれを誤使用した |
| `evidence/cpl-orientation/` | LCSCから取得したCPL向き実測record 17件（`archive_manifest.json`等のserver側bookkeepingは除外） |
| `loop/` | GUI経路最終runの`loop-summary`・`timing-record`・`lane-preflight`・router（`routing-summary`・`router-pass-progress`・`routing-connectivity`）・`design-predicates`・`cpl-basis-report`・`dfm-report`・DRC／ERC・rationale／firmware／enclosure coverage・`enclosure-artifacts`・`envelope-cad`・`stop-report` |
| `control/README.txt` | 対照run 5本のcommand行・終了コード・fixture選択の注記 |
| `control/control-a`、`control-b` | stale graphでの診断run（`strapping_pin: status='unknown'`） |
| `control/control-a2`、`control-b2` | 有効fixtureでの対照run（explore無／有）。summary・timing・lane-preflight・router・DRC／ERC・coverage・exploration report・verifier出力 |
| `control/control-c` | 有効specからの再生成run（`fixture-generation`停止）のsummary・timing |
| `report/bootstrap-record-init.json` | `/acd:init`のbootstrap record（`resolved_revision 5bf2c906…`、server digest一致） |
| `report/bootstrap-record-agent-workspace.json` | loop会話dirの同recordの取得結果（404。recordは存在しない） |
| `report/plugin-install-response.json` | plugin更新APIの応答（`resolved_ref`、`installed_at`） |
| `report/workspace-git-commits.json`、`report/workspace-git-changes.json` | 会話workspaceのcommit一覧（bootstrap以後のcommit無し）と変更file一覧 |
| `report/workspace-src-diffs/` | `contracts/parts-catalog.json`と`src/acd/core/part_selection.py`のunified diff |
| `report/agent-scripts/` | agentが作成したspec生成script 3件（`.py.txt`。1件目のdocstringはmini-blink-dongleを構造参照と明記） |
| `report/remote-manifest.txt` | remote workspaceから回収したfileの一覧 |

## 含めないもの

- `out/`配下の生成物そのもの（KiCad project、build tree、STEP／3MF等）。再生成可能で大容量のため。
- 第三者資材（Espressif library、KiCad footprint）。
- OpenHandsのsession key・API key、SSH鍵、endpoint情報。
- `.openhands/`・環境ファイル。

## 参照

- `docs/vibebb-standalone-verification.md` 17節（手順・タイムライン・第9回との比較・判定）
- `docs/vibebb-gap-analysis.md` AA節（AA-1〜AA-10）と Z節の作動状況表
- `docs/roadmap.md` 14.24
