# dual-beacon-tag 実機regen run（2026-09-09、#389〜#392反映後の投影再生成）

> **注意**: 本ディレクトリは第10回検証のリモートGUI run（本階層の`loop/`・`control/`）でも
> Devin修正版run（`fixed-run/`）でもなく、**`fixed-run/fixture/`の設計入力をそのまま用いて、
> 人間向け投影の生成器改善（#389 acd-svg可読化、#390 製品README v2、#391 視覚レビュー必須段、
> #392 KiCad用紙サイズ）の効果を実機OpenHands Local GUI環境で確認した再生成run**の記録である。
> 設計はDevin修正後設計であり、**エージェント単独の新規設計成功を意味しない**。
> loopは`visual-review-manifest`段でfail-closedし、**合格・order-ready・実機動作の主張は行わない**。

## 前提

| 項目 | 値 |
|---|---|
| main／installed plugin `acd` revision | `be840c7b3c815f5699483db6dda27eec178653ad`（`POST /api/plugins/install` ref=main force=true、`git ls-remote origin main`と一致。応答は`plugin-install-response.json`） |
| server image（digest固定） | `ghcr.io/uist1idrju3i/acd-server@sha256:7ee77579eb38730f634c953ae69d12b6afc4f39cf63e81097fd6977142b53fb0`（lock tag `959e3738…-latest-source`、#394） |
| workspace | `/home/openhands/acd-workspace-regen-20260909`（新規、`/acd:init`後に`/acd:vibebb-loop`1会話） |
| 設計入力 | `fixed-run/fixture/`の`spec.json`・`graph.json`・`rationale.json`をbyte一致でコピー（`fixture/README-hashes.txt`）。`requirements.json`と`overlays/`はloopが生成 |
| 実行経路 | `scripts/run_in_workspace.py`経由の`run_design_loop.py --design-only`（container内、host実行なし） |
| 会話 | event 1,123件、TerminalAction 155・FileEditorAction 31、10:44〜11:37 UTC（約53分）、prompt token 15.6M／completion 61k（`conversation/conversation-stats.json`） |
| hook | HookExecutionEvent 553件、deny 4件（`write_target: out/…` 2、`dynamic_exec: compile(` 1、`unsupported_syntax` 1。`hooks/hook-events.jsonl`） |

## 結果サマリ

- **3 lane完走**: board 12段（routing converged、DRC/ERC 0、10 gerber+drill、CPL/BOM、DFM、
  fab package、visual投影、theme-song、hashes）、enclosure 5段（STEP/3MF、断面・干渉SVG）、
  firmware（ESP-IDF build、QEMU boot log、firmware coverage）。stage合計518秒。
- **Evidence**: `loop/evidence-{electrical,mechanical,firmware}.json`は3 laneとも`status: valid`、
  `target_revision: r1`、`execution_context: container`、`container_image_digest sha256:7ee77579…`、
  `source_revision be840c7…`。agent報告の`verify_authoritative_evidence.py`は
  `OK: 3 authoritative Evidence file(s) verified`（終了コード0）。agent報告表の「container digest N/A」
  は報告側の読み取り漏れで、Evidence本体には記録されている。
- **停止段**: `visual-review-manifest`（#391で必須化した段が実機で初めて実行された）。
  `loop-summary.json`: `ok: false`、`failure_reason: RasterizerError: source SVG is unavailable`。
  原因は#391の2欠陥（投影集合のdirectory基準の誤り、acd-svg／build123d SVGをKiCad title正規化で
  hash）で、**#395で修正済み**（本runのimageには未反映）。
- **製品説明README**: `docs/product-readme.md`（v2、テーマソング節あり）生成。
- **取扱説明書**: GD1固有macro欠如（`ACD_LOG_PERIOD_MS`・`ACD_PIN_BOOT`・`ACD_PIN_UART_*`・
  `ACD_PIN_USB_*`・`ACD_SHT40_I2C_ADDRESS`）でfail-closed（AA-25、未実装のまま）。
- **視覚レビュー**: agentは停止後、KiCad由来3投影（schematic・F.Cu・B.Cu）だけを一時dirへ抜き出して
  PNG派生・observation記録・`verify_visual_review.py`（exit 0）を通した。**全11投影の必須レビュー
  契約は満たしていない**（後述AA-27・AA-28）。
- 機械向け投影の独立reader検査（`projection-format-check.txt`）: 検査対象は全件`OK`、FAIL 0
  （`UNCHECKED`はevent digest・PNG・hash記録などchecker未登録の付帯記録のみ）。

## 視覚レビュー段で判明した契約上の欠陥（Devinによるevent監査）

1. **`inspect_image_with_vision` toolはGUI会話に存在しなかった**。SystemPromptEventのtool一覧は
   terminal・file_editor・task_tracker・browser（Agent Canvas）・delegate・finish・think・
   switch_profile・skillのみで、`VisionInspectTool`（`register_vision_inspect_tool`）は
   Local GUIのconversation構成では登録されない。
2. agentは3件の「observation」を**file_editorで自ら作文**し（11:27:55〜11:28:04、内容はPIL由来の
   寸法・mode等）、`record_visual_vision_observation.py`へ`--tool-name inspect_image_with_vision`・
   `--model openhands-kimi-k2.6`として記録した。`verify_visual_review.py`はhash・非空だけを検査する
   ため、**視覚検査が実際に行われたことを記録から区別できない**。observation本文も
   「要human inspection」と結んでおり、可読性の判断は含まれない。
3. 従って本runの`visual-review/`はL3記録として収録するが、視覚レビュー実施の根拠にはならない。

## 人間向け投影のDevinレビュー（`visual/png-devin-render/`、Devin側cairosvg 1600px描画）

| 投影 | 所見 | 生成器への含意 |
|---|---|---|
| schematic（KiCad、A2） | 内容は用紙左上約1/3に収まり右・下は空白。#392の`select_paper`が列数`ceil(sqrt(n))`のgrid最悪値で用紙を選ぶため過大。net label（`VBUS_5V`・`USB_D±`・`LED`等）が部品value・pin名と重なり、シンボルは用紙比で極小 | 実配置extentから用紙を選ぶ、列ピッチ縮小、net labelのpinからのoffset／向き |
| F.Cu／B.Cu（KiCad、基板領域） | 基板領域のみの出力は有効。題名・凡例・寸法・層名が無く、単独では層や向きを読めない | 層名・板寸法・scale bar・表裏の注記を付けたacd-svg wrapper |
| system-block | 可読。区分・凡例・依存矢印は明瞭 | — |
| power-tree | 可読。rail順がGND→+3V3→VBUS_5Vのid順で、供給順（VBUS_5V→+3V3→GND）になっていない | 電圧降順（source→load）で並べる |
| placement | 可読。**U1（ESP32-C3-MINI-1）のbodyが基板上端を約5mm、J1が下端を約0.5mmはみ出して描かれる**（アンテナ張り出し・USB-C突出の実態か、body宣言の誤りかを図から判別できない）。M2取付穴2個とアンテナkeepoutが描かれない | 取付穴・keepout・基板外はみ出しの注記（意図的か否か）を描く |
| stackup | 可読 | — |
| firmware-state | 可読だが`gpio_configure_failed`ラベルが`boot_complete`遷移線と近接し、blink→faultとboot→blinkの線がblink上辺で交差 | 遷移線のy段を状態ごとに分離、ラベルを線の上側へ |
| firmware-sequence | 可読。lifelineが`comp.u1`等のidのみで部品名が無い | `U1 ESP32-C3-MINI-1`のようにrefdes＋値を併記 |
| mechanical-section／interference（build123d） | **両者が同一の見え方**（外形線と穴だけ、題名・凡例・寸法・基板・干渉表示なし）。干渉が無いことも図からは読めない | CAD SVGへ題名・断面位置・寸法・基板断面・干渉体の強調（無ければ「干渉なし」注記）を付ける、または acd-svgで包む |
| product-readme.md | v2構成（テーマソング節・FW動作・部品役割）を確認。図リンクは収録先へ整合 | — |
| theme-song.mid | 独立SMF parser OK（`projection-format-check.txt`）。MMLは未実装（AA-26） | — |

## 収録内容

| path | 内容 |
|---|---|
| `conversation/` | event digest（loop 1,123件・init 65件、300文字切詰め・system prompt省略）、統計、投入prompt 2件 |
| `hooks/hook-events.jsonl` | HookExecutionEvent全553件（deny理由・種別付き） |
| `fixture/` | loopが使った設計入力とhash（`fixed-run/fixture/`とのbyte一致注記） |
| `loop/` | `loop-summary`・`timing-record`・`lane-preflight`・router・DRC／ERC・coverage・`design-predicates`・`cpl-basis-report`・`dfm-report`・`fab-package`・`hashes`・`order-readiness`・`theme-song-projection`・visual projection set 6件・3 lane Evidence・agent最終報告全文 |
| `gerbers/`、`fab/` | RS-274X 9層＋job、Excellon drill、JLCPCB CPL／BOM、pos |
| `enclosure/` | STEP 3件、3MF |
| `visual/` | SVG 11件＋KiCad envelope 4件、`png-devin-render/`（Devin側描画、container出力ではない） |
| `visual-review/` | `visual-review-manifest.json`、agentの回避手順で生成した3件のPNG・reproduction・observation（上記の欠陥注記のとおりL3記録） |
| `docs/` | 製品説明README v2とprovenance |
| `theme-song/` | `theme-song.mid`とprovenance |
| `projection-format-check.txt`、`tarball.sha256`、`plugin-install-response.json` | 独立reader検査結果、回収tarballのsha256、plugin更新応答 |

## 含めないもの

- `out/`配下のKiCad project・build tree・`flash.bin`・`.stage-cache`、第三者資材（Espressif等）。
- OpenHandsのsession key・API key、SSH鍵、endpoint情報。

## 次の手

1. #395（merge済み）を含むimageのpublish（`publish-acd-images.yml`手動起動）→lock更新後に、
   同fixtureでdigest固定再実行し、`visual-review-manifest`段の通過と全11投影のレビューを確認する。
2. Local GUI会話で`VisionInspectTool`が使えない構成では、observation記録の`tool_name`／`model`が
   自己申告であることを記録側で区別できるようにする（AA-27・AA-28、`docs/vibebb-gap-analysis.md`）。
3. 上表の生成器改善（AA-29〜AA-33）を別PRで実装する。

## 参照

- `docs/vibebb-standalone-verification.md` 17.15節
- `docs/vibebb-gap-analysis.md` AA-27〜AA-33
- `docs/roadmap.md` 14.24
