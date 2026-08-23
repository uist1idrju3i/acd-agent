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
- `scripts/vision_proposal.py`: 視覚投影のビジョン応答から得た数値案（座標・回転）を候補として
  受け取り、決定論的に整合化（格子snap、許可回転へのsnap、領域内判定、keepout非重複、変位上限）
  してから代理指標を付けて出力する。ADR-0041に従う。

## 使い方

```python
import sys

sys.path.insert(0, "plugins/acd/skills/acd-placement-search/scripts")

uv run --script plugins/acd/skills/acd-placement-search/scripts/placement_search.py --input graph.json --fixture-dir fixtures/golden-design-1 --fab-profile profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json --output placements.json
uv run --script plugins/acd/skills/acd-placement-search/scripts/placement_score.py
from placement_score import rank_candidates, score_placement
```

`--script`はPEP 723のメタデータから依存を自己解決します。ローカルcheckoutで
開発する場合は、従来どおり`uv run python <path>`を使用します。

`acd.adapters.kicad.board.load_board_footprints()` と `board_keepouts()` で投影と同じ
footprint 幾何・keepout を読み、`compute_placements()` に渡す。得られた `Placement` を
設計入力ファイルへ書き戻し、`generate_board()`／`write_project()` で投影して
ERC/DRC ゲートにかける。参照実装は `scripts/run_gd1_pipeline.py` にある。

LLM が座標や回転角を直接提案してもよい。その場合も候補として同じ経路（設計入力への確定 →
投影 → ゲート）を通す。`compute_placements()` の `seeds` 引数へ確定済みの `Placement` を渡すと、
その部品の姿勢を固定したまま残りを決定論的に探索する。

## ビジョン案の取り込み

```bash
uv run --script plugins/acd/skills/acd-placement-search/scripts/vision_proposal.py \
  --proposal vision-proposal.json \
  --input graph.json \
  --relaxation-profile profiles/search/placement-relaxation-profile-default.json \
  --fixture-dir fixtures/golden-design-1 \
  --fab-profile profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json \
  --output out/vision-candidates.json
```

入力契約は次のとおりで、`artifact_kind`は`vision_placement_proposal`、`pass_evidence`は`false`固定である。

```json
{
  "artifact_kind": "vision_placement_proposal",
  "pass_evidence": false,
  "lane": "electrical",
  "observation": {
    "tool_name": "inspect_image_with_vision",
    "profile_name": "<vision profile>",
    "model": "<model>",
    "projection_id": "<projection node id>",
    "image_hash": "sha256:...",
    "response": "<VisualVisionObservation.response>"
  },
  "proposals": [{ "item_id": "U2", "x_mm": 4.4, "y_mm": 15.3, "rotation_deg": 87.0 }]
}
```

自然文はhash化してprovenanceに残すだけで、命令として解釈しない。`lane`は`electrical`
（footprint幾何・基板領域・基板keepout）と`mechanical`（筐体内部領域・部品body・取付穴）を
受け付ける。電気laneではビジョン案を`seeds`として固定し、残りの部品を`placement_search.py`で
決定論的に配置した完全な候補と、ビジョン案なしのbaselineを併記する。

出力は`artifact_kind="vision_placement_candidates"`、`pass_evidence=false`の候補報告であり、
Skill名・script sha256・提案hash・relaxation profile hash・graph revision・観測provenanceを含む。
候補も代理指標もEvidenceではなく、`hashes.json`やfab claimsへ書き込まない。

次の場合はすべてfail-closedで停止する。`artifact_kind`不一致、`pass_evidence`が`false`以外、
空応答、provenance欠落、不正なsha256、候補の欠落・重複・非有限値、未知の対象、未対応lane、
relaxation profileの欠落・破損、実測Evidenceのない回転・配線緩和、変位上限内で整合化できない案、
電気laneでの`--fixture-dir`／`--fab-profile`欠落。

## 前提と限界

- 追加の外部ツールは不要である。`acd-core` と `acd-adapter-kicad` を import する。
- 回転は 0° と 90° のみを探索する。それ以外が必要な設計では探索器を差し替える。
- ビジョン案の整合化で許可する回転と配線自由度は`profiles/search/`の版管理profileが定義する。
  既定は90度刻みで、1度刻みの任意回転・円弧配線・非45度配線は実測Evidenceがない限り拒否する。
- 機械laneの候補は提案された部品bodyだけを対象とし、他のbodyとの干渉は機械laneのゲートが判定する。
- 高ファンアウト網（GND/電源）は引力から除外するため、ベタ面前提の設計に依存する。
- 代理指標は概算であり、実配線可能性や実測を代替しない。
- この Skill の結果は ACD の設計ゲートの結果ではない。

## テスト

```bash
uv run pytest plugins/acd/skills/acd-placement-search -q
```

Skill のテストは ACD 本体のテスト（`uv run pytest`）とは別に実行する。
