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
