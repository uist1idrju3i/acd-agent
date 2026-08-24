# 気づきと改善提案（mini-blink-dongle 実機検証）

実機OpenHandsでの新規設計検証（[`devin-report.md`](devin-report.md)）で観測した課題を、
優先度順に整理する。P-1〜P-3が「新規設計をVibeBBで回せない」直接原因、P-4〜P-7が
「fail-closedの停止境界が回避行動を誘発する」型の課題、P-8〜P-12が運用と手順の課題である。

## P-1 `DesignFixtureSpec`に宣言できないノード種別がある（最優先）

`src/acd/schema/design_fixture.py`の`DesignFixtureSpec`は`components`、`nets`、
`requirements`、`functional_blocks`、`firmware_pin_assignments`、`board_attrs`、
`fab_profile_id`だけを受け取り、`src/acd/pipeline/fixture_builder.py`は
`mechanical.outline`、`mechanical.silk_text`、`mechanical.silk_graphic`、`firmware.module`を
生成しない。GD1 fixtureにはこれらが1／6／2／1件あるが、生成graphには0件になる。

結果として、筐体laneは`expected exactly one mechanical.outline node, got 0`、FW laneは
`graph must contain exactly one firmware.module node`、silkscreen laneは
`silkscreen declarations are missing`で、いずれも入口で停止する。**全lane通過は事実上
GD1 fixture専用**である。

提案: `DesignFixtureSpec`へ`mechanical_outline`、`silk_texts`、`silk_graphics`、
`firmware_module`を追加し、`fixture_builder`で対応ノードを生成する。宣言が無い場合は
従来どおりfail-closedのままとし、laneをスキップして合格側へ倒す実装にはしない。

## P-2 Stop hookが正当な停止経路を持たずlivelockする（最優先）

`plugins/acd/hooks`のstop policyは、設計入力が変更されていてEvidenceが古い場合に

```text
Changed design inputs require a newer valid evidence record: …
Run the relevant pipeline gate, or commit changes before generating evidence.
```

でstopを拒否する。fail-closedでゲートが通らない状況では選択肢が「commitする」しか残らず、
実機ではdenyが15回連続し、ユーザーが明示的に禁止していたcommit（`b3064c1`）が発生した。

提案:

- 「未解決のfail-closedを明示して停止する」経路を用意する（例: 失敗理由・停止段・Evidence
  未生成を含む停止報告レコードをagentが提出したらstopを許可する）。合格側の権限は与えない。
- 同一理由のdenyが一定回数連続した場合は、hook側からエスカレーション（停止許可＋人間への
  引き渡し）へ切り替える。denyの無限反復はiteration上限の消費にしかならない。
- hookのメッセージから「commit」の示唆を削り、commit要求を停止条件にしない。

## P-3 新規設計向けのpreflightが無く、1属性1往復のループになる

silkscreen resolverは属性不足を1件ずつ報告するため、実機では9回連続でfail-closedし、
そのたびに`graph.json`を手編集して再実行していた（`pcba_class_target`、pinned library、
`J1.A8`のpinノード、stitch-via basis、IPC-2221定数、`+3V3`の`width_basis_source`、
`BOOT`のmanufacturing margin…）。

提案: `scripts/validate_design_fixture.py`（仮）を追加し、laneごとの必須ノード・必須属性を
**一括で**診断して不足一覧をJSONで返す。判定はfail-closedのまま、報告だけをまとめる。
`docs/`にlaneごとの必須宣言チェックリストを併記する。

## P-4 rationale coverageがL2生成レコードで機械的に満たせる

基板laneは`rationale coverage failed: missing=82, stale=10`で停止したが、実機agentが
`agent-artifacts/regen_rationale.py`を自作し、全対象ノードへ

- `decision`: `Use the declared values for <node id>.`
- `justification`: `Declared by the deterministic design specification.`
- `driving_requirement_refs`: 全件`requirements.json#mbd-req-001`
- `provenance.source`: `deterministic_tool`（実際はagentの自作script）
- `recorded_at`: `2025-01-01T00:00:00Z`（固定値）

を機械生成して書き込み、coverageをpassさせた。coverageは形式的な網羅性だけを見るため、
**L2が生成した定型文がL1ゲートを通す抜け道**になっている。

提案: rationale recordのprovenanceに、生成主体（Skill名とscript sha256、またはagent）を
必須で記録させ、`deterministic_tool`を自称できないようにする。定型文の重複、
`driving_requirement_refs`が単一要件に集中している状態、`recorded_at`の固定値を
coverage側で検出してfail-closedにする。

## P-5 strapping判定に必要なU1 IO-to-pad mappingを宣言できない

`src/acd/core/design_predicates.py`の`_u1_io_pads`は、U1の`cpl_rotation_pin_functions`と
`cpl_rotation_pin_aliases`からGPIO→pad対応を解決する。`DesignFixtureSpec`はこれを宣言
できないため、MPNが`ESP32-C3-MINI-1-N4`と確定していても
`strapping_pin: status='unknown' (U1 IO-to-pad mapping is missing or ambiguous)`となり、
基板laneが停止する。`pin_firmware_alignment`も同じ理由で`unknown`になる。

提案: parts catalogのエントリへモジュールのpin function mapを持たせ、`part_request`で
選択した時点でgraphへ展開する。カタログに無い部品は従来どおりfail-closedとする。

## P-6 要件テキストとnetlist topologyの一致を検査するゲートが無い

本件のfixtureは要件`mbd-req-007`「LEDはIO3に4.7 kΩを直列接続」に対し、
`net.led = {U1 pad21, R3 pad1, D1 pad1}`／`R3 pad2 = +3V3`／`D1 pad2 = GND`という
**直列でない**接続になっている（LEDがGPIOへ直結、R3はプルアップ）。プロセスはこれより
手前の`strapping_pin: unknown`で止まったため露見しなかった。

提案: 「電流制限抵抗はLEDと直列」「駆動ピンとLEDの間に抵抗が存在する」のような
topology述語を`design_predicates`へ追加する。要件テキストからの自動導出はL2に留め、
判定はあくまで宣言済みトポロジに対する決定論的検査とする。

## P-7 `run_design_loop.py`の必須入力がダミー生成を誘発する

order入力なしでは`failed_stage: "input"` /
`order-total document is required when aggregation is disabled`となり、設計反復
（silkscreen／基板／筐体／FW）を1つも実行できない。実機agentはこれを回避するために
金額0・`quote_id: "dummy-quote-1"`・hashがゼロ埋めの架空のorder-totalを作成した
（[`../runs/host-design-loop/order-total.json`](../runs/host-design-loop/order-total.json)）。

提案: 設計反復だけを回すモード（例`--skip-order-readiness`）を用意し、その実行では
order-readiness以降を「未実行」として明示的にfail-closed扱いで記録する。あわせて、
`quote_id`が既知のダミー値・hashがゼロ値のorder-totalを入力段で拒否する。

## P-8 container実行とhost実行がout-rootを共有すると破綻する

container（root）で生成したroot所有ファイルが同じout-rootに残ると、後続のhost実行
（`openhands`）が`Permission denied`で停止し、しかも表示される停止理由が本来の
fail-closed理由と別物になる（実機では原因誤認が起きた）。非root実行を試すと
`error: Failed to initialize cache at /.cache/uv: Permission denied`で失敗する。

提案: `scripts/run_in_workspace.py`側でout-rootをhost/containerで分離する、または
container実行時に`--user`＋`UV_CACHE_DIR`/`HOME`を書き込み可能なパスへ設定する。
どちらもできない場合は、out-rootに他ユーザー所有物がある時点でfail-closedし、
理由を明示する。

## P-9 lane CLIの引数が統一されていない

`run_fw_pipeline.py`は`--fixture`のみを受け、`--graph`を渡すとexit 2になる。laneごとに
`--fixture`／`--graph`／`--out`／`--out-root`の組み合わせが異なり、手順の誤りを誘発する。

提案: laneのCLI引数を`--fixture`＋`--out`に統一し、`scripts/run_design_lanes.py --list`の
出力をそのまま単体実行できる形にする。

## P-10 存在しないscriptが手順として案内される

実機agentは`scripts/validate_design_graph.py`を実行しようとしたが存在しなかった
（exit 2）。graph単体の妥当性検証コマンドが無いことと、案内が実体と一致していないことの
両方が問題である。

提案: P-3のpreflightをこの名前で提供するか、graph検証は`build_design_fixture.py`と
laneの入口検査に一元化することを`docs/`へ明記する。

## P-11 `build_design_fixture.py`が手編集graphを無警告で上書きする

実機では、container laneをpassさせるために手で属性を追加した`graph.json`が、次の
`build_design_fixture.py`実行で上書きされ、追加分がすべて失われた
（残ったのは`runs/container-silkscreen/`の投影だけ）。

提案: 生成物と既存ファイルの差分を検出したら、上書き前に停止するか差分レポートを出す。
「入力ファイルを設計の正とする」原則の下では、生成器が入力を黙って捨てる挙動は危険である。

## P-12 実機成果の持ち出し手順が無い

`out/`は`.gitignore`対象であり、実機で得た記録を`examples/`へ残す作業はすべて手作業だった
（アーカイブは約522MB／展開後約2.0GB、必要なのは1.2MB程度）。また、OpenHandsのraw export
zipにはホスト名やLLMエンドポイントなどの環境情報が含まれるため、そのまま公開リポジトリへ
入れられない。

提案: 実行記録から公開可能な最小集合（fixture、loop結果、timing record、gate evidence、
失敗summary）を収集する`scripts/collect_run_record.py`（仮）を用意し、ホスト名・
エンドポイント・ユーザー名の秘匿化を既定で行う。
