# dual-beacon-tag 修正後run（Devin修正版）

> **注意**: 本ディレクトリは**第10回検証のリモートGUI run（本階層の `loop/`・`control/`）とは別の、
> Devinが設計入力（fixture spec）を修正してdigest固定containerで再実行した記録**である。
> 第10回の結果は引き続き**不合格**（board-pipeline `U2: graph CPL rotation offset differs
> from LCSC Evidence` で停止）であり、ここに収録するEvidence・投影は
> **エージェント生成設計ではなくDevin修正後設計**のものである。
> 「エージェントが単独で全投影を完走した」ことを意味しない。

## 結果サマリ

- 実行: digest固定image `ghcr.io/uist1idrju3i/acd-server@sha256:fb236ff5…a3b9e` 内で
  `run_design_loop.py --fixture fixtures/dual-beacon-tag --fixture-spec … --fixture-overwrite --design-only`。
- **最終run fix18 は設計側の全12段を通過**（routing converged、DRC/ERC 0、
  8 gerber+drill、CPL/BOM生成・クロス検証、DFM 0 findings、製造パッケージ、
  全visual投影、theme-song投影、hash manifest、筐体・FW lane完走）。
- `evidence-{electrical,mechanical,firmware}.json` が生成され、
  `scripts/verify_authoritative_evidence.py` で3 laneとも `status="valid"` /
  revision `r1` / container文脈 / source `573379d… clean` を確認
  （`loop/verify-authoritative-evidence.txt`: `OK: 3 authoritative Evidence file(s) verified`）。
- loop-summary は `ok: false` だが、唯一の停止は `order-readiness`:
  **design-only モードでは order readiness は構造的に未実行（fail-closed）**。
  `order-readiness.json` 自体は `status: "ready"`・unknowns 空。
  合格には発注入力（`--order-total` / quote record / order scope）が必要であり、
  設計探索では回復しない。**order-ready の主張はここでは行わない。**

## 実行一覧（fix1..fix19、すべて digest固定container内）

| run | 変更内容 | failed_stage | 失敗理由（要約） |
|---|---|---|---|
| fix1 | U2 `cpl_rotation_offset_deg` 180→0（後に撤回） | board-pipeline | `U2: graph CPL rotation offset differs from LCSC Evidence`（basisがestimatedだとoffsetが0.0に強制される機構を特定） |
| fix2 | U2 `evidence_basis`→confirmed、offset 180維持 | board-pipeline | `fitted component without LCSC part number`（J2がfittedのまま） |
| fix3 | J2 `assembly: not_fitted` | board-pipeline | `rationale coverage failed: missing=8 stale=8`（comp.j2のrecordが8属性を埋め込み・stale化） |
| fix4 | spec再生成方針へ転換（U2確定、J2 not_fitted、i2c net改名、J2開口部） | board-pipeline | `electrical deterministic gate` — DFM pad-to-board-edge（SW1 1.075mm < 0.3mm クリアランス違反相当）・FW `button` role欠如 |
| fix5 | `net.boot`→`net.button`（name=BOOT維持）、SW1 y 3.3→3.6 | board-pipeline | `UncoveredGroundRegionsError` F.Cu (18.3,8.6)-(24.2,12.5) |
| fix6 | U1 pad6→null（GPIO3未使用化）、stitch-via格子0.02、refill反復5 | board-pipeline | 同島が J1 直下 (10.3,15.2)-(15.4,19.8) に移動 |
| fix7 | `ground_plane_min_island_area_mm2` 30 | board-pipeline | `copper island is below declared minimum area` — 宣言値は充填後チェックのみでKiCad zoneへ未出力（デッドレバー、撤回） |
| fix8 | TP1テストポイント追加 | lane-preflight | `component_body` 未宣言（comp.tp1） |
| fix9 | TP1 body追加 | board-pipeline | DRC: `courtyards_overlap` J1↔TP1 + `starved_thermal` J1 A12/B1（1 spoke < 2） |
| fix10 | `min_clearance_mm` 0.10、TP1撤去 | board-pipeline | router `not_converged`（USB_D+ が18 pass停滞）→ 0.10は撤回 |
| fix11 | clearance 0.15復帰、via pitch 0.025 | board-pipeline | 同島不変（viaピッチに不感） |
| fix12 | J1 y 18.35→17.8 | board-pipeline | 島がJ1と共に平行移動（J1位置にも不感） |
| fix13 | `min_clearance_mm` 0.15→0.12（trackは0.15維持、JLC最小0.1を尊重） | board-pipeline→silkscreen-resolve | pourがpad列の隙間へ抜けて島解消。新停止: シルクラベル衝突 |
| fix14 | ラベル短縮（USB→J1, LED1→D1, LED2→D2, BTN→SW1）、search limit 12 | board-pipeline | **silk通過**（2反復でmeasured_pass）。最終gateで `not_order_ready`: CPL回転basis未確認15部品 |
| fix15 | board_id のみ残して機能ラベル全撤去 | silkscreen-resolve | `accepted unresolved text coordinates: board_id` — 単一未配置テキストは仮配置でmeasured_pass→fail-closed検出（resolverデッドロック、AA-14） |
| fix16 | 全15 fitted部品 `evidence_basis`→confirmed + note、D1 `lcsc` C16224→C12624（typo修正）、C2/C3/C4/R5/R6/D1の記録を宣言lcsc値で再fetch、silk復帰 | board-pipeline | `not_order_ready` — unknowns は SW1 のみに縮小 |
| fix17 | SW1 `cpl_rotation_evidence_basis`→confirmed（attrs + oe） | board-pipeline | 依然 SW1 — SW1は `part_request` 無しのため `cpl_rotation_evidence_revision` が自動注入されない（AA-13） |
| fix18 | SW1 attrsに `cpl_rotation_evidence_revision: "dual-beacon-tag-r1"` 等を明示 | order-readiness（design-only構造停止） | **設計全段通過**。Evidence 3 lane valid・検証OK |
| fix19 | （未実行）KT-0603A の正規LCSC番号は特定不能 → D2は現状維持・未解決項目へ | — | — |

## 設計入力の変更（`design-input-changes.diff`、対 `fixture-effective`）

1. **U2 CPL回転**: `cpl_rotation_evidence_basis` estimated→confirmed、offset 180.0維持、
   note を `evidence/dual-beacon-tag-cpl-orientation/U2.json (C6186)` 参照へ。
   `apply_cpl_contract` は basis≠confirmed の部品のoffsetを0.0へ強制するため、
   offset値ではなくbasisが真因だった（実測180.0はリポジトリ自身の
   `derive_lcsc_rotation_offset` で検証、max_error 0.27mm）。
2. **J2 not_fitted**: `assembly: not_fitted`、`jlcpcb_class: none`（手ハンダ付け前提。
   BOM/CPL/DFM/回転evidenceをskip）。
3. **net改名**: `net.scl→net.i2c_scl`、`net.sda→net.i2c_sda`、
   `net.boot→net.button`（net name "BOOT"・pin id `fw.pin.boot` は維持 —
   strapping gateはnet name、capability gateはrole suffixを見る）。
4. **U1 pad 6 → null**（GPIO3未使用化。FW pin一意性ゲートの `net.led` が
   pad 20/6 二重割当を解消）。
5. **SW1 y 3.3→3.6**（DFM pad-to-board-edge 0.3mm確保）。
6. **stitch-via**: `wavelength_fraction` 0.05→0.025、refill反復 3→5（密度探索。
   島自体はこれでは解消しなかった）。
7. **`min_clearance_mm` 0.15→0.12**（pour接続のpadモート縮小で J1 直下ポケット解消。
   track width は 0.15維持、JLC min 0.1 未満には下げない）。
8. **シルクラベル**: 4機能ラベルを短縮・search limit 12へ（fix14で解決済。
   fix15の全撤去はresolverデッドロックを示したため復帰）。
9. **全fitted部品の CPL回転evidence**: `evidence_basis: confirmed` +
   record参照note（計15件）。**D1 `lcsc` を C16224→C12624 に修正**
   （C16224は別部品=FPCコネクタでありspecのtypo。正規値は取得recordの
   `Manufacturer Part=KT-0603G` と LCSC商品ページで確認）。
10. **SW1**: `part_request` 不在のため `cpl_rotation_evidence_*` をattrsで完全宣言
    （`evidence_revision: dual-beacon-tag-r1` 含む。oe経路の自動注入は
    part_request無しでは走らない — AA-13）。

## contracts/parts-catalog.json の変更（`catalog-changes.diff`）

- KT-0603G・KT-0603A LED、PinHeader_1x04_P2.54mm_Vertical コネクタの追加のみ
  （commit 573379d、+80行）。footprint/symbolのsha256はcontainer内実ファイルで検証済。
- これは本修正runにおける**唯一の非fixture変更**であり、レビュー対象のリポジトリ変更として
  本ブランチへcherry-pick済み。

## LCSC Evidence record の再取得

`evidence/` の17件のうち、**宣言lcscと不一致／別部品だった6件を再fetch**
（host上で `scripts/fetch_lcsc_footprint_orientation.py` を実行した**入力**であり、
L1のauthoritative Evidenceではない — 検証は常にcontainer内でrecordの
canonical hash・refdes・lcsc一致・測定offset再計算を行う）:

| refdes | 宣言lcsc | 旧recordの中身 | 新recordの中身 |
|---|---|---|---|
| D1 | C12624（spec側も修正） | C16224 = FPCコネクタ10P | KT-0603G（0603 Green） |
| C2, C4 | C1591 | C440198=GRM21B 10uF / C1620=470pF | CL10B104KB8NNNC（100nF、宣言一致） |
| C3 | C1691 | C8598 = B5819W ダイオード | CL10A106MQ8NNNC（10uF、宣言一致） |
| R5, R6 | C23186 | C23162 = 4.7k | 0603WAF5101T5E（5.1k、宣言一致） |

残る11件（J1/U1/U2/D2/SW1/R1-R4/C1/J2）はagent取得recordをそのまま使用し、
container内でoffsetが再導出されることを確認済（U2=180.0、他は0.0、
J1はgeometry-exception経路で0.0）。

## 注意事項・未解決項目

- **order-readiness**: design-onlyでは構造的に未実行（fail-closedの仕様）。
  `order-readiness.json` の `status: "ready"` はboard-levelのCPL/BOM判定であり、
  発注ゲート自体は `--order-total` 等の発注入力が無ければ合格しない。
  本runは order-ready を**主張しない**。
- **本EvidenceはDevin修正後設計のもの**であり、第10回でagentが生成した設計の
  合格を意味しない。第10回のrunは board-pipeline で停止したまま。
- **D2（橙LED）未解決**: specは `mpn=KT-0603A` / `lcsc=C2290` だが、
  record C2290 の実体は `KT-0603W`（白）。LCSC・EasyEDAで
  `KT-0603A` の正規番号は確認できず（Kento 0603系列: R=C2286, Y=C2287,
  B=C2288, YG=C2289, W=C2290, G=C12624。amber/橙は型番体系に存在しない可能性）、
  D2は現状のまま残した。要件「橙LED」を厳密に満たすには mpn/lcsc/要件文の
  整合を再検討する必要がある（色の決定は製品判断のためここでは変更していない）。
- **既知のコード挙動**（修正せず観測のみ）:
  - `ground_plane_min_island_area_mm2` は充填後検証のみでKiCad zoneへ未出力（AA-11）
  - `apply_cpl_contract` が basis≠confirmed のoffsetを0.0へ強制（仕様として確認）
  - silkscreen resolverは未配置テキストがmeasured_passへ進むと位置を確定せず
    fail-closedする（AA-14）
- 本ディレクトリのbinary投影（gerber/STEP/3MF/MID）は **digest固定containerで
  生成・downloadされたもの**であり、host再生成ではない。

## 投影形式の独立検証（`projection-format-check.txt`）

利用者から`theme-song.mid`が再生できないとの報告を受け、収録した全投影72件（検査script・log・追加投影を含む）を
生成側writerとは独立したreaderで検査した（`check-projection-formats.py`、host実行のL3観測）。

- `theme-song.mid`: 収録版・container出力元・利用者受領版の3者はsha256一致
  （`4f0a7bcc…1972`、3317 byte）。`mido`（SMF parser）と`midicsv`で5 track・344 note、
  note_on／note_off対応、EOT位置がchunk長と一致、`timidity`で約44秒のrender成功。
  **ファイル構造の破損は再現できず**、報告された症状は再生環境側（OSに`.mid`の再生handlerが
  無い等）の可能性が残る。判別のため`timidity`でWAV→MP3へrenderした聴取用ファイルを
  報告に添付した（生成物ではないため未収録）。
- STEP×3: `ISO-10303-21;`〜`END-ISO-10303-21;`、entity 518〜2714件。
- 3MF: zip CRC全件OK、`3D/*.model`をXMLとしてparse、object 4件。
- gerber 8層: `%FSLA`／`%MO`指定と`M02*`終端、drill: `M48`〜`M30`、87穴。
- CSV 3件（行長一致）、SVG 9件（XML parse）、JSON 34件。

結果は72件すべて`OK`（`FAIL`／`UNCHECKED` 0件）。ただしこの検査は事後にhostで行ったもので、
pipeline自体は各投影を「書けたこと」と`hashes.json`のsha256でしか記録していない
（theme-songのみwriter内部の再読込でnote対応を確認）。writerと独立したreaderによる
形式検査をpipelineの投影段へ入れる項目をAA-23として
[`docs/vibebb-gap-analysis.md`](../../../docs/vibebb-gap-analysis.md)とroadmap 14.24へ追加した。

## 追加投影（`docs/`・`manufacturing-submission.json`）

利用者要望「acd-agentの持つすべての投影出力」に対し、loopが呼ばない生成器を同じdigest固定
container（`run_in_workspace.py`、server `sha256:fb236ff5…`）でfix18の入力から追加実行した。
loop外の生成器は`out/`を含まないworktree複製で動くため、fix18の`out/`をhostから`/acd-src`経由で
container内へ持ち込んで入力にした（設計入力・生成器は無変更）。

- `docs/product-readme.md`・`docs/product-readme.md.provenance.json`: 製品説明README
  （`generate_product_readme.py --graph … --projections visual-projections-{electrical,layout,system}.json`）。
  2回実行して文書はbyte一致（`6f6f9864…bc83`）。provenanceは`pass_evidence: false`のL3文書。
- `docs/instruction-manual.fail-closed.log`: 取扱説明書（`generate_instruction_manual.py`）は
  **fail-closed（exit 1）**。DBTの`acd_pins.h`（`LED`・`LED2`・`BUTTON`・`I2C_SDA`・`I2C_SCL`・
  `LED_BLINK_PERIOD_MS`）にGD1固有の必須macro（`ACD_PIN_UART_TX/RX`・`ACD_PIN_USB_DP/DN`・
  `ACD_PIN_BOOT`・`ACD_SHT40_I2C_ADDRESS`・`ACD_LOG_PERIOD_MS`）が無い。回避せずそのまま収録（AA-25）。
- `manufacturing-submission.json`・`manufacturing-submission.host-verdict-recheck.log`: 製造提出verdict
  （`verify_manufacturing_submission.py --require-authoritative`、CIの`container-gates`と同じ引数）。
  container内で`status: pass`（`required_artifacts`〜`evidence_validity`の8検査PASS）、
  host `--verdict`再検査exit 0。order lane（`order_readiness_status`・見積・order-total）は含まない。
- 未実行: PNG raster（`derive_png_visual_projections`にCLIが無い）、order lane投影（発注入力を作らない）。
  MML楽譜投影は未実装で利用者要望として計画へ（AA-26）。

これらがloopから生成されない点をAA-24（loop投影段への組み込み）として
[`docs/vibebb-gap-analysis.md`](../../../docs/vibebb-gap-analysis.md)とroadmap 14.24へ追加した。

本runでDevinが人手で越えた境界の振り返りと、それをagent単独の到達段へ繋げる
実装項目（AA-15〜AA-22）は
[`docs/vibebb-standalone-verification.md` §17.12](../../../docs/vibebb-standalone-verification.md)
を参照。

## 収録内容

- `fixture/`: 最終 `spec.json`・resolve後 `graph.json`・`rationale.json`
- `evidence/`: LCSC CPL向きrecord 17件
- `loop/`: loop-summary / timing-record / order-readiness / Evidence 3 lane /
  verifier出力 / hashes / theme-song-projection / visual-projections各種 /
  DFM report / fab-package manifest
- `fab/`: CPL（pos.csv + jlcpcb形式）と BOM CSV
- `gerbers/`: 全gerber + drill
- `enclosure/`: STEP×3 + 3MF（いずれも <150 KB）
- `theme-song/theme-song.mid`
- `visual/`: 配置・両面Cu・積層・回路図・系統図・機械断面/干渉 SVG
- `check-projection-formats.py`・`projection-format-check.txt`: 収録投影の独立reader検査（host、L3）
- `docs/`: 製品説明README＋provenance、取扱説明書のfail-closed log（container追加実行）
- `manufacturing-submission.json`・`manufacturing-submission.host-verdict-recheck.log`: 製造提出verdict（container）＋host再検査
- 省略: firmware `.bin`/build tree、`.kicad_pcb` 中間生成物、routed board
