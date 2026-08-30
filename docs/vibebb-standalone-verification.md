# VibeBB単体成立性の検証記録（2026-08-24, Devin環境）

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.44.1

本書は、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のM節（M-1〜M-6）が示す
「acd-agent単体でVibeBBが成立するか」を、汎用エージェント環境（Devin）で実行可能な範囲まで
実際に走らせて確認した記録である。既存の閾値、ゲート挙動、fail-closed境界、L1権限、dry-run既定は
変更していない。ツール不在や検証不能は「問題なし」ではなく「fail-closed／未検証」として記録する。

- 対象revision: main `775e889`（`vendor/software-agent-sdk` v1.44.1 / `9d143aac`）
- 実行環境: Ubuntu 22.04, x86_64, 2 vCPU, Docker利用可
- 実行内容: 既存script・pipeline・ゲートの実行のみ。設計判断（座標・GPIO・寸法・トポロジ）の
  人手による再決定は行っていない。

## 1. 外部ツールの有無

`scripts/probe_tools.py`の結果と、PATH外ツールの手動確認である。

| ツール | 有無 | 版 | 備考 |
|---|---|---|---|
| kicad-cli | あり | 10.0.5 | `/usr/bin/kicad-cli` |
| freerouting | あり | 2.3.0 | `/usr/local/bin/freerouting`（version検出はexit=1だが版取得可） |
| cad-kernel | あり | build123d 0.11.1 / cadquery-ocp 7.9.3.1.1 | Python distribution |
| java (JRE) | あり | OpenJDK 25.0.3 | freerouting実行に使用 |
| ESP-IDF | あり | v6.0.2 | 既定でPATHに無く`export.sh`が必要 |
| qemu-system-riscv32 | あり | 9.2.2 (esp_develop_9.2.2_20250817) | 同上 |
| Docker | あり | — | digest固定imageのpullと実行が可能 |
| ngspice | なし | — | hostへ導入せず、digest固定containerの45.2を正とする |

Dockerが利用可能だったため、host provisional経路とauthoritative経路の両方を実行できた。
以降で「未検証」とした項目は、ツール不在ではなく外部supplier接続とcredential、または実機に
依存する項目である。

## 2. コードレベル検証

`scripts/verify_all.py --list`の3段階（docs 3コマンド／standard 14／full 19）を確認し、
`--stage docs`と`--stage standard`を実行した。

| 段 | コマンド数 | 結果 |
|---|---|---|
| `--stage docs` | 3 | 全pass（`verify_docs.py`が96 Markdown、`verify_sdk_capabilities.py --check`、`git diff --check`） |
| `--stage standard` | 14 | 全pass（14/14 PASS、exit=0） |

standardの内訳はすべてPASSであり、`uv sync`、`ruff check`、`pyright`、
`pytest`（1306 passed / 3 skipped、231s）、`verify_docs.py`、`verify_skill_metadata.py`、
`verify_skill_package_ref.py --check`、`verify_sdk_capabilities.py --check`、
`verify_agent_prompts.py --check`、`verify_acd_tool_registration.py --check`、
`verify_model_policy.py --check`、`verify_agent_settings.py --check`、
`verify_context_view.py --check`、`git diff --check`を含む。

これは会話駆動loopの純Python部分（要件compiler `compile_requirement_change`、fixture builder
`build_design_fixture`、`contracts/topology-templates.json`によるトポロジ合成、機能ブロック
registry、`aggregate_order_total`、SDK tool登録面`src/acd/openhands/tools/definitions.py`）の
回帰確認であり、実設計の合格Evidenceではない。

## 3. 会話駆動loopの単体検証

`tests/openhands/distribution/test_vibebb_command.py`と`tests/pipeline/test_design_loop.py`の
個別実行は43 passed（8.25s）である。`/acd:vibebb-loop`が呼ぶ`run_design_loop`の固定順序と
fail-closed契約がテストレベルで担保されていることを確認した。

## 4. loop実行の実測（host provisional）

`scripts/run_design_loop.py`をGD1 fixtureへ適用し、段の順序と停止点を実測した。

| 実行 | 結果 | 停止段と理由 |
|---|---|---|
| order入力なし | fail-closed | `input`: `order-total document is required when aggregation is disabled` |
| aggregation mode、`--max-passes`既定 | fail-closed | `board-pipeline`: `router convergence_state='not_converged'`。`requirement-entry-validation`と`silkscreen-resolve`は通過 |
| aggregation mode、`--max-passes 99999` | fail-closed | `order-total-aggregation`: `order scope target revision does not match`。要件入口検査、silkscreen、基板、筐体、FWの各段はok |

段の順序は宣言どおり（要件入口整合検査 → silkscreen barrier → 基板／筐体／FW lane →
order-total集計 → 発注可否）であり、失敗段以降は実行されずfail-closedで停止した。FW laneは
ESP-IDF v6.0.2ビルドとQEMU 9.2.2実行まで到達し、`measurement_conditions`へ
`virtual verification only, not real-device evidence`を明記していた。

実測で判明した運用上の注意は次の2点である。ゲートは緩めずそのまま記録する。

1. `scripts/run_design_loop.py`の`--max-passes`既定値3がrouter pass budgetへ渡る。
   `scripts/run_gd1_pipeline.py`の同名引数の既定は99999であり、GD1はloop既定値では
   `not_converged`でfail-closedになる（envelopeの`measurement_conditions`は
   `headless; max 3 passes; max 1 router threads`）。ゲートの誤りではなく既定値の差であり、
   loop経路から発注可否へ到達させる場合はrouter pass budgetを明示する必要がある。
2. order-total集計へ渡せる現行revision向けquote recordが存在しない。
   `fixtures/contracts/valid/order-scope.json`は`target_revision`が`r12`、GD1 graphは`r1`で
   あるため契約不一致でfail-closedになる。実revisionのquote recordはsupplier接続なしには
   得られない（M-3）。ダミーquoteは作成していない。

## 5. GD1 pipelineのhost実行（provisional）

`scripts/run_in_workspace.py --local-provisional`経由の実行結果である。

| 実行 | 結果 |
|---|---|
| `scripts/resolve_gd1_silkscreen.py` | `status: resolved`（silkscreen `measured_pass`） |
| `scripts/run_gd1_pipeline.py` | exit=0、`evidence-electrical.json`が`status=valid`、routing wire 188 / via 24 |
| `scripts/run_gd1_enclosure_pipeline.py` | exit=0、`evidence-mechanical.json`が`status=valid`、干渉0.0mm³ / 最小クリアランス1.0mm / 最小肉厚2.0mm |

host実行はprovisionalであり合格側Evidenceにならない。これは文書上の宣言だけでなく実測でも
確認した。host Evidenceを`scripts/verify_authoritative_evidence.py`へ渡すと
`execution_context='host'`でFAILし、exit=1になる。筐体loop出力にも`authoritative: false`と
`provisional: true`が付与されていた。

## 6. authoritative検証（digest固定container）

| 手順 | 結果 |
|---|---|
| `scripts/print_locked_image.py --entry acd-server` | `ghcr.io/uist1idrju3i/acd-server@sha256:e7fb789c673a65d5fb91ad650f308415d90aa2921a3acaa7f3541f710645a175` |
| `docker pull` | 成功（2m49s、匿名pull可） |
| `scripts/run_in_workspace.py --image "$SERVER_REF"`でsilkscreen resolver、GD1基板、GD1筐体 | exit=0 |
| `scripts/verify_authoritative_evidence.py --revision-from fixtures/golden-design-1/graph.json` | `OK: 2 authoritative Evidence file(s) verified`（exit=0） |

生成Evidenceは`target_revision: r1`、`status: valid`、`execution_context: container`、
`container_image_digest: sha256:e7fb789c…45a175`を持ち、`docker/image-digests.json`のlockと
一致した。authoritative Evidenceの生成経路はacd-agent単体（Docker + GHCR匿名pull）で成立する。

## 7. M節の各項目とDevin環境での検証可能性

| # | 不足機能 | Devin環境での結果 | 区分 |
|---|---|---|---|
| M-1 | 筐体却下後の候補探索がloopへ自動連結されていない | 未連結であることをコードとCLI引数の両面で確認した。`run_design_loop`の探索連結入口は`explore_board`だけであり、`explore_enclosure_candidates`は`acd_explore_enclosure_candidates` toolとして存在するがloopからは呼ばれない。今回の筐体laneは合格したため却下経路は発火していない | 不足の存在は検証できた（却下時の自動再探索は対象なしで未発火） |
| M-2 | 任意graph向けの設計固有検証laneが無い | `src/acd/pipeline/lane_plan.py`のpytest subsetが`artifact_prefix == "gd1"`限定である点を確認した。GD1以外の設計には検証laneが宣言されない | 不足の存在は検証できた |
| M-3 | 見積取得と実発注のsupplier接続 | loopは`order-total-aggregation`で契約不一致によりfail-closedし、発注可否判定へ到達しない。`scripts/fetch_quote.py`と`scripts/order_execution.py`はprovider境界で停止し、実価格・在庫・納期・実装可否は外部APIとcredentialなしに取得できない。実発注は実行していない | 構造上、実装だけでは閉じない（未検証・fail-closed） |
| M-4 | 電池の充電・保護回路とEMC/ESDの設計述語 | `PREDICATE_CATALOG`は6件（`usb_cc`、`i2c_pullup`、`strapping_pin`、`pin_firmware_alignment`、`power_decoupling`、`power_boundary`）で、該当述語を持たない。判定対象自体が存在しない | 不足の存在は検証できた（機能は未実装） |
| M-5 | 実機FW検証 | FW laneはESP-IDFビルドとQEMU実行まで到達し、virtual実行である旨を明記する。実機書き込み後のEvidenceは実機が無いため取得できない | virtual（provisional）のみ／実機は検証不能 |
| M-6 | 自然文から宣言への変換責務（境界） | `compile_requirement_change`と`build_design_fixture`が構造化宣言を要求し、宣言不足が入口でfail-closedになることを実測した。自然文→宣言の変換はL2のAgentDefinitionが担うため決定論的実行では検証対象外 | 境界の維持は検証できた／L2会話部分は未検証 |

Devin環境で実行して確認できた下位機能は、要件入口整合検査、silkscreen barrier、
基板pipeline（ERC／DRC／routing／silkscreen／DFM）、筐体pipeline（CAD kernel、干渉、
クリアランス、肉厚、normalized hash）、FW pipeline（pin整合、ESP-IDFビルド、QEMU実行）、
lane並列（`--jobs 3`）、段順序のfail-closed、authoritative Evidence生成と決定論的検査である。

## 8. 結論

1. 宣言（`RequirementDocument`／`DesignFixtureSpec`）を入力とした要件record化とgraph検証から、
   silkscreen barrier、基板・筐体・FW laneの決定論的ゲート実行、lane並列、固定順序の
   fail-closed、digest固定container内のauthoritative Evidence生成とその検査までは、
   GD1の範囲でacd-agent単体として実際に成立した。
2. 実見積取得と実発注（M-3）は単体では成立しない。provider境界で停止し、外部supplier APIと
   credentialに依存する。今回は発注可否判定へ到達せず、これは「問題なし」ではなく
   未検証（fail-closed）である。
3. authoritative Evidenceはdigest固定containerが正であり、host実行だけでは成立しない。
   host Evidenceは`execution_context='host'`で明示的に落ちることを実測した。
4. 実機FW（M-5）とL2会話段（M-6）はDevin環境では検証できない。virtual結果を実機合格へ
   昇格させる経路は存在せず、区別は保たれていた。
5. acd-agent内で閉じる残存不足はM-1とM-2である。
