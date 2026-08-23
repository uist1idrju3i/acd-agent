# 設計要件の変更と設計動作の確認

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.43.1

本書は、agentへ設計を依頼するときの要件の与え方と、agentが実際に新規設計を行ったかを
判定する手順を記録する。GD1と同じ要件を与えた場合に新規設計が行われないことは
実行例の追検証で確定した観測であり、本書はその観測と、要件を変える場合の境界を示す。

## 観測（2026-08-20 実行例の追検証）

[`examples/sensor-node-20260820/`](../examples/sensor-node-20260820/)は、`graph_id`を
`sensor-node`とした実行例だが、設計実体はGD1と同一である。追検証で得た事実は次のとおり。

| 比較対象 | 結果 |
|---|---|
| `fixture/graph.json` と `fixtures/golden-design-1/graph.json` | 差分18行のみで、すべて`graph_id`とノードIDのリネーム。座標・部品・ネット・寸法・design ruleの差分は0件 |
| `board/gd1.kicad_pcb` と GD1 fixtureからの再生成物 | sha256が完全一致（`1c8a5f30…`） |
| ガーバ9ファイル | rawバイト列は不一致。差分はKiCadの生成日時（`TF.CreationDate`、`Created by KiCad … date`）だけで、日時を正規化すると9/9一致 |
| シルクの基板ID（`mechanical.silk_text.board_id`） | `golden-design-1-r1`のまま |

したがって、この実行例はpipelineとauthoritative Evidence生成が実機で動作したことの
証拠にはなるが、agentが新規に設計判断を行ったことの証拠にはならない。

## 同じ要件では新規設計にならない理由

1. 依頼文がGD1-REQ-001〜017の値（部品、GPIO割当、抵抗・容量値、基板寸法、層構成）を
   すべて維持するよう指定した場合、設計空間はGD1の1点に収束する。実行例の会話ログでも
   agentは同じ設計であると判断し、`graph_id`とノードIDのリネームだけを行っている。
2. 設計入力の生成手段はGD1専用である。`fixtures/golden-design-1/graph.json`は
   [`../scripts/build_gd1_fixture.py`](../scripts/build_gd1_fixture.py)と
   `src/acd/pipeline/gd1_fixture/`のPythonコードが固定の部品表・ネット・配置・要件から
   生成し、出力先も同fixtureに固定されている。別設計はこのbuilderでは生成できず、
   graph.jsonの手作業編集またはbuilder側の変更が必要になる。

## 変更できる要件次元

以下は決定論的ゲートが値を固定していない次元である。変更する場合は、同じ変更で
rationale recordを追加し、coverageの`unclassified`を出さないこと（[`../AGENTS.md`](../AGENTS.md)）。

- 基板外形寸法、取付穴の数と位置、部品配置、アンテナkeepoutの寸法
- LEDのGPIO（strapping pinを除く）と電流制限抵抗値
- I2CのGPIO割当（strapping pinを除く）
- センサ部品のMPN・footprint・I2Cアドレス
- シルクの文字・図形、筐体の寸法・肉厚・開口
- FWの周期・ログ出力などの振る舞い

## ゲートが契約として固定している値

以下は[`../src/acd/core/design_predicates.py`](../src/acd/core/design_predicates.py)が
各機能ブロック契約の判定として値・net名・トポロジを固定している次元である。宣言された
機能ブロックでは要件をここへ踏み込ませると`fail`または`unknown`になり、fail-closedで
停止する。新しいトポロジ族を追加する場合は、まず
[`../contracts/functional-block-registry.json`](../contracts/functional-block-registry.json)へ
適用契約を追加する。新しい物理判定や固定値を追加する変更では、述語、negative test、
ADRも同時に更新する。

固定値の表は、対応する機能ブロックが宣言された場合にだけ適用される。宣言された
ブロック内のnet・部品の不足は`not_applicable`ではなく`unknown`として停止する。

| 固定されている内容 | 述語 |
|---|---|
| CC1・CC2から`GND`へ5.1 kΩを各1本、MPN必須 | `evaluate_usb_cc` |
| `I2C_SDA`・`I2C_SCL`から`+3V3`へ4.7 kΩを各1本、MPN必須（net名も固定） | `evaluate_i2c_pullup` |
| IO2・IO8はno-connect、IO9は`BOOT`ネット、BOOTに繋ぐのは抵抗とスイッチだけ | `evaluate_strapping_pin` |
| LEDネットをstrapping padへ接続しない、FWのGPIO割当にIO2・IO8を使わない | `evaluate_strapping_pin` |
| `VBUS_5V`から`+3V3`へ渡る部品は1個（単一LDO）、各レールに10 µF以上と100 nF±0.02 µF | `evaluate_power_decoupling` |
| decouplingの許容距離は1 µF以下で3.0 mm、1 µF超で8.0 mm | `evaluate_power_decoupling` |
| 宣言ネット電圧の最大5.0 V、電源境界ネット電流の最大0.5 A、width basisは2種のみ | `evaluate_power_boundary` |
| 無線モジュールは認証ID・HVIN・文書参照・確認時刻のprovenanceが必須 | `evaluate_power_boundary` |

## 成果物名では設計同一性を判断できない

基板・筐体・FW pipelineの出力prefixは`gd1`固定であり、Evidenceの`subject_node`も
`electrical.board.gd1`にハードコードされている。別のgraphを`--fixture`で渡しても
`gd1-gerbers.zip`のような同名で出力されるため、ファイル名やEvidenceの対象node名を
設計が変わった根拠にしてはならない。この固定の解消は
[`roadmap.md`](roadmap.md)のマイルストーン14.6に記録済みである。

## 設計動作の確認手順

新しい実行例でagentが設計を行ったかを判定する場合、次の4点を実行例のレポートへ記録する。
いずれかが未取得の場合は、設計が行われたと主張しない。

1. graph.jsonのGD1 fixtureに対する差分行数と、そのうちリネーム以外の実体差分の内訳
2. `*.kicad_pcb`のsha256をGD1 fixtureからの再生成物と比較した結果
3. ガーバの比較結果。生成日時（`TF.CreationDate`、drillの`; #@! TF.CreationDate`）だけを
   正規化し、正規化後に一致するか差分が残るかを明記する
4. BOM・CPLの差分と、シルクの基板ID文字列

外部ツールの保存バイト列を設計状態の権威にせず、正規化規則の外にある差異は停止条件
として扱う（[`roadmap.md`](roadmap.md)のフェーズ横断の検証要件）。

## 検証

本書はMarkdownのみの文書であり、変更時は次で検証する。

```bash
uv run python scripts/verify_all.py --stage docs
```
