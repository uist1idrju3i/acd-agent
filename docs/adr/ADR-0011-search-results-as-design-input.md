# ADR-0011: 探索結果を設計入力として確定する

> ステータス: Accepted（投影・実測・再配置ループを実装済み）
> 日付: 2026-08-16
> 関連: [`ADR-0007-llm-guided-physical-design.md`](ADR-0007-llm-guided-physical-design.md)、[`ADR-0009-openhands-delegation-and-skills.md`](ADR-0009-openhands-delegation-and-skills.md)

## 決定

配置・回転・シルク探索の結果は候補として扱い、採用した座標を`graph.json`の設計入力
へ確定する。fixture生成時はSkill CLIをsubprocessで実行し、ACD本体からSkillの
Python moduleをimportしない。旧`scripts/skill_loader.py`は廃止した。

graphにはSkill名と実行scriptの`sha256:` hashをprovenanceとして記録する。時刻や
graph自身への参照は決定性を壊すため記録しない。Skill CLIの入力不備、候補欠落、
実行失敗、provenance欠落はfail-closedとする。

## 解消した観測範囲の不一致

従来のSkillと決定論的silkscreen gateには次の観測範囲の差があった。

| 条件 | Skill側 | ゲート側 |
|---|---|---|
| pad | 投影前BoardModelのpad矩形で候補を拒否 | 生成後Gerber/実測silkとpadを比較 |
| mask | 観測・判定しない | mask Gerberとの重なりを測定 |
| body | library由来body矩形で候補を拒否 | 生成後silkとbodyを測定 |
| courtyard | 計測して順位付けするが許容 | 測定・記録するが単独fail条件ではない |
| existing silk | 観測・判定しない | 既存silk実測との重なりを拒否 |
| nearest component | 判定しない | 最近傍部品の不一致を拒否 |
| board edge | BoardModelの候補bboxで判定 | 生成後Gerber bboxとedge marginを測定 |

この差は、ゲートが実測したcontextをSkillへ渡し、候補を同じ条件で逐次探索し、
受理後に再投影・再測定する「投影 → 実測 → 再配置」ループで解消した。GD1では
silkscreenゲートまで通過し、同一入力の再実行もbyte一致する。routing後のvia mask開口は
このrouting前ループの観測範囲外であり、最終pipelineのゲートが引き続き権威である。

## 理由

設計入力を固定することで、同一graphから再現可能な投影とゲートを実行できる。
Skillの代理指標やAI出力を合否の権威にしないことで、未観測条件を成功に見せる
ことを防ぐ。provenanceは候補の出所を追跡するためであり、合格Evidenceではない。
