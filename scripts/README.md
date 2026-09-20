# scripts/ 索引

`scripts/`はCLI入口とそのテスト可能なhelperを置く。各scriptは1つの分類に属し、
分類漏れは`scripts/tests/test_scripts_inventory.py`がfail-closedで検出する。
物理的なサブディレクトリ分割は行わない。SKILL.md、ToolDefinition、CI、
package contract（sha256）が`scripts/<name>.py`を直接参照しており、
移動はそれらの参照と契約を同じ変更で更新する別PRを要するためである。

検証段階の正は[`verify_all.py`](verify_all.py)（`--list`で列挙）である。
Skill固有のscriptは`plugins/acd/skills/<skill>/scripts/`に置き、
ACD本体・`scripts/`からimportしない（`verify_import_boundaries.py`で検査）。

## 検証（repository verification）

lint、契約drift、文書、生成物の決定論的検査。L3報告であり合格権限を持たない。

| script | 概要 |
| --- | --- |
| `verify_all.py` | 検証段階（docs／fast／standard／full）の正 |
| `verify_acd_tool_registration.py` | ToolDefinition登録manifestの生成・照合 |
| `verify_agent_prompts.py` | AgentDefinition promptのmanifest照合 |
| `verify_agent_settings.py` | agent設定・profile・credential manifestの照合 |
| `verify_authoritative_evidence.py` | Evidenceがauthoritative passを支持するか検査 |
| `verify_context_view.py` | EventLogからのcontext view再生照合 |
| `verify_dockerfiles.py` | Dockerfile構文検査 |
| `verify_docs.py` | Markdownリンク・anchor・文書契約検査 |
| `verify_gd1_references.py` | GD1参照のinventory drift検出 |
| `verify_image_digest_lock.py` | GHCR digest lockの照合 |
| `verify_import_boundaries.py` | core／Skill／hooks間のimport境界検査 |
| `verify_library_assets.py` | 宣言library assetの照合 |
| `verify_manufacturing_submission.py` | 製造提出verdictの独立L1再検査 |
| `verify_model_policy.py` | model routing policyの生成・照合 |
| `verify_ruff_ratchet.py` | Ruff complexity ratchet |
| `verify_sdk_capabilities.py` | SDK capability catalogの生成・照合 |
| `verify_skill_metadata.py` | Skill scriptのPEP 723 metadata検査 |
| `verify_skill_package_ref.py` | pinned ACD package contractの照合 |
| `verify_text_encoding.py` | text I/Oの`encoding="utf-8"`明示検査 |
| `verify_visual_review.py` | visual review manifestとvision観測の照合 |
| `validate_graph.py` | graph検証の正規入口 |
| `ci_changed_scope.py` | CI fast pathのscope分類 |
| `check_dependency_updates.py` | 依存更新候補の確認（非変更） |
| `probe_tools.py` | 外部ツールcapability probe |
| `probe_pinned_acd_graph.py` | pinned ACD packageでのfixture検証とFW Skill実行 |

## 決定論的ゲート（deterministic gates）

設計入力・Evidenceに対するL1／opt-in gateのCLI。

| script | 概要 |
| --- | --- |
| `check_bom_compliance.py` | BOM compliance宣言の要約 |
| `check_defect_record.py` | defect record horizontal-scope gate |
| `check_dft_coverage.py` | DFT coverage gate |
| `check_eco.py` | ECO close gate |
| `check_emc_esd.py` | EMC/ESD設計述語 |
| `check_fw_security.py` | firmware security build consistency gate |
| `check_harness.py` | wire-harness gate |
| `check_mechanical_dfm.py` | mechanical DFM gate |
| `check_mechanism_rules.py` | enclosure mechanism design rules |
| `check_motion_sweep.py` | mechanism motion-sweep gate |
| `check_part_lifecycle.py` | part lifecycle／second-source gate |
| `check_rationale.py` | design rationale文書のgraph照合 |
| `check_reliability_test_plan.py` | reliability-test mapping gate |
| `check_responsibility_assignment.py` | responsibility-assignment gate |
| `check_salvageability.py` | workaround salvageability gate |
| `check_visual_quality.py` | SVG projectionの可読性検査 |
| `check_workaround_retirement.py` | workaround retirement判定 |
| `pre_order_gate.py` | 発注前gate（発注は行わない） |

## pipeline実行と探索（pipeline runs and exploration）

fixture構築、lane実行、候補探索、投影の導出。

| script | 概要 |
| --- | --- |
| `build_design_fixture.py` | JSON仕様からの任意design fixture構築 |
| `build_gd1_fixture.py` | GD1 fixture builder |
| `make_component_3d_fixture.py` | 合成component STEP fixture |
| `pin_library_hashes.py` | fixture specへのsymbol／footprint sha256固定 |
| `select_kicad_3d_models.py` | PCB参照KiCad 3D modelの選択 |
| `resolve_gd1_silkscreen.py` | GD1 silkscreen配置の反復解決 |
| `run_gd1_pipeline.py` | GD1基板pipeline |
| `run_enclosure_pipeline.py` | 筐体（mechanical lane）pipeline |
| `run_firmware_lane.py` | 仮想firmware lane |
| `run_design_lanes.py` | silkscreen解決後の独立lane実行 |
| `run_design_loop.py` | graph駆動VibeBB design loop |
| `run_acd_goal.py` | bounded ACD goal loop（合格側はL1 gateのまま） |
| `run_component_3d.py` | 基板／部品／筐体3D統合 |
| `run_in_workspace.py` | OpenHands Docker workspaceでの決定論的実行 |
| `explore_board_candidates.py` | 配置／GPIO候補探索 |
| `explore_enclosure_candidates.py` | 筐体干渉候補探索 |
| `derive_rework_graph.py` | rework差分からのL3 graph投影 |
| `derive_visual_review_pngs.py` | visual review PNGとmanifestの導出 |
| `project_harness.py` | harnessのL3 artifact投影 |
| `collect_lane_artifacts.py` | 最小lane artifact集合の収集 |

## 推定・解析（opt-in estimates）

Evidenceへ昇格しないL3推定。

| script | 概要 |
| --- | --- |
| `analyze_pdn.py` | PDN／IR drop推定 |
| `estimate_bom_cost.py` | BOM cost推定 |
| `estimate_thermal.py` | 簡易熱推定 |
| `run_fem.py` | CalculiX FEM推定 |
| `run_spice_analysis.py` | graph由来SPICE推定 |
| `run_wca.py` | worst-case analysis推定 |

## 取込・登録・入力feedback（ingestion and registration）

外部観測・宣言の取込と、設計入力への境界付き反映。

| script | 概要 |
| --- | --- |
| `ingest_functional_run.py` | firmware functional-run記録の取込・評価 |
| `ingest_hil_run.py` | HIL runのPhysicalEvidence化 |
| `ingest_receipt.py` | 製造receiptと出荷manifestの照合 |
| `fetch_lcsc_footprint_orientation.py` | LCSC/EasyEDA footprint応答のEvidence化 |
| `record_visual_vision_observation.py` | vision応答のL3観測記録 |
| `register_firmware_capability.py` | firmware capability宣言の登録 |
| `register_functional_block.py` | functional-block契約の登録 |
| `register_part_catalog_entry.py` | parts-catalog entryの登録 |
| `propose_input_feedback.py` | physical Evidenceからの非変更proposal |
| `apply_input_feedback.py` | 境界付きpolicyでのproposal適用 |
| `compile_requirement_change.py` | 要求変更の結合入力変更へのcompile |

## 発注（ordering）

実provider送信は無効。dry-runとjournal再構成のみ。

| script | 概要 |
| --- | --- |
| `derive_order_scope.py` | order-scopeとquote request宣言の導出 |
| `fetch_quote.py` | provider境界経由のquote取得 |
| `aggregate_order_total.py` | quote記録のorder-total集約 |
| `order_execution.py` | fail-closed order dry-run |
| `side_effect_journal.py` | side-effect journalからのorder再構成 |

## 構想対話（idea dialogue）

| script | 概要 |
| --- | --- |
| `idea_estimate.py` | idea recordのL3概算 |
| `idea_next_questions.py` | 次の優先質問（L3） |
| `idea_progress.py` | idea進捗観測（L3） |
| `idea_record_turn.py` | 対話turnの適用 |
| `promote_idea.py` | 確認済みideaの要求recordへの昇格 |

## 運用・報告（operations and reporting）

image lock、資源測定、記録の公開、進捗報告。

| script | 概要 |
| --- | --- |
| `print_locked_image.py` | digest固定image参照の出力 |
| `pull_locked_image.py` | digest固定imageのpull |
| `update_image_digest_lock.py` | image digest lockの更新 |
| `update_skill_package_ref.py` | pinned ACD package refの更新 |
| `measure_image_tools.py` | container imageのtool版測定 |
| `measure_lane_resources.py` | lane実行中の資源sampling |
| `export_execution_records.py` | 実行記録の公開最小集合export |
| `report_final_basis.py` | 最終報告の事実節basis |
| `report_progress.py` | runのL3進捗digest |
