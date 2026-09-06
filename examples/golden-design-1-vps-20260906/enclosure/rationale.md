# Design rationale

- Graph: `golden-design-1`
- Revision: `r1`

## Coverage

- Status: `pass`
- Required subjects: `673`
- Covered subjects: `673`
- Unclassified attributes: `0`

## design_rule

### gd1-design-rules-board

- Subjects: `board.gd1`
- Attributes: `min_track_mm`, `min_clearance_mm`, `edge_copper_clearance_mm`, `via_diameter_mm`, `via_drill_mm`, `allowable_temperature_rise_k`, `width_basis_equation`, `width_measurement_tolerance_mm`
- Decision: Use 0.15 mm minimum track and clearance, 0.30 mm edge copper clearance, 0.60/0.30 mm vias, 10 K allowable rise, IPC-2221 width basis, and 0.01 mm width measurement tolerance.
- Justification: JLCPCB capability data permits 0.10 mm tracks and clearances, while the selected 0.15 mm minima retain 0.05 mm nominal margin. The 0.60 mm via diameter and 0.30 mm drill exceed 0.25/0.15 mm capability minima (with 0.20 mm recommended drill), 0.30 mm edge clearance exceeds the >=0.20 mm capability, and DeltaT=10 K with 0.01 mm measurement tolerance makes the 0.115469 mm calculated 5 V width measurable and routable as 0.15 mm.
- Rejected alternatives:
  - `Use 0.10 mm tracks and clearances`: That equals the JLCPCB capability floor and leaves no 0.05 mm design margin.
  - `Use 0.25/0.15 mm via geometry`: Those are capability minima; the adopted 0.60/0.30 mm geometry and 0.20 mm recommended drill guidance leave substantially more process margin.
  - `Use 0.20 mm edge clearance`: That equals capability, while 0.30 mm retains 0.10 mm additional edge margin.
- Driving requirements: `req.gd1-req-005`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-ground-stitch-board

- Subjects: `board.gd1`
- Attributes: `ground_plane_net`, `ground_plane_layers`, `ground_plane_min_island_area_mm2`, `stitch_via_wavelength_fraction`, `stitch_via_max_frequency_hz`, `stitch_via_refill_max_iterations`
- Decision: Use GND planes on F.Cu/B.Cu, 1.0 mm2 minimum islands, 2.4 GHz epsilon-r 4.3 lambda/20 stitch pitch, and at most 3 refill iterations.
- Justification: IPC-2221A and the RF wavelength guidance use the 2.4 GHz maximum frequency and epsilon-r=4.3; guided wavelength therefore gives the lambda/20 rule represented by 0.05. A 1.0 mm2 minimum island avoids tiny isolated copper, and refill is bounded at 3 iterations for deterministic completion while the GND plane spans F.Cu and B.Cu.
- Rejected alternatives:
  - `Use lambda/10 or a lower-frequency stitch rule`: At 2.4 GHz with epsilon-r=4.3, lambda/20 is the documented tighter RF spacing; lambda/10 would double the pitch.
  - `Accept islands below 1.0 mm2`: Very small isolated copper islands are difficult to connect reliably, can detach during fabrication, and make visual and electrical inspection ambiguous.
  - `Allow more than 3 refill iterations`: A bounded three-pass refill prevents a non-deterministic plane-generation loop.
- Driving requirements: `req.gd1-req-005`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

## fab_process

### gd1-fab-order

- Subjects: `fab.order_intent.gd1`
- Attributes: `fab_profile`, `quantity_pcs`, `surface_finish`, `soldermask_color`, `assembly_sides`, `pcba_class_target`, `delivery_format`
- Decision: Order 5 pcs with jlcpcb-fr4-2l-1oz, HASL, green mask, top-side assembly, economic PCBA, and a single delivery.
- Justification: §6/§9 select 5 prototype boards, the jlcpcb-fr4-2l-1oz profile, HASL, green mask, top-side assembly, economic PCBA, and single delivery. The standard outline tolerance is +/-0.2 mm; high precision +/-0.1 mm is unavailable below 50 x 50 mm, so the 30 x 25 mm board remains on the standard lane.
- Rejected alternatives:
  - `Use high-precision +/-0.1 mm outline tolerance`: The profile disallows high precision for boards below 50 x 50 mm; the 30 x 25 mm board must use +/-0.2 mm.
  - `Order 1 pc or assemble both sides`: The 5-piece, top-side prototype lane is the declared §6/§9 manufacturing plan.
- Driving requirements: `req.gd1-req-013`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-017`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

## firmware_pin

### gd1-firmware-module-declaration

- Subjects: `fw.module.main`
- Attributes: `mcu_component`, `entry_state`, `boot_log_message`
- Decision: Declare the GD1 main firmware module, MCU component, and entry state.
- Justification: §9.1の機能範囲をDesign Graphから決定論的に抽出するため、MCUと初期状態の関係を機械可読に宣言する。状態遷移・シーケンス投影は非権威のL3観測であり、Evidenceやゲート判定の根拠にはしない。
- Rejected alternatives:
  - None recorded: The module and entry-state declarations are the required graph source.
- Driving requirements: `req.gd1-req-008`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-19T00:00:00+00:00`

### gd1-firmware-net

- Subjects: `fw.pin.boot`, `fw.pin.i2c_scl`, `fw.pin.i2c_sda`, `fw.pin.led`, `fw.pin.uart_rx`, `fw.pin.uart_tx`, `fw.pin.usb_dn`, `fw.pin.usb_dp`
- Attributes: `net`
- Decision: Assign IO18/IO19 to USB_D-/USB_D+, IO4/IO5 to SDA/SCL, IO7 to LED, IO9 to BOOT, and IO21/IO20 to UART TX/RX.
- Justification: The §5 pin table assigns IO18/IO19 to USB_D-/USB_D+, IO4/IO5 to the SHT40 SDA/SCL bus, IO7 to the indicator, IO9 to BOOT, and IO21/IO20 to UART TX/RX. Recording these exact mappings keeps USB, I2C, LED, strapping, and serial-console constraints aligned across firmware, schematic, and routing.
- Rejected alternatives:
  - `Swap USB_D- and USB_D+`: The USB differential interface requires the documented IO18/IO19 polarity.
  - `Use IO2, IO8, or IO9 for the LED`: The pin table reserves strapping-sensitive functions and assigns the indicator to IO7.
  - `Move UART to an unassigned GPIO pair`: The documented IO21/IO20 pair provides the required serial-log interface without changing the declared pin plan.
- Driving requirements: `req.gd1-req-008`, `req.gd1-req-010`, `req.gd1-req-011`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-002`, `docs/golden-design-1.md#GD1-REQ-003`, `docs/golden-design-1.md#GD1-REQ-009`, `docs/golden-design-1.md#GD1-REQ-012`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-firmware-sequence-declarations

- Subjects: `fw.sequence.001`, `fw.sequence.002`, `fw.sequence.003`, `fw.sequence.004`, `fw.sequence.005`
- Attributes: `step_index`, `actor`, `target`, `action`
- Decision: Declare the minimal GD1 firmware interaction sequence for initialization, LED control, sensor reading, and serial logging.
- Justification: §9.1のLED、SHT40、USB-Serial-JTAGログ機能範囲を実在node id間の決定論的なsequenceとして宣言する。sequence投影は非権威のL3観測であり、未決の周期・速度・妥当範囲を含めない。
- Rejected alternatives:
  - None recorded: Only graph-declared actors, targets, and logical actions are extracted.
- Driving requirements: `req.gd1-req-001`, `req.gd1-req-008`, `req.gd1-req-010`, `req.gd1-req-011`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-19T00:00:00+00:00`

### gd1-firmware-state-declarations

- Subjects: `fw.state.boot`, `fw.state.fault`, `fw.state.measure`, `fw.state.report`, `fw.state.sensor_init`
- Attributes: `initial`
- Decision: Declare the minimal GD1 firmware state set with boot as the sole initial state.
- Justification: §9.1のLED、SHT40、シリアルログ機能範囲から最小限の状態粒度をDesign Graphへ宣言する。状態投影は非権威のL3観測であり、散文やAI所見から状態を推定しない。
- Rejected alternatives:
  - None recorded: The graph declaration is the sole source for firmware state extraction.
- Driving requirements: `req.gd1-req-001`, `req.gd1-req-010`, `req.gd1-req-011`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-19T00:00:00+00:00`

### gd1-firmware-transition-declarations

- Subjects: `fw.transition.boot_sensor_init`, `fw.transition.measure_fault`, `fw.transition.measure_report`, `fw.transition.report_measure`, `fw.transition.sensor_init_measure`
- Attributes: `from_state`, `to_state`, `trigger`
- Decision: Declare the GD1 firmware state transitions using logical trigger identifiers.
- Justification: §9.1の機能範囲からboot、SHT40初期化、計測、報告、読み取り失敗の遷移を抽出可能にする。未決の周期や妥当範囲は宣言せず、遷移投影は非権威のL3観測に限定する。
- Rejected alternatives:
  - None recorded: Logical trigger declarations avoid inferring timing or recovery behavior from prose.
- Driving requirements: `req.gd1-req-001`, `req.gd1-req-011`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-19T00:00:00+00:00`

### gd1-pin-i2c

- Subjects: `fw.pin.i2c_sda`, `fw.pin.i2c_scl`
- Attributes: `gpio`
- Decision: Keep SDA/SCL on IO4/IO5.
- Justification: GD1-REQ-003/011 and the pin table fix IO4=SDA, IO5=SCL for SHT40 0x44 with separate 4.7 kΩ pull-ups.
- Rejected alternatives:
  - `Swap or move SDA/SCL`: The requirement explicitly defines IO4=SDA and IO5=SCL.
- Driving requirements: `req.gd1-req-011`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-003`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-pin-led-boot

- Subjects: `fw.pin.led`, `fw.pin.boot`
- Attributes: `gpio`
- Decision: Keep LED on IO7 and BOOT on IO9.
- Justification: GD1-REQ-010 requires IO7 through 1 kΩ and excludes IO2/IO8/IO9; GD1-REQ-009 reserves IO9 for BOOT.
- Rejected alternatives:
  - `Assign LED to IO2/IO8/IO9`: Those strapping-sensitive pins are explicitly excluded.
- Driving requirements: `req.gd1-req-010`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-009`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-pin-uart

- Subjects: `fw.pin.uart_tx`, `fw.pin.uart_rx`
- Attributes: `gpio`
- Decision: Keep UART TX/RX on IO21/IO20 at the declared test points.
- Justification: GD1-REQ-012 names TX(IO21) and RX(IO20) observation pads, while GD1-REQ-002 requires serial-log access in the USB workflow.
- Rejected alternatives:
  - None recorded: `GD1-REQ-012` fixes TX/RX GPIOs and test points, while `GD1-REQ-002` fixes serial-log access; no alternate UART mapping is defined.
- Driving requirements: None
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-002`, `docs/golden-design-1.md#GD1-REQ-012`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-pin-usb

- Subjects: `fw.pin.usb_dn`, `fw.pin.usb_dp`
- Attributes: `gpio`
- Decision: Keep USB D-/D+ on IO18/IO19.
- Justification: GD1-REQ-008 and the pin table reserve IO18/IO19 for internal USB-Serial-JTAG used for flashing and logs.
- Rejected alternatives:
  - `Use another GPIO pair or external bridge`: The requirement fixes internal USB on IO18/IO19 and excludes the bridge.
- Driving requirements: `req.gd1-req-008`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-002`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

## mechanical

### gd1-board-overhang

- Subjects: `mechanical.board_edge_overhang.u1`
- Attributes: `edge`, `overhang_mm`
- Decision: Reserve a 5.4 mm top-edge overhang for the ESP32-C3-MINI-1 antenna.
- Justification: GD1-REQ-015 and §8.1 identify the ESP32-C3-MINI-1 antenna at the top edge and require a 5.4 mm overhang. This separation keeps enclosure material and copper away from the antenna boundary while preserving the 30 x 25 mm board datum.
- Rejected alternatives:
  - `Use 0 mm overhang`: A flush edge would place enclosure material and copper directly under the ESP32-C3-MINI-1 antenna, degrading the RF keepout and violating GD1-REQ-015.
  - `Use 3.0 mm overhang`: The smaller extension would leave less separation between the antenna and the board/enclosure boundary than the 5.4 mm RF clearance requirement.
- Driving requirements: `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-connector-openings

- Subjects: `mechanical.connector_opening.j1`
- Attributes: `face`, `center_x_mm`, `center_y_mm`, `width_mm`, `height_mm`, `margin_mm`
- Decision: Cut a front-face 8.0 x 5.0 mm opening centered at (15.0,5.0) mm with 0.5 mm margin.
- Justification: §8.1 declares the USB-C body as 9.0 x 7.0 mm at the front datum, while the enclosure opening is 8.0 x 5.0 mm centered at (15.0,5.0) with 0.5 mm margin for connector access. The front face matches the USB-C insertion direction and the board opening datum.
- Rejected alternatives:
  - `Move the opening to a side or back face`: USB-C insertion occurs at the front face, so a different face would prevent the intended cable approach.
  - `Use 0.0 mm margin`: Zero margin leaves no room for the 0.5 mm opening-to-body interface allowance, wall thickness, connector insertion tolerance, or the board outline tolerance of +/-0.2 mm.
- Driving requirements: `req.gd1-req-006`, `req.gd1-req-013`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-enclosure

- Subjects: `mechanical.enclosure.gd1`
- Attributes: `fastener_method`, `material`, `wall_thickness_mm`
- Decision: Use PA12-HP nylon with a 2.0 mm wall and M2 self-tapping screws.
- Justification: GD1-REQ-014 requires a board/enclosure shared hole interface; the mechanical lane declares PA12-HP nylon, a 2.0 mm wall, and self-tapping M2 fastening so the enclosure projection remains tied to the board interface without post-processing.
- Rejected alternatives:
  - None recorded: The GD1 mechanical declaration fixes the shared enclosure interface, PA12-HP nylon, and self-tapping M2 fastening for this fixture.
- Driving requirements: `req.gd1-req-014`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-enclosure-clearance

- Subjects: `mechanical.enclosure.gd1`
- Attributes: `interference_tolerance_mm3`, `internal_clearance_mm`, `lid_fit_gap_mm`, `lid_screw_hole_diameter_mm`, `min_wall_thickness_mm`, `standoff_height_mm`, `standoff_pilot_hole_diameter_mm`, `standoff_radius_mm`, `tolerance_mm`
- Decision: Use 1.2 mm minimum wall, 1.0 mm internal clearance, 4.0 mm standoff height with 2.0 mm radius, 1.6 mm pilot holes, 2.2 mm lid holes, 0.2 mm lid gap, 0.05 mm tolerance, and 0.01 mm3 interference limit.
- Justification: §8.1/§9 define the minimum wall, component clearance, standoff geometry, M2 pilot and lid hole diameters, lid gap, CAD tolerance, and interference threshold. These values leave measurable assembly room while preserving the declared self-tapping fastening interface.
- Rejected alternatives:
  - `Use 1.0 mm walls or 0.0 mm lid gap`: Both are below the declared 1.2 mm minimum wall or 0.2 mm fit gap and would consume the 0.05 mm tolerance budget.
  - `Allow 0.1 mm3 interference`: The declared 0.01 mm3 threshold is a hard gate; accepting ten times more collision would hide assembly failure.
- Driving requirements: `req.gd1-req-014`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-outline

- Subjects: `mechanical.outline.gd1`
- Attributes: `width_mm`, `depth_mm`, `thickness_mm`
- Decision: Use a 30.0 × 25.0 mm, 1.6 mm board.
- Justification: GD1-REQ-013 fixes two-layer FR-4, 1.6 mm, and the approximate 30 × 25 mm envelope; GD1-REQ-014 adds the four-hole enclosure interface.
- Rejected alternatives:
  - `Use high-precision 50 × 50 mm fabrication`: §6 says high precision requires at least 50 × 50 mm and three tooling holes, conflicting with GD1.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-014`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-outline-holes

- Subjects: `mechanical.outline.gd1`
- Attributes: `corner_radius_mm`, `mount_hole_count`, `mount_hole_1_x_mm`, `mount_hole_1_y_mm`, `mount_hole_1_diameter_mm`, `mount_hole_2_x_mm`, `mount_hole_2_y_mm`, `mount_hole_2_diameter_mm`, `mount_hole_3_x_mm`, `mount_hole_3_y_mm`, `mount_hole_3_diameter_mm`, `mount_hole_4_x_mm`, `mount_hole_4_y_mm`, `mount_hole_4_diameter_mm`
- Decision: Use R1.0 mm corners, four 2.2 mm M2-clearance holes at (1.5,1.5), (28.5,1.5), (1.5,23.5), and (28.5,23.5) mm.
- Justification: GD1-REQ-013/014 and §8.1 select a 30 x 25 mm rounded outline with R1.0 corners and four 2.2 mm holes for M2 clearance. The 1.5 mm edge offsets leave the 2.2 mm aperture inside the standard +/-0.2 mm outline tolerance while preserving the shared enclosure datum.
- Rejected alternatives:
  - `Use 2.0 mm holes`: M2 clearance needs the declared 2.2 mm aperture; 2.0 mm would reduce assembly clearance.
  - `Place holes 0.5 mm from the edge`: The 1.5 mm offsets provide more edge material and keep the 2.2 mm aperture inside the +/-0.2 mm standard outline tolerance.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-014`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

## net_class

### gd1-net-p3v3-power-declaration

- Subjects: `net.p3v3`
- Attributes: `power_rail`, `power_source_pin`
- Decision: Declare +3V3 as a power distribution rail supplied by pin.u2.2.
- Justification: The graph explicitly identifies the regulator output pin as the source of this rail; the power-tree projection must use this declaration rather than infer power semantics from names or symbols.
- Rejected alternatives:
  - None recorded: The explicit graph declaration is the required machine-readable source.
- Driving requirements: `req.gd1-req-004`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-net-power

- Subjects: `net.vbus_5v`, `net.gnd`, `net.p3v3`
- Attributes: `voltage_nominal_v`, `current_max_a`
- Decision: Class VBUS_5V=5.0 V/0.5 A, GND=0 V/0.5 A, and +3V3=3.3 V/0.5 A as the power domain.
- Justification: GD1-REQ-004/005 define 5.0 V USB input and less than 0.5 A operation; GD1-REQ-007 defines the regulated 3.3 V rail. The 0.5 A planning limit is therefore applied to VBUS, return, and regulator output, while GND is 0 V and its routed segments still use the power width basis.
- Rejected alternatives:
  - `Assign 5.0 V/0.5 A to +3V3 and GND without distinguishing domains`: +3V3 is regulated to 3.3 V and GND is 0 V; collapsing the values would misstate the electrical envelope.
  - `Use 0.15 A for VBUS or +3V3`: That would not cover the declared sub-500 mA prototype boundary.
- Driving requirements: `req.gd1-req-004`, `req.gd1-req-005`, `req.gd1-req-007`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-net-signal

- Subjects: `net.en`, `net.boot`, `net.led`, `net.led_a`, `net.i2c_sda`, `net.i2c_scl`, `net.uart_tx`, `net.uart_rx`
- Attributes: `voltage_nominal_v`, `manufacturing_margin_mm`
- Decision: Class EN/BOOT/LED/I2C/UART=3.3 V with 0.00 mm added manufacturing margin.
- Justification: GD1-REQ-009/010/011/012 define 3.3 V control, indicator, sensor, and UART signals. Their current is set by pull-ups, the LED resistor, or receiver inputs rather than the 0.5 A power boundary, so these logic routes use the manufacturing minimum and no added current-derived margin.
- Rejected alternatives:
  - `Apply the 0.5 A power class to every control and sensor net`: EN, BOOT, I2C, UART, and LED currents are limited by pull-up values, receiver inputs, or the 1 kOhm LED resistor, so the power-domain current class is not electrically applicable.
  - `Add a power-style routing margin to these signals`: These are logic routes whose manufacturability is governed by the 0.15 mm fab minimum; extra current-carrying width is reserved for the 0.5 A power domain rather than added to signal traces.
- Driving requirements: `req.gd1-req-010`, `req.gd1-req-011`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-009`, `docs/golden-design-1.md#GD1-REQ-012`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-net-usb

- Subjects: `net.cc1`, `net.cc2`, `net.usb_dn`, `net.usb_dp`
- Attributes: `voltage_nominal_v`, `manufacturing_margin_mm`
- Decision: Class CC1/CC2=5.0 V and USB_D-/USB_D+=3.3 V with 0.00 mm added manufacturing margin.
- Justification: GD1-REQ-004/006/008 define USB-C sink CC signals and IO18/IO19 USB data at logic voltage. These nets are logic/current-minimum routes, so they use no added power-domain margin rather than applying the 0.5 A class.
- Rejected alternatives:
  - `Apply the 5.0 V/0.5 A power class to USB data`: USB_D-/USB_D+ are 3.3 V logic lines and CC1/CC2 are configuration inputs, so they do not carry the power-domain current.
  - `Add a power-style routing margin to USB logic and CC traces`: The USB routes are governed by interface geometry and the fab minimum line width; current-derived width margin belongs to VBUS, +3V3, and GND, not these logic/configuration nets.
- Driving requirements: `req.gd1-req-004`, `req.gd1-req-006`, `req.gd1-req-008`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-net-vbus-power-declaration

- Subjects: `net.vbus_5v`
- Attributes: `power_rail`, `power_source_pin`
- Decision: Declare VBUS_5V as a power distribution rail supplied by pin.j1.a4.
- Justification: The graph explicitly identifies the USB VBUS pin as the source of this rail; the power-tree projection must use this declaration rather than infer power semantics from names or symbols.
- Rejected alternatives:
  - None recorded: The explicit graph declaration is the required machine-readable source.
- Driving requirements: `req.gd1-req-004`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

## part_selection

### gd1-radio-module

- Subjects: `comp.u1`
- Attributes: `radio_module`
- Decision: Declare U1 as a radio module requiring certification provenance.
- Justification: U1 is the ESP32-C3-MINI-1-N4 module selected for GD1 and its regulatory certification documents are attached to the graph.
- Rejected alternatives:
  - `Mount the ESP32-C3 chip directly with a self-designed antenna`: This would require obtaining and maintaining certification for the custom RF design rather than using the selected certified module.
  - `Omit the radio_module declaration`: Without the declaration, missing or incomplete certification provenance would not be checked as part of the GD1 safety boundary.
- Driving requirements: `req.gd1-req-008`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-buttons

- Subjects: `comp.sw1`, `comp.sw2`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt two TS-1088-AR02016 parts in Button_Switch_SMD:SW_SPST_TS-1088-xR020 as the RESET and BOOT tactile switches.
- Justification: GD1-REQ-009 requires separate RESET and BOOT controls; the 6 x 6 mm TS-1088 package supplies both tactile interfaces within the declared board area.
- Rejected alternatives:
  - None recorded: `docs/golden-design-1.md` §5.2 and `GD1-REQ-009` specify separate RESET and BOOT switches; no other switch function is defined.
- Driving requirements: None
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-009`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-cc

- Subjects: `comp.r1`, `comp.r2`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt two 5.1 kOhm 0603 parts as the USB-C CC1 and CC2 sink pulldowns.
- Justification: GD1-REQ-006 requires one 5.1 kOhm sink resistor per CC line; 0603 parts provide the required pair in the small USB-C keepout.
- Rejected alternatives:
  - `Omit one CC resistor`: The USB CC gate requires both CC1 and CC2 resistors.
- Driving requirements: `req.gd1-req-006`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-017`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-en

- Subjects: `comp.r3`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt one 10 kOhm 0603 resistor as the EN pull-up in the reset network.
- Justification: The §5.2 EN network declares 10 kOhm pull-up, 1 uF capacitor, and RESET switch; 0603 keeps the RC network routable in the declared passive lane.
- Rejected alternatives:
  - None recorded: `docs/golden-design-1.md` §5.2 fixes the EN network at 10 kΩ and 1 µF, leaving no alternate value in this fixture.
- Driving requirements: None
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-009`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-en-cap

- Subjects: `comp.c6`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt one 1 uF 0603 capacitor as the EN reset RC capacitor.
- Justification: §5.2 pairs 1 uF with the 10 kOhm EN pull-up and RESET switch; the 0603 package fits the declared RC reset network.
- Rejected alternatives:
  - None recorded: `docs/golden-design-1.md` §5.2 fixes the EN timing capacitor at 1 µF as part of the reset RC network.
- Driving requirements: None
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-009`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-holes

- Subjects: `comp.h1`, `comp.h2`, `comp.h3`, `comp.h4`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt four 2.2 mm MountingHole footprints as the four shared M2 mounting-hole features.
- Justification: GD1-REQ-014 requires four shared M2 anchors; the 2.2 mm mounting-hole footprint provides M2 clearance without an assembled part.
- Rejected alternatives:
  - None recorded: `req.gd1-req-014` fixes four shared M2 holes as the board/enclosure interface, so the hole features have no part-selection alternative.
- Driving requirements: `req.gd1-req-014`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-i2c

- Subjects: `comp.r4`, `comp.r5`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt two 4.7 kOhm 0603 resistors as the SHT40 SDA and SCL pull-ups.
- Justification: GD1-REQ-011 requires one 4.7 kOhm pull-up on each SHT40 SDA/SCL line; two 0603 parts satisfy that bus topology and board-area constraint.
- Rejected alternatives:
  - `One shared or missing pull-up`: The requirement and I2C gate require one resistor on each line.
- Driving requirements: `req.gd1-req-011`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-003`, `docs/golden-design-1.md#GD1-REQ-017`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-ldo

- Subjects: `comp.u2`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt AMS1117-3.3 in Package_TO_SOT_SMD:SOT-223-3_TabPin2 as the 5 V to 3.3 V regulator.
- Justification: GD1-REQ-007 names AMS1117-3.3; the SOT-223 package is the declared 6.5 x 3.5 mm regulator body and supports the specified 5 V to 3.3 V path.
- Rejected alternatives:
  - None recorded: `req.gd1-req-007` specifies AMS1117-3.3 by part number and its capacitor network, so this record has no regulator choice to compare.
- Driving requirements: `req.gd1-req-007`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-017`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-ldo-in

- Subjects: `comp.c1`, `comp.c2`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt 10 uF and 100 nF 0603 capacitors as the regulator input bulk and high-frequency pair.
- Justification: GD1-REQ-007 requires the AMS1117 input bulk/high-frequency pair; the two 0603 capacitor packages fit beside the regulator.
- Rejected alternatives:
  - None recorded: `req.gd1-req-007` fixes the regulator input pair at 10 µF plus 100 nF, so no alternative capacitor values are represented.
- Driving requirements: `req.gd1-req-007`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-017`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-ldo-out

- Subjects: `comp.c3`, `comp.c4`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt 10 uF and 100 nF 0603 capacitors as the regulator output bulk and high-frequency pair.
- Justification: GD1-REQ-007 requires the same pair at the 3.3 V output; 0603 packages fit beside the regulator output and preserve the declared decoupling topology.
- Rejected alternatives:
  - None recorded: `req.gd1-req-007` fixes the regulator output pair at 10 µF plus 100 nF, so no alternative capacitor values are represented.
- Driving requirements: `req.gd1-req-007`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-017`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-led

- Subjects: `comp.d1`, `comp.r6`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt KT-0603R plus one 1 kOhm 0603 resistor as the IO7 red indicator circuit.
- Justification: GD1-REQ-001/010 require a red indicator driven through 1 kOhm on IO7; 0603 LED and resistor packages fit the declared indicator lane.
- Rejected alternatives:
  - `Assign LED to IO2, IO8, or IO9`: GD1-REQ-010 excludes those strapping-sensitive pins.
- Driving requirements: `req.gd1-req-001`, `req.gd1-req-010`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-017`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-mcu

- Subjects: `comp.u1`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt ESP32-C3-MINI-1-N4 in Espressif:ESP32-C3-MINI-1 as the USB-capable MCU module.
- Justification: GD1-REQ-008 fixes the module and its IO18/IO19 USB-Serial-JTAG path; the declared 13.2 x 16.6 mm module is the §8.1 placement envelope.
- Rejected alternatives:
  - `Bare ESP32-C3 plus custom RF`: GD1-REQ-008 names the module and GD1-REQ-015 requires its module antenna keepout.
- Driving requirements: `req.gd1-req-008`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-017`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-mcu-cap

- Subjects: `comp.c5`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt one 100 nF 0603 capacitor as the MCU local decoupler.
- Justification: §5.2 requires a separate local 100 nF at the ESP32-C3-MINI-1 supply; the 0603 package fits adjacent to the module power pin.
- Rejected alternatives:
  - `Rely only on regulator capacitors`: The power-decoupling gate requires a separate MCU-pin 100 nF.
- Driving requirements: `req.gd1-req-007`, `req.gd1-req-008`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-sensor

- Subjects: `comp.u3`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt SHT40-AD1B-R3 in the Sensirion DFN-4 1.5 x 1.5 mm footprint as the I2C humidity sensor.
- Justification: GD1-REQ-003/011 require SHT40 at I2C address 0x44; the DFN-4 1.5 x 1.5 mm package fits the §8.1 sensor placement envelope.
- Rejected alternatives:
  - `AHT20 secondary candidate`: GD1-REQ-011 specifies SHT40 at 0x44.
- Driving requirements: `req.gd1-req-011`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-003`, `docs/golden-design-1.md#GD1-REQ-017`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-testpoints

- Subjects: `comp.tp1`, `comp.tp2`, `comp.tp3`, `comp.tp4`, `comp.tp5`, `comp.tp6`, `comp.tp7`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt seven 1.5 mm TestPoint footprints as the bring-up probe features.
- Justification: GD1-REQ-012 requires seven bring-up pads; the 1.5 mm TestPoint footprint has no body and preserves probe access without adding an assembled package.
- Rejected alternatives:
  - None recorded: `GD1-REQ-012` lists the seven required observation signals; it does not define an alternate test-point component.
- Driving requirements: None
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-012`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-select-usbc

- Subjects: `comp.j1`
- Attributes: `mpn`, `lcsc`, `value`, `footprint`
- Decision: Adopt TYPE-C-31-M-12 in Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12 as the front USB-C sink connector.
- Justification: GD1-REQ-004/006 require a USB-C sink interface; the 9.0 x 7.0 mm §8.1 connector body and official footprint provide the declared power, CC, and data access.
- Rejected alternatives:
  - `USB-PD source/charging connector`: GD1-REQ-004 excludes USB PD, battery, and charging circuitry.
- Driving requirements: `req.gd1-req-004`, `req.gd1-req-006`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-017`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

## placement

### gd1-body-policy-none

- Subjects: `mechanical.component_body.20`, `mechanical.component_body.21`, `mechanical.component_body.22`, `mechanical.component_body.23`, `mechanical.component_body.24`, `mechanical.component_body.25`, `mechanical.component_body.26`, `mechanical.component_body.27`, `mechanical.component_body.28`, `mechanical.component_body.29`, `mechanical.component_body.30`
- Attributes: `body_type`, `mounting_side`
- Decision: Use body_type=none and mounting_side=top for seven TestPoint pads and four M2 mounting holes.
- Justification: §8.1 declares that test points and mounting holes have no component body and 0.0 mm height; keeping their top-side feature declarations preserves probe access and the four-hole mechanical datum without inventing a package body.
- Rejected alternatives:
  - `Assign a solid body or nonzero height to test points and holes`: TestPoint and MountingHole features are pads/apertures with no package volume; assigning height would create false enclosure collisions and misrepresent probe and screw access.
  - `Place the features on the bottom side`: Top-side pads and apertures are needed for direct probing and for the shared mounting-hole datum used by the enclosure.
- Driving requirements: `req.gd1-req-014`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-012`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-body-policy-solid

- Subjects: `mechanical.component_body.1`, `mechanical.component_body.2`, `mechanical.component_body.3`, `mechanical.component_body.4`, `mechanical.component_body.5`, `mechanical.component_body.6`, `mechanical.component_body.7`, `mechanical.component_body.8`, `mechanical.component_body.9`, `mechanical.component_body.10`, `mechanical.component_body.11`, `mechanical.component_body.12`, `mechanical.component_body.13`, `mechanical.component_body.14`, `mechanical.component_body.15`, `mechanical.component_body.16`, `mechanical.component_body.17`, `mechanical.component_body.18`, `mechanical.component_body.19`
- Attributes: `body_type`, `mounting_side`
- Decision: Use solid bodies on the top assembly side for MCU, USB-C, regulator, sensor, LED, switches, and passives.
- Justification: §8.1 declares the physical bodies and GD1-REQ-013 requires top-side assembly; body_type=solid and mounting_side=top are policy values for assembled packages, not values inferred from a routed board.
- Rejected alternatives:
  - `Flip solid bodies to the bottom side`: That would violate the one-sided assembly declaration and change enclosure/antenna clearances.
  - `Treat package bodies as none`: The declared solid bodies have nonzero heights and must participate in the enclosure clearance gate.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-body-position-actives

- Subjects: `mechanical.component_body.3`, `mechanical.component_body.4`
- Attributes: `x_mm`, `y_mm`, `rotation_deg`
- Decision: Place regulator and sensor bodies at their declared coordinates.
- Justification: §8.1 places the AMS1117 body at (10.0,18.0) and the SHT40 body at (24.0,8.0), both at 0 degrees. Separating the regulator from the sensor keeps heat and bulk away from the humidity sensor while leaving the sensor in an exposed board region; these are source-backed mechanical coordinates rather than KiCad placement observations.
- Rejected alternatives:
  - `Move the regulator beside the sensor`: That would put the heat-producing regulator in the sensor lane and reduce the environmental measurement margin.
  - `Move the sensor into the regulator or antenna lane`: That would compromise sensor exposure or the ESP32 antenna boundary.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-body-position-holes

- Subjects: `mechanical.component_body.27`, `mechanical.component_body.28`, `mechanical.component_body.29`, `mechanical.component_body.30`
- Attributes: `x_mm`, `y_mm`, `rotation_deg`
- Decision: Place M2 hole centers at their declared coordinates.
- Justification: §8.1 places the four 2.2 mm M2 holes at (1.5,1.5), (28.5,1.5), (1.5,23.5), and (28.5,23.5) mm. These corner centers define the shared board/enclosure standoff datum and keep the mounting pattern outside the active routing lanes; the declared positions are used directly.
- Rejected alternatives:
  - `Move a hole inward into the passive lanes`: That would consume routing area and reduce the symmetric enclosure support pattern.
  - `Place a hole over a connector or component body`: That would create a mechanical collision and invalidate the 2.2 mm M2 clearance.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-body-position-led

- Subjects: `mechanical.component_body.5`
- Attributes: `x_mm`, `y_mm`, `rotation_deg`
- Decision: Place the LED body at its declared coordinate.
- Justification: §8.1 places the 1.6 x 0.8 mm LED body at (5.0,20.0) with 0 degrees. The indicator stays near the board edge for visibility and near its 1 kOhm driver route without consuming the MCU, USB, or enclosure-standoff lanes; the declared coordinate is used without runtime supplementation.
- Rejected alternatives:
  - `Move the LED beside the MCU antenna`: That would crowd the RF keepout and make the indicator less visible at the board edge.
  - `Move the LED to the USB opening`: That would consume connector-access space and lengthen the IO7 indicator route.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-body-position-mcu

- Subjects: `mechanical.component_body.1`
- Attributes: `x_mm`, `y_mm`, `rotation_deg`
- Decision: Place ESP32-C3-MINI-1 at (15.0,13.0,0.0 deg).
- Justification: §8.1 places the 13.2 x 16.6 mm ESP32-C3-MINI-1 body at (15.0,13.0) with 0 degrees rotation. Centering the module leaves the top antenna edge aligned with the 5.4 mm overhang while keeping the USB connector and enclosure standoffs in their separate datums; only the declared mechanical input is used here.
- Rejected alternatives:
  - `Move the MCU toward the top edge`: That would reduce the antenna boundary and standoff clearance available at the top edge.
  - `Rotate the module 90 degrees`: Rotation would change the antenna direction and disrupt the documented USB/data and power lane orientation.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-body-position-passives

- Subjects: `mechanical.component_body.8`, `mechanical.component_body.9`, `mechanical.component_body.10`, `mechanical.component_body.11`, `mechanical.component_body.12`, `mechanical.component_body.13`, `mechanical.component_body.14`, `mechanical.component_body.15`, `mechanical.component_body.16`, `mechanical.component_body.17`, `mechanical.component_body.18`, `mechanical.component_body.19`
- Attributes: `x_mm`, `y_mm`, `rotation_deg`
- Decision: Place 0603 passive bodies at their declared coordinates.
- Justification: §8.1 places the twelve 0603 passives in repeated x/y lanes at x=8.0 or 12.0 mm and y=8.0, 11.0, 14.0, or 17.0 mm, all at 0 degrees. The repeated grid keeps decouplers close to their regulator/MCU pins, keeps pull-ups beside SDA/SCL, and leaves the antenna, USB opening, and mounting-hole datums clear; only the declared mechanical lane is authoritative.
- Rejected alternatives:
  - `Move the passive grid toward the antenna edge`: That would consume RF keepout and increase the MCU decoupling path.
  - `Scatter passives around the board perimeter`: That would lengthen power and pull-up routes and reduce the compact 0603 placement needed for the declared board area.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-body-position-switches

- Subjects: `mechanical.component_body.6`, `mechanical.component_body.7`
- Attributes: `x_mm`, `y_mm`, `rotation_deg`
- Decision: Place RESET/BOOT bodies at their declared coordinates.
- Justification: §8.1 places RESET at (7.0,5.0) and BOOT at (23.0,5.0), both at 0 degrees. The two switches share the front-side control row at opposite sides of the board, leaving the central USB opening unobstructed and allowing the corresponding silkscreen labels to remain readable; the row is a declared mechanical arrangement.
- Rejected alternatives:
  - `Cluster both switches beside USB-C`: That would crowd the front connector opening and reduce independent finger access.
  - `Place a switch over a standoff datum`: The switch bodies need the top-side control surface and must not collide with enclosure supports.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-body-position-testpoints

- Subjects: `mechanical.component_body.20`, `mechanical.component_body.21`, `mechanical.component_body.22`, `mechanical.component_body.23`, `mechanical.component_body.24`, `mechanical.component_body.25`, `mechanical.component_body.26`
- Attributes: `x_mm`, `y_mm`, `rotation_deg`
- Decision: Place test-point centers at their declared coordinates.
- Justification: §8.1 places the seven 1.5 mm test points along y=23.0 mm at x=2.0, 10.0, 18.0, and 26.0 mm, with repeated positions for shared nets. The edge row keeps probes accessible from the board perimeter and avoids the enclosure standoffs and active bodies; the source declaration is not replaced by runtime placement.
- Rejected alternatives:
  - `Move test points to the board center`: Center placement would be blocked by components and would make probe access difficult inside the enclosure.
  - `Move the row to within 0.5 mm of the edge`: That would reduce pad-to-edge manufacturing material and leave less tolerance for probing and outline variation.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-body-position-usbc

- Subjects: `mechanical.component_body.2`
- Attributes: `x_mm`, `y_mm`, `rotation_deg`
- Decision: Place USB-C body at (15.0,5.0,0.0 deg).
- Justification: §8.1 places the 9.0 x 7.0 mm USB-C body at (15.0,5.0) with 0 degrees rotation. This center aligns the connector with the front-face 8.0 x 5.0 mm opening and leaves the insertion face accessible while the board and enclosure mounting datums remain behind it; the coordinate is a declaration, not a runtime readback.
- Rejected alternatives:
  - `Move USB-C to a side edge`: A side placement would no longer align with the front-face opening or the intended cable insertion direction.
  - `Rotate the connector 90 degrees`: The rotated body would not match the front opening orientation and would alter the 0.5 mm opening interface margin.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-place-active

- Subjects: `comp.u2`, `comp.u3`
- Attributes: `placement_x_mm`, `placement_y_mm`, `placement_rotation_deg`
- Decision: Place comp.u2=(4.15,14.70,90.0 deg); comp.u3=(15.00,13.05,0.0 deg).
- Justification: §9 places active parts after fixed anchors; keeping AMS1117 with its power lanes and SHT40 with its I2C block follows the declared functional blocks without an undocumented visual preference.
- Rejected alternatives:
  - `Place passives before active parts`: §9 fixes active parts as stage 2 and decoupling as stage 3.
- Driving requirements: `req.gd1-req-007`, `req.gd1-req-011`
- Driving requirement references: None
- Provenance source: `acd_skill`
- Skill: `acd-placement-search`
- Script hash: `sha256:af2d7836c941ea323cc62c314ebc5254d6541da169bb935e027e34a0e907a2b4`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-place-capacitors

- Subjects: `comp.c1`, `comp.c2`, `comp.c3`, `comp.c4`, `comp.c5`, `comp.c6`
- Attributes: `placement_x_mm`, `placement_y_mm`, `placement_rotation_deg`
- Decision: Place comp.c1=(7.53,20.28,0.0 deg); comp.c2=(7.53,22.28,0.0 deg); comp.c3=(9.28,14.78,0.0 deg); comp.c4=(7.28,2.53,90.0 deg); comp.c5=(16.53,14.78,0.0 deg); comp.c6=(23.03,4.03,90.0 deg).
- Justification: §9 makes decoupling stage 3 and derives its objective from distance to the declared regulator/MCU power pins; C6 remains in the EN RC network.
- Rejected alternatives:
  - `Place capacitors only in leftover space`: The power-decoupling gate requires proximity to the relevant pin.
- Driving requirements: `req.gd1-req-007`, `req.gd1-req-008`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-009`
- Provenance source: `acd_skill`
- Skill: `acd-placement-search`
- Script hash: `sha256:af2d7836c941ea323cc62c314ebc5254d6541da169bb935e027e34a0e907a2b4`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-place-holes

- Subjects: `comp.h1`, `comp.h2`, `comp.h3`, `comp.h4`
- Attributes: `placement_x_mm`, `placement_y_mm`, `placement_rotation_deg`
- Decision: Place comp.h1=(3.00,3.00,0.0 deg); comp.h2=(27.00,3.00,0.0 deg); comp.h3=(3.00,22.00,0.0 deg); comp.h4=(27.00,22.00,0.0 deg).
- Justification: GD1-REQ-014 makes the four-hole pattern the board/enclosure interface; the declared upper-left origin and coordinates therefore control placement.
- Rejected alternatives:
  - `Use fewer or independent holes`: The shared four-M2 pattern is explicit.
- Driving requirements: `req.gd1-req-014`
- Driving requirement references: None
- Provenance source: `acd_skill`
- Skill: `acd-placement-search`
- Script hash: `sha256:af2d7836c941ea323cc62c314ebc5254d6541da169bb935e027e34a0e907a2b4`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-place-led

- Subjects: `comp.d1`
- Attributes: `placement_x_mm`, `placement_y_mm`, `placement_rotation_deg`
- Decision: Place comp.d1=(11.78,12.78,0.0 deg).
- Justification: The LED is the visible IO7 indicator required by GD1-REQ-010. Its placement is resolved after the fixed anchors and active/decoupling stages under the §9 remaining-component order, while the D1 label is handled by the separate silkscreen search.
- Rejected alternatives:
  - `Place D1 without the series-resistor functional path`: The LED function is defined as the IO7-to-1 kΩ path in the GD1 circuit declaration.
- Driving requirements: `req.gd1-req-010`
- Driving requirement references: None
- Provenance source: `acd_skill`
- Skill: `acd-placement-search`
- Script hash: `sha256:af2d7836c941ea323cc62c314ebc5254d6541da169bb935e027e34a0e907a2b4`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-place-mcu

- Subjects: `comp.u1`
- Attributes: `placement_x_mm`, `placement_y_mm`, `placement_rotation_deg`
- Decision: Place comp.u1=(15.00,2.90,0.0 deg).
- Justification: §9 makes the RF module an anchor; GD1-REQ-015 requires antenna overhang and an empty copper/GND/component/silk keepout. The pad-bbox anchor and deterministic candidate search preserve that constraint.
- Rejected alternatives:
  - `Move it fully inside the board`: GD1-REQ-015 requires the antenna to overhang the board edge.
- Driving requirements: `req.gd1-req-008`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `acd_skill`
- Skill: `acd-placement-search`
- Script hash: `sha256:af2d7836c941ea323cc62c314ebc5254d6541da169bb935e027e34a0e907a2b4`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-place-resistors

- Subjects: `comp.r1`, `comp.r2`, `comp.r3`, `comp.r4`, `comp.r5`, `comp.r6`
- Attributes: `placement_x_mm`, `placement_y_mm`, `placement_rotation_deg`
- Decision: Place comp.r1=(21.53,21.28,90.0 deg); comp.r2=(27.53,17.53,90.0 deg); comp.r3=(28.28,13.53,90.0 deg); comp.r4=(13.28,15.03,0.0 deg); comp.r5=(23.28,19.78,90.0 deg); comp.r6=(8.78,17.28,90.0 deg).
- Justification: These resistors serve CC, EN, I2C, and LED functions. §9 orders remaining components by courtyard area then refdes, making the result repeatable rather than arbitrary.
- Rejected alternatives:
  - `Use arbitrary manual order`: That would discard the declared courtyard/refdes ordering.
- Driving requirements: `req.gd1-req-006`, `req.gd1-req-010`, `req.gd1-req-011`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-009`
- Provenance source: `acd_skill`
- Skill: `acd-placement-search`
- Script hash: `sha256:af2d7836c941ea323cc62c314ebc5254d6541da169bb935e027e34a0e907a2b4`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-place-switches

- Subjects: `comp.sw1`, `comp.sw2`
- Attributes: `placement_x_mm`, `placement_y_mm`, `placement_rotation_deg`
- Decision: Place comp.sw1=(24.05,9.05,90.0 deg); comp.sw2=(4.55,7.80,0.0 deg).
- Justification: The switches implement separate RESET and BOOT functions; their remaining-component placement follows the deterministic §9 order after anchors, active parts, and decoupling.
- Rejected alternatives:
  - `Swap their net roles`: GD1-REQ-009 names separate RESET and BOOT functions.
- Driving requirements: None
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-009`
- Provenance source: `acd_skill`
- Skill: `acd-placement-search`
- Script hash: `sha256:af2d7836c941ea323cc62c314ebc5254d6541da169bb935e027e34a0e907a2b4`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-place-testpoints

- Subjects: `comp.tp1`, `comp.tp2`, `comp.tp3`, `comp.tp4`, `comp.tp5`, `comp.tp6`, `comp.tp7`
- Attributes: `placement_x_mm`, `placement_y_mm`, `placement_rotation_deg`
- Decision: Place comp.tp1=(19.80,13.30,0.0 deg); comp.tp2=(22.80,13.80,0.0 deg); comp.tp3=(22.05,16.80,0.0 deg); comp.tp4=(25.80,13.80,0.0 deg); comp.tp5=(27.55,7.30,0.0 deg); comp.tp6=(27.55,10.30,0.0 deg); comp.tp7=(25.05,16.80,0.0 deg).
- Justification: GD1-REQ-012 names the exact seven observed signals; their non-assembled footprints are placed to preserve probe access within the fixed board envelope.
- Rejected alternatives:
  - `Omit dedicated test points`: GD1-REQ-012 explicitly requires these observation pads.
- Driving requirements: None
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-012`
- Provenance source: `acd_skill`
- Skill: `acd-placement-search`
- Script hash: `sha256:af2d7836c941ea323cc62c314ebc5254d6541da169bb935e027e34a0e907a2b4`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-place-usbc

- Subjects: `comp.j1`
- Attributes: `placement_x_mm`, `placement_y_mm`, `placement_rotation_deg`
- Decision: Place comp.j1=(15.00,21.35,0.0 deg).
- Justification: §9 makes the USB receptacle a mating-side board-edge anchor derived from body and pad geometry, keeping the sink-only VBUS/CC/data interface usable.
- Rejected alternatives:
  - `Move it away from the edge`: The mating-side connector anchor would no longer describe a usable USB-C interface.
- Driving requirements: `req.gd1-req-004`, `req.gd1-req-006`
- Driving requirement references: None
- Provenance source: `acd_skill`
- Skill: `acd-placement-search`
- Script hash: `sha256:af2d7836c941ea323cc62c314ebc5254d6541da169bb935e027e34a0e907a2b4`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

## population

### gd1-component-assembly

- Subjects: `comp.u1`, `comp.j1`, `comp.u2`, `comp.u3`, `comp.d1`, `comp.sw1`, `comp.sw2`, `comp.r1`, `comp.r2`, `comp.r3`, `comp.r4`, `comp.r5`, `comp.r6`, `comp.c1`, `comp.c2`, `comp.c3`, `comp.c4`, `comp.c5`, `comp.c6`, `comp.tp1`, `comp.tp2`, `comp.tp3`, `comp.tp4`, `comp.tp5`, `comp.tp6`, `comp.tp7`, `comp.h1`, `comp.h2`, `comp.h3`, `comp.h4`
- Attributes: `assembly`
- Decision: Populate 19 functional parts; leave 7 TestPoint pads and 4 M2 mounting-hole features not_fitted, with no DNP or variant population.
- Justification: §9 and GD1-REQ-017 require the assembly projection to use JLCPCBA-eligible parts. The 19 functional components are fitted, while test points remain probe pads and mounting holes remain mechanical apertures rather than DNP or BOM variants.
- Rejected alternatives:
  - `Mark a fitted functional part DNP or introduce a variant`: A DNP or variant would remove a declared function from the single GD1 BOM/CPL and require a separate population definition.
  - `Assemble TestPoint pads or MountingHole features`: Test points are accessed by probes and mounting holes provide screw clearance; neither has a solderable component body intended for PCBA placement.
- Driving requirements: `req.gd1-req-013`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-017`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

## routing_width

### gd1-width-control

- Subjects: `net.en`, `net.boot`, `net.led`, `net.led_a`, `net.i2c_sda`, `net.i2c_scl`, `net.uart_tx`, `net.uart_rx`
- Attributes: `width_basis`
- Decision: Use manufacturing minimum for reset, boot, LED, I2C, and UART nets.
- Justification: Their basis attributes identify logic or resistor-limited behavior as controlling; §8.0 adopts/measures 0.15 mm, above the 0.10 mm fabrication minimum, without treating low-current signals as power paths.
- Rejected alternatives:
  - `Use a power-net basis for every control net`: The declared width_basis_source identifies logic or resistor-limited behavior.
- Driving requirements: `req.gd1-req-010`, `req.gd1-req-011`, `req.gd1-req-013`
- Driving requirement references: `docs/golden-design-1.md#GD1-REQ-009`, `docs/golden-design-1.md#GD1-REQ-012`
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-width-power

- Subjects: `net.vbus_5v`, `net.p3v3`, `net.gnd`
- Attributes: `width_basis`
- Decision: Use IPC-2221 current capacity for power and return nets.
- Justification: GD1-REQ-004/005 limit the domain to 5 V and <500 mA; §8.0 derives 0.115469 mm, adopts/measures 0.15 mm, and treats GND routed segments separately from its filled plane.
- Rejected alternatives:
  - `Use only manufacturing minimum`: Power current is the controlling constraint in the declared basis.
- Driving requirements: `req.gd1-req-004`, `req.gd1-req-005`, `req.gd1-req-013`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-width-usb

- Subjects: `net.cc1`, `net.cc2`, `net.usb_dn`, `net.usb_dp`
- Attributes: `width_basis`
- Decision: Use manufacturing minimum for CC and USB data nets.
- Justification: The basis attributes classify CC and USB D-/D+ as logic, not current-capacity conductors; §8.0 adopts/measures 0.15 mm against the 0.10 mm fabrication minimum.
- Rejected alternatives:
  - `Apply the power current width`: The declared basis says current is not controlling for these logic nets.
- Driving requirements: `req.gd1-req-006`, `req.gd1-req-008`, `req.gd1-req-013`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

## safety_scope

### gd1-safety-scope

- Subjects: `sb.gd1`
- Attributes: `profile`, `intended_use`, `max_net_voltage_v`, `max_current_a`, `module_certified`
- Decision: Declare a hobby author_prototype boundary with certified ESP32-C3 module provenance.
- Justification: GD1-REQ-004/005 set a hobby author_prototype boundary of 5.0 V maximum and 0.5 A maximum. The ESP32-C3-MINI-1-N4 module certification provenance is attached to the graph and checked by SB2.
- Rejected alternatives:
  - `Declare 12 V or 1.0 A operation`: GD1-REQ-004/005 set the operating envelope at 5.0 V and 0.5 A; doubling either limit would be an unsupported safety-scope change.
  - `Treat the boundary as a certified product`: The documented use case is a hobby author_prototype, while certified module provenance is checked without declaring the complete product certified.
- Driving requirements: `req.gd1-req-004`, `req.gd1-req-005`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

## silkscreen

### gd1-silk-back

- Subjects: `mechanical.silk_text.dev_board`, `mechanical.silk_text.board_id`
- Attributes: `x_mm`, `y_mm`, `rotation_deg`
- Decision: Place DEV BOARD and golden-design-1-r1 on B.SilkS.
- Justification: The graph keeps branding and board identification on B.SilkS while the resolver reserves the sequential F.SilkS pass for RST, BOOT, D1, and USB. The accepted context candidates are DEV BOARD (8.016282355, 11.0472) at 0° and golden-design-1-r1 (8.95, 14.47915) at 0°; their evidence records the fixed-silk, pad, mask-opening, and board-edge rejection counts used to select these positions.
- Rejected alternatives:
  - `Place DEV BOARD or the board identifier on F.SilkS`: The graph's side declaration assigns branding and identification to B.SilkS, leaving the sequential F.SilkS resolver and its available clearance for operational labels.
- Driving requirements: `req.gd1-req-013`
- Driving requirement references: None
- Provenance source: `acd_skill`
- Skill: `acd-silkscreen-placement`
- Script hash: `sha256:554ac9c114c9bfa716ad4faf07ea7b87af487cde60b80fd009c7df685c3611d4`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-silk-functional

- Subjects: `mechanical.silk_text.reset`, `mechanical.silk_text.boot`, `mechanical.silk_text.led`, `mechanical.silk_text.usb`
- Attributes: `x_mm`, `y_mm`, `rotation_deg`
- Decision: Place RST/BOOT/D1/USB as front functional labels.
- Justification: The updated silkscreen resolver keeps the four operational labels on F.SilkS and places them in the declared sequential order after excluding board-edge, same-side pad, mask, existing-silk, body/courtyard, and nearest-component conflicts. The accepted context candidates are RST (26.325, 5.4) at 0°, BOOT (2.3, 5.15) at 0°, D1 (9.1, 12.4) at 0°, and USB (8.075, 23.9) at 0°; the graph evidence records the rejection counts and full-evidence hash for each result.
- Rejected alternatives:
  - `Retain the former RESET label and its former candidate`: The silkscreen observation update changed the label to the shorter RST form and reran the sequential resolver; the former candidates and RESET text are not the accepted graph state.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `acd_skill`
- Skill: `acd-silkscreen-placement`
- Script hash: `sha256:554ac9c114c9bfa716ad4faf07ea7b87af487cde60b80fd009c7df685c3611d4`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-silk-graphic-design

- Subjects: `mechanical.silk_graphic.vibebb`
- Attributes: `layer`, `stroke_width_mm`, `polygon_points`, `graphic_parts`, `source_path`, `source_sha256`, `source_viewbox_mm`, `source_scale`, `placed_size_mm`, `board_edge_margin_mm`, `placement_search_order`, `placement_center_mm`, `rotation_degrees`
- Decision: Use deterministic SVG-derived VibeBB artwork on B.SilkS at scale 0.4, 90° rotation, 7.2 × 16.0 mm, with provenance and fail-closed minimum-stroke validation.
- Justification: The approved SVG asset is converted deterministically into Design Graph geometry at scale 0.4 and 90° rotation; source path, SHA-256, placement center, dimensions, and rotation remain in the graph. The scaled minimum stroke is 0.16 mm, while below-profile strokes are rejected rather than clamped; projection plus independent Gerber measurement remain authoritative.
- Rejected alternatives:
  - `Retain the hand-coded placeholder polygon or omit source provenance`: That would not preserve the approved artwork geometry or Design Graph provenance.
  - `Use an artwork size below the profiled minimum feature width`: That would violate the 0.15 mm manufacturing minimum.
- Driving requirements: `req.gd1-req-013`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-silk-graphic-qr

- Subjects: `mechanical.silk_graphic.repository_qr`
- Attributes: `layer`, `stroke_width_mm`, `polygon_points`, `graphic_parts`, `source_path`, `source_sha256`, `source_viewbox_mm`, `source_scale`, `placed_size_mm`, `board_edge_margin_mm`, `placement_search_order`, `placement_center_mm`, `rotation_degrees`, `qr_module_matrix`, `qr_source_module_pitch_mm`, `qr_module_pitch_mm`, `qr_quiet_zone_modules`
- Decision: Add the repository QR as deterministic even-odd SVG-derived B.SilkS artwork at 13.5 mm square with module fidelity enforcement.
- Justification: The approved repository URL is encoded in the pinned SVG asset; the graph preserves its source hash, compound contours, placement center, source and projected pitch, 37×37 module matrix, and four-module quiet zone. Filled projection has no outline stroke; independent Gerber measurement compares every cell and fails closed on any mismatch.
- Rejected alternatives:
  - `Use a raster QR or omit the quiet-zone geometry`: That would not preserve deterministic vector manufacturing geometry.
  - `Scale below the 0.15 mm profiled minimum feature width`: That would violate the fabrication profile.
- Driving requirements: `req.gd1-req-013`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-silk-text-rules

- Subjects: `mechanical.silk_text.reset`, `mechanical.silk_text.boot`, `mechanical.silk_text.led`, `mechanical.silk_text.usb`, `mechanical.silk_text.dev_board`, `mechanical.silk_text.board_id`
- Attributes: `layer`, `text`, `height_mm`, `stroke_width_mm`, `board_edge_margin_mm`, `placement_search_order`, `placement_offset_step_mm`, `placement_search_limit_mm`, `placement_safety_margin_mm`
- Decision: Use 1.0 mm text height, 0.15 mm stroke, 0.15 mm board-edge margin, 0.25 mm search step, 8.0 mm limit, 0.15 mm safety margin, and top,bottom,right,left,top_right,bottom_right,bottom_left,top_left order.
- Justification: §12 and the graph use the fab minimum 1.0 mm text height and 0.15 mm stroke, with 0.15 mm edge/safety margin. The resolver advances in 0.25 mm steps up to 8.0 mm and searches in the declared top,bottom,right,left,top_right,bottom_right,bottom_left,top_left order, making rejection and acceptance reproducible.
- Rejected alternatives:
  - `Use 0.10 mm stroke or 0.5 mm text`: Both are below the profiled 0.15 mm stroke and 1.0 mm text minima.
  - `Use 0.50 mm step or unlimited search`: The declared 0.25 mm step and 8.0 mm limit provide deterministic resolution and bounded failure.
- Driving requirements: `req.gd1-req-013`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

## stackup

### gd1-board-envelope

- Subjects: `board.gd1`
- Attributes: `width_mm`, `height_mm`, `assembly_side`, `antenna_keepout`
- Decision: Use a 30.0 x 25.0 mm board envelope, top-side assembly, and an antenna keepout.
- Justification: GD1-REQ-013 and §8.1 define the 30 x 25 mm physical envelope, top-side assembly, and ESP32-C3 antenna boundary. electrical.board width/height deliberately equal mechanical.outline width/depth so the electrical and mechanical lanes evaluate the same board datum rather than two competing outlines.
- Rejected alternatives:
  - `Use a different electrical width/height from the mechanical outline`: A mismatch would make routing clearances and enclosure fit refer to different edges; the two 30 x 25 mm declarations must remain identical.
  - `Place copper or parts in the antenna keepout`: GD1-REQ-015 forbids that in the 5.4 mm antenna boundary.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`

### gd1-stackup-board

- Subjects: `board.gd1`
- Attributes: `layers`, `material`, `thickness_mm`, `copper_oz`, `finish`
- Decision: Use a 2-layer FR-4 stackup, 1.6 mm nominal thickness, 1 oz (35 um) copper, and HASL finish.
- Justification: §6 and GD1-REQ-013 select a 2-layer FR-4 prototype. The 1.6 mm board has the declared +/-10% thickness tolerance (1.44-1.76 mm), 1 oz means 35 um outer copper, and HASL follows the profiled prototype process.
- Rejected alternatives:
  - `Use 4 layers or 2.0 mm thickness`: The documented 2-layer 1.6 mm prototype stackup is sufficient for the 30 x 25 mm board; adding layers or 0.4 mm thickness changes the declared fab lane without a cited need.
- Driving requirements: `req.gd1-req-013`, `req.gd1-req-015`
- Driving requirement references: None
- Provenance source: `human`
- Skill: `not applicable`
- Script hash: `not applicable`
- Agent model: `not applicable`
- Conversation event ref: `not applicable`
- Recorded at: `2026-08-17T00:00:00+00:00`
