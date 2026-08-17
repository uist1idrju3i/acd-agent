---
name: acd-silkscreen-placement
description: Resolve silkscreen label positions for an ACD board by deterministic perimeter search, recording accepted and rejected candidates as evidence. Use when functional labels must be positioned before the board projection and DRC.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - silkscreen
  - label placement
  - board edge
  - footprint clearance
  - DRC
---

# シルクスクリーン文字の配置探索

ACD本体はシルク文字の探索を持たない。グラフ宣言の抽出（`acd_core.silkscreen.extract_silkscreen_lane`）
だけが本体に残り、位置決めはこの Skill が行う。結果は候補であり、合否は ACD の
決定論的ゲート（DRC と独立再読込）が判定する。

## できること

- `scripts/silkscreen_search.py`: 宣言された基準（基板外形または参照 footprint）の周囲を、
  宣言された探索順・オフセット刻み・上限で走査し、直交回転のみを候補にする。
  パッド、部品外形、基板端マージンと干渉する候補は却下し、理由付きで evidence に残す。
  有効候補がなければ fail-closed で停止する。
- 採用基準は「基準中心までの距離が最小」で、同値は宣言探索順 → 回転順 → courtyard 重なり面積
  → オフセットの順に決める。裏面など位置がグラフに確定している文字は探索しない。

## 使い方

```python
import sys

sys.path.insert(0, "plugins/acd/skills/acd-silkscreen-placement/scripts")

uv run python plugins/acd/skills/acd-silkscreen-placement/scripts/silkscreen_search.py --input silkscreen-input.json --output silkscreen-output.json

resolved = resolve_silkscreen_placements(lane, board_projection.model)
```

`lane` は `extract_silkscreen_lane()` の結果、`board_projection.model` は配置確定後の
`BoardModel` である。参照実装は `scripts/run_gd1_pipeline.py` にある。

## 前提と限界

- 追加の外部ツールは不要である。`acd-core` を import する。
- 文字幅は字高からの概算であり、実際のストロークフォント幅ではない。狭小基板では
  DRC で不合格になりうる。
- 部品回転は 0/90/180/270° のみを扱う。
- この Skill の結果は ACD の設計ゲートの結果ではない。

## テスト

```bash
uv run pytest plugins/acd/skills/acd-silkscreen-placement -q
```

Skill のテストは ACD 本体のテスト（`uv run pytest`）とは別に実行する。
