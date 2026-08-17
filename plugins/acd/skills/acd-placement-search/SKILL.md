---
name: acd-placement-search
description: Search deterministic component placements (position and rotation) for an ACD board and rank candidates with surrogate metrics. Use when a board needs placements before the KiCad projection and the ERC/DRC gates.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - placement
  - component layout
  - footprint
  - rotation
  - ERC
  - DRC
---

# 基板の配置探索とスコアリング

ACD本体は配置探索を持たない。座標と回転角は設計データであり、この Skill は候補を作る
だけである。採否は OpenHands 側が判断し、合否は ACD の決定論的ゲート
（ERC/DRC と独立再読込）が判定する。

## できること

- `scripts/placement_search.py`: 固定アンカー（RF モジュールを上端、USB コネクタを下端、
  取付穴を四隅）と、残る部品の格子走査による決定論的な first-fit 探索。走査順は refdes 昇順、
  候補位置は 0.25mm 格子の行優先で、同一入力なら常に同一結果を返す。配置できない部品が
  あれば fail-closed で停止する。
- `scripts/placement_score.py`: 代理指標（HPWL、部品間最小ギャップ、基板外形までの最小ギャップ）
  と候補の順位付け。順位付けは合格根拠にしない。

## 使い方

```python
import sys

sys.path.insert(0, "plugins/acd/skills/acd-placement-search/scripts")

uv run python plugins/acd/skills/acd-placement-search/scripts/placement_search.py --input graph.json --fixture-dir fixtures/golden-design-1 --fab-profile profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json --output placements.json
from placement_score import rank_candidates, score_placement
```

`acd.adapters.kicad.board.load_board_footprints()` と `board_keepouts()` で投影と同じ
footprint 幾何・keepout を読み、`compute_placements()` に渡す。得られた `Placement` を
設計入力ファイルへ書き戻し、`generate_board()`／`write_project()` で投影して
ERC/DRC ゲートにかける。参照実装は `scripts/run_gd1_pipeline.py` にある。

LLM が座標や回転角を直接提案してもよい。その場合も候補として同じ経路（設計入力への確定 →
投影 → ゲート）を通す。

## 前提と限界

- 追加の外部ツールは不要である。`acd-core` と `acd-adapter-kicad` を import する。
- 回転は 0° と 90° のみを探索する。それ以外が必要な設計では探索器を差し替える。
- 高ファンアウト網（GND/電源）は引力から除外するため、ベタ面前提の設計に依存する。
- 代理指標は概算であり、実配線可能性や実測を代替しない。
- この Skill の結果は ACD の設計ゲートの結果ではない。

## テスト

```bash
uv run pytest plugins/acd/skills/acd-placement-search -q
```

Skill のテストは ACD 本体のテスト（`uv run pytest`）とは別に実行する。
