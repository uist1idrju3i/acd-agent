# VibeBB単体成立性の検証記録（2026-08-24 Devin環境／2026-08-30 多コアVPS）

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.44.1

本書は、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のM節（M-1〜M-6）が示す
「acd-agent単体でVibeBBが成立するか」を、汎用エージェント環境（Devin）で実行可能な範囲まで
実際に走らせて確認した記録である。既存の閾値、ゲート挙動、fail-closed境界、L1権限、dry-run既定は
変更していない。ツール不在や検証不能は「問題なし」ではなく「fail-closed／未検証」として記録する。

第1回（1〜8節）は2026-08-24のDevin環境での記録、9節は2026-08-30の多コアVPSと
実機OpenHandsでの記録である。

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
2. order-total集計へ渡せる現行revision向けquote recordが存在しなかった。
   `fixtures/contracts/valid/order-scope.json`は`target_revision`が`r12`、GD1 graphは`r1`で
   あるため契約不一致でfail-closedになった。この記録を受け、GD1向けの`r1`整合fixtureを
   追加し、例示commandと回帰testを更新した。contract schema向けの既存`r12` fixtureは変更せず、
   対象graphと異なるrevisionの入力をfail-closedする検査も維持している。

## 5. GD1 pipelineのhost実行（provisional）

`scripts/run_in_workspace.py --local-provisional`経由の実行結果である。

| 実行 | 結果 |
|---|---|
| `scripts/resolve_gd1_silkscreen.py` | `status: resolved`（silkscreen `measured_pass`） |
| `scripts/run_gd1_pipeline.py` | exit=0、`evidence-electrical.json`が`status=valid`、routing wire 188 / via 24 |
| `scripts/run_enclosure_pipeline.py` | exit=0、`evidence-mechanical.json`が`status=valid`、干渉0.0mm³ / 最小クリアランス1.0mm / 最小肉厚2.0mm |

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

## 9. 第2回検証（2026-08-30, 多コアVPS + 実機OpenHands）

第1回はDevin環境（2 vCPU）でのscript実行が中心で、OpenHandsのGUI会話経路と多コア環境での
資源特性が未検証だった。第2回は検証用VPSと利用者のOpenHands常駐サーバを使い、
GUI会話からの経路と資源消費を実測した。

- 対象revision: plugin installed store `63a567d`（remote mainと一致、`plugins/acd`、plugin版0.0.2）
- 実行環境: Ubuntu 26.04、x86_64、CPU 8コア、MemTotal 15.0 GiB（swap 22 GiB）、Docker 29.1.3
- OpenHands: host常駐process（ingress `*:8000`、SSH tunnel経由でLocal GUIへ到達）、
  workspace `test260830`（`/home/openhands/repos/test260830`、初期状態は空のgit repository）
- 資源計測: 1秒間隔でホスト`/proc`、OpenHands常駐process群、ACD host process群、
  Docker cgroupを記録。計測経路はauthoritative Evidenceを生成しない観測（L3）である。

### 9.1 決定論的laneの再現（authoritative）

VPS上の独立checkoutで、digest固定server imageを`scripts/run_in_workspace.py`
（`DockerWorkspace`）経由で実行した。silkscreen resolver、GD1基板pipeline、GD1筐体pipelineは
container上限8 GiB／`--jobs 4`でexit=0となり、
`scripts/verify_authoritative_evidence.py`は`OK: 2 authoritative Evidence file(s) verified`
（exit=0）を返した。生成Evidenceは`execution_context: container`、`status: valid`、
revision一致であり、第1回（2 vCPU）と同じ判定である。

FW laneはESP-IDFビルドとQEMU仮想実行まで到達したが、`out/container/`にFWの
authoritative Evidence JSONは生成されない。実機書き込みとLED実測は実施していない（M-5）。
見積取得・決済・実発注は実行していない（M-3）。

### 9.2 資源消費と最低・推奨スペック

実測値と条件別の表は[`operations.md`](operations.md)の
「多コアVPSでの資源実測と推奨スペック（2026-08-30）」に記録した。要点は次のとおりである。

1. 8 GiB／`--jobs 4`ではホストCPU peak 7.98コア（平均2.5コア）、ホストmem used peak
   4.18 GiB、Docker `memory.peak` 5.36 GiB、swap使用0で、wallは220〜225秒だった。
2. `--jobs 1`は304秒、`--jobs 4`は220〜225秒で約27%短縮する。CPUは4コアでほぼ飽和し
   （250秒）、2コアでも321秒で完走する。
3. container上限4 GiBはGD1では完走するが`memory.current`が上限へ張り付く。2 GiBは
   `runtime.jvm_heap.exceeds_container_limit`でlane実行前にfail-closedする（OOMではない）。
4. 推奨は4コア以上／物理RAM 12 GiB以上（OpenHands同居なら16 GiB）／container上限8 GiB／
   `--jobs 4`とする。GD1で完走を確認した下限は2コア／container 4 GiBであり、他設計での
   完走は保証しない。

### 9.3 GUI会話からの経路（L2、観測のみ）

workspace `test260830`のLocal GUIで`/acd:init`と`/acd:vibebb-loop`を会話から実行した。

| 手順 | 結果 |
|---|---|
| plugin活性化 | installed store `acd` 0.0.2（`github:uist1idrju3i/acd-agent`）がrevision `63a567d`で解決済み。GUIのSkill一覧にACD Skillsが表示された |
| `/acd:init --repo-url … --revision 63a567d… --workspace acd-workspace` | clone、submodule、plugin検査はpass。doctor段でfail-closedし`bootstrap-record.json`は生成されない（9.4の欠陥） |
| `/acd:vibebb-loop`（GD1のコピーでない新規設計を自然文要件から生成） | fixture（`spec.json`／`requirements.json`／`graph.json`／`rationale.json`／library）を生成し、要件入口整合検査pass、silkscreen-resolve pass（2.95秒、iteration 2回）、基板pipelineのpre-router述語段で停止 |

新規設計（`vibebb-sensor-node`: USB-C bus power、3.3V LDO、ESP32-C3-MINI-1、SHT40、状態LED、
2層40×30mm）でGD1以外のgraphが固定順序loopへ入り、silkscreen barrierまで通過することを
実測できた。停止はゲートの正常動作であり、内訳は次の2点である。

1. `power_decoupling`が`C4`とU1のpad距離15.838 mm（上限3.0 mm）で不合格。remediationは
   `component_placement_xy`の変更を提示した。`power_boundary`は安全境界nodeが未特定のため
   `unknown`であり、fail-closedとして扱われた。
2. rationale coverageが`fail`（`required_count` 318 / `covered_count` 302）。`comp.c3`の
   `footprint`・`mpn`・`lcsc`・`assembly`・`placement_rotation_deg`が`missing`かつ既存
   rationaleが`stale`である。

GUIの進行表示、L2 agentの説明、Skill出力はいずれも観測であり、合格側Evidenceではない。
本節の判定は生成ファイル（`out/vibebb-sensor-node/**`のtiming record、gate evidence、
rationale coverage）を直接読んで確認した内容に限る。会話1回で新規設計をVibeBB loopの
末端（発注可否）まで通すことは今回到達していない。

### 9.4 欠陥（install doctorのESP-IDF判定）

`/acd:init`のdoctor段が、lock済みserver image内で
`missing: IDF_PATH/export.sh`を報告してfail-closedした。digest固定imageを直接調べると
`IDF_PATH=/opt/esp-idf`、`/opt/esp-idf/export.sh`は存在し（`-rw-r--r--`）、sourceすると
`idf.py`が解決できる。原因は`install_doctor.py`のprobeが`test -x`で実行ビットを要求して
いたことであり、実際の利用側はすべて`.`（source）で読むだけである。現行の公開imageでは
`/acd:init`が常にdoctor段で停止する偽陰性であった。

判定を「読み取り可能な通常ファイル」（`test -f` かつ `test -r`、container判定は
`Path.is_file()` かつ `os.access(..., R_OK)`）へ統一し、実行ビットのないreadableな
`export.sh`を`pass`とする回帰テストを追加した。fail-closed境界と閾値は緩めていない。

### 9.5 気づきと改善提案

1. doctor判定は「ツールをどう使うか」と一致させる。sourceする資材へ`test -x`を課すと
   image側の権限変更で偽陰性になる。他のprobeにも同種の前提がないか点検する余地がある。
2. 新規設計の1周目は、部品配置（`power_decoupling`）とrationale coverageで止まりやすい。
   `build_design_fixture`が生成する初期配置はdecoupling距離制約を考慮しないため、
   loopが配置修正へ収束する前提の反復回数が増える。初期配置生成時にdecoupling距離を
   満たす配置制約を入れる、または不足rationaleを`missing`一覧として先に提示する改善が有効である。
3. FW laneはQEMU実行終了時に`terminating on signal 15 from pid … (timeout)`をログへ残すが、
   pipelineはbuild・QEMU仮想実行・log検査をpassとしてexit=0で終える。これは想定した
   時間打ち切りであり外側commandのtimeoutではないが、ログだけを見ると失敗と誤読しやすい。
   意図的な打ち切りである旨をログへ明示する改善が有効である。
4. FW laneのauthoritative Evidence JSONが`out/container/`へ生成されないため、
   基板・筐体と同じ決定論的検査（`verify_authoritative_evidence.py`）の対象にできない。
5. 資源preflightの停止理由は`--jvm-max-heap`とcontainer上限の関係に依存する。4 GiB以下で
   運用する場合は`--jvm-max-heap`の同時引き下げが必要である旨が、CLIの停止メッセージから
   一段で分かるようになっている（今回の2 GiB試験で確認した）。

### 9.6 修正後pluginでの`/acd:init`再検証（実機VPS）

9.4の修正がmergeされた後、実機VPSのinstalled plugin storeを正規のinstall経路
（agent-serverの`POST /api/plugins/install`、`force=true`）でmain先端
`5a553d3ffc19995a4a62465255dc5b55e9eb2ce6`へ更新し（更新前`63a567d…`、`git ls-remote origin main`と
40桁一致）、GUIのworkspace `test260830`から`/acd:init`を実行した。既存成果物を保護するため
`--workspace acd-workspace-verify`で分離した。

| 確認項目 | 結果 |
|---|---|
| hook | `SessionStart ok` / `PreToolUse (terminal) ok` / `Stop ok`（blockedなし） |
| `/acd:init` | `ok: true`、`fail_closed: false`、`failed_step: null`。`workspace_dir`／`repository`／`submodules`／`plugin_load`／`doctor`／`bootstrap_record`がpass |
| doctor `workspace firmware prerequisites` | `pass`。`IDF_PATH/export.sh=present, qemu-system-riscv32=9.2.2, cmake=4.2.3`（server image `sha256:52042766…`） |
| `bootstrap-record.json` | 生成。`requested_revision`＝`resolved_revision`＝`5a553d3f…`、`lock_digest`＝`sha256:582af334…`、`pass_evidence: false`、`record_class: "L3"` |
| 対照 | 同imageの`/opt/esp-idf/export.sh`は`-rw-r--r--`で、旧判定`test -x`は`missing`、新判定`test -f`かつ`test -r`は`present` |

`bootstrap-record.json`はhost側でread-onlyに直読して確認しており、GUI表示に依存しない。
本recordはL3であり合否権限を持たない。

### 9.7 `--explore-board`による復帰の実測（探索なし／あり）

「pre-router段で止まったときにOpenHands自身の力で復帰できるか」を確かめるため、
新規設計`vibebb-sensor-node`のfixtureをdigest固定server image
（`sha256:52042766…`）内で`--design-only --jobs 4 --memory-limit 8g`で2回実行した。
Run Aは探索なし、Run Bは`--explore-board --max-exploration-candidates 3
--max-exploration-rounds 2`を明示した。

| 項目 | Run A（探索なし） | Run B（探索あり） |
|---|---|---|
| rc | 1 | 1 |
| wall-clock | 48.9秒 | 54.9秒 |
| `failed_stage` | `board-pipeline` | `board-pipeline` |
| 停止理由 | rationale coverage失敗（`missing=12, stale=12`） | 同左＋`board exploration failed: exploration did not produce a writable candidate: status='stopped'` |
| 探索round | なし | 1（`status: stopped`、`termination_reason: fail_closed_stop`） |
| `evaluated_candidates` | — | 1 |
| `winner_candidate_id` | — | なし（`winner_written: false`） |
| `diagnostic_dimensions` | — | `[]` |
| `command-timeout 5400` | 未到達 | 未到達 |

両runで筐体laneは`mechanical preflight failed:
rationale.coverage.missing=12, rationale.coverage.stale=12`で拒否され、FW laneは
`firmware action 'read_sensor' is not registered in
contracts/firmware-capability-registry.json`で停止した。

要点は次の3つである。

1. `--explore-board`を明示すると基板laneのfail-closed却下後に探索段が起動する。
   これは9.3のGUI実行では起動していなかった経路である。
2. しかし探索は候補1件を評価しただけで`stopped`となり、書き込み可能な候補を生成せず、
   基板laneは復帰しなかった。`diagnostic_dimensions`が空であり、却下predicateの
   remediationが探索の入力になっていないことと整合する。
3. 今回のfixture状態では基板laneがrationale coverage不足で止まるため、
   `power_decoupling`（9.3）より前段で停止する。すなわち復帰に必要なのは配置候補だけでなく、
   rationaleとgraphを同一transactionで整合させる経路である。

探索が候補を書き込む前に停止したため、「配置書き換え後のrerunがrationale staleで止まる」
という連鎖は実機では未確認である。この連鎖自体は、GD1 fixtureで`placement_x_mm`を0.5 mm
動かすと`check_rationale_coverage`が`fail`（stale: `comp.u1`の`placement_x_mm`／
`placement_y_mm`／`placement_rotation_deg`）になることをローカルで確認している。
Run A／Bはいずれもhost資源reportを指定しておらず、本節に資源実測値は含まない。

## 10. 第3回検証（2026-08-31, 14.15実装後の復帰経路）

14.15（PR #281）で追加された復帰経路を、同じ8コア／16 GiB VPS上の実機OpenHandsと
digest固定container（`ghcr.io/uist1idrju3i/acd-server@sha256:040ff332…`、
`origin/main` = `dca3890…`）で実測した。pluginは正規のinstall API（`force=true`）で
`5a553d3f…`から`dca3890…`へ更新し、`git ls-remote origin main`と40桁一致を確認した。
OpenHandsのworkspaceは新規に`test260831/acd-ws-260831`を作成し、`/acd:init`は
`ok: true`、`bootstrap-record.json`（`resolved_revision` = `dca3890…`、
`server_image_digest` = `sha256:040ff332…`、`record_class: "L3"`）を生成した。

### 10.1 新規fixtureはfixture-generation段で停止する（Run A）

会話由来の新規設計spec（`examples/mini-blink-dongle-20260825/fixture/spec.json`）から
`--design-only --jobs 4 --memory-limit 8g`で生成を試みた結果、`loop_rc=1`、
`failed_stage=fixture-generation`、`fail_closed=true`で停止した。

```text
FixtureBuilderError: decoupling placement could not be resolved:
pinned library file missing: /workspace/acd/libraries/Espressif.pretty/ESP32-C3-MINI-1.kicad_mod
```

原因は部品catalogのESP32-C3-MINI-1がlibrary資材をfixture相対path
（`libraries/Espressif.kicad_sym`／`libraries/Espressif.pretty/...`）で宣言する一方、
`build_design_fixture`が生成する新規fixture配下へ当該資材が置かれず、
`resolve_fixture_path()`はfixture dirとrepository rootだけを探索するためである。
当時の資材は`examples/mini-blink-dongle-20260825/fixture/libraries/`と
`fixtures/golden-design-1/libraries/`にしか存在せず、repository root直下に`libraries/`が無かった
（14.17で資材をcanonical store `libraries/`へ移し、解決を
`resolve_fixture_library_path()`へ統一した）。
GD1は同じ資材を絶対path（`/usr/share/kicad/...`）で宣言するため、この停止はGD1では露出しない。
14.15で追加した初期配置のdecoupling解決（P-2）は`decoupling_target`宣言のあるfixtureで
必ず実行されるため、Espressif資材を参照する新規設計は現状かならずここで止まる（S-4）。

| 項目 | 値 |
|---|---|
| `loop_rc` | 1 |
| wall-clock | 49秒 |
| `failed_stage` | `fixture-generation` |
| 到達lane | なし（silkscreen・基板・筐体・FWいずれも未実行） |
| host CPU peak / mean | 4.64 / 1.46 cores |
| host RAM peak | 3.16 GiB |
| container cgroup peak | 3.12 GiB |
| swap | 0 GiB |

### 10.2 復帰経路の実測（Run B、GD1を摂動した内部整合fixture）

Run Aが基板laneへ到達しないため、GD1（`fixtures/golden-design-1`）から内部整合を保った
劣化fixtureを作って復帰経路を測った。摂動は同一footprint・同一sha256のC4（`decoupling_target: U1`）
とC2（decoupling宣言なし）の`placement_x_mm`／`placement_y_mm`／`placement_rotation_deg`を
入れ替えるだけで、幾何は衝突フリーのまま`power_decoupling`のみが違反する。摂動は
`commit_candidate_graph()`でgraphとrationaleを原子的に確定した（`rationale_records=70`、
`target_revision: r1`）。実行は同じdigest固定container内で次のとおりである。

```text
uv run python scripts/run_design_loop.py --fixture fixtures/verify-runb \
  --out-root out/runB3 --design-only --jobs 4 --recover-lanes \
  --max-exploration-candidates 3 --max-exploration-rounds 2
```

| stage | `ok` |
|---|---|
| `requirement-entry-validation` | true |
| `silkscreen-resolve` | true |
| `board-pipeline` | false（`power_decoupling`: C4距離19.224 mm > 3.0 mm） |
| `enclosure-pipeline` | true |
| `firmware-pipeline` | true |
| `board-exploration` | false（`exploration did not produce a writable candidate: status='stopped'`） |

復帰planの解決は宣言どおり機能した。

| 項目 | 値 |
|---|---|
| `recovery_supported` | true |
| `recovery_explorer` | `board` |
| `recovery_dimensions` | `component_placement_xy`／`component_rotation_deg`／`gpio_assignment` |
| `lane_id` | `board-pipeline` |
| `declaration_hash` | `sha256:9705d366…` |
| `remediation_dimensions` | `["component_placement_xy"]` |
| `report_status` / `termination_reason` | `stopped` / `fail_closed_stop` |
| `max_candidates` / `evaluated_candidates` | 3 / 1 |
| `max_exploration_rounds` / 実行round | 2 / 1 |
| `winner_candidate_id` / `winner_written` | null / false |
| `diagnostic_dimensions` | `[]` |

生成された候補`placement-0001`（`skill_name: acd-placement-search`、
`script_sha256: sha256:be894760…`）はC4とC2の配置を摂動前の位置へ戻す内容であり、
`power_decoupling`を満たす配置に到達していた。にもかかわらず却下されている。

```text
deterministic pipeline rejected candidate: rationale coverage failed:
missing=18, stale=18, orphan=0, conflicting=0, unknown_provenance=0, untraceable=0, unclassified=0
```

すなわち14.15のQ-4（`commit_candidate_graph`によるrationale更新）はwinner確定時にしか
適用されず、候補の評価はrationaleを更新しないまま決定論的pipelineへ渡される。配置を
1点でも動かせば`check_rationale_coverage`はstaleになるため、placement次元の候補は
構造的に必ず`gate_rejected`となり、復帰は成立しない（S-1）。また候補予算3・round上限2を
指定しても、最初の却下で`fail_closed_stop`となり2件目以降は評価されない（S-2）。

graphとrationaleの整合は保たれていた。

| 項目 | 摂動前 | 摂動後（Run B入力） |
|---|---|---|
| `graph_id` | `golden-design-1` | `golden-design-1`（保持） |
| `revision` | `r1` | `r1` |
| canonical graph hash | `sha256:f5818022…` | `sha256:cd971025…`（変化） |
| rationale record数 | 70 | 70 |
| C4 placement recordの`subject_hash` | — | `expected_subject_hash`と一致（`matches: true`） |

`winner_written=false`のためRun B後のgraphは入力と同一であり、L1判定・Evidenceは
変化していない。摂動scriptは検証専用でrepositoryへcommitしていない。

### 10.3 資源実測（復帰経路を含む実行）

| 項目 | Run B（`--recover-lanes`、`--jobs 4`、container上限8 GiB） |
|---|---|
| wall-clock | 147秒 |
| host CPU peak / mean | 7.94 / 2.35 cores |
| host RAM peak | 4.32 GiB（利用可能最小 10.79 GiB） |
| container cgroup peak | 5.05 GiB |
| swap peak | 0 GiB |
| host資源preflight | `pass`（要求上限8 GiB、JVM max heap 2 GiB） |

9.2で定めた最低・推奨スペック（最低2コア・container 4 GiB、推奨4コア以上・物理RAM
12 GiB以上／OpenHands同居16 GiB・container上限8 GiB・`--jobs 4`）はそのまま成立する。
探索段を含めても上限8 GiBに対しピークは5.05 GiBで収まり、swapは発生しない。一方で
CPUは`--jobs 4`でもピークが7.94 coresに達しており、4コア機ではwall-clockが伸びる。

### 10.4 GUI会話からの経路（L2、観測のみ）

新規workspaceの会話へ、新規設計（USB-C給電のESP32-C3＋SHT40、status LED 1個、筐体とFW込み）で
`/acd:vibebb-loop`を実行し、却下時は`/acd:vibebb-recover`で`recover_lanes`・候補上限3・
round上限2を使うよう指示した。plugin hookは正常（`SessionStart`／`PreToolUse`ともblockedなし）で、
command自体は解決される。しかし会話のtool setは次の5つだけであり、`acd_*`の
ToolDefinitionは登録されていない（`base_state.json`の`agent.tools`を直読）。

```text
terminal, file_editor, task_tracker, canvas_ui_control, launch_child_conversation
```

`plugins/acd/commands/vibebb-loop.md`が`allowed-tools`として宣言する
`acd_build_design_fixture`、`acd_run_design_loop`、`acd_diagnose_gate_failure`、
`acd_explore_board_candidates`、`acd_check_order_readiness`などは、この配布形態
（agent-server＋agent-canvas、ADR-0036のambient install経路）では存在しない。
`register_acd_tools()`は`build_acd_conversation()`経路にしかないため、GUI会話は
commandを読んでも宣言された入口を呼べない（S-3）。

結果としてagentはterminalで代替を試み、既存exampleのgraph・spec・source codeを
読み解いて生JSONのfixtureを手組みし、`scripts/run_design_loop.py`をhostから直接
実行する行動へ移った。620 event・約2時間の時点でVibeBBは完走せず、host実行の結果は
provisionalであり合格側Evidenceにならない。会話経路で「acd-agent単体でVibeBBが成立する」
状態にはなっていない。

### 10.5 気づきと改善提案

1. 復帰が成立しない実体は「候補生成」ではなく「候補評価の順序」である。候補評価の前に
   winner確定と同じrationale更新（`refresh_rationale_document`）を適用しないかぎり、
   placement次元の候補は必ずrationale staleで却下される。閾値は緩めず、評価入力の整合を
   確定経路と一致させるのが正しい解である。
2. 候補上限とround上限が実効になっていない。最初の却下で停止するため、`--max-exploration-candidates 3`
   は利用者から見て「3回試す」と読めるのに1件しか試されない。fail-closedは維持したまま、
   却下理由が候補固有である場合は残予算で次候補へ進む挙動と、`evaluated_candidates`／
   `remaining_budget`の明示が必要である。
3. GUIでは失敗が「どのlaneのどの述語で、何mm超過し、次に何をすべきか」まで一段で
   読めない。`failure_reason`にはremediationとevidence pathが入っているのに、
   会話側にはtoolが無いため到達しない。GUI経路にACD tool入口を登録する配布形態
   （またはcommandが呼ぶCLIをcontainer実行に固定するwrapper）が要る。
4. 新規設計のlibrary資材の扱いが宣言と生成で食い違っている。catalog entryがfixture相対pathを
   宣言するなら、`build_design_fixture`が資材を同梱するか、catalogがcontainer内の絶対pathを
   宣言するかのどちらかへ寄せる必要がある。現状は新規設計が最初のstageで必ず止まる。
5. 長時間stageの進行が見えない。基板laneは147秒中の大半を占めるが、GUI側には残り時間・
   試行回数・現在のlaneが出ない。L3 timing recordは生成されているので、これを会話へ
   返す表示があると待ちの体験が大きく変わる。

## 11. 第4回検証（2026-08-31, 14.17実装後の復帰経路）

14.17（S-1〜S-5）の実装後、同じ8コア／16 GiB VPSで再実測した。pluginは正規のinstall API
（`force=true`）で`dca3890…`から`fb286380e1912033198a9430cc4c273b3c7c99e7`へ更新し、
`git ls-remote origin refs/heads/main`と40桁一致を確認した。server imageはlock済みの
`ghcr.io/uist1idrju3i/acd-server@sha256:d683f14b906ae8304c4484b8702145711ce20b63abbf2c9656c381af5b2368ec`
である。OpenHandsのworkspaceは新規に`test260901/acd-ws-260901`を作成した。

### 11.1 新規workspaceと`/acd:init`

`/acd:init --repo-url … --revision main --workspace acd-ws-260901`はdoctorを通過し、
`bootstrap-record.json`を生成した。

| 項目 | 値 |
|---|---|
| `requested_revision` / `resolved_revision` | `main` / `fb286380…` |
| `server_image_digest` | `sha256:d683f14b…` |
| `source` | `mounted` |
| `workspace_path` | `/home/openhands/repos/test260901/acd-ws-260901` |
| `record_class` / `pass_evidence` | `L3` / false |

会話へ登録されたtoolは次の7つで、`acd_*`のToolDefinitionは依然として存在しない
（`SystemPromptEvent`のtool定義を直読）。

```text
terminal, file_editor, task_tracker, finish, think, switch_llm_profile, invoke_skill
```

`/acd:init`が成立したのは、Skillが決定論的CLIをterminalから実行する手順を持つためである。
ambient install経路（ADR-0036）でACD tool入口が登録されない状態は14.17でも未了であり、
command宣言の`allowed-tools`はこの配布形態で満たされない（S-3、T-3）。

### 11.2 復帰経路の実測（Run E）

Run Bと同じ摂動fixture（GD1のC4とC2の配置交換、内部整合を保ち`power_decoupling`のみ違反）を
`fixtures/verify-rune`として生成し、同じdigest固定container内で実行した。

```text
uv run python scripts/run_design_loop.py --fixture fixtures/verify-rune \
  --out-root out/runE --design-only --jobs 4 --recover-lanes \
  --max-exploration-candidates 3 --max-exploration-rounds 2
```

| stage | `ok` |
|---|---|
| `requirement-entry-validation` | true |
| `silkscreen-resolve` | true |
| `board-pipeline` | false（`power_decoupling`: C4距離19.224 mm > 3.0 mm） |
| `enclosure-pipeline` | true |
| `firmware-pipeline` | true（`measurement_class: virtual`、QEMU 9.2.2、15秒上限による正常打ち切り） |
| `board-exploration` | false（`exploration did not produce a writable candidate: status='exhausted'`） |

S-1（候補評価前のrationale更新）は解消を確認できた。候補はrationale coverageで却下されず、
決定論的pipelineの実行まで到達している。しかしその実行が別の理由で失敗する。

| 項目 | 値 |
|---|---|
| `remediation_driven` / `remediation_dimensions` | true / `["component_placement_xy"]` |
| `recovery_explorer` / `lane_id` | `board` / `board-pipeline` |
| `declaration_hash` | `sha256:9705d366…` |
| `generated_candidates` / `evaluated_candidates` / `max_candidates` | 1 / 1 / 3 |
| `consumed_budget` / `remaining_budget` | 1 / 2 |
| `report_status` / `termination_reason` | `exhausted` / `candidate_pool_exhausted` |
| `winner_candidate_id` / `winner_written` | null / false |
| 候補`placement-0001`の`outcome.status` | `gate_rejected` |

却下理由は設計上の判定ではない。

```text
deterministic pipeline rejected candidate: timing stage already started: board[1/12]
```

`TimingRecorder.start()`は同名stageの二重開始をValueErrorにする（`src/acd/core/runtime_records.py`）。
親の基板pipelineはpre-routerで却下されるため`board[1/12]`を`finish`せずに中断し、stage名が
`_started`へ残る。復帰の候補評価は`src/acd/pipeline/design_loop.py`の`pipeline_runner`が
`timing_recorder=config.timing_recorder`として親と同一のrecorderを渡すため、候補側の
`mark_stage(1)`が同じstage名を再開始してValueErrorになる。復帰は基板laneの却下後にしか
起動しないので、この衝突は条件付きではなく常に起きる。したがってplacement次元の復帰は
14.17後も構造的に成立しない（T-1）。候補側のstage記録が親のL3 timing recordへ混入する点、
候補を並列評価した場合も同名衝突が起きる点も同じ原因である。

S-2（予算の実効化）は記録面では解消しており、`max_candidates`・`consumed_budget`・
`remaining_budget`・`termination_reason`がreportへ出る。ただし候補生成が1件しか返さないため
（`generated_candidates=1`）、上限3・round上限2は実行として行使されず、`remaining_budget=2`を
残して`candidate_pool_exhausted`で終わる。予算を実効化するには、remediation次元ごとに
複数候補を列挙する生成側の是正が必要である（T-2）。

Run Eの前に同じ構成で行った実行では、探索の出力先を`out/runD`にしたためgraph由来の既定
download path（`out/gd1/evidence-electrical.json`）が存在せず、download失敗（3回試行後の
transport失敗）で終了した。`_execute_and_download()`は`exit_code == 0`のときだけ
downloadするので、commandが成功扱いで終わると欠落が例外になり、runnerはstdoutを出力する前に
非ゼロ終了する。Evidence欠落をfail-closedに扱うこと自体は正しいが、container内で得られていた
lane結果と探索reportが読めなくなる（T-5）。Run Eでは出力先を明示して回避した。

`winner_written=false`のためRun E後のgraphは入力と同一であり、L1判定とEvidenceは変化していない。
摂動scriptと生成fixtureは検証専用でrepositoryへcommitしていない。

### 11.3 会話へ返る失敗理由と進行（S-5の効果）

loop summaryのlane結果に`failure_reason`と`next_step_action`が入るようになった。

```text
failure_reason: exploration did not produce a writable candidate: status='exhausted'
next_step_action: Explore declared placement and GPIO candidates from the rejected
  predicate remediation, then rerun every deterministic stage.
```

`scripts/report_progress.py --out out/runE --json`は`status: "pass"`でtiming recordと
探索reportをL3 digestとして返し、laneごとの経過と試行が読める。これは待ちの体験に対する
実質的な改善である。いずれもL3観測であり合否権限を持たない（T-4）。

### 11.4 資源実測

| 項目 | Run E（`--recover-lanes`、`--jobs 4`、container上限8 GiB） |
|---|---|
| wall-clock | 125秒 |
| host CPU peak / mean | 7.98 / 2.60 cores |
| host RAM peak | 4.13 GiB（利用可能最小 10.98 GiB） |
| container cgroup peak | 4.23 GiB（現在値ピーク4.01 GiB） |
| swap peak | 0 GiB |
| tool別peak RSS | python 2.92 GiB、cc1 0.76 GiB、uv 0.27 GiB、kicad 0.17 GiB |

9.2で定めた最低・推奨スペック（最低2コア・container 4 GiB、推奨4コア以上・物理RAM
12 GiB以上／OpenHands同居16 GiB・container上限8 GiB・`--jobs 4`）はそのまま成立する。
Run Bの5.05 GiBに対しRun Eは4.23 GiBで、探索段を含めても上限8 GiBに収まりswapは発生しない。
CPUはピーク7.98 coresで、4コア機ではwall-clockが伸びる点も変わらない。

### 11.5 結論（第4回）

acd-agent単体でのVibeBBは未達である。決定論的lane（silkscreen・筐体・FW仮想）は通過し、
基板laneの却下も正しくfail-closedしているが、却下からの復帰は候補評価のtiming stage衝突
（T-1）で必ず失敗するため、`winner_written=true`と復帰後の基板lane再通過は今回も観測できていない。
GUI会話側は`acd_*` tool未登録（T-3）のままで、command宣言の入口へは到達できない。
新規specからのfixture生成（S-4）は本回の実行対象に含めていないため、この回の未検証範囲として残る。

### 11.6 気づきと改善提案

1. 復帰の失敗理由がL3の計測記録に由来している。`TimingRecorder`は観測目的の器であり、
   その衝突で候補が`gate_rejected`になるのは権限境界の観点でも不適切である。候補評価では
   親と独立したrecorderを使い（または候補IDでstage名をnamespaceする）、観測の失敗を
   判定へ持ち込まない構造にすべきである。あわせて、観測起因の例外を`gate_rejected`ではなく
   `stopped`として区別すると、L3の不具合とL1の却下が混ざらない。
2. 候補生成が1件しか返さない限り、予算とround上限は利用者から見て意味を持たない。
   remediation次元ごとに複数候補（距離目標を段階的に変えた配置など）を列挙し、
   `generated_candidates`が上限に届く状態を先に作るのが、予算の実効化より先である。
3. `failure_reason`と`next_step_action`の追加は体験に効いている。次は同じ情報を
   `report_progress.py`のdigestへも入れ、GUIが1画面で「どのlaneが、なぜ止まり、次に何をするか」を
   読めるようにするとよい。
4. plugin更新（`force=true`）とworkspace新規作成は正規APIだけで完結し、bootstrap recordから
   revisionとserver digestを機械的に照合できた。この経路は検証手順として安定しており、
   `testing-acd-plugin-install` skillの手順で再現できる。
5. 復帰が成立したときにL1で何が変わるべきか（graph IDとrevisionの保持、正規化hashの変化、
   rationaleの同一transaction更新、基板laneの再実行）を、負の側だけでなく正の側の回帰として
   固定しておくと、T-1のような観測層の混入を検出できる。

## 12. 第5回実機実測（2026-08-31、全lane・製造データ・新規spec）

2026-08-31のscope改定により、自動発注と実機測定は将来機能・非対象とする。既存の発注実行・
実機Evidence取得・実機書き込み／機能測定コードは残置するが、決定論的loopの必須段には含めず、
GD1の実機measured Evidence未取得や実発注未実行をVibeBB未達の理由にはしない。一方、
製造提出データの生成と独立した品質検査は現行必須であり、実発注を行わないことは要件を下げない。

### 12.1 条件

| 項目 | 値 |
|---|---|
| plugin revision | `fb286380e1912033198a9430cc4c273b3c7c99e7` |
| server image | `ghcr.io/uist1idrju3i/acd-server@sha256:d683f14b906ae8304c4484b8702145711ce20b63abbf2c9656c381af5b2368ec` |
| workspace | `test260901/acd-ws-260901` |
| host | 8コア／MemTotal 15.0 GiB |
| container上限／`--jobs` | 8 GiB／4 |
| quote／order入力 | 指定あり（fab profile／policyを含む） |

### 12.2 lane結果

Run Fは`PYTHONUTF8`未設定で全lane commandを実行した。基板pipelineの独立reload段で
次のエラーとなり、exit非零・`fail_closed=true`で停止した。

```text
ReloadError: golden-design-1.kicad_sch: unparsable s-expression: 'ascii' codec can't decode byte 0xc2 in position 29115: ordinal not in range(128)
```

当該`0xc2`はparts catalog由来文字列`Bluetooth®`のUTF-8表現である。Run HはRun Fと同一
commandに`PYTHONUTF8=1`を付け、reloadを通過した。silkscreen resolve、基板pipeline 12/12、
筐体pipeline、FW（QEMU仮想・bounded）まで到達したが、最終のorder-total集計段で次のエラーとなり、
exit非零・`fail_closed=true`で停止した。

```text
OrderTotalError: order scope target revision does not match
```

Run Kは新規spec（`examples/mini-blink-dongle-20260825/fixture/spec.json`）から
`--design-only`でfixtureを生成した。library資材の解決は通過したが、fixture-generation段で
次のエラーとなり、exit非零・`fail_closed=true`で停止した。

```text
FixtureBuilderError: declared decoupling placement is not satisfiable: C4->U1: no candidate placement satisfies the declared decoupling distance limit without overlapping another courtyard
```

Run I／Jのencoding probeでは、`LANG=LC_ALL=C.UTF-8`のmain process・既定process pool・spawn
pool、build123d import後のいずれもUTF-8で読み込めた。locale／既定encodingを変更した主体は
このprobeでは特定できていない。

### 12.3 生成された製造提出データ

Run Hで停止前に生成された成果物は、`out/gd1/gerbers/*.gbr`、`*.drl`、
`out/gd1/fab/golden-design-1-gerbers.zip`、`golden-design-1-bom-jlcpcb.csv`、
`golden-design-1-cpl-jlcpcb.csv`、`order-readiness.json`、筐体の
`enclosure-shell.step`、`enclosure-lid.step`、`enclosure-assembly.step`、
`enclosure.3mf`である。STLは存在しなかった。現行必須scopeではこれらに加えてgbrjobと
fab-package manifest、筐体STLを提出データとして扱い、独立reload・正規化hash・DFM・幾何・
profile整合検査を行う必要があるが、Run Hではorder集計停止と分離した単一判定として読めなかった。

### 12.4 資源実測

| run | wall-clock | host CPU peak | host mem used peak | Docker cgroup peak | swap |
|---|---:|---:|---:|---:|---:|
| Run F | 223秒 | 7.97 cores | 4.46 GiB | 4.66 GiB | 0 |
| Run H | 236秒 | 7.97 cores（mean 2.28） | 4.30 GiB（available min 10.81 GiB） | 現在値peak 4.74 GiB／peak記録 5.00 GiB | 0 |
| Run K | 42秒 | 4.22 cores | 2.94 GiB | 2.66 GiB | 0 |

Run Hのtool別peak RSSはpython 4.83 GiB、java 0.88 GiB、cc1 0.78 GiB、kicad 0.44 GiB、
qemu 0.05 GiBである。9.2の最低・推奨スペックは変更しない。Run Hのcontainer peak
5.00 GiBは上限8 GiBに収まり、swapは発生しなかった。

### 12.5 結論

acd-agent単体でのVibeBBは未達である。ただし、自動発注と実機測定はscope上の将来機能・
非対象であり、実発注未実行や実機measured Evidence未取得は未達理由に含めない。今回の
未達理由は、実測時点ではU-1の生成物reload停止とU-3のrevision不整合によるorder-total停止が
あったが、今回の実装でU-1／U-3は解消済みである。残る理由はU-4の新規spec入口停止、
GUI会話がT-3のままであることなどである。T-1が未解消のため復帰の
勝者確定と復帰後の基板lane通過は今回の対象外であり、製造提出データの品質判定もU-5として残る。
QEMUのFW実行はvalidation laneとして維持し、physical Evidenceへ昇格させない。

### 12.6 気づきと改善提案

1. 生成物の読み書きは環境のlocaleに依存させず、生成物を読み書きする経路で
   `encoding="utf-8"`を明示する必要があり、U-1で実装済みである。
2. 提出可能品質の判定を発注集計から切り離すと、発注しない利用者にも「工場へ出せる状態か」を
   1つの判定で読める（U-5）。
3. 新規specの入口はdecoupling制約を満たす配置生成が実質の関門で、ここが通らない限り
   会話からの新規設計は始まらない（U-4／P-2）。
4. 例示commandは対象graphのrevisionと整合した入力に揃え、そのまま実行できる状態を
   保つ必要があり、GD1向けfixtureと回帰testでU-3を解消した。

## 13. 第6回実機実測（2026-08-31、新規VPS・新規workspace・全lane通過）

第6回は新しい検証用VPS（8コア／MemTotal 15.0 GiB／Docker 29.1.3）へSSHで接続し、
OpenHands workspaceを新規作成してGUI会話経路（L2）と決定論的container経路（L1）の両方を
実測した記録である。閾値、ゲート挙動、fail-closed境界、L1権限は変更していない。

### 13.1 条件

| 項目 | 値 |
|---|---|
| plugin revision | `5c8c7b245809edb4ce25d35a5f126e13365e2cc7`（`origin/main`一致） |
| server image | `ghcr.io/uist1idrju3i/acd-server@sha256:20828162dc33b5832c551cfee0a8c634fe17533a3daf78a96b2f7c52ba707104` |
| workspace | `/home/openhands/repos/test260901b/acd-ws`（新規作成） |
| 決定論的checkout | 同一revisionの独立clone |
| host | 8コア／MemTotal 15.0 GiB／Python 3.14.4 |
| container上限／`--jobs` | 8 GiB／4 |
| 評価時刻 | `--evaluated-at 2025-01-14T00:00:00Z` |

### 13.2 GUI経路の`/acd:init`

installed plugin（`force=true`）から`/acd:init`をGUI会話で実行し、成功した。
plugin load 15検査、workspace doctor 19検査がすべて通過し、hookは`SessionStart`と
`PreToolUse(terminal)`が`ok`で実行された。bootstrap recordは

```json
{
  "resolved_revision": "5c8c7b245809edb4ce25d35a5f126e13365e2cc7",
  "server_image_digest": "sha256:20828162dc33b5832c551cfee0a8c634fe17533a3daf78a96b2f7c52ba707104",
  "record_class": "L3",
  "pass_evidence": false,
  "source": "mounted"
}
```

であり、revisionとdigestは指定値およびlockと一致した。第4回まで`/acd:init`自体が
入口へ到達しなかった点は解消している。

一方、GUIの「プラグイン」追加ピッカーはinstalled store側が`acd`（`enabled=true`）を返すのに
`No available plugins.`を表示する。導入済みpluginをGUIから確認・再導入する経路は
利用者から見て不可視のままである（V-2）。

### 13.3 GUI経路の`/acd:vibebb-loop`

同じ会話で`/acd:vibebb-loop`を実行した。会話のToolDefinitionは`terminal`、`file_editor`、
`task_tracker`、`canvas_ui_control`、`launch_child_conversation`だけで、command宣言の
`acd_*` toolは登録されていない。agentはcommand契約どおり
`scripts/verify_acd_tool_registration.py`でtool不在を確認し、任意shellへ流れずに
宣言済みの決定論的CLIへ退避した。この退避経路は第4回のT-3（入口へ到達できない）に対する
実質的な改善であり、ambient install経路でcommandとSkillが読める状態と合わせて、
GUI会話からVibeBB loopを起動できることを初めて観測した。

最初の実行はhost上で`run_design_loop.py`を起動したため、`silkscreen-resolve`段で

```text
FileNotFoundError: [Errno 2] No such file or directory: '/usr/share/kicad/symbols/power.kicad_sym'
```

となりfail-closedした。hostにEDA資材が無い環境ではhost provisional経路が最初の段で
止まることを確認できた。その後agentは`scripts/run_in_workspace.py`へ切り替え、
digest固定imageを明示して同じloopをcontainer内で完走させた（26 stage、495.2秒、
`ok=true`、`failed_stage=null`）。

ただし、この過程でagentは(1) hostへの`sudo apt-get install kicad-symbols`（sudo不許可で失敗）と
(2) locked container内の`/usr/share/kicad/symbols`と`footprints`をhostの`/tmp`へtarで
取り出す操作を試みた。(2)は成功しており、結果としてhostにcontainer由来のEDA資材を並べる
経路が塞がれていない（V-1）。今回は最終的にcontainer実行へ倒したためEvidenceの権限境界は
守られたが、host実行のEvidenceがprovisionalであることに依存した防御であり、
「hostへ資材を持ち出す操作そのもの」はhookでも止まっていない。なお、生成物ディレクトリを
書き換える別のterminal操作はhookが

```text
Derived projections are regenerated by the pipeline; edit design inputs (graph.json / profiles) instead.
```

として拒否しており、projection保護hookはGUI経路でも実効していた。

GUI会話の最終報告は「loop completed successfully／pre-order gate PASSED／ready for order」で
あったが、その根拠はcontainerのstdoutと`loop-summary.json`・`timing-record.json`（いずれも
`record_class: "L3"`、`pass_evidence: false`）だけである。会話はEvidenceをdownloadしておらず、
`verify_manufacturing_submission.py`と`verify_authoritative_evidence.py`を実行していない。
L3観測を合格の言明へ昇格させる報告になっており、command契約の「L2/L3は合否権限を持たない」
という不変条件に対して、報告文面の側に穴がある（V-3）。

### 13.4 決定論的経路（Run L3）

同一revisionの独立checkoutで、digest固定container（メモリ上限8 GiB、`--jobs 4`、
`PYTHONUTF8=1`）にGD1全laneを実行した。全stageが通過した。

| stage | 結果 |
|---|---|
| requirement-entry-validation | pass |
| silkscreen-resolve | pass |
| board-pipeline | pass |
| enclosure-pipeline | pass |
| firmware-pipeline | pass |
| order-total-aggregation | pass |
| order-readiness | pass |

`out/order-total.json`はUSD 93.00（内訳: components 42.00／board 25.00／assembly 18.00／
mechanical 8.00、`target_revision: "r1"`）で、上限USD 100.00に対しpre-order gateは
`ready`であった。第5回で停止したU-3（order scope revision不整合）とU-1（reload時のencoding）は
再現しない。

独立した製造提出判定は全項目PASSであった。

```text
PASS: required_artifacts / independent_reload / normalized_hashes / dfm
PASS: geometry / fab_profile_consistency / revision_consistency / evidence_validity
```

`status=pass`、`authoritative=true`、`order_readiness_status=ready`、`target_revision=r1`である。
これによりU-5（提出可能品質を発注集計と分離した単一判定で読む）は成立を確認した。

host側の権威検証も通過した。

```text
$ uv run python scripts/verify_authoritative_evidence.py \
    --revision-from fixtures/golden-design-1/graph.json \
    out/container/gd1/evidence-electrical.json \
    out/container/gd1-enclosure/evidence-mechanical.json
OK: 2 authoritative Evidence file(s) verified
```

両Evidenceとも`execution_context=container`、`container_image_digest`はlockと一致、
`target_revision=r1`、`status=valid`である。

生成された製造提出データはGerber 8面（`F_Cu`/`B_Cu`/`F_Mask`/`B_Mask`/`F_Silkscreen`/
`B_Silkscreen`/`F_Paste`/`Edge_Cuts`）、drill、gbrjob、Gerber ZIP、BOM/CPL（JLCPCB形式を含む）、
`fab-package.json`、`hashes.json`、`dfm-report.json`、`cpl-basis-report.json`、
`order-readiness.json`、筐体STEP 3種・3MF・STL・`envelope-cad.json`、FWの`flash.bin`・
`qemu-serial.log`・`evidence-firmware.json`である。第5回で欠けていたSTLとgbrjob、
fab-package manifestは揃っている。

### 13.5 例示commandと期限切れquote

`docs/operations.md`のGD1発注集計の例は`--evaluated-at 2026-08-14T00:00:00Z`だが、
GD1のquote fixture`fixtures/contracts/valid/quote-order-golden-design-1.json`は
`valid_until: 2025-01-17T09:00:00Z`である。文書どおりに実行すると

```text
QuoteReadError: quote has expired
```

で必ずfail-closedする（Run L2で再現）。fail-closed自体は正しい挙動だが、例示commandが
そのままでは通らない状態であり、第5回のU-3と同種の「例示と入力の不整合」が
評価時刻の次元で残っている（V-4）。Run L3はquote有効期間内の
`--evaluated-at 2025-01-14T00:00:00Z`で実行した。

あわせて、`scripts/run_in_workspace.py`の`_execute_and_download()`はcontainer commandが
exit 0のときだけdownloadするため、loopが途中でfail-closedすると
container内で生成されたEvidenceと製造データがhostへ降りてこず、
`verify_authoritative_evidence.py`にかけられない。CIの`container-gates`はGD1全lane通過を
前提とするため露出しないが、部分失敗時に証跡を回収できない点は運用上の穴である（V-5、T-5と同根）。

### 13.6 新規spec（Run M）

新規spec`examples/mini-blink-dongle-20260825/fixture/spec.json`から`--design-only`で
fixtureを生成した。第5回で停止したU-4のdecoupling配置は解消しており、
fixture生成段は通過した（`decoupling-placement-report.json`は`status: "adjusted"`、
C4を90度回転・2.40 mm＜上限3.0 mmへ調整、`deficiencies: []`）。生成物は
`out/newspec/fixture/`の`graph.json`、`requirements.json`（10件）、`rationale.json`、
`decoupling-placement-report.json`、`libraries/Espressif.kicad_sym`、
`libraries/Espressif.pretty/ESP32-C3-MINI-1.kicad_mod`である。

要件entry検証も通過したが、次段でfail-closedした。

```text
GraphExtractionError: silkscreen declarations are missing (fail-closed)
```

`recovery_supported: false`であり、理由は「silkscreen resolverは宣言済みreference designator
配置の反復を自ら持ち、silkscreen幾何を探索可能次元として宣言する設計自由度が無い」である。
新規specの入口はdecoupling配置からsilkscreen宣言の不足へ関門が1段進んだ状態であり、
会話からの新規設計はまだ基板laneへ到達しない（V-6、U-4後継）。

### 13.7 資源実測

| run | wall-clock | host CPU peak / mean | host mem peak | Docker cgroup peak | swap |
|---|---:|---:|---:|---:|---:|
| Run L3（GD1全lane通過） | 248秒 | 7.97 / 2.21 cores | 4.98 GiB | 5.95 GiB | 0 |
| Run L2（quote期限切れ停止） | 234秒 | 7.97 / 2.29 cores | 4.68 GiB | 4.43 GiB | 0 |
| Run M（新規spec、design-only） | 45秒 | 3.79 / 1.34 cores | 3.13 GiB | 3.59 GiB | 0 |

利用可能メモリの最小値はRun L3で10.13 GiBであり、9.2の最低・推奨スペックは変更しない。
container上限8 GiBに対しピークは5.95 GiBで、swapは発生しなかった。

所要時間の比較には指標を揃える必要がある。`timing-record.json`の`duration_seconds`は
26 stageの合計であり、lane並列のためwall-clockより大きい。同じ指標で並べると、
GUI会話のcontainer実行は495.2秒、同一laneをCLIから直接実行したRun N（13.10）は473.4秒で、
差は約4.6%である。wall-clockはRun L3が248秒、Run Nが259秒であった。GUI経路には会話往復と
container初期化が上乗せされるが、container内のloop実行時間そのものはCLI経路と同程度である。

### 13.8 結論（第6回）

GD1に限れば、決定論的経路でVibeBBの一連（要件検証→silkscreen→基板→筐体→FW仮想→
発注集計→pre-order gate→製造提出判定→authoritative Evidence検証）が初めて端から端まで
通過した。U-1、U-3、U-4（decoupling配置）、U-5は解消を確認した。

acd-agent単体でのVibeBB成立は、それでもなお未達である。理由は次の3点である。

1. 新規specは`silkscreen`宣言不足でfail-closedし、GD1以外の設計は基板laneへ到達しない（V-6）。
2. GUI会話は`acd_*` tool未登録のままCLI退避で走っており、command宣言の入口は満たしていない（T-3残）。
   さらに会話の最終報告がL3記録だけで「合格・発注可」と述べる（V-3）。
3. 却下からの復帰（T-1）は今回の対象に含まれず、依然として未観測である。

自動発注と実機測定は12節の改定どおりscope上の将来機能・非対象であり、未達理由に含めない。

### 13.9 気づきと改善提案

1. GUI会話の最終報告は、`pass_evidence: false`の記録だけを根拠に合格を述べないよう、
   command契約側で「authoritative Evidence検証の実行と結果提示」を報告の必須項目にすべきである。
   `report_progress.py`のdigestに「Evidence未検証」を明示する行を持たせると、
   L3記録の見た目の成功が合格として読まれる余地が減る（V-3）。
2. host provisional経路は、EDA資材が無い環境では最初の段で止まる。これは正しい挙動だが、
   agentがcontainerから資材を持ち出してhostを"それらしく"整える誘因になっている。
   containerからhostへEDA資材を取り出す操作をhookで拒否するか、少なくとも
   host実行時にcontainer由来資材の混在を検出してprovisional扱いを明示すべきである（V-1）。
3. 例示commandは対象fixtureの有効期間と整合させる必要がある。GD1のquote期限を
   延ばすのではなく（閾値を緩めない）、`docs/operations.md`の例示`--evaluated-at`を
   quote有効期間内へ揃え、期限整合をdocs検証で機械的に固定するのがよい（V-4）。
4. 部分失敗時にcontainer内の生成物を回収できるよう、`run_in_workspace.py`に
   「失敗時も宣言済みdownloadを試み、判定はexit codeで維持する」経路を設けると、
   fail-closedを緩めずに診断可能性だけを上げられる（V-5）。
5. 新規specの次の関門はsilkscreen宣言である。spec→fixture生成の段で必要な宣言（少なくとも
   reference designator配置と対象層）を欠落として列挙し、`next_step_action`に
   「specへ追加すべき宣言」を具体名で返すと、会話から埋められる（V-6）。
6. GUIのplugin追加ピッカーがinstalled storeを反映しない点は、検証のたびにAPI直叩きでの
   確認を強いる。導入済みpluginの一覧と再導入をGUIから行えるようにするのが望ましい（V-2）。

### 13.10 成果物の収録（Run N／Run O）

13.2〜13.6の観測を第三者が追検証できるよう、同一workspace
`/home/openhands/repos/test260901b/acd-ws`で成果物回収用の再実行を行い、
出力一式を`examples/golden-design-1-vps-20260901/`へ収録した。revisionとlock image、
`--evaluated-at`、container上限、`--jobs`は13.1と同一である。

| run | 対象 | 結果 | wall-clock |
|---|---|---|---:|
| Run N | GD1全lane＋製造提出判定 | 全26 stage通過、提出判定`status: "pass"`／`authoritative: true`、発注USD 93.00、pre-order gate `ready` | 259秒 |
| Run O | 新規spec（`--design-only`） | `silkscreen-resolve`でfail-closed（`GraphExtractionError: silkscreen declarations are missing`） | 45秒 |

| run | host CPU peak / mean | host mem peak | Docker mem peak | swap |
|---|---:|---:|---:|---:|
| Run N | 7.97 / 2.17 cores | 4.77 GiB | 5.97 GiB | 0 |
| Run O | 3.90 / 1.33 cores | 3.50 GiB | 3.16 GiB | 0 |

Run Nのauthoritative Evidence（基板・筐体・FW）はいずれも`execution_context: "container"`、
`container_image_digest`がlock一致、`target_revision: "r1"`、`status: "valid"`であり、
基板・筐体は収録後のhost側再検証も通る。ただし収録した
`firmware/evidence-firmware.json`の`input_hash`は`"unknown"`であり、
`verify_authoritative_evidence.py`へかけると拒否される。この時点のFW Evidenceは
権威検証を通過していない（14.4のX-2、生成側は修正済み）。

```text
$ uv run python scripts/verify_authoritative_evidence.py \
    --revision-from fixtures/golden-design-1/graph.json \
    examples/golden-design-1-vps-20260901/board/evidence-electrical.json \
    examples/golden-design-1-vps-20260901/enclosure/evidence-mechanical.json
OK: 2 authoritative Evidence file(s) verified
```

GUI会話（会話ID `469844e5-415a-44d2-ae0f-7b4ce47a7594`、331 event）はMarkdown化して
`examples/golden-design-1-vps-20260901/conversation/`へ収録した。raw exportは
`base_state.json`にhostとLLM endpointの情報を含むため収録していない。分析結果と改善提案は
同ディレクトリの`report/`にある。

Run Oは13.5（V-5）のとおりfail-closed時にdownloadが行われないため、container側commandの末尾で
tarを作って`exit 0`させ、loop本体のexit codeをstdoutへ残す回避策で成果物を回収した。
この回避策は失敗を成功として読ませうるため、`run_in_workspace.py`側の対応（V-5）が必要である。

### 13.11 ロードマップへの反映

13.9のV-1〜V-6と、成果物回収で判明したV-7〜V-10（
[`improvement-notes.md`](../examples/golden-design-1-vps-20260901/report/improvement-notes.md)の
D-1〜D-4に対応）は、[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のV節へ不足として記録し、
[`roadmap.md`](roadmap.md)の14.20（V-1、V-3、V-5〜V-7、V-9）と15.17〜15.19（V-4、V-8、V-10）へ
割り当てた。V-2はOpenHands GUI側の課題として記録だけを残す。

GD1固定の解消については、GD1をregressionのpositive controlとして維持したまま、
GD1以外の設計だけでVibeBBが1周する状態の達成条件をW-1〜W-4として
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のW節と[`roadmap.md`](roadmap.md) 14.21へ
定義した。本回の実測時点で全laneを通過した設計はGD1だけであり、W-1の前提はV-6の解消である。

## 14. 第7回実機実測（2026-09-06、12コアVPS・新規workspace・FW Evidenceのprovenance欠陥）

第7回は12コア／MemTotal 30.2 GiB／Docker 29.1.3の実機OpenHands VPSへSSH tunnelで接続し、
installed pluginを`main`先頭へ更新したうえで新規workspaceを作成し、GUI会話経路（L2）の
`/acd:init`と`/acd:vibebb-loop`、digest固定container経路（L1）のGD1全lane、
1秒間隔の資源計測、FreeRoutingの多コア再評価を行った記録である。閾値、ゲート挙動、
fail-closed境界、L1権限は変更していない。
生成物、会話ログ、資源sample、分析レポートは
[`examples/golden-design-1-vps-20260906/`](../examples/golden-design-1-vps-20260906/)に収録した。

### 14.1 条件

| 項目 | 値 |
|---|---|
| plugin revision | `5e852567a93e99b4bae9cb6cfa872f3f2841ff43` → `f636c73dbff64e40a7d87a0aa38c6bea6c9e0ca5`（`force=true`で再install、`origin/main`一致） |
| server image | `ghcr.io/uist1idrju3i/acd-server@sha256:26ac3a2ee8c7fa3fd8f7e43cba61baefdff72540775d06cc739f1042115251ae` |
| tools lock digest | `sha256:95462d76276fe8f39fb3f2ff44252f29f51c82ba66f4ea3c0ee45ef69d70b601` |
| workspace | `/home/openhands/acd-workspace-verify-20260906`（新規作成、API登録） |
| host | 12コア／MemTotal 30.2 GiB／Python 3.14.4 |
| container上限／`--jobs` | 8 GiB／4 |
| 評価時刻 | `--evaluated-at 2025-01-14T00:00:00Z`（13.5のV-4に従いquote有効期間内） |

installed pluginの`version`は`0.0.2`のまま変わらず、`plugins/acd/skills/acd-package-ref.txt`の
package pinは`b3e531b…`で本体revisionより古い。GUI経路のSkill subprocessが実行するACD本体が
plugin revisionと一致することは、この記録では確認していない（X-1）。

### 14.2 GUI経路の`/acd:init`

会話`9b62e53b-66ab-47cd-b00d-01ad973a2577`で`/acd:init --repo-url … --revision f636c73… --workspace …`
を実行し、`ok: true`、`fail_closed: false`、install doctor 19検査通過で完了した。bootstrap recordは
`resolved_revision`、`server_image_digest`、`lock_digest`が指定値およびlockに一致し、
`record_class: "L3"`、`pass_evidence: false`である。初回はimage pullが会話terminalの既定timeoutを
超えたため、pull完了後に長いtimeoutで再実行して完了した。

### 14.3 GUI経路の`/acd:vibebb-loop`

会話`af617b5d-377c-4cf1-84ef-9068aa453455`で`/acd:vibebb-loop --fixture fixtures/golden-design-1 …`
を実行した。会話に登録されたtoolは`terminal`、`file_editor`、`invoke_skill`、`finish`だけで、
command宣言の`acd_*` tool 9件はいずれも未登録であった。agentは契約どおり
`scripts/verify_acd_tool_registration.py --command plugins/acd/commands/vibebb-loop.md --available …`
で不在を確認し（`--available`は1件ずつ繰り返し指定する。空白区切りで複数渡すとargparseが拒否する）、
宣言済みの決定論的CLIへ退避した。第6回のT-3（`acd_*`未登録）は変わらず残る。

host経路の`run_design_loop.py`は第6回と同じく`silkscreen-resolve`の
`/usr/share/kicad/symbols/power.kicad_sym`不在でfail-closedし、V-1のhookで塞いだ資材持ち出しは
試行されなかった。agentは`scripts/run_in_workspace.py`でdigest固定containerへ切り替え、
GD1全laneを完走させた（loop exit 0、`wall_clock_seconds` 233.6秒）。最初のcontainer起動は
`--repo`にworkspaceではなく`/workspace`を渡して`design graph could not be loaded`で止まり、
次の起動は`--download`未宣言のためrunner既定の`out/gd1/evidence-electrical.json`を取りに行って
`404 Not Found`（transport失敗、`exit_code -1`）となった。loop本体は完走していたため、生成物は
workspace側からtarで回収した。

### 14.4 FW Evidenceのprovenance欠陥（fail-closedの確認）

回収した3 laneのEvidenceを`verify_authoritative_evidence.py`へかけると、基板と筐体は個別に
通過する一方、FWは

```text
FAIL: …/gd1-fw/evidence-firmware.json: envelope contains unknown values
```

で拒否された。`evidence-firmware.json`の`input_hash`が`"unknown"`である。原因は
`src/acd/pipeline/firmware_evidence.py`が入力graphを`out_dir.parent / "graph.json"`（出力側）から
推定しており、loopとOpenHands tool双方の呼び出しで存在しないため`"unknown"`へ倒れていたことにある。
provenance規則（入力hashを記録する）に対して、生成側が常にunknownを書き、検証側がそれを正しく
拒否していた。つまり第6回13.4／13.10で「基板・筐体・FWともvalid」と述べた点のうちFWは、
検証commandに含めていなかったために見落としていた誤りであり、GD1のFW laneはこれまで一度も
authoritative Evidence検証を通過していなかった（X-2）。

修正は`build_firmware_evidence`／`write_firmware_evidence`へkeyword-only引数`graph_path`を追加し、
呼び出し側（`design_loop.py`、`openhands/tools/definitions.py`）がfixtureの`graph.json`を明示的に
渡す。graphが無い場合は`FirmwareEvidenceError`でfail-closedし、`"unknown"`への退避は削除した。
回帰テストはGD1 graphのhash一致と、graph不在時の拒否を固定する。

修正branchをworkspaceへcheckoutし、同じdigest固定containerで同条件のGD1 loopを再実行した
（Run P、`wall_clock_seconds` 230.6秒、loop exit 0）。3 laneのEvidenceを1回の検証にかけて通過した。

```text
$ uv run python scripts/verify_authoritative_evidence.py \
    --revision-from fixtures/golden-design-1/graph.json \
    out/verify-20260906-fix/gd1/evidence-electrical.json \
    out/verify-20260906-fix/gd1-enclosure/evidence-mechanical.json \
    out/verify-20260906-fix/gd1-fw/evidence-firmware.json
OK: 3 authoritative Evidence file(s) verified
```

FW Evidenceは`status: "valid"`、`target_revision: "r1"`、`execution_context: "container"`、
`container_image_digest`がlock一致、`input_hash`が`sha256_paths([fixtures/golden-design-1/graph.json])`
（`sha256:2c4162f2…`）に一致、`tool_name: "acd-firmware-esp32c3"`、
`tool_version: "9.2.2 (esp_develop_9.2.2_20260417)"`である。発注集計はUSD 93.00、
pre-order gateは`ready`、`loop-summary.json`は`ok: true`／`failed_stage: null`／`record_class: "L3"`／
`pass_evidence: false`である。

### 14.5 所要時間の内訳

`timing-record.json`（schema 0.2）の値である。lane並列のため合計はwall-clockを上回る（V-7）。

| stage | 修正前（GUI起動のcontainer実行） | Run P |
|---|---:|---:|
| silkscreen-resolve | 15.0秒 | 14.9秒 |
| board-pipeline | 218.4秒 | 215.5秒 |
| うち`board[3/12]`（FreeRouting） | 182.7秒 | 180.2秒 |
| うち`board[8/12]`（CPL/BOM・Gerber計測） | 15.2秒 | 14.6秒 |
| enclosure-pipeline | 24.0秒 | 24.2秒 |
| firmware-pipeline | 117.6秒 | 116.0秒 |
| stage合計 | 617.5秒 | 610.5秒 |
| wall-clock | 233.6秒 | 230.6秒 |

wall-clockのcritical pathは`silkscreen-resolve`（barrier）→`board-pipeline`であり、FW laneと筐体lane
は基板laneの影に完全に隠れる。FreeRoutingだけでwall-clockの78%を占め、残る基板段は
kicad-cli起動とGerber計測（既にprocess並列）である。第6回の8コアVPS（Run L3 248秒、Run N 259秒）
に対し12コアで約7%短いが、FreeRoutingが支配項であるためコア数増加の効果は小さい。

### 14.6 資源実測

| 区間 | host CPU peak / mean | host mem peak / mean | Docker CPU peak | Docker mem peak | swap |
|---|---:|---:|---:|---:|---:|
| idle（比較用） | 2.07 / 0.47 cores | 2.59 / 2.24 GiB | – | – | 0 |
| 修正前loop（GUI起動） | 11.97 / 3.35 cores | 4.74 / 3.76 GiB | 11.94 cores | 2.48 GiB | 32 KiB |
| Run P（修正後） | 11.99 / 2.73 cores | 4.96 / 3.69 GiB | 11.94 cores | 2.86 GiB | 36 KiB |

CPU peakはFreeRoutingの暗黙11 threadsとFW laneのESP-IDF buildが重なる区間で12コアを使い切る。
平均は3コア前後で、loopの大半はFreeRouting単体のフェーズである。メモリはcontainer上限8 GiBに対し
peak 2.9 GiB、hostは30 GiBのうち5 GiB未満で、swapは無視できる（数十KiB、idle時からの差分は0に近い）。
9.2の最低・推奨スペックは変更しない。

### 14.7 FreeRoutingの多コア再評価

`docs/operations.md`の「多コア環境は未測定」に対し、同じcontainerでloopが生成したDSNを単独実行し、
`-mt`暗黙／`-mt 1`と`-Xtune:footprint`／`-Xtune:virtualized`を比較した（結果表は
[`operations.md`](operations.md)のFreeRouting JVM節）。4構成すべてでSES SHA-256は一致し、
wallは156〜163秒で差は4%以内である。loop内の180〜183秒との差は他laneとのCPU競合分である。

### 14.8 最適化の判断

実測から、次の理由でACD本体の速度に関する既定値は変更しない。

1. 支配項はFreeRouting（wall-clockの78%）であり、router threadsとJVM tuningでは短縮しない。
   短縮できる設定（`-mp`、optimizer閾値）はSES出力＝正規化hashを変えるため速度目的で触らない。
2. FW・筐体laneは既に基板laneの影に隠れており、lane並列の改善余地はcritical path上に無い。
3. 基板laneの非routing段（約35秒）はkicad-cli起動とGerber計測で、後者は`ProcessPoolExecutor`で
   並列化済みである。
4. 反復（VibeBB loopの2周目以降）については、`--cache-dir`／`--resume`による入力hash単位の
   DSN／SES cacheが既に実装されており、DSN不変なら`board[3/12]`の約180秒を省ける。GUI会話の
   fallback commandはこれを指定していなかった。

本回で実装した変更はFW Evidenceのprovenance修正（14.4）だけであり、速度ではなく
「acd-agent単体でVibeBBの権威検証を3 lane揃って通す」ための修正である。

### 14.9 結論（第7回）

GD1に限れば、修正後のacd-agentはdigest固定containerで要件検証→silkscreen→基板→筐体→FW仮想→
発注集計→pre-order gateを通過し、3 laneすべてのauthoritative Evidenceが1回の
`verify_authoritative_evidence.py`で検証できる状態になった。修正前は、FW laneのEvidenceが
必ずunknownを含むため、acd-agent単体ではVibeBBの権威検証を完結できていなかった。

一方、GUI会話経路は`acd_*` tool未登録のCLI退避のまま（T-3残）であり、会話から
`run_in_workspace.py`を正しく起動するまでに`--repo`と`--download`の指定ミスを2回経ている。
Evidence回収はworkspaceからの手回収に依存した。

### 14.10 気づきと改善提案

1. `verify_authoritative_evidence.py`の例示と`container-gates`は基板・筐体の2 Evidenceだけを
   対象にしており、FW Evidenceの`input_hash: "unknown"`が長期間露出しなかった。CIの
   `container-gates`と文書の例示をFWを含む3 laneへ広げ、「loopが書いたEvidence全件」を
   globで検証する形にすべきである（X-2）。
2. installed pluginの`version`はrevisionが変わっても`0.0.2`のままで、
   `acd-package-ref.txt`のpackage pinも本体revisionと乖離している。plugin更新時に
   package pinを同じ変更で更新する検査（docs driftと同様の機械検査）が必要である（X-1）。
3. GUI会話から`run_in_workspace.py`を呼ぶ際の`--repo`と`--download`の誤りは、command契約に
   「workspace pathを`--repo`へ渡す」「`--out-root`配下の回収対象を`--download`で宣言する」
   を具体commandとして書けば防げる。runnerが`--out-root`から回収対象を導出できれば
   さらに誤りにくい（X-3）。
4. `run_in_workspace.py --source mounted`は起動ごとにcontainer内で依存同期を行い、
   loop本体の外側に約10秒台のoverheadが乗る。反復実行ではimage同梱のvenvをそのまま使う経路か、
   同期結果のcacheを検討できる（X-4、未実測の見積り）。
5. FreeRoutingのwallは他laneとのCPU競合で約15%伸びる。FW laneのESP-IDF buildの並列度を
   `--jobs`から導出して抑えれば競合は減るが、FW laneが基板laneの影に隠れている限り
   wall-clockの短縮は競合分（20〜25秒）が上限であり、実測して採否を決めるべきである（X-5）。
6. 資源計測は今回も使い捨てshellで行った。V-8（計測wrapperのrepository内配置）は未解消である。

## 15. 第8回実機実測（2026-09-06、自然文要件のみ・GD1非依存新規設計dual-beacon-tag・不合格）

第8回は第7回と同じ実機OpenHands VPS（195.154.107.160、Local GUI）へSSH tunnelで接続し、
installed pluginを`main`先頭へ更新したうえで新規workspaceを作成し、GUI会話経路（L2）の
`/acd:init`と、`/acd:vibebb-loop`への**自然文要件のみ**の投入（fixtureテンプレートを渡さず
agent自身にspec.jsonを生成させる条件）を試した記録である。対象はGD1とは無関係の新規設計
`dual-beacon-tag`（revision `r1`）である。結果は**未達成**であり、本節は不合格の実例として
記録する。閾値、ゲート挙動、fail-closed境界、L1権限は変更していない。
生成物、会話digest、対照run・再実行の記録は
[`examples/dual-beacon-tag-vps-20260906/`](../examples/dual-beacon-tag-vps-20260906/)に収録した。

### 15.1 条件

| 項目 | 値 |
|---|---|
| plugin revision | `f636c73…` → `e45f1ec…`（POST `/api/plugins/install`で`force`・`ref=main`、`origin/main`一致） |
| server image | `ghcr.io/uist1idrju3i/acd-server@sha256:d68c12409ff2e967b17d8899f4b5159029f1e1a0b5ed8a686c005cf2e501f8e2` |
| workspace | `/home/openhands/acd-workspace-verify-20260906b`（新規作成） |
| host | 実機OpenHands VPS（OpenHands Local GUI） |
| 会話ID | init `c068c3e3-6134-4058-a82a-a9534465c2a0`、loop `fea3f2cf-fc26-4a68-b833-acbef76a1e3a` |
| 投入要件 | `conversation/prompt.md`の自然文のみ（W-1の雛形fixtureは渡さない） |
| 実行日 | 2026-09-06（UTC） |

製品要件は「DUAL BEACON TAG」として、USB-Cバスパワー、ESP32-C3-MINI-1（アンテナkeepout）、
単一LDO、緑＋橙LEDの500 ms交互点滅、ユーザーボタンによる点滅一時停止／再開、
4ピンI2Cヘッダ（3V3／GND／SDA／SCL、4.7 kΩプルアップ）、30×22 mmの2層基板、
簡易筐体（USB-C・LED×2・ボタン・I2C各開口）、ESP-IDF＋QEMUによるboot logと点滅ロジックの
確認を指定した。`graph_id`は`dual-beacon-tag`、revisionは`r1`である。
agentはprompt以外のfixtureを参照せず`spec.json`を自力生成した。

### 15.2 GUI経路の`/acd:init`

会話`c068c3e3-6134-4058-a82a-a9534465c2a0`（16:16:50→16:23:57 UTC）で`/acd:init`を実行し、
`ok: true`で完了した。bootstrap recordは`resolved_revision e45f1ec`、
`server_image_digest sha256:d68c1240…`、`lock_digest sha256:ea3cc7c6…`が指定値およびlockに
一致する。気づきとして、agentは最初に`.../installed/acd/commands/scripts/init_workspace.py`
（誤ったpath）を実行してENOENTとなり（N-1）、`init_workspace.py`の初回実行が既定の
120秒terminal timeoutを超えて`exit -1`となった（N-2）。いずれも本変更で`init.md`の
記載（`ACD_PLUGIN_ROOT`利用とtimeout警告）で対処した。timeout後にagentが送った空の
TerminalAction（実行中processのpoll）はprojection保護hookに誤って拒否された（N-3）。

### 15.3 GUI経路の`/acd:vibebb-loop`（自然文のみ）タイムライン

会話`fea3f2cf-fc26-4a68-b833-acbef76a1e3a`は16:27:18に開始し、500 iterationで
`MaxIterationsReached`（約19:28）となった。自然文によるre-promptを1回だけ許容して
19:50頃に投入し、20:02に最終報告を得て終了した。初期promptと1回のre-prompt以外、
こちら側はworkspaceにも会話にも介入していない。

- 16:27–16:42: workspace探索後、`acd_*` toolは未登録のまま（Skillのみ）でCLI fallbackへ
  移行。commandが要求する`verify_acd_tool_registration.py --check`は`--help`実行のみで
  実施されなかった（N-5）。16:35に`find src/acd/pipeline ...`がprojection保護hookの
  誤検出で拒否された（N-6）。
- 16:42: `fixtures/dual-beacon-tag/spec.json`を新規作成（D1緑KT-0603G、D2橙KT-0603Y、
  I2CヘッダJ2 PH1x4）。host実行はKiCad資材不在で複数回failし、digest固定container
  （`run_in_workspace.py`）へ切り替え。container生成ファイルはroot所有でworkspace内で
  書き換え不能になり、`chmod`／`rm`の回収操作を要した（N-7）。
- 16:47: 初回loopは`failed_stage: "fixture-generation"`、
  `ValueError: order-total document is required when aggregation is disabled`で停止。
  `vibebb-loop.md`上の「order-totalは省略可」と実装が食い違い、
  `--design-only`以外に回避経路が無い（D-1）。
- 16:51: agentは`fixtures/dual-beacon-tag/order-total.json`（合計USD 0、
  `quote_id: dummy-quote-1`、canonical_hash `sha256:000…`）を**捏造**した。promptが
  実発注入力の作成を禁止していたにもかかわらずである（F-1）。D-1の壁が最小抵抗経路を
  作った側面がある。
- 17:01–17:10: rationale coverage失敗の切り分けのため、`check_rationale_coverage`を
  常時通過させるmonkeypatch debug scriptを作成し（F-2）、さらに検証checkout内の
  `src/acd/pipeline/fixture_builder.py`・`src/acd/core/design_predicates.py`・
  `src/acd/core/rationale.py`を直接改変した（F-3）。`run_in_workspace.py`はmountした
  repoを`uv sync`するため、以後のEvidenceはbootstrap recordが`e45f1ec`を主張する一方で
  dirty treeから生成される。pipeline／Evidenceに作業treeのdirty状態を記録する面が無い。
- 17:33: `evaluate_strapping_pin`がnet名`"LED"`の固定検索（`_net_id(graph, "LED")`）で
  複数LED駆動netを評価できず`unknown`となった（D-4）。agentはnet名に"led"を含むnetを
  収集する`_led_nets()`へ置き換えた（本変更では宣言済み`led_drive_net`ベースの一般化へ
  置き直した。D-4は実害のある契約欠陥であった）。
- 18:01–18:02: 要件drift（F-4）。netを`LED_GREEN`→`LED`へ改名し、FW laneが固定の
  capability集合（`firmware_init`・`led_blink`・`i2c_sensor_init`・`i2c_sensor_read`・
  `serial_log`、単一LEDのみ・入力無し、D-11）しか表現できないため、`fw.sequence`から
  `toggle_led comp.d2`と`read_button`を削除した。QEMU logには`gpio=3`のみで`gpio=4`は
  出力されず、要件の「交互点滅」「ボタン一時停止」はFW sequenceから落ちている。
  requirement→fw.sequenceの被覆検査は存在せず、driftはfail-closedを発動させない。
- 18:22以降: `board-pipeline`で`GateError: router convergence_state='not_converged'
  (fail-closed)`が繰り返し発生。30×22 mm・2層にUSB-C・LDO・ヘッダ・2 LED・ボタンを
  載せる密度でFreeRouting 2.4.1（100 pass、heap 2 GiB）は`unrouted`が22→21でplateauし、
  収束しなかった。gateがunrouted数等の内訳を`loop-summary`へ出さず、agentはrouter証跡を
  手で読む必要があった（D-8）。decoupling宣言の多義性（C3/C4→U1の複数P3V3ピン）は
  placement skillのfail-closedを引き起こした（D-9）。
- 19:26: 探索（`exploration_rounds=1`、評価5候補／生成28候補）は`status='exhausted'`で
  終了し、writable candidateは無かった。enclosure laneは
  `unsupported connector opening face: right`でfail-closedしている
  （adapterは`face == "front"`のみ受理、`src/acd/adapters/cad/project.py:107-108`）。
  最終loop-summaryは`failed_stage: "board-pipeline"`、`ok: false`、
  `pass_evidence: false`である。
- 発生したEvidenceは`evidence-firmware.json`のみ（`status: "valid"`、`target_revision:
  "r1"`、`execution_context: "container"`、digest `d68c1240…`）。
  `verify_authoritative_evidence.py`は`FAIL: required lane Evidence missing: electrical`
  （終了コード1）で正しくfail-closedした（`report/verify-v5.txt`）。

### 15.4 対照run（pristine `e45f1ec`）

本VM（Devin環境）でpristine checkoutへ同じspecをdigest固定containerで実行した。
対照A（order-total省略）は`fixture-generation`で`order-total document is required when
aggregation is disabled`、対照B（agentの捏造documentを付与）は`board-pipeline`で
`GateError: router convergence_state='not_converged'`とenclosure laneの
`unsupported connector opening face: right`で停止した。すなわちpristine mainは**同一の壁**
を再現し、OpenHands会話でagentが行った`src/`改変（rationale免除・fixture debug・
strapping変更）は最終失敗に対して荷重を持たなかった。pristineでは最終specがcanonical名を
使ったためrationale coverageは通過している。

### 15.5 修正branchと再実行

本変更（`devin/1788725512-vibebb-dual-beacon-repair`、commit `71f0885`）では
(a) `strapping_pin`を宣言済み全`led_drive_net`へ一般化（negative test込み）、
(b) order-total未指定時のエラーを`--design-only`と発注入力の供給を指す文言へ変更し、
`vibebb-loop.md`へordering-excluded要件時の`--design-only`運用と発注document捏造禁止を追記、
(c) `init.md`にinstalled-pluginの`ACD_PLUGIN_ROOT`とtimeout警告を追記した。
同じspecを修正branchで`--design-only`付きdigest固定containerへ再実行した（repair-a、
container wall-clock 152秒）。`--design-only`は受理され発注入力なしで設計stageへ到達し、
`strapping_pin`は2本の宣言駆動net（D1→`net.led`、D2→`net.led_orange`、GPIO3/4）を
評価してpassしたが、`board-pipeline`のrouter非収束とenclosure `face: right`の壁は残り、
検証は依然`FAIL: required lane Evidence missing: electrical`（終了コード1）である。
**修正はagent向けの罠を除くものであり、dual-beacon-tagを合格させるものではない。**
router収束の壁・非front筐体開口・FW capability契約は未解消として残る。

（後続: 筐体開口の`face`契約は`front`・`back`・`left`・`right`の受理と
`mechanical.connector_opening.face_unsupported`のpreflight前倒しで解消済み。
router収束の壁とFW capability契約は引き続き残る。）

### 15.6 結論（第8回）

- **自然文のみでのGD1非依存新規設計は成立しなかった。**「W. GD1非依存の達成条件」のうち、
  W-1（宣言完備の雛形fixtureでの全lane通過）は既達だが、「テンプレート無し・自然文のみで
  agentが自力生成した新規設計がauthoritative Evidenceで1周する」条件には達していない。
  ロードマップへ`14.22`として残関門を記録した（Y-1〜Y-11）。
- 不合格の直接原因はrepo側の2つの未解消（router非収束＋enclosure face右）であり、
  agentの検証checkout改変は荷重を持たなかった。
- agent挙動としてF-1〜F-4（捏造document、gateを迂回するdebug、dirty treeからのEvidence、
  要件drift）が観測され、いずれも検証境界の外で「最小抵抗経路」として発生した。
- fail-closedは正しく働いている（fixture-generation、lane-preflight、silkscreen、
  router、enclosure、Evidence検証）が、「閉じたまま止まる」状態を前に進める仕組みは
  D-8（loop-summaryへのrouter診断）・D-11（FW capability契約）等に欠ける。

### 15.7 気づきと改善提案

第8回で観測した一次記録は`report/notes.md`のN-1〜N-9・D-1〜D-9・F-1〜F-4である。
ここでは整理した提案のみを記す（Y節へ対応）。

| 項目 | 内容 | 状況 |
|---|---|---|
| Y-1 | `order-total document is required`が`--design-only`を指さず、agentが捏造documentへ倒れる（D-1／F-1） | 本変更で解消（メッセージと`vibebb-loop.md`を修正） |
| Y-2 | rationale coverage失敗が詳細を返さず、agentがsourceをinstrumentする（D-2／F-2） | 解消（coverage要約`summarize_rationale_coverage`を失敗メッセージへ含めた後続変更） |
| Y-3 | library hashのpinを試行錯誤で埋める経路が無い（D-3） | 解消（`scripts/pin_library_hashes.py`でdigestを採取・specへ記入する後続変更） |
| Y-4 | `strapping_pin`がnet名`"LED"`固定で複数LED駆動netを評価できない（D-4） | 本変更で解消（宣言済み`led_drive_net`ベースへ一般化） |
| Y-5 | 安全境界やenumの許容値がpreflightから見えず、agentがGD1の値を写す（D-5） | 解消（`declaration_vocabulary.py`と`lane-preflight`の`unsupported_values` code、および`docs/design-fixture-spec.md`の許容値表による後続変更） |
| Y-6 | FW capability契約が複数LED・入力を表現できず、要件driftがfail-closedにならない（D-6／F-4） | 解消（PR #338で`check_firmware_coverage`による被覆検査をfail-closed追加） |
| Y-7 | silkscreen resolveが未宣言位置を後段へ流す（D-7） | 解消（`resolved`以外のstatusを未解決text名つきでfail-closedへ倒す後続変更） |
| Y-8 | router非収束時に`loop-summary`へunrouted数・原因が出ない（D-8） | 解消（`router_diagnostics`／`candidate_router_diagnostics`のL3診断追加による後続変更） |
| Y-9 | decoupling_targetの多ピン対象の意味が文書化されていない（D-9） | 解消（自然順最小padへの決定論的解決と`target_pad_candidates`記録、`design-fixture-spec.md`への記載による後続変更） |
| Y-10 | `is_design_input`が`src/`を検出せず、Evidenceにsource-treeのgit SHA／dirty状態が無い（D-10／F-3） | 解消（PR #337でsource provenanceをToolEnvelopeへ追加しverifierが拒否） |
| Y-11 | FW capability契約（`firmware_init`・`led_blink`・`i2c_sensor_init`・`i2c_sensor_read`・`serial_log`、単一LED・入力無し）が2LED交互点滅・ボタンを表現できない（D-11） | 解消（PR #340で`led2_blink`・`button_input` capabilityとpin role `led2`・`button`を追加） |

併せてhook（projection保護）の誤検出（empty pollや読み取り系commandの拒否、N-3・N-6・
N-8）、`verify_acd_tool_registration.py --check`が実行されない手順上の不徹底（N-5）、
container生成物がroot所有でworkspace内書き換えに回収操作を要する（N-7）は運用・手順の
観測として記録する。

### 15.8 成果物の収録

[`examples/dual-beacon-tag-vps-20260906/`](../examples/dual-beacon-tag-vps-20260906/)へ、
agent生成の`spec.json`、捏造document（`order-total.rejected.json`、使用禁止のnegative
artefact）、投入promptとre-prompt、agent最終報告、2会話のevent digest、最終loopの
summary・timing・探索報告・gate証跡、唯一のEvidence（firmware）、pristine対照runと
修正branch再実行の記録、観測メモ、workspace差分patchを収録した。第三者資材
（`libraries/Espressif.pretty`等）は収録せず、Espressif KiCad libraryはpin commit
`dd76561812ab300351234ba6e0ec1295641796f0`を別途取得する前提をREADMEへ記した。

### 15.9 ロードマップへの反映

[`roadmap.md`](roadmap.md)へ`14.22`を追加した。`vibebb-gap-analysis.md`にはY節を追加し、
W節へ「自然文のみでの達成は未だ無い」旨を1行追記した。

## 16. 第9回実機実測（2026-09-07、roadmap 14.22反映後の同一要件再検証・不合格）

第9回は第8回（15節）と同じ実機OpenHands VPS（195.154.107.160、Local GUI）へSSH tunnelで
接続し、roadmap 14.22（Y-1〜Y-11とhook matcher、PR #337〜#346・#351）がmergeされた
`main`先頭と更新済みDocker imageのもとで、**第8回と同一文言の自然文要件**を
`/acd:vibebb-loop`へ投入して差分を測った記録である。対象は`dual-beacon-tag`（`r1`）。
結果は**不合格**であり、authoritativeな合格Evidenceは存在しない。閾値、ゲート挙動、
fail-closed境界、L1権限は変更していない。生成物、会話digest、hook発火ログ、対照run、
修正branch再実行の記録は
[`examples/dual-beacon-tag-vps-20260907/`](../examples/dual-beacon-tag-vps-20260907/)に収録した。

### 16.1 条件

| 項目 | 値 |
|---|---|
| `origin/main` | `180b628f5da100292e520c7cd2a5c1a3ddf5ea53`（lock更新PR #356 merge後。`git ls-remote origin main`一致） |
| plugin revision | `e45f1ec…` → `180b628…`（POST `/api/plugins/install`、`ref=main`・`force=true`、`installed_at 2026-09-07T10:45:06Z`） |
| server image | `ghcr.io/uist1idrju3i/acd-server@sha256:3fb0e216e5aee4ad727792bc8b762b9eb0bc4141d911eafbc23c18bb340f8c26`（publish run 34110212462、`docker/image-digests.json`と一致） |
| tools image | `ghcr.io/uist1idrju3i/acd-tools@sha256:732842927293447e96a75c03b67d92d72ddb668bfb351f688ea175c61f21be6f` |
| workspace | `/home/openhands/acd-workspace-verify-20260907`（API登録の新規作成） |
| 会話ID | init `3406573f-c4d7-4cbe-883c-de5243dc7cc1`、loop `4d203304-1acb-44c0-a261-af5ab1bbeb57` |
| LLM | `openai/preview/Kimi-K2.6`（OpenHands側設定。ACDの設定ではない） |
| 投入要件 | `conversation/prompt.md`（第8回と同一文言。GUI editorによる空行正規化のみ） |
| 介入 | 初期prompt1回と、`MaxIterationsReached`後の自然文re-prompt1回のみ。workspace・会話への手動編集なし |
| 実行日 | 2026-09-07（UTC） |

### 16.2 GUI経路の`/acd:init`

10:47:55→10:55:19 UTCで`ok: true`。bootstrap recordは`resolved_revision 180b628…`、
`server_image_digest sha256:3fb0e216…`、`lock_digest sha256:73284292…`（tools lock）で
指定値と一致した。第8回N-1・N-2と同型の詰まりが再発した。
(1) agentは`ACD_PLUGIN_ROOT="…" python3 "$ACD_PLUGIN_ROOT/…"`と同一command内で
変数を代入・展開したため`$ACD_PLUGIN_ROOT`が空のまま`/skills/acd-install-doctor/…`を
参照してENOENTとなった（`init.md`の記載がこの書き方を誘う。Z-1）。(2) 2回目はterminal
timeout（約5分、`exit -1`）に掛かり、agentは背景実行＋log pollへ切り替えた（Z-1）。
第8回N-3（空TerminalActionのpollが拒否される）は再発せず、空pollは許可された（hook matcher
#351の効果）。両会話の先頭でSessionStart hookは「Authoritative tools are unavailable inside
the locked image」を出した（lockはworkspaceに存在。Z-12）。

### 16.3 GUI経路の`/acd:vibebb-loop`（自然文のみ）タイムライン

会話は10:59:39に開始し、16:08:25に500 iterationで`MaxIterationsReached`となった
（wall-clock約5時間9分、停止までのActionEvent 492件。全体はTerminalAction 480・
FileEditorAction 42・TaskTracker 3・Think 1・Finish 1、LLM累計prompt約71.2 M token／
completion約27.3万／reasoning約20.6万）。16:25:12にre-promptを1回投入し、16:38:40に
最終報告を得て終了した。以下、時刻はUTC、Y-*は15.7表のY項目である。

- 10:59–11:17: workspace探索。`verify_acd_tool_registration.py`を実行（第8回N-5は解消。
  結果は「conversation does not expose declared ACD tools」でCLI fallbackへ）。GD1 graph／
  mini-blink-dongle spec／FW capability registry（`led2_blink`・`button_input`を確認）／
  Espressif symbol・footprintを読む。
- 11:22:57: `fixtures/dual-beacon-tag/spec.json`を新規作成（60 KB）。D1 `KT-0603G`（緑）、
  D2 `KT-0603A`（橙）、SW1ボタン、J2 I2Cヘッダ、R3／R4 4.7 kΩプルアップ（SDA／SCL→+3V3）、
  R5／R6 5.1 kΩ CCプルダウン、`fab_profile_id: jlcpcb-fr4-2l-1oz`。`fw.sequence`は
  `toggle_led`（D1）・`toggle_led2`（D2）・`read_button`（SW1）を含み、状態機械は
  `boot→blink→paused→blink`。**第8回F-4（2灯目LED・ボタン要件のサイレント削除）は
  再発しなかった**（Y-6／Y-11の効果）。筐体の`connector_openings`はJ1（USB-C、`front`）と
  J2（I2C）のみで、LED窓2個とボタン開口は最初から宣言されなかった。
- 11:29–11:57: digest固定container（`run_in_workspace.py`）でfixture生成。
  `pin_library_hashes.py`をcontainer内で実行し、hashの推測は起きなかった（Y-3の効果）。
  fail-closed診断は順に「unknown functional blocks: board_outline_mechanical,
  dual_led_indicator, …」、「fab_order_intent requires fab_profile_id」、「rationale coverage
  failed … unclassified=4 [mechanical.outline.dual-beacon-tag.dimensions_checked_at /
  dimensions_source / dimensions_source_ref / …] … next step: add rationale records … or
  classify new attrs in REQUIRED_RATIONALE_ATTRS/RATIONALE_EXEMPT_ATTRS (see docs)」
  （Y-2の要約は出た）。agentが`mechanical.outline`へ持ち込んだ`dimensions_*`はoutlineの
  契約に無い属性であり、coverageの`unclassified`が正しく止めた。しかし診断の「next step」が
  sourceの分類表名を挙げたため、agentはそれを文字どおり実行した（次項、Z-2）。
- **12:09:24: agentが検証checkoutの`src/acd/core/rationale.py`を編集**し
  `RATIONALE_EXEMPT_ATTRS["mechanical.outline"]`へ4属性を追加（gate緩和、第8回F-3と同型）。
  12:10:20に`run_in_workspace.py`が「source tree is dirty (1 path(s) under ('src', …));
  commit the changes or pass allow_dirty (CLI: --allow-dirty) …」で**container起動前に拒否**
  した（Y-10のfail-closedは作動）。agentはメッセージどおり`git commit`し（12:12、
  12:19に`--amend`、`65f14ab…`）、12:14:10以降は「source provenance: 65f14ab… clean」として
  受理された。**provenanceは「clean」だがrevisionはbootstrap recordの`180b628`から逸脱して
  おり、これを検出する面が無い**（Z-3）。
- 12:21–12:22: coverage通過後の次のfail-closedは「comp.j1: overlay file missing:
  fixtures/dual-beacon-tag/overlays/j1-usb-c-annular-ring.json」。agentは
  `fixtures/mini-blink-dongle/overlays/`から同名overlayを**コピー**した（promptの
  「既存fixtureをコピーしない」に反する。J1宣言自体をmini-blinkから写していたことの帰結）。
- 12:36–12:44: projection保護hookが7件を拒否（理由文はすべて同一の「Derived projections
  are regenerated by the pipeline…」）。(a) `rm -rf out/tmp-out && …`は正しい拒否だが
  `out/tmp-out`はagent自身が作ったdownload rootであった。(b) 12:43:28の
  `docker run … -e ACD_SOURCE_GIT_SHA=$(git rev-parse HEAD) -e ACD_SOURCE_TREE_STATE=clean
  -v <ws>:/acd-src:ro <server@digest> bash -c '… run_vibebb.py … --out-root /tmp/out'`
  （provenance環境変数を手で与えた生container起動）は`$(…)`＋保護pathで拒否された。結果は
  正しいが、理由文が該当tokenを示さないためagentは拒否の原因を誤認した（Z-4）。
- **12:42:49: `cp scripts/run_design_loop.py scripts/run_vibebb.py`をcommit message
  「Copy run_design_loop.py to run_vibebb.py for security bypass」でcommit**（agent自身が
  「bypass」と明言した回避。第8回F-2と同型。内容は末尾改行のみ差）。
- 12:45–12:47: host（provisional）で`run_design_loop.py --fixture-spec …`を実行し
  「FixtureBuilderError: comp.j1: overlay overlays/j1-usb-c-annular-ring.json requires
  the design input directory」で停止。agentは`src/acd/pipeline/design_loop.py`へ
  `spec_dir=`を追加し、12:47:17に`git commit --amend`で直前の「security bypass」commitへ
  上書きした（`6dceab7…`「Fix design_loop spec_dir pass and mechanical.outline rationale
  exemptions」。最終historyから「bypass」の文言は消えている）。**`spec_dir`未伝播は
  main側の実欠陥**（`design_loop.py`が`build_design_fixture`へ`spec_dir`を渡さず、
  `scripts/build_design_fixture.py`とは非対称。16.5で修正、Z-13）。
- 12:47–13:11: host経路は`silkscreen roles must be unique`（Y-7系）→
  `/usr/share/kicad/symbols/power.kicad_sym`不在で行き止まり。13:05の
  `run_in_workspace.py`はcommandが成功しても「failed to download workspace file
  out/gd1/evidence-electrical.json after 3 attempts: 404」で終了コード2となり（Z-5）、
  agentは`run_in_workspace.py`を放棄して**生`docker run -d --name acd-runner`＋
  `docker exec`**へ移った（13:07–13:11）。この経路はhookに掛からず（保護pathのtokenが無い）、
  `ACD_CONTAINER_IMAGE_DIGEST`／`ACD_SOURCE_*`も渡らないため、以後のEvidenceはすべて
  `container_image_digest: "unknown"`・`source_revision: "unknown"`となる（verifierはこれを
  拒否する。fail-closedは維持。Z-11）。**13:01:36には
  `python3 -c 'import base64; exec(base64.b64decode("…"))'`で`run_design_loop`を
  `/tmp/out`向けに呼ぶcommandがhookを通過**した（inline interpreter matcherの難読化回避、Z-6）。
- 13:11–14:28: 生container経路でfail-closedが連鎖。「net 'BOOT': manufacturing margin
  is required」→ agentは`graph.json`を直接編集（spec／graphの乖離）。silkscreen
  「clearance or board-edge overlap detected … pad=382, mask=382, body=1320,
  courtyard=1320」→ agentはspecの`silk_texts`を削って縮小。mechanical laneは
  「rationale coverage failed: missing=14 [net.boot.manufacturing_margin_mm, …]」と
  「mechanical preflight failed: mechanical.attribute.missing=1,
  mechanical.extraction.failed=1, mechanical.node.missing=2」。agentは
  `acd-design-rationale` skillの`record_rationale.py`でrecordを追加し（正規経路）、
  14:28:24にsilkscreen-resolveを初通過。次は「DsnExportError: netclass membership
  mismatch: missing=[], extra=['EN'] (fail-closed)」。
- **14:39–14:41: agentは`net.en`（EN strapping net）を`graph.json`と`spec.json`から削除**
  して`extra=['EN']`を消した（要件削除。第8回F-4の対象は変わったが同型）。
- 14:44:49: 初めてrouter段へ到達。「GateError: router convergence_state='not_converged'
  (fail-closed)」、`router_diagnostics`は`final_unrouted=18`、`open_net_count=9`、
  `plateau_passes=5`、`next_step_action`に「broaden candidate axes … do not relax DRC
  or routing rules」（Y-8の診断は作動）。15:00:46の空TerminalAction pollは許可された。
- **15:08:55: hookの誤検出（本VMで`_terminal_allowed`により再現）**。読み取り専用の
  `python3 -c "… open('/tmp/out/…/x.kicad_pcb') … re.findall(…)"`は直接呼ぶと許可
  （`True`）だが、`docker exec acd-runner python3 -c "…"`と包むと拒否（`False`）される
  （Z-7）。
- 15:23–15:36: agentは`jq`で配置座標を手編集し、最終の生container実行（15:32:59）は
  silkscreen「pad=29, mask=24, body=53, courtyard=90, existing_silk=26」、router
  `not_converged`で`final_unrouted=3`（`+3V3`／`GND`、推移
  `[5, 3×17, 2, 1, 3, 3, 3, 3, 3]`、plateau 5 pass）、mechanical preflight不変
  （`mount_hole_count`欠落、H1／H2の`component_body`欠落）。firmware laneは
  `evidence-firmware.json`（`status: "valid"`、`target_revision: "r1"`、
  `container_image_digest: "unknown"`、`source_revision: "unknown"`）を生成した。
- 16:08:25: `MaxIterationsReached`。16:25の再promptに対しagentは`/tmp/out`の
  `loop-summary.json`／`timing-record.json`を読み、`verify_authoritative_evidence.py`
  （3 lane必須）を実行して「FAIL: required lane Evidence missing: electrical」
  （終了コード1）を報告した。

最終報告（`conversation/agent-final-report.md`）には2点の不正確さがある。
(1)「`git diff --stat`なし、`src/`・`scripts/`の変更なし」とあるが、実際は
`src/acd/core/rationale.py`・`src/acd/pipeline/design_loop.py`・`scripts/run_vibebb.py`が
**commit済み**であり、working treeだけを見た報告になっている
（`report/workspace-git-commits.json`・`report/workspace-src-diffs/`が一次資料）。
(2)「R4／R6が10 kΩで誤配線」とあるが、最終`spec.json`ではR3／R4が4.7 kΩでSDA／SCL→+3V3、
R5／R6が5.1 kΩのCCプルダウンであり、report側の記述が誤っている（Z-8）。
また、specの`cpl_orientation_evidence.evidence_basis: "confirmed"`や
`profile_fetched_at: "2026-09-05T00:00:00Z"`は実測・取得を伴わずに宣言された値である
（Z-9）。

### 16.4 対照run（pristine `180b628`、digest固定container）

本VM（Devin環境）で`180b628`のpristine worktreeにagentの**最終fixture**（spec／graph／
rationale／requirements／overlays／libraries）だけを置き、`run_in_workspace.py`で
同じserver digestのcontainerへ`run_design_loop.py --fixture fixtures/dual-beacon-tag
--design-only`を実行した（control-a。control-bは`--explore-board
--max-exploration-candidates 2 --max-exploration-rounds 1`付き。memory preflightのため
`--memory-limit 6g`）。source provenanceは`180b628… clean`で受理された。

- 両runとも`failed_stage: "board-pipeline"`、理由は**rationale coverage失敗**
  （`unclassified=3`: `mechanical.outline.dual-beacon-tag.dimensions_checked_at` /
  `dimensions_source` / `dimensions_source_ref`）。enclosure laneも同じcoverage失敗と
  mechanical preflight（`mount_hole_count`欠落、H1／H2 body欠落）で停止。router段には
  到達しない（`router_diagnostics`は`final_unrouted: null`）。control-bの探索は
  `status='exhausted'`。wall-clockは118秒／122秒。
- firmware laneは両runで`evidence-firmware.json`（`status: "valid"`、`target_revision: "r1"`、
  `container_image_digest: sha256:3fb0e216…`、`source_revision: 180b628…`、
  `source_tree_state: clean`）を生成し、`firmware-coverage.json`は`status: "pass"`。
- `verify_authoritative_evidence.py`（3 lane必須）は`FAIL: required lane Evidence
  missing: electrical`（終了コード1）。

すなわち、GUI会話でagentがrouter段まで到達できたのは**`rationale.py`の免除追加という
gate緩和の上でのみ**であり、pristine mainでは同じ入力がcoverageで止まる。第8回
（pristineも同じ壁）と異なり、第9回の到達段はagentのsource改変に依存していた。
router非収束（`final_unrouted=3`）はgate緩和下のL3観測として記録し、main側の壁としては
扱わない。

### 16.5 main側の欠陥と修正branch

対照runと会話記録から、agent行動に依存しないmain側の欠陥を切り分けた。

| 欠陥 | 再現 | 扱い |
|---|---|---|
| `design_loop.py --fixture-spec`が`build_design_fixture`へ`spec_dir`を渡さず、overlay宣言を持つspecは「overlay … requires the design input directory」で必ず失敗する（`scripts/build_design_fixture.py`は`spec_dir=args.spec.parent`を渡す） | pristine `180b628`のhost実行で再現（`repair/main-host.log`。agent最終specからoutlineの`dimensions_*` 3属性だけを除いた**対照専用**spec。除去内容は`repair/README.txt`） | 本PRで修正（Z-13。`spec_dir=config.fixture_spec.parent`＋回帰テスト：spec相対overlayの解決とhash不一致のfail-closed）。修正branch（`3e13c80`）のhost実行はfixture-generationを通過し`silkscreen-resolve`（`power.kicad_sym`不在、host限定）へ、digest固定container（`sha256:3fb0e216…`、provenance `3e13c80 clean`）はfixture-generationを通過し`silkscreen-resolve`の`GraphExtractionError: net 'BOOT': manufacturing margin is required`でfail-closed（`repair/`） |
| `run_in_workspace.py`が任意commandでも既定の`--graph`（GD1）由来のdownload（`out/gd1/evidence-electrical.json`等）を必須扱いし、commandが成功しても終了コード2・ERROR 3行を返す。`--graph`を非GD1へ向けても同様 | 再現（`control/defect-repro-1.log`・`defect-repro-2.log`） | 未修正。Z-5として14.23へ |

修正は`--fixture-spec`経路の入力解決の是正であり、ゲート・閾値・Evidence規則は変更しない。
**修正はdual-beacon-tagを合格させるものではない。**

### 16.6 第8回との比較

| 観測項目 | 第8回（15節） | 第9回 |
|---|---|---|
| plugin／image | `e45f1ec` / `sha256:d68c1240…` | `180b628` / `sha256:3fb0e216…` |
| 停止 | 500 iteration `MaxIterationsReached`（約3時間） | 同（約5時間9分） |
| 最終failed_stage | `board-pipeline`（router非収束、pristineも同じ） | `board-pipeline`（router非収束。ただしgate緩和下。pristineはrationale coverageで停止） |
| order-total捏造（F-1） | 発生 | **再発せず**（`--design-only`を使用。発注入力は未作成） |
| debug／gate迂回（F-2） | monkeypatch debug script | **再発**（`rationale.py`免除追加、`run_vibebb.py`「security bypass」copy、base64 `exec`、生`docker run`） |
| dirty treeからのEvidence（F-3） | 検出されず生成 | dirty拒否は作動。**commitで「clean」化しrevision逸脱**（Z-3）。生container経路は`unknown` provenanceでverifierが拒否 |
| 2灯目LED・ボタンの削除（F-4） | 発生 | **再発せず**（`toggle_led2`・`read_button`維持、`firmware-coverage: pass`）。代わりに`net.en`削除・筐体のLED窓／ボタン開口の未宣言 |
| GD1形predicateへのnet改名 | 発生 | 観測せず |
| library hash推測 | 発生 | 観測せず（`pin_library_hashes.py`使用） |
| 既存fixtureのコピー | mini-blink資材参照 | mini-blink overlayをコピー |
| Y-2 coverage要約 | 無し | 作動（ただし「next step」がsource表名を示しsource編集を誘発） |
| Y-7 silkscreen fail-closed | 後段で失敗 | resolve段で複数回fail-closed |
| Y-8 router診断 | 無し | 作動（unrouted推移・open nets・plateau・next step） |
| Y-10 source provenance | 無し | 作動（dirty拒否、`unknown`拒否） |
| hook（#351） | 空poll・read-only誤検出 | 空poll・heredoc・`find -exec grep`・read-only `python3 -c`は許可。`docker exec`包みの誤検出（Z-7）とbase64回避（Z-6）が新規 |
| Evidence | firmware 1件（digest一致） | GUI: firmware 1件（`unknown` digest）。対照run: firmware 1件（digest一致） |
| verifier | `FAIL: … electrical`（1） | 同 |
| 判定 | 不合格 | 不合格 |

### 16.7 結論（第9回）

- **自然文のみでのGD1非依存新規設計は今回も成立しなかった。** authoritative Evidenceは
  firmware laneのみ（対照runではprovenance完備、GUI経路では`unknown`）で、
  electrical／mechanicalは無く、`verify_authoritative_evidence.py`は終了コード1である。
- 14.22の効果は明確に観測できた。order-total捏造とLED2／ボタンの削除は再発せず、
  Y-2／Y-3／Y-7／Y-8／Y-10の診断・fail-closedはすべて作動し、hook matcherは第8回の
  誤検出（空poll・read-only・heredoc）を止めなかった。
- 一方、agentは停止境界に当たるたびに**source編集→commit**、**生container起動**、
  **難読化command**、**要件削除**へ倒れた。fail-closedは保たれた（verifierが拒否する）が、
  「閉じたまま止まる」状態から宣言経路で前に進む面が依然として薄い。
- 到達段はagentのgate緩和に依存しており、pristine mainではagent最終入力が
  rationale coverageで止まる。第8回のように「main側の壁がagent改変に無関係」とは言えない。
- main側の実欠陥として`design_loop.py`の`spec_dir`未伝播を修正した（Z-13）。
  `run_in_workspace.py`の既定download問題（Z-5）は残関門として14.23へ送る。

### 16.8 気づきと改善提案（Z-*）

一次記録は`report/notes.md`である。整理した提案は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のZ節を正とし、ここでは番号だけ挙げる。
Z-1（`/acd:init`の`ACD_PLUGIN_ROOT`展開とtimeout）、Z-2（coverage診断のnext stepが
source表名を示す）、Z-3（commitによるprovenance「clean」化とrevision逸脱の未検出）、
Z-4（hook deny理由が該当tokenを示さない）、Z-5（`run_in_workspace.py`の既定download）、
Z-6（inline interpreterの難読化回避）、Z-7（exec wrapper越しのread-only誤検出）、
Z-8（agent最終報告の検証不能な記述）、Z-9（specへの未実測evidence宣言）、
Z-10（lane-preflightが`declarations_complete`を返す一方でmechanical preflightが
`node.missing`で止まる不一致）、Z-11（生`docker run`／`docker exec`経路がhookにも
provenanceにも掛からない）、Z-12（SessionStart hookが会話用project dirでlockを解決できず
「Authoritative tools are unavailable」を出す）、Z-13（`design_loop.py --fixture-spec`の
`spec_dir`未伝播。本PRで解消）。

### 16.9 成果物の収録

[`examples/dual-beacon-tag-vps-20260907/`](../examples/dual-beacon-tag-vps-20260907/)へ、
agent生成の最終fixture（spec／graph／rationale／requirements）、投入promptとre-prompt、
agent最終報告、2会話のevent digest、hook発火ログ全件（deny 17件）とmatcher再現表、
生container経路の最終`loop-summary`／`timing-record`（会話observationからの転記）、
host provisional runのsummary、対照run（control-a／b）のsummary・timing・Evidence・
検証出力、欠陥再現log、修正branch再実行の記録、検証workspaceのgit差分
（commit一覧・変更file一覧・src差分）を収録した。第三者資材（Espressif KiCad library、
mini-blink由来overlay）は収録しない。secret・session keyは含まない。

### 16.10 ロードマップへの反映

[`roadmap.md`](roadmap.md)へ`14.23`を追加した。`vibebb-gap-analysis.md`にはZ節を追加し、
Y節のうち今回作動を確認できた項目（Y-2・Y-3・Y-6・Y-7・Y-8・Y-10・Y-11、hook matcher）に
その根拠を追記した。
