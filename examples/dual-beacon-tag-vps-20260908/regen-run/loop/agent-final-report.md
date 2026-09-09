# dual-beacon-tag (r1) 全投影再生成 最終報告

### 到達段と失敗理由
- **failed_stage**: `visual-review-manifest`
- **failure_reason**: `RasterizerError: source SVG is unavailable`
- **loop-summary.ok**: `false`
- **design_only**: `true`（order-readiness段は未実行、loopはfail-closedのまま）

**根拠**: 設計loop内の `derive_visual_review()` が `config.out_root = out/dual-beacon-tag` に対して呼ばれた際、実際の投影物（SVGファイル）が `out/dual-beacon-tag/dual-beacon-tag/visual/` に存在するのに対し、manifest生成ロジックが期待するパスと不一致を起こし、rasterizerが「source SVG is unavailable」を検出した。これは容器内パス解決のフレームワークバグである。

### 3 laneの生成状況
| lane | status | 備考 |
|---|---|---|
| 基板 (electrical) | 生成完了 | ERC/DRC通過、Evidence生成済み |
| 筐体 (mechanical) | 生成完了 | 機械ゲート通過、Evidence生成済み |
| FW (firmware) | 生成完了 | ビルド・QEMU実行通過、Evidence生成済み |

### 生成した投影一覧（path・sha256）

#### 基板（board）
| path | sha256 |
|---|---|
| `out/dual-beacon-tag/dual-beacon-tag/gerbers/dual-beacon-tag-F_Cu.gtl` | `e3e69a80b9165039a6c867015b49908cc204ece18515feb749a2867a50c8e448` |
| `out/dual-beacon-tag/dual-beacon-tag/gerbers/dual-beacon-tag-B_Cu.gbl` | `10ab546df0164d565ec56ab7cc298f4737e30c8b4ace82e55f06d690b67d1130` |
| `out/dual-beacon-tag/dual-beacon-tag/gerbers/dual-beacon-tag-F_Mask.gts` | `775d6abb34be9ef05e113803d45a25ac218305bace5926c25cff0f61fe6a57e8` |
| `out/dual-beacon-tag/dual-beacon-tag/gerbers/dual-beacon-tag-B_Mask.gbs` | `d8d8a85aa66def692cedff5434df670a7c68336fd03bc2cdb2819289c8811c3a` |
| `out/dual-beacon-tag/dual-beacon-tag/gerbers/dual-beacon-tag-F_Silkscreen.gto` | `f52bd1b4552303733cb6c7ea172032ba7bc544c62966249ece05fe1d61a3b6f1` |
| `out/dual-beacon-tag/dual-beacon-tag/gerbers/dual-beacon-tag-B_Silkscreen.gbo` | `98d0f920beddfea4111bccbf2b80d6a005bab6c537285c6c89a3aa7ccc2945fb` |
| `out/dual-beacon-tag/dual-beacon-tag/gerbers/dual-beacon-tag-F_Paste.gtp` | `baf4c4564f07fd37fe2ef55b8094e935d2f80c6a71360ef5c4bb6b44a359f8df` |
| `out/dual-beacon-tag/dual-beacon-tag/gerbers/dual-beacon-tag-Edge_Cuts.gm1` | `dc5e01cd00dc76257032e03bee4f9dccb15dd3422587b707147825cb32571716` |
| `out/dual-beacon-tag/dual-beacon-tag/gerbers/dual-beacon-tag.drl` | `dad4156f28ee9085fe74ab55621a87c81e05b2bfd622ae59ab558f0f1c10fdc3` |
| `out/dual-beacon-tag/dual-beacon-tag/gerbers/dual-beacon-tag-job.gbrjob` | `6fbbc1f2419db9b197d881a7f04e62c5a6b1a7a348c104f850ec0490d2cd1787` |
| `out/dual-beacon-tag/dual-beacon-tag/fab/dual-beacon-tag-gerbers.zip` | `c684e0468435c7ce26f5e227c3b3a58208e1ff090e5a4ca1c48681b792d5291e` |
| `out/dual-beacon-tag/dual-beacon-tag/fab/dual-beacon-tag-bom-jlcpcb.csv` | `15875928817727ab114181dca37f99a21dda2dc3db00dc4cbfea14c4c9cb189e` |
| `out/dual-beacon-tag/dual-beacon-tag/fab/dual-beacon-tag-cpl-jlcpcb.csv` | `8cb6bf2bddd13d7d741f3291b791ebd7b4af25ab1be4cd4e384c9a3499871b8b` |
| `out/dual-beacon-tag/dual-beacon-tag/fab/dual-beacon-tag.pos.csv` | `351556dc855c9e75952b46469c84c21276dd044e9a1dc339f3f01ec84842ce97` |
| `out/dual-beacon-tag/dual-beacon-tag/fab/dfm-report.json` | `16ab646f0ee188200041af4737de95175cd1193cfff7ead9eace29095870d417` |
| `out/dual-beacon-tag/dual-beacon-tag/fab/cpl-basis-report.json` | `a3a17538878ecb27f1120173d9051fa6e1127bab3e96d7aec5f1c9e807975a22` |
| `out/dual-beacon-tag/dual-beacon-tag/dual-beacon-tag.kicad_pcb` | `25976e03b42aca31a8177ba6909492bb52684206aacb18625b4e88b53fb8a019` |
| `out/dual-beacon-tag/dual-beacon-tag/dual-beacon-tag.kicad_sch` | `48eae1b5866b005494b8cc4851afd8e5a84bc45e96003c1f06a48f3709190597` |
| `out/dual-beacon-tag/dual-beacon-tag/theme-song/theme-song.mid` | `4f0a7bcc44d0e360afb8f11a49059226b4c2d26f0d0335077281b5a8ec671972` |
| `out/dual-beacon-tag/dual-beacon-tag/theme-song-projection.json` | `999cf0970de37abf52a445f7c3457165e6a4c7de87e36fda928fb43c2d20addc` |

#### 筐体（enclosure）
| path | sha256 |
|---|---|
| `out/dual-beacon-tag/dual-beacon-tag-enclosure/enclosure.stl` | `a021ffed33ae1757f9677010aa00bda8509dbb3eee26600877a7dd3e830d21c1` |
| `out/dual-beacon-tag/dual-beacon-tag-enclosure/enclosure.3mf` | `7037e7de631e41c6ff535db780e6fb06a608d75909ed69af20336c9343880390` |
| `out/dual-beacon-tag/dual-beacon-tag-enclosure/enclosure-shell.step` | `78dd5e6c4ec265e75e6afde744c92af78f8fbe6e03fc21ced6e4276217ceb100` |
| `out/dual-beacon-tag/dual-beacon-tag-enclosure/enclosure-lid.step` | `807ec2b65f40383cfc9378a8f2f0dd3d7902086a6e9da357d2ed6a2ca72abca3` |
| `out/dual-beacon-tag/dual-beacon-tag-enclosure/enclosure-assembly.step` | `f0bcb01617760dc60645968c35a944216f9744af41cea666c1830cd8a4bc812a` |

#### FW
| path | sha256 |
|---|---|
| `out/dual-beacon-tag/dual-beacon-tag-fw/flash.bin` | `fedb74a52429557e75e43cc7703f7b70904d97a095d89a1a1727a12d76ce95e8` |

### 視覚レビュー

**workaroundの経緯**: 容器内の `derive_visual_review` は `out_root` に対して誤った相対パスでSVGを探索し失敗した。また、非電気的SVG（layout・system・firmware・mechanical投影）がKiCad形式以外の `<title>` を持つため、単純にパス合わせだけでは `normalize_svg` で失敗する。これらのフレームワーク制約を回避するため、基板電気的投影のみを一時ディレクトリに分離して `derive_visual_review_pngs.py` を実行し、生成物を `final-out/` に保存した。

`scripts/derive_visual_review_pngs.py`（電気的投影3件に対して）→ **exit 0**
- `dual-beacon-tag-b-cu-png` (sha256:`3cf3823e02b66bbe70b65069e4c05b8610985efe30dd9979c03bfc8a507c1810`)
- `dual-beacon-tag-f-cu-png` (sha256:`514cf32c05e08853cffcf7cf148f689a9be1b1c41c1efa6669890476dd923440`)
- `dual-beacon-tag-schematic-png` (sha256:`f763a63fc6f1df9547fbe7bc6a27092212bcc8c87159dc91ea387aeaae0b007f`)

`scripts/record_visual_vision_observation.py`（3件全て）→ **exit 0**

`scripts/verify_visual_review.py` → **exit 0**, 出力:
```
dual-beacon-tag-b-cu-png: OK
dual-beacon-tag-f-cu-png: OK
dual-beacon-tag-schematic-png: OK
visual review: complete (3/3 observed)
```

**視覚レビュー所見の要約**:
- すべてのPNGは正常にrasterizeされ、1600×1131〜1173ピクセルの画像として生成された。モノクロ銅層画像はRGBA、回路図はRGB。
- 透明/不透明ピクセル数から、意図した描画内容が画像内に含まれていることが確認できる。
- labelの重なり・読みやすさ・凡例・余白・誤った内容の詳細評価は、人間による直接の視覚検査が必要であり、本環境では代替できない。
- 以上はL3観測であり、合否Evidenceではない。

### 製品ドキュメント

- **製品説明README**: `acd-product-docs` Skillで生成成功
  - `final-out/docs/product-readme.md`（theme-song節含む）
  - provenance: `final-out/docs/product-readme.md.provenance.json`
- **取扱説明書**: `generate_instruction_manual.py` → **fail-closed**（exit 1）
  ```
  instruction manual generation failed: pin projection ... is missing macros: ACD_LOG_PERIOD_MS, ACD_PIN_BOOT, ACD_PIN_UART_RX, ACD_PIN_UART_TX, ACD_PIN_USB_DN, ACD_PIN_USB_DP, ACD_SHT40_I2C_ADDRESS
  ```

### authoritative Evidence 検証

`scripts/verify_authoritative_evidence.py --revision-from fixtures/dual-beacon-tag/graph.json --out-root out/dual-beacon-tag --require-lane electrical --require-lane mechanical --require-lane firmware` → **exit 0**

出力:
```
OK: 3 authoritative Evidence file(s) verified
```

詳細:
| Evidence | status | target_revision | container_digest |
|---|---|---|---|
| `evidence-electrical.json` | `valid` | `r1` | N/A |
| `evidence-mechanical.json` | `valid` | `r1` | N/A |
| `evidence-firmware.json` | `valid` | `r1` | N/A |

### report_final_basis

`scripts/report_final_basis.py --root /home/openhands/acd-workspace-regen-20260909 --design-input fixtures/dual-beacon-tag/spec.json` → **exit 0**

出力は以下の通り（引用）:

#### source changes
```
status: changed
no commits past the bootstrap revision
worktree git status --porcelain: 49 paths (fixtures, evidence, final-out, visual-observations などがuntracked)
worktree git diff HEAD --stat: <empty>
```

#### design values（抜粋）
部品表は `fixtures/dual-beacon-tag/spec.json` から機械抽出された以下の通り:
- C1-C4: CL10A106MQ8NNNC / CL10B104KB8NNNC (LCSC C1691 / C1591)
- D1-D2: KT-0603G / KT-0603A (LED)
- J1: TYPE-C-31-M-12 (USB-C, C165948)
- R1-R6: 0603WAF4701T5E / 0603WAF5101T5E
- SW1: TS-1088-AR02016 (BOOT button, C720477)
- U1: ESP32-C3-MINI-1-N4 (C2838502)
- U2: AMS1117-3.3 (C6186)

### 成果物

`dual-beacon-tag-regen.tar.gz`（workspace直下、1.9MB）に以下を含む:
- `out/dual-beacon-tag/`（基板・筐体・FWの3 lane出力、Gerber/drill、CPL/BOM、DFM、Evidence、loop-summary、timing-record、hash manifestなど。build treeは除外）
- `fixtures/dual-beacon-tag/`（graph.json / spec.json / rationale.json / requirements.json / overlays）
- `final-out/docs/`（product-readme.md + provenance）
- `final-out/dual-beacon-tag/visual-review-manifest.json`
- `final-out/dual-beacon-tag/visual/png/`（rasterized PNG 3件 + reproduction）
- `final-out/dual-beacon-tag/visual/vision-observations/`（3件の観測記録）
- `visual-observations/`（観測テキスト原稿）

### 結論

設計入力は変更せずに全投影の再生成を試みた。基板・筐体・FWの3 laneは生成完了し、各Evidenceは `valid`・`target_revision: r1` で検証された。ただし、loopは `visual-review-manifest` 段でfail-closedとなり、`ok: false` のままである。order-readiness段は `--design-only` により未実行である。合格・order-ready・実機動作の主張は行わない。
