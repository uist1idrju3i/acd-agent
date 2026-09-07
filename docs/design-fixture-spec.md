# DesignFixtureSpec（spec.json）記述リファレンス

`DesignFixtureSpec`は任意設計をspecから決定論的にfixture（`graph.json`）へ
生成するための設計入力である。`scripts/run_design_loop.py --fixture-spec`や
`acd_run_design_loop`の`fixture_spec`へ渡すJSON objectとして記述する。
この文書はagentがspecを書く際の宣言場所と許容値を示す。ゲートの判定条件や
閾値はここに記載しない。不明な値は推測せず、fail-closed停止を設計入力の
不備として直す。

スキーマの正は`src/acd/schema/design_fixture.py`である。本書はそれを説明する
補助文書であり、差異があればスキーマとコードを正とする。

## 構成

| spec field | 生成されるnode kind | 備考 |
|---|---|---|
| `design_name`・`revision`・`graph_id` | graph識別子 | `graph_id`省略時はfixture名から決定 |
| `board_attrs` | `electrical.board` | 外形・層・設計ruleを`attrs`へ宣言する |
| `components[]` | `electrical.component`＋`electrical.pin` | `refdes`・`library_ref`または`part_request`・`attrs`・`pads`（pad→net対応） |
| `nets[]` | `electrical.net` | `net_id`と`attrs` |
| `requirements[]` | `requirement` | 要件record |
| `functional_blocks[]` | `design.functional_block` | `block_id`・`node_id`・`requirement_ids` |
| `mechanical_outline` | `mechanical.outline` | 筐体設計の基板外形 |
| `component_bodies[]` | `mechanical.component_body` | `refdes`参照の3D body |
| `connector_openings[]` | `mechanical.connector_opening` | `refdes`参照の開口 |
| `board_edge_overhangs[]` | `mechanical.board_edge_overhang` | `refdes`・`requirement_id`必須 |
| `enclosure` | `mechanical.enclosure` | 全bodyと開口へ依存する |
| `safety_boundary` | `safety.boundary` | SB2 predicateが読む安全境界 |
| `silk_texts[]`／`silk_graphics[]` | `mechanical.silk_text`／`mechanical.silk_graphic` | `depends_on`は任意 |
| `firmware_module`（`states`・`transitions`・`sequence_steps`） | `firmware.module`・`firmware.state`・`firmware.state_transition`・`firmware.sequence_step` | 状態機械とsequence |
| `firmware_pin_assignments[]` | `firmware.pin_assignment` | `pin_id`・`net`・`gpio` |
| `fab_profile_id`・`fab_order_intent` | `fab.order_intent` | 発注意図 |
| `fab_process_allowances[]` | `fab.process_allowance` | `rule_id`・`requirement_id`・理由 |
| `rationale_recorded_at` | rationale | coverage時刻の宣言 |

## 許容値

`attrs`は自由form辞書だが、lane predicateとpreflightは次の語彙だけを受理する。
語彙の正は`src/acd/core/declaration_vocabulary.py`であり、
`lane-preflight` stageが違反を`unsupported_values`としてfail-closedで報告する。

| 宣言 | 許容値 | 違反時のcode |
|---|---|---|
| `safety_boundary.attrs.intended_use` | `author_prototype` | `safety.boundary.intended_use_unsupported` |
| `safety_boundary.attrs.module_certified` | `certified` | `safety.boundary.module_certified_unsupported` |
| `safety_boundary.attrs.battery`／`charger`／`motor_actuator_laser` | bool（`true`または`false`の宣言必須） | `safety.boundary.hazard_flag_invalid` |
| `safety_boundary`ノード数 | ちょうど1 | `safety.boundary.missing` |
| `nets[].attrs.width_basis` | `current_ipc2221`または`manufacturing_minimum` | `net.width_basis_unsupported` |
| `board_edge_overhangs[].attrs.edge` | `top`・`bottom`・`left`・`right` | extractionが`GraphExtractionError`でfail-closed |
| `connector_openings[].attrs.face` | `front`のみ | extractionがfail-closed（他faceは契約拡張の対象） |
| `cpl_orientation_evidence.evidence_basis` | `estimated`または`confirmed` | schema検証でfail-closed |

`connector_openings`の`center_x_mm`は開口面の水平軸に沿ったoutline原点からの
距離であり、`center_y_mm`は基板面からの高さである。

`components[].attrs.decoupling_target`は対象ICの`refdes`文字列である。
placement skillはcapacitor側の非GND pinと対象pinが共有する電源netを一意に
要求する。対象が複数padで同じ電源netを共有する場合、skillはpadを自然順
（数字列は数値順）の最小値へ決定論的に解決し、選択した`target_pad`と全候補
`target_pad_candidates`を配置出力へ記録する。共有電源netを持つcapacitor pinが
1本でない場合やGND pinが1本でない場合は`ambiguous decoupling declaration`として
fail-closedで停止する。`evaluate_power_decoupling` gateはnet上の全pad対で
最小距離を測るため、pad選択はgate判定と整合する。

`components[].attrs`の`symbol_file`／`footprint_file`に対応する
`symbol_sha256`／`footprint_sha256`は、実ファイルのbyte列を`sha256:<64 hex>`で
hashした値である。採取と記入はdigest固定container内で
`scripts/pin_library_hashes.py --spec <spec.json> --write`を使う。

## lane-preflightの見え方

`lane-preflight` stageは宣言欠落（`missing_nodes`・`missing_attrs`）と
上表の語彙違反（`unsupported_values`）を一括してreportし、不備があれば
fail-closedで停止する。`next_step_action`は追記する宣言場所
（`SPEC_DECLARATION_PATHS`）と許容値を示す。`declarations_complete`は宣言の
存在を意味するだけで、lane gateの合格を保証しない。
