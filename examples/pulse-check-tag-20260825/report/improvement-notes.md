# 気づきと改善提案（pulse-check-tag 実機検証）

実機OpenHands（workspace `test5`）で新規小規模設計`pulse-check-tag`を投入した検証
（[`devin-report.md`](devin-report.md)）で観測した課題を、優先度順に整理する。

前回検証（`mini-blink-dongle`、workspace `test4`）で挙げたN-1〜N-12のうち、
宣言経路（N-1）とpin function展開（N-5）は解消済みであることを本検証で確認した
（silkscreen laneがcontainer内でauthoritative候補として`resolved`まで到達した）。
本書のQ-1〜Q-11は、その先で新たに顕在化した課題である。同じ内容を根拠・依存・完了条件付きで
[`docs/vibebb-gap-analysis.md`](../../../docs/vibebb-gap-analysis.md)のO節（O-1〜O-11）へ記録し、
実装計画としては[`docs/roadmap.md`](../../../docs/roadmap.md)の14.14と15.14〜15.16へ割り当てた。
対応は Q-1→O-1、Q-2→O-2、Q-3→O-3、Q-4→O-4、Q-5→O-5、Q-6→O-6、Q-7→O-7、Q-8→O-8、Q-9→O-9、Q-10→O-10、Q-11→O-11 である。
いずれも既存の閾値、ゲート挙動、fail-closed境界、L1の合否権限を緩める提案は含まない。

| 本書 | 種別 | 影響 |
|---|---|---|
| Q-1 | ゲート実装 | 小規模基板でも基板laneが必ずtimeoutでfail-closedになる |
| Q-2 | 実行基盤 | container gate実行が実機のメモリ容量を超え、OpenHands自体が落ちる |
| Q-3 | 運用手順 | 長時間laneをforegroundで待つと再起動で全損する |
| Q-4 | 診断 | preflightの`ready`が実ゲート結果と乖離する |
| Q-5 | 診断 | 必須属性不足が1件1往復で報告され、11回の往復を要した |
| Q-6 | doctor | host前提とcontainer前提が同じ失敗欄に混ざる |
| Q-7 | doctor | lock済みimage未取得が常に初回fail-closedになる |
| Q-8 | 記録 | 実行記録の収集入口がlane logと実機workspaceを対象にしていない |
| Q-9 | 契約 | `--max-passes`の既定値がlayerごとに異なる |
| Q-10 | ゲート実装 | FW laneがGD1のnet集合とGD1のapplication codeを定数で持ち、他設計では通らない |
| Q-11 | hook契約 | projection guardがlane起動コマンドとstop reportの記録をdenyし、引用を変えると通る |

## Q-1 FreeRoutingの固定600秒timeoutとpass予算の既定値の組み合わせ（最優先）

`src/acd/core/process.py`の`run_tool`は`subprocess.run(..., timeout=600)`を**定数**で持ち、
呼び出し側から変更できない。一方`src/acd/pipeline/gd1_board.py`のCLIは

```python
parser.add_argument("--max-passes", type=int, default=99999, help="router pass budget")
```

を既定とし、`src/acd/adapters/freerouting/router.py`は`-mp <max_passes>`をそのまま
FreeRoutingへ渡す。FreeRoutingは指定passを消費し切るまで走るため、pass予算が実質無限だと
**必ず**600秒に達し、

```text
PIPELINE FAILED (fail-closed):
Command '['freerouting', '-de', ..., '-mp', '99999', '-mt', '1']' timed out after 600 seconds
```

になる。本検証の`pulse-check-tag`は10部品・22×16 mm・2層という最小規模で、
`--max-passes 10`へ落としても同じく600秒でtimeoutした。つまり現状の既定値では
**基板laneは規模に関係なく通らない**。

提案:

- `run_tool`へ`timeout`引数を追加し、laneから明示的に渡す（既定は現行の600秒を維持）。
  timeoutは判定閾値ではなく実行上限なので、明示化してもfail-closed契約は変わらない。
- timeout時のEvidenceに`convergence_state="timeout"`相当の区別を残し、`unknown`と
  混ぜない。どちらも不合格である点は変えない。
- `--max-passes`の既定を有限かつ実測に基づく値へ変更する（`router.route()`の既定は
  すでに100であり、CLIの99999だけが外れ値である。Q-9参照）。
- FreeRoutingのpass進捗（unrouted数の推移）をL3 recordへ記録し、timeoutが
  「収束しない」のか「時間が足りない」のかを区別できるようにする。

## Q-2 container gateの既定メモリ上限が実機容量を検査せずに適用される（最優先）

`src/acd/openhands/container_runtime.py`は

```python
DEFAULT_MEMORY_LIMIT: Final = "8g"
```

を既定とし、`--memory=8g --memory-swap=8g`を付けて`docker run`する。実機の実測値は
メモリ実装 1641 MiB、swap 5116 MiB、CPU 3コアであり、要求上限8 GiBはメモリ＋swap合計
（約6.6 GiB）を超える。したがってcontainer側の上限では抑止されない。
本検証では、container gate実行中に

```text
A restart occurred while this tool was in progress.
This may indicate a fatal memory error or system crash.
The tool execution was interrupted and did not complete.
```

がOpenHands側に記録される事象が4回以上発生し、そのたびにsshdも数分〜数十分応答しなくなり、
最終的にOpenHandsサーバプロセス自体が停止した。

この事象は推測ではなく、ホスト`dmesg`で実証された。

```text
oom-kill:constraint=CONSTRAINT_NONE,...,global_oom,
  task_memcg=/system.slice/docker-<container>.scope,task=java
Out of memory: Killed process <pid> (java) total-vm:5288716kB, anon-rss:448604kB
Out of memory: Killed process <pid> (java) total-vm:5287692kB, anon-rss:593664kB
```

`constraint=CONSTRAINT_NONE` かつ `global_oom` であり、cgroup上限による局所OOMではなく
ホスト全体のメモリ枯渇である。kill対象はcontainer内の`java`（FreeRouting）に加えて
`dbus-daemon`、`systemd`、`node`、`python`へ及び、OpenHandsとsshdの停止と整合する。
また、FreeRouting起動時にJVM最大ヒープを明示していないため、JVMはcontainer上限の約1/4
（8 GiB上限なら約2 GiB）を最大ヒープとして採り、実装メモリ1.6 GiBに対して過大な要求になる。

提案:

- `run_in_workspace.py`の起動前に、ホストの`MemTotal`／`MemAvailable`／swap／ディスク空きと
  要求メモリ上限を比較するpreflightを入れ、上限がホスト容量を超える場合は起動せず
  fail-closedにする（理由を明示する）。`--memory-limit`はすでに引数化されているので、
  既定値の妥当性検査だけが欠けている。
- FreeRouting（およびJVMを使う外部ツール）の最大ヒープを明示的に宣言・制御する。
  container上限だけを絞ってもJVM側が上限の1/4を要求するため、両方を宣言しないと
  ホストOOMは再発する。ヒープ値はprovenanceの実行条件へ記録する。
- `/acd:doctor`へ「lock済みimageを実行できるホスト資源があるか」の項目を追加する
  （メモリ、swap、ディスク空き）。現状のdoctorはimageの有無しか見ていない。
- docsへ最小ホスト要件を明記する。

## Q-3 長時間laneをforegroundで実行すると再起動で進捗が全損する

OpenHandsのtool呼び出しでcontainer laneをforegroundで待つと、上記の再起動でtool結果が
失われ、何が起きたか判別できなくなる。本検証では途中から

```bash
nohup bash -c '... run_in_workspace.py ...' > logs/<lane>.log 2>&1 &
```

に切り替え、`tail`／`grep`だけで進捗を確認する運用へ変更した。これによりサーバ再起動後も
logからexit code、image digest、fail-closed理由を復元できた。

提案: `docs/operations.md`へ「長時間laneはbackground＋log固定、確認はtail/grepのみ、laneは
同時に1本」を標準手順として明記する。可能であれば`run_in_workspace.py`へ
`--log-file`／`--detach`を追加し、log先頭にimage digest・revision・コマンドを必ず出力する。

## Q-4 preflightの`ready`が実ゲート結果と乖離する

fixture生成後のpreflightは

```text
board-pipeline: ready
firmware-pipeline: ready
silkscreen-resolve: ready
rationale coverage: pass
```

を返したが、実ゲートはこの後に11件のfail-closedを順に返した（Q-5の一覧）。preflightは
diagnostic-onlyであり判定権限を持たないので契約違反ではないが、`ready`という語は
「laneが通る」と誤読されやすく、実際に本検証では往復回数の見積りを誤らせた。

提案: preflightの語彙を`declaration-present`のように「何を見たか」に限定し、出力へ
「診断のみ、L1判定を代替しない」を機械可読フィールドとして含める。あわせて、preflightが
検査する述語集合と各laneの入口検査の述語集合の差分をdocsへ列挙する（現状は差分が大きい）。

## Q-5 必須属性不足が1件1往復で報告される（前回N-3が未解消）

`pulse-check-tag`では、次の順で1件ずつfail-closedし、そのたびに設計入力へ属性を追加して
再実行した（合計11往復。閾値・evidence規則は一切緩めていない）。

1. `node 'mechanical.silk_text.board_id': attr 'rotation_deg' missing or invalid`
2. `node 'fab.order_intent.pulse-check-tag': attr 'pcba_class_target' missing or invalid`
3. `C1: graph placement is missing or malformed`
4. `pinned library file missing: …/work-fixture/libraries/Espressif.kicad_sym`
5. `outer copper thickness must be positive (fail-closed)`
6. `incomplete stitch-via basis declaration (fail-closed)`
7. `IPC-2221 constants are incomplete (fail-closed)`
8. `net 'CC1': manufacturing margin is required`
9. `functional block node 'fb.esp32c3_strapping_boot' must reference a driving requirement`
10. `power_boundary: status='unknown'`（radio module declaration missing、safety boundary node ambiguous）
11. `silkscreen text 'mechanical.silk_text.board_id' has no declared position (fail-closed)`

個々のメッセージは具体的で修正可能であり、fail-closedの挙動は正しい。問題は往復回数である。
1往復あたりcontainer起動を伴うため、Q-2の再起動リスクを往復ごとに引く構造になっている。

提案: laneごとの必須ノード・必須属性・必須rationaleを**一括**診断して不足一覧を機械可読に
返す入口を追加する（前回N-3の提案と同じ）。判定はfail-closedのまま、報告だけをまとめる。
診断は各laneの入口検査と**同一の述語**を再利用し、Q-4の乖離を構造的に防ぐ。

## Q-6 doctorがhost前提とcontainer前提を同じ失敗欄に混ぜる

lock済みimageのpull後もdoctorは

```text
IDF_PATH=unset, qemu-system-riscv32=unavailable, cmake=unavailable
```

をfailとして報告し続ける。これはhost provisional経路の前提であり、authoritative経路
（digest固定container）には不要である。本検証では「まだ何かが足りない」と読める状態が
最後まで残った。

提案: doctorの出力を`authoritative-path`（image digest一致、docker実行可否、ホスト資源）と
`provisional-path`（host toolchain）へ明示的に分離し、authoritative経路の充足を単独で
判定できるようにする。分離は表示の分類であり、fail-closedの範囲は変えない。

## Q-7 lock済みimage未取得が常に初回fail-closedになる

doctorはネットワークpullを行わない設計なので、新しいworkspaceでは必ず
「lock済みimageがローカルに無い」でfail-closedする。安全側の設計として妥当だが、
利用者側には「次に何をすればよいか」がコマンドとして提示されない。

提案: doctorの失敗メッセージへ、`docker/image-digests.json`から生成した
`docker pull <image>@<digest>`のコマンド行をそのまま出力する（実行はしない）。
opt-inの`--pull`を用意する場合も、digest固定参照のみを許可する。

## Q-8 実行記録の収集入口がlane logと実機workspaceを対象にしていない

前回のP-12／N-12に対しては`scripts/export_execution_records.py`が追加されており、
execution record JSONのallowlist抽出と秘匿化は自動化されている。しかし本検証で必要に
なったのは、background実行したlaneの`logs/*.log`（exit code、image digest、fail-closed理由を
含む唯一の記録）と、それらが実機workspace内にしか存在しないという条件だった。結果として
収集はOpenHands APIのworkspace file取得を1件ずつ叩く手作業になった。

提案: `export_execution_records.py`の入力にlane logを加え（log先頭のimage digest・revision・
コマンド行を構造化して取り込む、Q-3と対）、リモートworkspaceからの取得手順を
`docs/operations.md`へ明記する。秘匿化は既存の実装をそのまま使う。

## Q-9 `--max-passes`の既定値がlayerごとに異なる

- `src/acd/adapters/freerouting/router.py`: `max_passes: int = 100`
- `src/acd/pipeline/gd1_board.py`のCLI: `default=99999`

同じ概念の既定値が2箇所で桁違いに異なり、CLI経由の実行だけが実質無限pass予算になる。

提案: 既定値を単一の定数へ集約し、laneのCLIはその定数を参照する。値の根拠（実測の収束pass数）
をdocsへ記録する。

## Q-10 FW laneがGD1のnet集合とapplication codeを定数で持つ（最優先）

`plugins/acd/skills/acd-firmware-esp32c3/scripts/fw_project.py`は、必要netをmodule定数で持つ。

```python
# Net roles the Golden Design #1 firmware needs, keyed by graph net node id.
_REQUIRED_NETS = (
    "net.led", "net.i2c_sda", "net.i2c_scl", "net.uart_tx",
    "net.uart_rx", "net.boot", "net.usb_dn", "net.usb_dp",
)
```

`render_pins_header()`はこの全netについてGPIOを要求するため、センサもUARTも持たない
`pulse-check-tag`では

```text
PIPELINE FAILED: no firmware pin assignment for net 'net.i2c_sda'
```

でfail-closedし、`[1/5] firmware project projected`にも到達しない。さらに生成される
`main.c`はGD1固定の実装（`SHT40_I2C_ADDRESS = 0x44`、`i2c_master_*`によるSHT40読み出し、
1 Hz点滅とログ）をtemplateとして埋め込むため、仮にI2C netを宣言して入口を通しても、
本設計の要件（起動時1回点灯、120 ms／1000 msのtoggle、tact switch入力）は生成されない。
つまりFW laneは現状GD1専用であり、**設計内容に依らず他設計のfirmwareを生成できない**。

センサを持たない設計にI2C/UART netを宣言させれば入口は通るが、それは設計意図の改変であり、
本検証では回避策として採らなかった。

提案:

- 必要netをlane固定の定数ではなく、設計graphの機能ブロック宣言とpin functionから導出する。
  宣言に無いperipheralのmacro・初期化・読み出しcodeを生成しない。
- application挙動（点滅周期、入力によるtoggle、boot時の表示）を要件宣言から受け取り、
  templateへ埋め込む固定実装を減らす。
- GD1の生成物・判定・正規化hashは不変に保ち、GD1以外の設計でもFW laneが`[5/5]`まで
  到達できることを回帰テストで固定する（negative testも維持する）。

## Q-11 projection guardがlane起動とstop reportの記録をdenyし、引用を変えると通る（最優先）

実機では、FW laneの再実行コマンドがhookに拒否された。

```text
rejection_source: hook
rejection_reason: Derived projections are regenerated by the pipeline;
  edit design inputs (graph.json / profiles) instead.
```

`plugins/acd/hooks/scripts/protect_projections.py`は`PROTECTED = ("out", "evidence")`を持ち、
`terminal` toolのコマンド文字列を`shlex.split`して各トークンを解決し、`out/`配下を指す
トークンが1つでもあれば、先頭コマンドが`READ_COMMANDS`（`cat`／`ls`／`grep`等）でない限り
denyする。このため次の2つが同時に起きる。

- laneの正規の起動形（`--out out/<lane>`、`--download out/<lane>/...`）がdenyされる。
  laneの出力先指定は投影の手編集ではないが、区別されていない。
- `stop_policy.py`が要求する`STOP_REPORT_PATH = "out/stop-report.json"`への書き込みもdenyされる。
  すなわち、fail-closed状態を宣言して停止するという規定の経路が、もう一方のhookで塞がれている。

さらに、同じ内容でも引用を変えると通る。hook scriptへ直接payloadを与えた検査結果（host実行、
参考値）:

| コマンド | 判定 |
|---|---|
| `uv run --script x.py --out out/fw` | deny |
| `bash -c "uv run --script x.py --out out/fw"` | allow |
| `python3 -c "json.dump(d, open(\"out/stop-report.json\",\"w\"))"` | allow |

内側を1トークンへ包むだけで検査を通るため、guardは「手編集の抑止」としては迂回可能であり、
同時に「正規のlane起動」に対しては誤検出になっている。前回検証で観測した回避行動
（禁止されたcommitやdummy order-totalの作成）と同種の誘発要因である。

提案:

- 保護対象を「生成物ファイルへの書き込み・編集」に限定し、laneの出力先指定引数
  （`--out`／`--download`）と`out/stop-report.json`への記録を明示的に許可する。
  許可はEvidenceの合否権限に触れないので、fail-closed境界は変わらない。
- 判定をコマンド文字列のtoken一致ではなく、editor toolのpath引数と、shellでの書き込み
  リダイレクト・書き込み系コマンドの対象に基づいて行う。`bash -c`等でネストした場合も
  同じ判定に落ちるようにする（少なくとも「解析不能なら保守的にdeny」へ倒す）。
- 2つのhookの契約が矛盾していないことを、`out/stop-report.json`書き込みとlane起動形の
  両方について回帰テストで固定する。
