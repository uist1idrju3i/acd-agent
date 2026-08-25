# 検証レポート: VibeBBのacd-agent単体成立性（実機OpenHands・新規設計 pulse-check-tag）

本書は、Devin固有の支援機能を使わず、ユーザーの実機OpenHands環境と`acd-agent` pluginだけで
VibeBB（Vibe BreadBoarding）が成立するかを検証した結果の報告である。設計の投入・ゲート実行・
判定はすべて実機OpenHandsのagentが行い、Devin側は会話の送受信と実行記録の収集・分類に限った。

- 検証日: 2026-08-25（UTC）
- 実行主体: 実機OpenHands + ACD plugin（**Devinはゲート実行と判定を代行していない**）
- workspace: `test5`（`git clone`は使わず`/acd:init`で初期化）
- 対象revision: `4b689fece94d82285312b5c7b36a7795ad617cbf`
  （plugin resolved ref、workspaceのcheckout、repository `main`先端の3者一致を確認）
- plugin source: `github:uist1idrju3i/acd-agent`
- 題材: 新規小規模設計`pulse-check-tag`（revision `r1`、MCUはGD1と同じ`ESP32-C3-MINI-1`）
- 実発注、見積取得、supplier API呼び出し、決済、注文確定: **いずれも未実施**
- 実行環境の識別情報（ホスト名、ドメイン、エンドポイント、ユーザー名、鍵、token）は
  本書および本フォルダに含めない

## 1. 結論

1. **要件宣言からfixture graph生成、silkscreen laneのcontainer合格までは、acd-agent単体で
   成立した。** 前回検証（`mini-blink-dongle`／workspace `test4`）で最大の障害だった
   「`DesignFixtureSpec`がmechanical・silkscreen・firmware moduleを宣言できない」（N-1）と
   「U1のIO-to-pad mappingを宣言経由で与えられない」（N-5）は解消しており、GD1以外の設計でも
   laneの入口に到達できるようになっている。
2. **FW laneはGD1専用の実装で止まる。** MPN宣言の不足を補った後、
   `plugins/acd/skills/acd-firmware-esp32c3/scripts/fw_project.py`が`_REQUIRED_NETS`として
   GD1のnet集合（I2C・UARTを含む）を定数で持つため、センサを持たない`pulse-check-tag`では
   `no firmware pin assignment for net 'net.i2c_sda'`でfail-closedした。生成される`main.c`も
   GD1固定（SHT40読み出し）であり、設計内容に依らず他設計のfirmwareは生成できない
   （[`improvement-notes.md`](improvement-notes.md) Q-10）。設計側にI2C netを宣言させれば入口は
   通るが、設計意図の改変になるため採らなかった。
3. **基板lane以降は通過していない。** digest固定container内のFreeRoutingが、pass予算
   `--max-passes 99999`（CLI既定）でも`--max-passes 10`でも`run_tool`の固定600秒timeoutに達し、
   fail-closedで停止した。`convergence_state`が`converged`になった証拠は存在しない。
4. **筐体lane・order-total・pre-orderゲートも、いずれも合格に到達しない。** 筐体laneは
   entrypointが`scripts/run_gd1_enclosure_pipeline.py`固定で、`pulse-check-tag`には
   `mechanical.enclosure`／`mechanical.component_body`ノードが無く、入口の
   `validate_and_project_rationale`で`rationale coverage failed: missing=94`となった。
   order-total集約は必須入力`--quote-record`（`QuoteRecord`）と`OrderScope`が
   fixtureに存在せず実行できない。pre-orderゲートはorder-totalが無いため入力欠損で停止し、
   `plugins/acd/hooks/order-policy.json`の`required_evidence_ids`と`design_graph_paths`も
   GD1固定である（§4-2、Q-12）。
5. **authoritative Evidenceは1件も成立していない。** silkscreen laneはdigest固定container内で
   `status: "resolved"`まで到達したが、これはresolverの出力であってrevision一致・
   `status="valid"`のauthoritative Evidence（`evidence-electrical.json`／
   `evidence-mechanical.json`相当）ではない。したがって「acd-agent単体でVibeBBを実現できた」とは
   結論できない。
6. **fail-closedは全段で正しく働いた。** 属性不足、`unknown`、library不足、timeoutのいずれも
   合格側へ倒れず、11件の設計不足を順に検出した（§5）。本検証で閾値・期待値・evidence規則を
   緩めた箇所は無い。
7. **実機側の実行基盤も律速である。** container gate実行中にOpenHands側で
   `A restart occurred while this tool was in progress`（fatal memory error / system crash）が
   4回以上発生し、そのたびにSSHが数分〜数十分不応答となり、最終的にOpenHandsサーバプロセス
   自体が停止した。container既定メモリ上限8 GiBに対しホスト実装容量が足りていない
   （[`improvement-notes.md`](improvement-notes.md) Q-2）。

## 2. 題材とGD1との差分

GD1（golden-design-1）のgraphをコピー・改名したものではなく、自然文要件から新規に宣言した
小規模設計である。MCUのみGD1と同一とした。

| 項目 | pulse-check-tag | GD1 |
|---|---|---|
| MCU | ESP32-C3-MINI-1（同一） | ESP32-C3-MINI-1 |
| 機能 | 起動時にLEDを1回点灯、通常は120 ms／1000 msの点滅、tact switch押下で周期をtoggle | センサノード（SHT4x、I2C、UART） |
| センサ・I2C | なし | SHT4x（I2C） |
| 入力 | tact switch 1個 | GD1構成 |
| 表示 | 緑色LED 1個 | LED |
| LED直列抵抗 | 2.2 kΩ | 1 kΩ |
| 電源 | USB Type-Cバスパワー5 V＋3.3 V LDO 1個。battery・充電回路・USB PD negotiationなし | 同系だが構成差あり |
| 部品点数 | 10点前後 | 30 |
| 外形 | 22 × 16 mm（2層） | 30 × 25 mm（2層） |
| silkscreen | 設計名とrevisionを記載 | GD1のsilk宣言 |
| GPIO制約 | ESP32-C3のboot/strapping pinをLED・switchへ割り当てず、選択理由をrationaleへ記録 | GD1 fixtureはIO7を使用 |

前回検証の`mini-blink-dongle`（workspace `test4`）とも別題材である（外形・部品構成・
点滅仕様・抵抗値・GPIO割当が異なる）。

## 3. 初期化とdoctor

| 段 | 実行 | 結果 |
|---|---|---|
| plugin ref照合 | plugin resolved refとworkspace checkout、`main`先端 | 一致 |
| `/acd:init`（引数なし） | 必須引数の不足を報告 | 正しい入力検証（fail-closed） |
| `/acd:init`（`--repo-url`／`--revision`／`--workspace`指定） | checkout、submodule初期化、`uv sync`、plugin load | 成功 |
| `/acd:doctor`（初回） | lock済み`acd-tools` imageがローカルに無い、`IDF_PATH` unset、`qemu-system-riscv32` unavailable、`cmake` unavailable | fail-closed（doctorは自動pullしない） |
| digest固定imageのpull（ユーザー承認のうえ実施） | `acd-tools`／`acd-server`をdigest指定でpull | 両方とも取得済み状態 |
| `/acd:doctor`（pull後） | lock済みimage可用性はpass。host側のFW前提（`IDF_PATH`／`qemu-system-riscv32`／`cmake`）は依然fail | authoritative経路は充足、provisional経路は不足 |

doctorが自動pullしない挙動、および未取得を`unknown`扱いでfail-closedにする挙動は
`AGENTS.md`の不変条件と整合する。一方で、host前提とcontainer前提が同じ失敗欄に混ざるため
「authoritative経路が充足したのか」が読み取りにくい（Q-6、Q-7）。

## 4. lane別の実行結果

すべてのauthoritative候補実行は、`docker/image-digests.json`のlock値
（`acd-server`、digest `sha256:a5e6a23…48bbedd`）を`scripts/run_in_workspace.py`経由で
起動して行った。実行logにはimage digestが`RepoDigests`由来として記録されている。

| lane | 実行経路 | 結果 | 分類 |
|---|---|---|---|
| fixture生成 | host（`build_design_fixture.py`） | 初回は`comp.d1`の`value`欠落で停止、宣言修正後に生成成功 | provisional（生成物であり判定ではない） |
| preflight | host | `board-pipeline: ready`／`firmware-pipeline: ready`／`silkscreen-resolve: ready`／`rationale coverage: pass` | diagnostic observation（L1判定ではない。なお`rationale coverage`はhook側の固定パス判定であり対象設計を見ていない。Q-13） |
| silkscreen resolve | digest固定container | `status: "resolved"`（11件のfail-closedを解消した後） | container実行の成功。authoritative Evidenceそのものではない |
| 基板 | digest固定container（`--max-passes 99999`＝CLI既定） | `PIPELINE FAILED (fail-closed)`: FreeRoutingが600秒でtimeout | fail-closed（未合格） |
| 基板 | digest固定container（`--max-passes 10`） | 同じく600秒でtimeout、exit code 1 | fail-closed（未合格） |
| FW | digest固定container（`--memory-limit 1g`） | `PIPELINE FAILED: node 'comp.c1': attr 'mpn' missing or not a string`（宣言不足）。MPNとrationaleを補った後は`PIPELINE FAILED: no firmware pin assignment for net 'net.i2c_sda'` | fail-closed（未合格。後者はlane実装側のGD1固定が原因、Q-10） |
| 筐体 | digest固定container（`--memory-limit 1g`） | `PIPELINE FAILED (fail-closed): rationale coverage failed: missing=94, stale=0, orphan=0, conflicting=0, unknown_provenance=0, untraceable=0, unclassified=0`、exit code 1 | fail-closed（未合格。entrypointがGD1固定、Q-12） |
| order-total集約 | host（`aggregate_order_total.py`） | 必須引数`--quote-record`の不足で実行拒否、exit code 2 | fail-closed（未合格。入力`QuoteRecord`／`OrderScope`が存在しない） |
| pre-orderゲート／order readiness | host（`pre_order_gate.py --check-only`） | `could not parse order total`、exit code 2 | fail-closed（未合格。order-total未生成、policyもGD1固定） |
| 実発注・見積・supplier API・決済 | — | **未実施**（ユーザーが実施予定） | 対象外 |

## 4-2. 筐体・order-total・pre-orderの実行結果

基板・FW laneに続き、残る3段をdigest固定container（筐体）とhost（集約・ゲート）で実行した。
いずれも合格しておらず、Evidenceも生成されていない。

| 段 | 到達stage | fail-closedメッセージ | 直接原因 |
|---|---|---|---|
| 筐体lane | `validate_and_project_rationale`（`[0/5]`の前） | `rationale coverage failed: missing=94, stale=0, orphan=0, conflicting=0, unknown_provenance=0, untraceable=0, unclassified=0` | `scripts/run_design_lanes.py`は`enclosure`に対し`scripts/run_gd1_enclosure_pipeline.py`（docstringは`Golden Design #1 mechanical pipeline`）を固定で呼ぶ。`pulse-check-tag`には`mechanical.enclosure`・`mechanical.component_body`ノードが無く、`mechanical.outline`にも`mount_hole_count`が無い。加えてgraph全体で94件のrationaleが不足している |
| order-total集約 | なし（引数検証） | `aggregate_order_total.py: error: the following arguments are required: --quote-record/--quote` | 必須入力の`QuoteRecord`（部品原価、PCB／PCBA見積、筐体費用）と`OrderScope`が`fixtures/pulse-check-tag`配下・`evidence/`・`out/`のいずれにも存在しない。実見積を取得しない条件では生成経路が無い |
| pre-orderゲート | なし（order-total読込） | `could not parse order total` | order-totalが無い。さらに`plugins/acd/hooks/order-policy.json`は`required_evidence_ids`を`["evidence.gd1.electrical", "evidence.gd1.mechanical"]`、`design_graph_paths`を`["fixtures/golden-design-1/graph.json"]`で固定しており、GD1以外の設計は発注可否判定の対象にならない |

筐体laneの不足を埋めるには機械設計ノードと94件のrationaleを新規宣言する必要があるが、
部品寸法・筐体構成の実データが無い状態でこれを埋めることは架空宣言の追加になるため行わなかった。
またorder-total集約はダミー値を作らず未生成のまま記録した（ゲート側は不正な入力を
`could not parse order total`で正しく拒否した）。

## 5. fail-closedの検出列（設計入力の不足）

silkscreen laneと基板lane入口で、次の順に1件ずつ検出された。いずれも設計入力へ不足属性を
追加して解消しており、閾値・期待値・evidence規則の緩和は行っていない。

1. `node 'mechanical.silk_text.board_id': attr 'rotation_deg' missing or invalid`
2. `node 'fab.order_intent.pulse-check-tag': attr 'pcba_class_target' missing or invalid`
3. `C1: graph placement is missing or malformed`
4. `pinned library file missing: out/pulse-check-tag-silkscreen-resolve/work-fixture/libraries/Espressif.kicad_sym`
5. `outer copper thickness must be positive (fail-closed)`
6. `incomplete stitch-via basis declaration (fail-closed)`
7. `IPC-2221 constants are incomplete (fail-closed)`
8. `net 'CC1': manufacturing margin is required`
9. `functional block node 'fb.esp32c3_strapping_boot' must reference a driving requirement`
10. `power_boundary: status='unknown'`（radio module declarationの欠落、safety boundary nodeの欠落・曖昧）
11. `silkscreen text 'mechanical.silk_text.board_id' has no declared position (fail-closed)`

このうち10は`unknown`をそのままfail-closedにしており、L1契約どおりの挙動である。

## 6. 基板laneのtimeoutの解析

```text
PIPELINE FAILED (fail-closed):
Command '['freerouting', '-de', '.../pulse-check-tag.dsn', '-do', '.../pulse-check-tag.ses',
 '-mp', '10', '-mt', '1']' timed out after 600 seconds
```

- `src/acd/core/process.py`の`run_tool`はsubprocess timeoutを`600`の定数で持ち、呼び出し側から
  変更できない。
- `src/acd/pipeline/gd1_board.py`のCLIは`--max-passes`の既定を`99999`とし、
  `src/acd/adapters/freerouting/router.py`の関数既定（`100`）と桁違いに異なる。
- FreeRoutingは指定passを消費し切るまで走るため、10部品・22 × 16 mm・2層という最小規模でも
  600秒に達した。pass予算を10へ絞っても結果は変わらなかった。
- したがって現状の既定値の組み合わせでは、**基板laneは設計規模に依らず通らない**構造にある
  （Q-1、Q-9）。

なお、`--max-passes`はCLIが公開する正規のpass予算指定であり、これを変更することはゲート閾値や
evidence規則の緩和には当たらない。`convergence_state`が`converged`でない限り合格として扱って
いない点は本検証を通じて維持した。

## 7. Evidenceの分類

| 成果物 | 実行主体 | 分類 |
|---|---|---|
| silkscreen resolverの`status: "resolved"`出力とKiCad投影 | digest固定container | container実行の成功記録。authoritative Evidenceではない |
| 基板laneのtimeout記録（exit code 1、image digest付き） | digest固定container | fail-closedの記録（不合格） |
| fixture生成物、preflight出力、rationale coverage | host | provisional／diagnostic observation |
| doctor出力 | host | L3観測 |
| `evidence-electrical.json`／`evidence-mechanical.json`相当 | — | **存在しない** |
| order-total、order readiness判定 | — | **未実行** |

「container内で実行した」ことは`authoritative`の必要条件だが十分条件ではない。revision一致と
`status="valid"`のEvidenceが無い段階で合格と読んではならない。

## 8. 実行基盤側の障害（今回の律速）

- container gate実行中に、OpenHands側へ次が記録された（4回以上）。

  ```text
  A restart occurred while this tool was in progress.
  This may indicate a fatal memory error or system crash.
  The tool execution was interrupted and did not complete.
  ```

- そのたびにホストのsshdが数分〜数十分不応答になり（ICMPは応答）、最終的にOpenHands
  サーバプロセス自体が停止した。
- 停止の原因はホスト全体のOOMであることが、ユーザーから提供された`dmesg`で確認できた。
  観測事実は次のとおりである（推測ではない）。

  ```text
  oom-kill:constraint=CONSTRAINT_NONE,...,global_oom,
    task_memcg=/system.slice/docker-<container>.scope,task=java
  Out of memory: Killed process <pid> (java) total-vm:5288716kB, anon-rss:448604kB
  Out of memory: Killed process <pid> (java) total-vm:5287692kB, anon-rss:593664kB
  ```

  `constraint=CONSTRAINT_NONE` かつ `global_oom` であり、cgroup上限による局所OOMではなく
  ホスト全体のメモリ枯渇である。kill対象にはcontainer内の`java`（FreeRouting）2プロセスに加え、
  `dbus-daemon`、`systemd`、`node`、`python`が含まれ、OpenHandsとsshdが不応答になった事象と整合する。
- FreeRoutingを直接投入した診断実行のlogは`Docker workspace is ready`の直後で途切れており、
  router出力（所要時間・unrouted数）は記録されていない。log中のcontainer IDは、上記OOM
  メッセージの`docker-<container>.scope`と同一である。すなわちこの診断は「timeoutした」のではなく
  「ホストOOMでkillされた」ため、収束特性の実測値は得られていない。
- 実行環境の実測値: メモリ実装 1641 MiB、swap 5116 MiB、CPU 3コア、ルートFSは十分な空き。
- 一方、`src/acd/openhands/container_runtime.py`の既定は`DEFAULT_MEMORY_LIMIT = "8g"`であり、
  実行logのとおり`docker run --memory=8g --memory-swap=8g`で起動される。この上限は
  ホストのメモリ＋swap合計（約6.6 GiB）を超えており、container側の上限では抑止されない。
  さらにFreeRoutingのJVMは最大ヒープを明示していないため、JVMのcontainer-aware既定
  （上限の約1/4＝約2 GiB）を採り、実装メモリ1.6 GiBに対して過大な要求になる。
  ホスト資源との整合は起動前に検査されていない（Q-2）。
- 対策として、laneをforegroundで待たず`nohup ... > logs/<lane>.log 2>&1 &`のbackground＋log
  方式へ切り替えた。これにより再起動後もexit code、image digest、fail-closed理由をlogから
  復元できた（Q-3）。

## 8-2. hookによる正規操作の拒否

FW laneの再実行時に、次のhook拒否が観測された。

```text
rejection_source: hook
rejection_reason: Derived projections are regenerated by the pipeline;
  edit design inputs (graph.json / profiles) instead.
```

`plugins/acd/hooks/scripts/protect_projections.py`はコマンド文字列中の`out/`配下トークンを
検出してdenyするため、laneの正規の出力先指定（`--out out/<lane>`、`--download out/<lane>/...`）が
拒否される。同じ規則により、`stop_policy.py`が要求する`out/stop-report.json`への記録も
拒否される。すなわちfail-closed状態を宣言して停止する規定経路が、もう一方のhookで塞がれている。

hook scriptへ直接payloadを与えた検査（host実行、参考値）では、`bash -c "..."`のように内側を
1トークンへ包むと同じ内容がallowになった。誤検出と迂回可能性が同時に成立している
（[`improvement-notes.md`](improvement-notes.md) Q-11）。本検証ではguardを迂回する書き換えは
行わず、拒否の事実を記録として残した。

## 9. 未検証項目

- 新規設計のauthoritative Evidence生成（基板・筐体・FWのいずれも未成立）。
- FreeRoutingの収束実測（`-mp 1`直接実行による所要時間とunrouted数の推移は未取得）。
- FW laneのビルドとQEMU仮想実行（`[1/5]`にも到達しておらず、`[2/5]`〜`[5/5]`は未実行）。
- 筐体laneの`[1/5]`以降（入口のrationale被覆で停止）。
- order readinessの判定表示（order-totalが生成できないため、判定そのものを表示できていない）。
- 実発注、見積取得、supplier接続、決済（ユーザーが実施予定であり、本検証では対象外）。
- 自然文要件から`DesignFixtureSpec`への変換の決定論的検証（この工程は現状L2に依存する）。

## 10. 改善提案

13件を[`improvement-notes.md`](improvement-notes.md)へQ-1〜Q-13として整理した。優先度上位は次の6件。

1. `run_tool`のtimeoutを引数化し、`--max-passes`の既定値を単一定数へ集約する（Q-1、Q-9）。
   現状の既定値では基板laneが規模に依らずtimeoutする。
2. container起動前にホスト資源（メモリ・swap・ディスク）を検査し、既定メモリ上限が容量を
   超える場合はfail-closedにする。doctorへも同項目を追加する（Q-2）。
3. FW laneの必要netと生成codeをGD1固定の定数からgraph宣言由来へ移す（Q-10）。
   現状はI2C／UARTを持たない設計のfirmwareを生成できない。
4. projection guardの対象を生成物への書き込みに限定し、laneの出力先指定と
   `out/stop-report.json`の記録を許可する（Q-11）。現状は規定の停止経路が塞がれ、
   引用を変えると迂回できる。
5. 筐体lane entrypointと発注policyのGD1固定を解消し、order-totalの入力（`QuoteRecord`／
   `OrderScope`）を設計から導出できるようにする（Q-12）。現状はGD1以外の設計が
   order readiness判定に到達できない。
6. lane必須宣言の一括preflightを、各laneの入口検査と同一述語で提供する（Q-4、Q-5）。
   現状は11往復のcontainer起動を要し、Q-2のクラッシュリスクを往復ごとに引く。
