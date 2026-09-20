# 測定記録

外部ツール・代替候補・非GD1 fixtureの実測記録である。すべてL3の観測記録であり、判定・閾値・
Evidenceへ作用しない。運用手順は[`operations.md`](operations.md)を参照する。

## 代替router（OrthoRoute）の単独実測と不採用（15.21）

OrthoRoute（MIT、commit `dbc4bc6cd1bb85a1acef23f8ce6b0ddccce86215`、`orthoroute_version`
1.0.0）のheadless modeをGD1と`dual-beacon-tag`で単独実測した。結果は**不採用**であり、
2層小基板をOrthoRouteで配線する経路は追加しない。本節はL3の実測記録であり、判定・閾値・
合否には作用しない。FreeRoutingの既定経路は変更しない。

入力は次のとおり用意した。`.kicad_pcb`から`.ORP`を生成するheadless経路はOrthoRoute側に
無い（KiCad IPC pluginがGUIから書き出す）ため、OrthoRoute同梱の`KiCadFileParser.load_board`
で`.kicad_pcb`を直接読み、`export_board_to_orp(compress=False)`で書き出す補助scriptを
リポジトリ外で用いた。

| 対象 | 入力 | `.kicad_pcb` SHA-256 |
|---|---|---|
| GD1 | `examples/golden-design-1-vps-20260901/board/golden-design-1.kicad_pcb`（未配線、`(segment` 0） | `1c8a5f306157d2afabaa5129e14f170080f82ddff6c5ff1323b644a93e634e89` |
| `dual-beacon-tag` | `examples/dual-beacon-tag-vps-20260906/fixture/spec.json`のFW pin roleだけを現行registry名（`led_orange`→`led2`、`user_btn`→`button`）へ置換してfixtureを生成し、lock済み`acd-tools`（`sha256:f6183da561f22b8c80197af37c700665ed6e9d273b9d1267658e61a36577dc25`、kicad-cli 10.0.6）内で`write_project`が出力した未配線基板（footprint 19、`(segment` 0） | `804ab1150e62a0555fe6339f636e7bcbd739a56b8a62f47d5597783b6bcf5e47` |

`.ORP`の決定性は、`metadata.export_timestamp`（`utcnow()`）を除いた正規化JSONの
SHA-256で照合した。同一入力から2回生成した結果はGD1が
`d71d8ef80324599ccfc8b8e9db7caefccb6cbee54c80211775ee5b737103f98e`、
`dual-beacon-tag`が`8167909844db9e2ab0b8545b84324ed8cee2ee758731e37fe0f6850301130307`で、
いずれも2回一致した（`metadata.filename`も出力名に依存するため同名で生成する）。
生の`.ORP`バイト列はtimestampにより毎回異なる。ただしparserは基板外形ではなくpad範囲から
`board.bounds`を導き（GD1で`x_min 0.85`〜`x_max 28.68`）、netclass・DRC規則は基板の
`.kicad_pcb`／`.kicad_dru`を読まず既定値（track 0.25、clearance 0.2、via 0.6/0.3）を
埋める。

実行は2 vCPU・約7 GiBのVM（Python 3.12.13、numpy 2.5.3、scipy 1.18.1、GPUなし）で
`python main.py headless <board>.ORP -o <board>.ORS --cpu-only`を対象ごとに2回行った。
GPU modeは、本VMと常設実環境（195.154.107.160、ASPEED VGAのみ、`/dev/nvidia*`なし、
cupyなし）の双方にCUDA GPUが無いため実測できず、未測定として残す。

| 対象 | run | wall-clock | 反復 | 収束 | 配線net | 出力track／via | `total_wirelength_mm` | `.ORS`正規化SHA-256（timestamp・所要時間を除く） |
|---|---|---|---|---|---|---|---|---|
| GD1 | 1 | 19.06秒 | 250 | NO | 3/14 | 12／6 | 0.0 | `a0d5fc11d2ae7ef7753e0630102bb746018ae1341ff5470912aa09269b3f22f2` |
| GD1 | 2 | 18.48秒 | 250 | NO | 3/14 | 12／6 | 0.0 | `4ce9d4a4fad39fbe48513b35bddde62885d36b7d7f50f5f9187192157f761e3e` |
| `dual-beacon-tag` | 1 | 18.47秒 | 250 | NO | 4/12 | 15／8 | 0.0 | `631d74c5a4a5e566276675b04278c6691ed1d781579ddaa89bb6c6d9ae11602e` |
| `dual-beacon-tag` | 2 | 18.37秒 | 250 | NO | 4/12 | 15／8 | 0.0 | `631d74c5a4a5e566276675b04278c6691ed1d781579ddaa89bb6c6d9ae11602e` |

`.ORS`の正規化hashは`metadata.export_timestamp`・`metadata.total_time_seconds`・各反復の
`iteration_time_seconds`を除いたJSONのSHA-256である。

観測された事実は次のとおりである。

- **収束しない**。両基板とも`max_iterations` 250を使い切り`Converged: NO`で終了した。
  配線されたnetは電源系（GD1: `+3V3`・`GND`・`VBUS_5V`、`dual-beacon-tag`: `CC2`・
  `D1_ANODE`・`GND`・`VBUS_5V`）だけで、信号netは1本も配線されず`total_wirelength_mm`は0.0
  である。出力trackはpad escape stubのみである。
- **2層基板が配線対象外**。`board_analyzer`は`Layers: 2 total, 0 signal`と報告し、
  H/V layerとも空である。外層への平面segmentは`[EMIT-GUARD] refusing planar segment on
  outer layer`で捨てられ（GD1 run1で11,546件、`dual-beacon-tag` run1で15,915件）、
  Manhattan格子ルータが内層を配線層、外層をpad／escape専用とするbackplane前提が2層小基板に
  合わない。graph構築側には2層例外があるが、解析・emit側と整合していない。
- **再現性が入力に依存する**。`dual-beacon-tag`は2回の`.ORS`正規化hashが一致したが、
  GD1は一致せず、`GND`のescape stub終点とvia位置（y 17.6↔18.0、22.8↔23.6）が2回で
  変わった。escape plannerは`seed=42`を宣言するが、同一入力・同一版でも出力集合が
  決定論的とは言えない。
- **DRC照合は不能**。`.ORS`をKiCad基板へ戻す経路はGUI plugin（Ctrl+I）だけで、
  headlessの`.ORS`→`.kicad_pcb`変換が無いため`kicad-cli pcb drc`を適用できない。
  出力viaは`diameter 0.4／drill 0.15`で、`.ORP`側に埋められた既定DRC（via 0.6/0.3）とも
  基板の`.kicad_dru`（via hole ≥0.15、annular ≥0.18）とも整合しない。

以上により、15.21は「決定論的`.ORP`生成は可能だが、router出力が非収束・非決定的・DRC照合
不能」として不採用で閉じる。router契約やGPU preflight（roadmap-futureの第2・3段）は
起票しない。多層backplane用途で再検討する場合は、内層を持つ入力で本節と同じ手順
（2回実行と正規化hash一致、`.ORS`→基板変換経路の確認）を再実施する。

## 他の代替routerの調査と単独実測（15.21補遺）

OrthoRoute不採用に続き、2026-09-15時点でheadless実行できるPCB autorouterを一次情報
（各repositoryのLICENSE・README・docs）で調査し、条件を満たす3件を同じ入力で実測した。
本節もL3の記録であり、判定・閾値・合否には作用しない。FreeRouting 2.4.1（GPL-3.0、
subprocess実行）の既定経路は変更しない。

### 調査結果とライセンス

| 候補 | ライセンス | 形態 | headless | 入出力 | 判断 |
|---|---|---|---|---|---|
| FreeRouting 2.4.1（現行） | GPL-3.0-only | Java JAR、subprocess | `-de`/`-do` | DSN→SES | 現行のまま維持 |
| KiCadRoutingTools 0.22.0（drandyhaas、`f0838d2`） | MIT | Python＋Rust `grid_router` | `route.py in.kicad_pcb out.kicad_pcb` | `.kicad_pcb`直接 | **実測**（下表） |
| kicad-tools 0.20.0（rjwalters、`kct`） | MIT | Python＋任意C++/CUDA backend | `kct route --layers 2 --seed N` | `.kicad_pcb`直接 | **実測**（下表） |
| freeroute 2026.7.14（warehack） | GPL-3.0-or-later | pure Python、subprocess | `freeroute in.dsn -o out.ses` | DSN→SES | **実測**（下表） |
| pcb-rnd | GPL-2.0-or-later | C、`--gui batch`＋`AutoRoute(AllRats)` | 可 | 自前形式、DSN export／SES import plugin | 未実測。KiCad→pcb-rnd→KiCadの二重変換が要り、DRC規則の往復を保証できないため保留 |
| gEDA PCB | GPL-2.0-only | C、batch HID | 可 | `.pcb`のみ | KiCad／DSN入出力が無く対象外 |
| routing-rs | AGPL-3.0-only | Rust CLI | 可 | DSN、`.kicad_pcb`出力 | READMEが「doesn't work yet」と明記、AGPLのため対象外 |
| tscircuit capacity-autorouter／dsn-converter | MIT | TypeScript library | CLI無し | SimpleRouteJson／DSN変換のみ | DSN→SESを直接出すCLIが無く対象外 |
| tscircuit freerouting-http | LICENSE不明 | HTTP service wrapper | service前提 | DSN over HTTP | FreeRouting本体の包装であり対象外 |
| Horizon EDA／LibrePCB | GPL-3.0-only | desktop EDA | autorouter無し | — | 対象外（LibrePCBはFreeRouting連携のみ） |
| DeepPCB | 商用service | cloud／API | 要account | DSN等 | 設計データが外部へ出るため対象外（既記録どおり） |

GPL/AGPLのrouterはsubprocess実行に限り、ACDへimport結合しない（`AGENTS.md`）。

### 実測

入力はOrthoRoute実測と同じ未配線GD1（`examples/golden-design-1-vps-20260901/board/`）と
生成`dual-beacon-tag`基板である。各条件を同一VM（2 CPU、GPUなし）で2回実行し、
`.kicad_pcb`は`(uuid …)`／`(tstamp …)`を除いて空白を正規化したSHA-256、`.ses`はそのまま
SHA-256で比較した。DRCはdigest固定acd-tools image（KiCad 10.0.6）の`kicad-cli pcb drc
--severity-all --all-track-errors --refill-zones`で、入力基板の`.kicad_pro`／`.kicad_dru`
（GD1: via 0.6/0.3、track 0.15、clearance 0.15）を並置して評価した。GD1入力の未配線状態
は`unconnected` 84、warning 35（`lib_footprint_issues` 30、`silk_edge_clearance` 5）であり、
現行FreeRouting経路の記録（`golden-design-1.drc.json`）はerror 0、`unconnected` 0である。

| router | 対象 | run | wall-clock | 終了code | 配線 | 正規化hash一致 | DRC（入力規則） |
|---|---|---|---|---|---|---|---|
| KiCadRoutingTools 既定（`--escalation fab`） | GD1 | 1・2 | 5.2／4.9秒 | 0 | 14/14 net | 一致 | `unconnected` 0、error: `via_diameter` 1・`annular_width` 1・`starved_thermal` 2 |
| KiCadRoutingTools `--escalation off --strict-sizes` | GD1 | 1・2 | 6.3／6.3秒 | 0 | 14/14 net報告 | 一致 | `unconnected` 1、error: `starved_thermal` 3 |
| KiCadRoutingTools 既定／strict | `dual-beacon-tag` | 1・2 | 12.7／12.8、7.3／7.4秒 | 0 | `+3V3`・`VBUS_5V`・`I2C_SDA`・`I2C_SCL`が`failed_single` | 一致 | `unconnected` 17（入力32）、`via_dangling` 2、入力由来のerror 100超 |
| kicad-tools `kct route`（C++ backend、`--seed 1`） | GD1 | 1・2 | 720.7／723.2秒 | 1 | 0/12 net（`Unrouted: 10/12`） | 一致 | `unconnected` 83、`copper_edge_clearance` 16、`track_dangling` 1 |
| kicad-tools `kct route` | `dual-beacon-tag` | 1・2 | 1.0／0.9秒 | 2 | 出力なし（`J1`・`J2`がEdge.Cuts外で拒否） | — | — |
| freeroute | GD1 | 1・2 | 0.54秒 | 0 | 15 net中1 net（`VBUS_5V`）のみSESに存在 | 一致 | SESのため未評価 |
| freeroute | `dual-beacon-tag` | 1・2 | 3.4秒 | 0 | 15 net中3 net | 一致 | SESのため未評価 |

観測された事実は次のとおりである。

- **KiCadRoutingTools**はGD1を約5秒で全net接続し、出力は2回で一致した（wall-clock
  はFreeRoutingの実機実測180秒に対し1/30以下）。ただし既定の`--escalation fab`は
  via-in-padでvia径を0.6→0.4 mmへ自動で狭め、出力`.kicad_pro`の`rules.min_via_diameter`を
  0.6→0.4へ**書き換えて**自身のDRCを通す。入力規則で評価するとerrorが残り、規則を保つ
  `--escalation off --strict-sizes`では未接続1件と`starved_thermal` 3件が残る。
  `dual-beacon-tag`では4 netが失敗しても終了codeは0であり、合否は`JSON_SUMMARY_MIN`の
  `failed`を読まなければ判別できない。kicad-cli不在時は自己検査がNO-OPになる旨を自ら警告する。
- **kicad-tools**はGD1で12分かけて0/12 netしか配線せず、`dual-beacon-tag`は
  placement検査で拒否した（`J1`・`J2`が基板外）。
- **freeroute**は決定論を明示する唯一のDSN→SES routerだが、alpha版で両基板とも
  ほとんどのnetをSESへ出力しなかった。
- `dual-beacon-tag`の生成基板は入力時点で`shorting_items` 8、`courtyards_overlap` 16を
  含み、router比較には不適である（14.22の残作業と同根）。

以上により、代替routerは**いずれも現時点では不採用**とし、FreeRouting経路を維持する。
最有力はKiCadRoutingToolsで、採用を再検討する条件は、(1) 入力規則を書き換えない
modeで`kicad-cli pcb drc`（入力`.kicad_pro`）がerror 0・`unconnected` 0になること、
(2) 失敗netが終了codeへ反映されるか`JSON_SUMMARY_MIN.failed`をfail-closedで読む契約を
定義すること、(3) router選択をrevisionに束縛した設計入力として宣言し、正規化hashの
変化を投影差分として扱うことである。再検討時は本節の手順（2回実行、hash一致、入力
規則でのDRC）を同じ入力で再実施する。


## 非GD1 fixture（mini-blink-dongle）の実行記録

`fixtures/mini-blink-dongle/spec.json`は新規specの雛形であり、silkscreen（`silk_texts`）、
筐体、FW状態機械、stitch via、CPL基準の出所、`overlays/`の足跡overlay、fab発注意図を
すべて明示宣言する。宣言不足は`build_design_fixture.py`の`lane_preflight_status`と
`next_step_action`へ具体名で返り、自動補完はしない。rationale coverageの失敗は
`FixtureBuilderError`へ`summarize_rationale_coverage`の1行要約（status、
missing／stale／unknown_provenance／orphan／untraceable／conflicting／
unclassified／templated／generator_violationsの件数と先頭5件の属性名）と
分類表への案内を含めて返る。判定条件は変更しない。この会話向けnext stepは
設計入力側の次手（missing/stale subjectへのrationale record追加、
unclassified属性はrationale契約外なので設計入力から除くか契約変更を別PRで提案）
だけを示し、source側の分類表名（`REQUIRED_RATIONALE_ATTRS`／
`RATIONALE_EXEMPT_ATTRS`）は開発者向け情報としてメッセージへ出さない。

```bash
uv run python scripts/build_design_fixture.py \
  --spec fixtures/mini-blink-dongle/spec.json --out out/mbd-fixture
uv run python scripts/run_design_lanes.py --fixture out/mbd-fixture --out-root out/mbd
```

authoritative実行は`scripts/run_in_workspace.py`（`DockerWorkspace`、lock済みserver image）で
行い、CIの`container-gates`と同じcommandを使う。2026-09-06のlocal実測（8 GiB host、
`--memory-limit 6g`）では、4 laneの`wall_clock_seconds`は135 s（`stage_duration_sum_seconds`
451 s）で、`verify_authoritative_evidence.py`と`verify_manufacturing_submission.py
--require-authoritative`はいずれもPASSした。この実測はL3観測であり、合格判定はcontainer内の
決定論的ゲートとdownloadしたEvidenceの検証結果だけが担う。
