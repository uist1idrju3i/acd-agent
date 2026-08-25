# 気づきと改善提案（pulse-check-tag 実機検証）

実機OpenHands（workspace `test5`）で新規小規模設計`pulse-check-tag`を投入した検証
（[`devin-report.md`](devin-report.md)）で観測した課題を、優先度順に整理する。

前回検証（`mini-blink-dongle`、workspace `test4`）で挙げたN-1〜N-12のうち、
宣言経路（N-1）とpin function展開（N-5）は解消済みであることを本検証で確認した
（silkscreen laneがcontainer内でauthoritative候補として`resolved`まで到達した）。
本書のQ-1〜Q-9は、その先で新たに顕在化した課題である。同じ内容を根拠・依存・完了条件付きで
[`docs/vibebb-gap-analysis.md`](../../../docs/vibebb-gap-analysis.md)のO節（O-1〜O-9）へ記録し、
実装計画としては[`docs/roadmap.md`](../../../docs/roadmap.md)の14.14と15.14〜15.16へ割り当てた。
対応は Q-1→O-1、Q-2→O-2、Q-3→O-3、Q-4→O-4、Q-5→O-5、Q-6→O-6、Q-7→O-7、Q-8→O-8、Q-9→O-9 である。
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

を既定とし、`--memory=8g --memory-swap=8g`を付けて`docker run`する。実機のホスト実装容量は
前回検証時の観測で約1.6 GB（available 約460 MB）であり、上限がホスト容量を大きく超える。
本検証では、container gate実行中に

```text
A restart occurred while this tool was in progress.
This may indicate a fatal memory error or system crash.
The tool execution was interrupted and did not complete.
```

がOpenHands側に記録される事象が4回以上発生し、そのたびにsshdも数分〜数十分応答しなくなり、
最終的にOpenHandsサーバプロセス自体が停止した。

提案:

- `run_in_workspace.py`の起動前に、ホストの`MemTotal`／`MemAvailable`と要求メモリ上限を
  比較するpreflightを入れ、上限がホスト容量を超える場合は起動せずfail-closedにする
  （理由を明示する）。`--memory-limit`はすでに引数化されているので、既定値の妥当性検査だけが
  欠けている。
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
