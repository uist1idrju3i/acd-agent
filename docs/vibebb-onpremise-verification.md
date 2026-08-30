# VibeBB単体成立性の実機検証記録（2026-08-25, 実機OpenHands環境 / 新規設計）

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.44.1

本書は、[`vibebb-standalone-verification.md`](vibebb-standalone-verification.md)がGD1（既存fixture）で
確認した範囲を、**利用者の実機OpenHands環境**と**GD1ではない新規設計**へ広げて実測した記録である。
目的は「Devin固有機能なしに、acd-agent単体（実機OpenHands + `/acd:*` command）でVibeBBの
設計反復が回るか」を確認することであり、ゲート、閾値、Evidence規則、fail-closed境界は変更していない。

- 検証日: 2026-08-25
- 対象revision: `bd2ddaf`（installed pluginの解決refも同一。stale cacheではないことを確認）
- 実機: 利用者所有ホスト、Ubuntu 26.04 LTS、CPU 3、メモリ約1.6GB、Docker server 29.1.3
- workspace: `/home/openhands/repos/test4`（手動`git clone`は行わず、`/acd:init`相当の初期化のみ）
- 実行主体: 実機OpenHandsのconversation（ACD plugin `acd` 0.0.2 が有効）
- 発注、見積取得、supplier API、決済は実行していない

## 1. 実機環境の外部ツール

| ツール | host PATH | 備考 |
|---|---|---|
| Python 3.14.4 / uv 0.12.5 | あり | `uv sync`成功 |
| Docker | あり | digest固定imageのpull可 |
| kicad-cli | なし | digest固定container（KiCad 10.0.5）側に存在 |
| freerouting / java | なし | 同上（FreeRouting 2.3.0 / OpenJDK 26.0.1） |
| idf.py（ESP-IDF） | なし | 同上（ESP-IDF 6.1 / QEMU RISC-V 9.2.2） |

host側は電気・機械・FWの外部ツールを持たないため、host実行は**provisional**にすらならない段が
存在する。authoritative Evidenceはlock済み
`ghcr.io/uist1idrju3i/acd-tools@sha256:b82dbf6e…d95eef`が正である。

## 2. `/acd:init`（workspace初期化）で判明した2件の不具合

実機のtest4は「`.git`のみ、commitなし、remoteなし」の空Git repositoryだった。この状態で
`/acd:init`（`plugins/acd/skills/acd-install-doctor/scripts/init_workspace.py`）が
fail-closedし、初期化が完了しなかった。本PRで次の2点を修正した。

1. **空Git repositoryを再利用できない**。既存workspaceの再利用は`origin`が設定済みの場合だけを
   想定しており、commitもremoteも無いdirectoryを`git clone`もreuseもできない状態で拒否していた。
   修正後は、workspaceがdirtyでなく、かつcommitが1つも無い場合に限り`origin`を追加してfetchし、
   対象revisionへ`--detach`する。commit済みでoriginが無いworkspaceは、素性が判定できないため
   従来どおり拒否する（fail-closedを緩めていない）。
2. **install doctorのJSONが切り詰められてparse不能**。stdoutを4000文字へ切ってから
   `json.loads`していたため、実機の長いdoctor出力が常に`status="unknown"`（fail-closed）になった。
   修正後はparseには全文を使い、報告文書へ載せる文字列だけを4000文字へ制限する。

回帰テストは`tests/openhands/session/test_init_workspace_script.py`で固定した（空Git repositoryの
reuse成功、commit済みorigin無しの拒否、4000文字超doctor出力のparse成功）。

## 3. 新規設計（GD1のコピーではない）の投入

会話経由で次の小規模設計を宣言し、`spec.json`から`scripts/build_design_fixture.py`でgraphを生成した。
GD1 fixtureのコピーではなく、規模・GPIO・定数・外形を変えている。

| 項目 | GD1 | 新規設計 `mini-blink-dongle` |
|---|---|---|
| MCU | ESP32-C3-MINI-1 | 同じ（同一MPN） |
| 部品点数 | 30 | 12 |
| 基板外形 | 30.0 × 25.0 mm | 20.0 × 15.0 mm |
| LED GPIO | 7 | 3 |
| LED電流制限抵抗 | 1k | 4.7k |
| LDO | AMS1117-3.3 | 同じ |
| センサ / I2C | あり | なし |
| 点滅周期 | 500 ms | 250 ms（要件record上） |

`build_design_fixture.py`は成功し、`graph.json`（70KB）と`rationale.json`が生成された
（`{"graph_id": "mini-blink-dongle", "revision": "r1", "status": "written"}`）。
すなわち**要件宣言→graph生成までは新規設計でも成立する**。

## 4. 新規設計に対する各laneの実測結果（すべてfail-closed）

`scripts/run_design_lanes.py`および各pipeline scriptを直接実行した結果である。

| lane | 実行 | 結果 | 停止理由（実出力） |
|---|---|---|---|
| silkscreen barrier | `resolve_gd1_silkscreen.py` | fail-closed | `RESOLUTION FAILED (fail-closed): silkscreen declarations are missing (fail-closed)` |
| 基板 | `run_gd1_pipeline.py` | fail-closed | `strapping_pin: status='unknown' (U1 IO-to-pad mapping is missing or ambiguous)` |
| 筐体 | `run_gd1_enclosure_pipeline.py` | fail-closed | `expected exactly one mechanical.outline node, got 0` |
| FW | `run_fw_pipeline.py` | fail-closed | `PIPELINE FAILED: graph must contain exactly one firmware.module node` |
| order-total / 発注可否 | `run_design_loop.py` | 未到達 | 前段でfail-closed（加えてorder入力なしでは`order-total document is required when aggregation is disabled`） |

`run_design_lanes.py`はsilkscreen barrierで停止し、以降のlaneを実行しない
（`{"ok": false, ...}`, exit=1）。段順序とfail-closedは宣言どおりに機能した。

なお、digest固定container内ではsilkscreen resolverが一度`[1/4] PASS`まで到達している。ただし
それは実機agentが`graph.json`へ属性を手で追加した未commitの状態に対する実行で、その手編集
graphは直後の`build_design_fixture.py`再実行で失われている。Evidence記録も伴わないため、
合格側の根拠にはならない（投影の存在とlane通過は別である）。実行記録と成果物は
[`examples/mini-blink-dongle-20260825/`](../examples/mini-blink-dongle-20260825/)に収めてある。

### 4.1 根本原因: 汎用fixture builderが電気系ノードしか出力しない

`src/acd/pipeline/fixture_builder.py`が生成するノードは
`requirement` / `electrical.net` / `electrical.component` / `electrical.pin` / `electrical.board` /
`design.functional_block` / `firmware.pin_assignment` / `fab.order_intent`に限られる。
`mechanical.silk_text`、`mechanical.silk_graphic`、`mechanical.outline`、`firmware.module`は
`DesignFixtureSpec`（`src/acd/schema/design_fixture.py`）に宣言する手段が無い。

GD1は専用builder `src/acd/pipeline/gd1_fixture/`（electrical / mechanical / firmware）が
これらのノードを作るため全laneへ到達できる。したがって

> **新規設計は「graph生成」までは単体で成立するが、silkscreen barrier以降のすべてのlaneへは
> 構造的に到達できない。**

これは閾値や判定の問題ではなく入力契約の不足であり、
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のM-2（任意graph向けの設計固有検証laneが無い）を
より上流で顕在化させたものである。M-2は「検証laneの宣言が無い」だが、実測では
**そもそもlane入力ノードを宣言できない**ため、GD1以外ではlaneが1つも通らない。

### 4.2 `strapping_pin`がunknownになる条件

`evaluate_strapping_pin`は`U1`の`cpl_rotation_pin_functions` / `cpl_rotation_pin_aliases`から
IO2/IO8/IO9のpadを一意解決できないと`unknown`（fail-closed）になる。これらはcomponent nodeの
属性であり、`FixtureComponentSpec.attrs`へ直接書く以外の宣言経路がない。
`FixtureCplOrientationEvidence`は`evidence_at` / `evidence_method` / `evidence_basis` /
`evidence_note`のみで、pad↔pin function対応を持たない。新規設計でstrapping述語を評価させるには
KiCad symbolまたはparts catalogからpin functionを取り込む経路が必要である。

## 5. 会話駆動での運用上の問題

1. **Stop hookがcommitを強要する**。design入力（`fixtures/**/graph.json`）を更新した状態で
   会話を終了しようとすると、Stop hookが
   `Changed design inputs require a newer valid evidence record: ... Run the relevant pipeline gate, or commit changes before generating evidence.`
   で毎回停止を拒否する。laneがfail-closedしていてEvidenceを作れない場合、agentに残る選択肢は
   「commitする」だけになり、実機では利用者の明示的な「commitしない」指示に反して
   detached HEADへcommitが行われた。fail-closedで停止した事実の報告を、hookが許可すべきである。
2. **iteration上限での打ち切り**。exportの`base_state.json`では6会話のうち3会話
   （`max_iterations` 80、80、300）が`execution_status: "error"`（`MaxIterationsReached`）で
   終了した。原因の一部は上記Stop hookの再試行loopと、長い出力の再読み込みである。
3. **out/の権限残骸**。同一out-rootをroot実行のcontainerとhostで共用すると、
   silkscreen resolverのwork-fixture複製が`[Errno 13] Permission denied` /
   `[Errno 1] Operation not permitted`で失敗する。out-rootを分けると解消した。
   実機archiveのtarエントリ所有者を確認すると、`out/mini-blink-dongle/**-silkscreen-resolve/`配下の
   48エントリが`root/root`であり、container実行が残したroot所有物へhost実行が衝突したと
   推定できる（断定ではない）。
   fail-closedの理由が「設計の不足」ではなく「実行環境の権限」になるため、区別できる
   エラーメッセージが望ましい。
4. **rationale coverageがL2生成レコードで満たせてしまう**。基板laneの
   `rationale coverage failed: missing=82, stale=10`に対し、実機agentは自作scriptで全対象ノードへ
   定型文の`decision`/`justification`と`provenance.source: "deterministic_tool"`を一括生成し、
   coverageをpassさせた（当該scriptは
   [`examples/mini-blink-dongle-20260825/agent-artifacts/`](../examples/mini-blink-dongle-20260825/agent-artifacts/)に
   保存）。coverageは網羅性のみを見るため、生成主体を問わない限りL1の抜け道になる。
5. **要件テキストとtopologyの不一致が検出されない**。今回のfixtureはLEDをIO3に4.7 kΩで
   直列接続する要件に対し、R3が`+3V3`へのプルアップとして入りLEDがGPIOへ直結しているが、
   これを検査する述語がない（`strapping_pin: unknown`で手前に停止したため露呈しなかった）。
6. **FW pipelineのCLI引数**。`run_fw_pipeline.py`は`--graph`を受け付けず`--fixture`のみである。
   他laneが`--fixture`/`--graph`を混在させているため、会話経路では引数探索の往復が発生した。

## 6. authoritative / provisional の境界

- 本検証で得られたlane結果は**すべてhost実行のfail-closed**であり、合格側Evidenceは1件も生成していない。
- digest固定container経路は`docker pull`まで成功したが、非root userでの実行時に
  `error: Failed to initialize cache at /.cache/uv`が発生し、container内laneは完走していない。
  したがって**新規設計のauthoritative Evidenceは未取得（未検証）**である。
- 実機FW書き込みは実施していない。QEMU virtual結果を実機合格へ昇格させる経路は存在しない。

## 7. 結論

1. 実機OpenHands + acd-agent単体で、`/acd:doctor`相当のinstall doctor、workspace初期化、
   要件宣言→`build_design_fixture`によるgraph生成までは新規設計でも成立する（§2の2件の修正が前提）。
2. 新規設計では、silkscreen / 基板 / 筐体 / FWの4laneすべてがfail-closedし、1つも通らない。
   原因は判定の厳しさではなく、`DesignFixtureSpec`がmechanical・silkscreen・firmware moduleの
   ノードを宣言できないことである（§4.1）。**現時点でVibeBBの全lane通過はGD1専用**である。
3. 段順序、barrier、fail-closed、host/authoritativeの区別は宣言どおりに機能した。
   unknownを合格へ昇格させる経路は観測されなかった。
4. Stop hookは、fail-closedで停止した会話に対してcommit以外の終了手段を与えておらず、
   運用上の安全性（利用者の指示に反するcommit）を損なう。
5. 新規設計のauthoritative Evidence、実発注、実機FWは未検証である。

## 8. 改善提案

優先度は「新規設計でVibeBBを閉じる」観点で並べた。いずれも本PRでは実装していない。
実機ログとworkspaceアーカイブの全件レビューを踏まえた12件版は
[`examples/mini-blink-dongle-20260825/report/improvement-notes.md`](../examples/mini-blink-dongle-20260825/report/improvement-notes.md)にある。
各項目は[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のN節（N-1〜N-12）と
[`roadmap.md`](roadmap.md)の14.13・15.10〜15.13へ反映済みである。

1. **`DesignFixtureSpec`へmechanical / silkscreen / firmware moduleの宣言を追加する**。
   最低限、`mechanical.outline`（外形と穴）、`mechanical.silk_text` / `silk_graphic`（role付き）、
   `firmware.module`（entry state、周期などのFW契約）を宣言できれば、GD1専用builderに依存せず
   全laneへ到達できる。既存GD1 builderは同じ宣言へ移行するか、専用builderのまま残して
   契約の同一性をテストで固定する。
2. **pin function / aliasの取り込み経路を作る**。KiCad symbol（`libraries/*.kicad_sym`）または
   parts catalog entryの`pin_functions`からcomponent属性を決定論的に生成し、
   `strapping_pin`などの述語がunknownで落ちないようにする。生成元はprovenanceへ記録する。
3. **Stop hookに「fail-closedで停止した」終了経路を認める**。直前のゲート実行が
   fail-closedで記録されている場合は、design入力の変更があってもcommitを要求せずに終了を許す。
   現状はhookが利用者指示に反するcommitを誘発する。
4. **lane scriptの引数と命名の統一**。`resolve_gd1_silkscreen.py`、`run_gd1_pipeline.py`、
   `run_gd1_enclosure_pipeline.py`はGD1以外にも使うため、`gd1`を含まない名前へ改称し、
   `--fixture`/`--graph`/`--out`の受け口を揃える。
5. **out-rootの権限起因失敗を分類する**。work-fixture複製失敗時に`PermissionError`を
   「環境起因（設計判定ではない）」として区別し、同一out-rootをroot実行と共用した場合の
   復旧手順を出力する。
6. **`run_design_loop.py`のorder入力要求を段階化する**。設計反復だけを回したい場合に
   order-total documentを必須にしないmode（発注可否段のみskipし、skipをfail-closedとして記録）が
   あると、実機での設計反復に会話1回で到達できる。
7. **install doctorの長い出力を前提にする**。今回の切り詰めparse不具合と同種の問題を防ぐため、
   JSON境界（stdoutはJSONのみ、人間向けはstderr）をscript側で固定する。
8. **低メモリ環境の明示**。実機の空きメモリは約460MBで、KiCad/FreeRouting/ESP-IDFの
   container実行には不足する可能性が高い。`/acd:doctor`が必要メモリの下限を検査し、
   不足をfail-closedとして報告することが望ましい。
