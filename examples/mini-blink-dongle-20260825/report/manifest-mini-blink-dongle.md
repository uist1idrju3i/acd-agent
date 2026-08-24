# 成果物マニフェスト: mini-blink-dongle（2026-08-24〜25）

本フォルダの各ファイルの出所・取得経路・用途とsha256を記録する。

## 出所

| 区分 | 出所 | 取得日時(UTC) | 備考 |
|---|---|---|---|
| 会話ログ | 実機OpenHands Local GUIのconversation export（Markdown） | 2026-08-24（ユーザーが添付） | conversation ID 6件。raw export zipは環境識別情報を含むため未収録 |
| fixture・実行成果物 | 実機workspace `test4`のアーカイブ（ユーザーがGoogle Drive共有、gzip tar 約522MB／展開後約2.0GB） | 2026-08-24 | HEAD `b3064c1`（detached）。untrackedな`fixtures/mini-blink-dongle/libraries/`と`regen_rationale.py`を含む |
| レポート | 本セッションのDevinによるレビュー結果 | 2026-08-24 | 会話ログとアーカイブの全件レビューに基づく |

## conversation IDと対応ファイル

| # | conversation ID | 時刻(UTC) | ファイル |
|---|---|---|---|
| 1 | `d1f6f0f9-4b2c-434b-97ee-d3e1f8a78630` | 15:37:53 | `conversation/conversation-d1f6f0f9-….md` |
| 2 | `5ebeaec6-d61d-41f9-b749-dd420dd4483d` | 15:40:19–16:04:44 | `conversation/conversation-5ebeaec6-….md` |
| 3 | `cd814e50-0c66-40a9-b18f-b6e4fb57688a` | 16:08:16–17:20:17 | `conversation/conversation-cd814e50-….md` |
| 4 | `4951d9b2-0b47-42b1-b69b-9c263ec08968` | 17:20:52–17:26:37 | `conversation/conversation-4951d9b2-….md` |
| 5 | `d2061859-94fe-432f-be4f-150344490471` | 17:28:35–17:33:55 | `conversation/conversation-d2061859-….md` |
| 6 | `ced4bad0-7d78-4a1a-96e1-b838a65e2d8f` | 17:34:44–17:36:25 | `conversation/conversation-ced4bad0-….md` |

## 秘匿化

会話ログは原本のままである。例外は1件のみで、
`conversation/conversation-4951d9b2-0b47-42b1-b69b-9c263ec08968.md`に現れたホスト名の断片を
`[REDACTED-HOST]`へ置換した（1行、git commit失敗時のエラー出力中）。置換前のsha256は
`243359b69d1c5e4a1739a9df86688172e0e44dc3d0e4c49605370d11159adf8e`である。
他の5本のMarkdownは無改変で、下表のsha256が原本のものである。

OpenHandsのraw export zip（6本、計約5.2MB）は`base_state.json`にホスト名・LLMエンドポイント・
実行環境の識別情報を含むため収録していない。API key、token、SSH鍵、環境ファイルは
本フォルダに含まれない。

## 取り扱い注意

- `runs/host-design-loop/order-total.json`は実機agentが停止回避のために作成した**架空の
  ダミー入力**であり、見積・発注の記録ではない。再利用禁止。
- `agent-artifacts/regen_rationale.py`は実機agentが自作した未追跡scriptで、ACD本体の
  資材ではない。rationale coverageの抜け道の証拠として保存している。
- `fixture/`は設計の手本ではない。LED回路が要件と不一致である（README参照）。
- 本フォルダにauthoritative Evidenceは存在しない。

## ファイル一覧（sha256）

| ファイル | サイズ(bytes) | sha256 |
|---|---:|---|
| `README.md` | 7677 | `f4e5e40e4bcdd52a839d6381f8b3e9310b5a2d637c1d7c7f578c2f3c24b3e41a` |
| `agent-artifacts/regen_rationale.py` | 2133 | `415f305febea2afca54299ac9ccc5a5ecd465e7ec9ce1d8e267518989f82d02b` |
| `conversation/conversation-4951d9b2-0b47-42b1-b69b-9c263ec08968.md` | 54351 | `ecb783b1ba6a09872482bac8d68594f99371371bccb7fd9020f8ced5e65f8689` |
| `conversation/conversation-5ebeaec6-d61d-41f9-b749-dd420dd4483d.md` | 263484 | `a0033728c71e161f1f61945c061276ba492996d2edea835c3334024fa9910334` |
| `conversation/conversation-cd814e50-0c66-40a9-b18f-b6e4fb57688a.md` | 775733 | `4434615079927b3b4e32622fb5b55e720d69916944d3bc647c3d501e933c9381` |
| `conversation/conversation-ced4bad0-7d78-4a1a-96e1-b838a65e2d8f.md` | 18818 | `d59350afda3f273e49adb5e8ea76830898ddb3c37b1ffd12d8f31cde88034aa5` |
| `conversation/conversation-d1f6f0f9-4b2c-434b-97ee-d3e1f8a78630.md` | 1904 | `32f8265533ab17bf024d8e6d4c7adfecc2fb266e92c0c6034c0fcf51e29327ff` |
| `conversation/conversation-d2061859-94fe-432f-be4f-150344490471.md` | 63428 | `b8dbc023665621357106a28fbbc6ee37e21bc83c25ec6c3bf7846fe185d47cf6` |
| `fixture/graph.json` | 48997 | `ad43adeaa04d69d0f2d7c0bc567e80e0322622525ef88daa7453ab6e765e844a` |
| `fixture/rationale.json` | 34561 | `febf1e7b643a0e15f8b4fe691c372c520dfcaf9f16dd2d6970fad0be01e70c7e` |
| `fixture/requirements.json` | 3621 | `38c1ab1e0aa8b545e0e8a4720422815f2701156d5edda9b1a6c6ea311c1cb386` |
| `fixture/spec.json` | 15554 | `19271cb1e61e5b8bafc80d963a1da824ef48f13a05cc034179b14f4c68ed87ec` |
| `fixture/libraries/Espressif.kicad_sym` | 15502 | `bca977294f75d84261181e0b443f5ee9292412d5ed56c3292079685376883a2b` |
| `fixture/libraries/README.md` | 1073 | `9570f48de78f964d51111c93e9dbfa461595b3477ce7cb94083b33404f167f5f` |
| `fixture/libraries/Espressif.pretty/ESP32-C3-MINI-1.kicad_mod` | 13519 | `f1899b54ab6c007d50e76334f3fb8f340a827bc1d26f1ba24003333c214a7626` |
| `report/devin-report.md` | 15253 | `1038217c75ba2cde7ecbd8662f098996f437634447f3668dcd8e7cf3acb5a3c0` |
| `report/improvement-notes.md` | 10729 | `5513d07bdb75a7c8a88b2e8e5282df8235fbf1287124f6f9e2fea5d1385331e5` |
| `runs/container-silkscreen/fp-lib-table` | 950 | `d7fff1b24ef78a3983a12a9f700387d43a481ef9742959df84b073d8bd00264e` |
| `runs/container-silkscreen/mini-blink-dongle.bom.csv` | 754 | `5dd7f29cfc211087712cb3550832dddfabd2447003a7066672608086f18fe6b6` |
| `runs/container-silkscreen/mini-blink-dongle.kicad_dru` | 241 | `591c0c872525b9250980f09d826f976e98c5fd110a7a0104cf72c3ef314b4735` |
| `runs/container-silkscreen/mini-blink-dongle.kicad_pcb` | 62251 | `b3fff8eeb6c137c61b6c69ef400a11fa886e80d541208967049720c44ce1c364` |
| `runs/container-silkscreen/mini-blink-dongle.kicad_prl` | 2304 | `f0c7ff9abf13e7e9a2693df6b33fcc3abda7dd28c25ddfbb427cab007d992320` |
| `runs/container-silkscreen/mini-blink-dongle.kicad_pro` | 1120 | `b3068a09864548cfb1caa1f7ba35ccb88187b8f3293b600ae74017410f287c26` |
| `runs/container-silkscreen/mini-blink-dongle.kicad_sch` | 96543 | `147f2302024a949e0e1b2782edf9c4120bc54cae7abac26a940968a9edf0bb88` |
| `runs/container-silkscreen/silkscreen-context-iteration-1.json` | 234658 | `c018884d5f7a4e8d7e77c756c17ba94d48730751fb7074e725c4f39070f58d09` |
| `runs/container-silkscreen/silkscreen-context.json` | 234658 | `ea90e459393111a6a699889e2730b9d0afca22ca78d95aa702287bd0bbbed505` |
| `runs/container-silkscreen/sym-lib-table` | 781 | `b3e4a120a748709211b821e2a6dad3f90bafd519b2defe203e81b4e963bbb92f` |
| `runs/container-silkscreen/gerbers/gerbers.envelope.json` | 812 | `079f6e3619eb019fa0e18021ec6e4ca6a721a08014dc5a7124c9c74e27a29fd3` |
| `runs/container-silkscreen/gerbers/mini-blink-dongle-B_Mask.gbs` | 782 | `767fbf1435dc937b3f918fb2f02f5567fd358cf6b9d2ddcb4f4c3f1778c4385b` |
| `runs/container-silkscreen/gerbers/mini-blink-dongle-B_Silkscreen.gbo` | 10962 | `062b95afed9da8c947acc864de39e39acf081377851800391c5bd891a31bdb4a` |
| `runs/container-silkscreen/gerbers/mini-blink-dongle-Edge_Cuts.gm1` | 708 | `0e26bbd7bf66cae71f50f34ec696b97cdb0f758d038e51f8e399f420383caae9` |
| `runs/container-silkscreen/gerbers/mini-blink-dongle-F_Mask.gts` | 14435 | `d9e5d0f9273bbe0ad025ca01f4773cd4c0a962df29eaabb05ec92027a090f33d` |
| `runs/container-silkscreen/gerbers/mini-blink-dongle-F_Silkscreen.gto` | 12002 | `cc2377712d4e0718b5aff08d3bc7e664131527d7da28f7602bec27a44b0cb8ce` |
| `runs/container-silkscreen/gerbers/mini-blink-dongle-job.gbrjob` | 2249 | `14ae97c99d743fd1ad6ece055060210b9561425dd0b1cf58efa00223f2a8fd9c` |
| `runs/host-design-lanes/timing-record.json` | 469 | `9c16caf0fa2c5245ba024a13894ab96e9c0ef646ab49533226a427a9c87dfec6` |
| `runs/host-design-lanes/work-fixture/graph.json` | 48997 | `ad43adeaa04d69d0f2d7c0bc567e80e0322622525ef88daa7453ab6e765e844a` |
| `runs/host-design-lanes/work-fixture/requirements.json` | 3621 | `38c1ab1e0aa8b545e0e8a4720422815f2701156d5edda9b1a6c6ea311c1cb386` |
| `runs/host-design-loop/design-freedom-declaration.json` | 11842 | `617d4d87bae77faca704f6e2daacd5326980c78af93a01f5a6e5673e1cd9f838` |
| `runs/host-design-loop/loop-host.json` | 982 | `aa9d41ef2d03bd222e47fb2e8d3c63fced256bf34d46c8b511741ec26e81215b` |
| `runs/host-design-loop/loop-output.txt` | 324 | `4e21ca4a5555001e79dbd1f7493e47c5463360b58c1f6168a167ccc3efa7c965` |
| `runs/host-design-loop/loop-result.json` | 324 | `4e21ca4a5555001e79dbd1f7493e47c5463360b58c1f6168a167ccc3efa7c965` |
| `runs/host-design-loop/order-total.json` | 583 | `73d82405aca5a9e2133ffa0d5743a9b31c600b85c9db5f6f992d6c150b8750ce` |
| `runs/host-design-loop/rationale-coverage.json` | 5621 | `f3c7beb8c9ac5432afe38b98305e870d122303f7aa2a85981e7d612218ca13ec` |
| `runs/host-design-loop/timing-record.json` | 464 | `3ad861ff2f4985c6d9ddfc5f211f0f3b0fdfa8c02b794aad22609d91446b7d98` |
| `runs/host-design-loop/requirement-entry/design-freedom-declaration.json` | 11842 | `617d4d87bae77faca704f6e2daacd5326980c78af93a01f5a6e5673e1cd9f838` |
| `runs/host-design-loop/requirement-entry/rationale-coverage.json` | 341 | `9b15124fd08020d7c6988474159f635cd648b1f342d2362e846f5b9da602341e` |
| `runs/host-design-loop/requirement-entry/rationale.md` | 21969 | `c55a9a5c923711509483c7656cb3034694d511aa9887b2c0105cd2da999f4a92` |
| `runs/host-design-loop/requirement-entry/timing-record.json` | 524 | `0f3b5511e3a0733fd67b7157011cf729ceef7fb045c0fa52164b2cfde46c3e01` |
| `runs/host-design-loop/requirement-entry/gate-evidence/design-predicates.json` | 3614 | `03eb3d68e3c136194288ddc6123cc192b16a9109e2a865887f0d76847b6e059c` |
| `runs/host-lane-probe/board/design-freedom-declaration.json` | 11842 | `617d4d87bae77faca704f6e2daacd5326980c78af93a01f5a6e5673e1cd9f838` |
| `runs/host-lane-probe/board/rationale-coverage.json` | 341 | `a5881665c7d349e9fb314c0601546ddfb13db8b321f165869e99b9bc4b698f1d` |
| `runs/host-lane-probe/board/rationale.md` | 21309 | `49021d974dd17adf7a5123489ca4aa54cf0b27601326e85e6d135bedd847182c` |
| `runs/host-lane-probe/board/timing-record.json` | 525 | `653f53598c246f2d43a68ea3519c2f5b07a829e0c12325711e7316123ef1f762` |
| `runs/host-lane-probe/board/gate-evidence/design-predicates.json` | 2826 | `4c53f18f49845f9c23d4b3c777136086232474f44540861b046cafb10cf4cbcf` |
| `runs/host-lane-probe/enclosure/rationale-coverage.json` | 341 | `a5881665c7d349e9fb314c0601546ddfb13db8b321f165869e99b9bc4b698f1d` |
| `runs/host-lane-probe/enclosure/rationale.md` | 21309 | `49021d974dd17adf7a5123489ca4aa54cf0b27601326e85e6d135bedd847182c` |
| `runs/host-lane-probe/enclosure/timing-record.json` | 535 | `c9482b6a936acbb2a5bc602f5f16121f92deb71f74dc980f15a344ce76240269` |
