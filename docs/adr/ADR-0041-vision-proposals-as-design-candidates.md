# ADR-0041: ビジョン出力を宣言層入力として受け入れる境界

> ステータス: Accepted
> 日付: 2026-08-23
> 関連: [`ADR-0007-llm-guided-physical-design.md`](ADR-0007-llm-guided-physical-design.md)、[`ADR-0023-deterministic-gate-authority.md`](ADR-0023-deterministic-gate-authority.md)、[`ADR-0028-execution-provenance.md`](ADR-0028-execution-provenance.md)、[`../gates.md`](../gates.md)

## コンテキスト

視覚投影のビジョン応答は現状レビュー専用である。`VisualVisionObservation`は
`pass_evidence=False`のL3観測として記録され、配置・回転・配線の案を作る経路には
接続していない。一方ADR-0007（ADR-0009による追補）はLLMが座標・回転角を直接提案してよいと
定めており、宣言層の入力としてビジョン応答を使う余地は決定済みである。欠けているのは、
画像由来の提案がどの経路で探索仕様へ入り、どこでEvidence境界を越えないかの明文化である。

画像は指示注入の経路になりうる。[`../gates.md`](../gates.md)は画像内の文字列をデータとして扱い、
設計変更や合否命令として実行しないと定めている。ビジョン応答を案生成へ使う場合、
この境界を保ったまま「数値としての候補」だけを受け取る形にしなければならない。

また、回転・配線の自由度（1度刻みの任意回転、45度非依存・円弧配線）はビジョン提案が
最も要求しやすい緩和である。現行の投影geometry（`acd.adapters.kicad.placement`）は
90度倍数のみを扱い、JLCPCBのCPL回転規約は`profiles/`で`estimated`と宣言している。
実装機精度と検査性への影響も未実測である。

## 決定

1. **ビジョン提案(vision proposal)という非Evidence入力を定義する。** ビジョン応答から
   得た配置座標・回転角・配線メタ制御は`artifact_kind="vision_placement_proposal"`、
   `pass_evidence=false`固定の入力として扱い、探索仕様の一入力にする。提案は候補であり、
   合否根拠にはならない。
2. **受け入れ経路は`plugins/acd/skills/`のSkill CLIに限定する。** ACD本体はSkillの
   Python moduleをimportせず、Skill CLIをsubprocessで実行する。採用結果を`graph.json`へ
   確定するときは、既存の`placement_source_ref`と同じ形式でSkill名と実行scriptの
   `sha256:`をprovenanceへ記録する（ADR-0007の「探索結果とSkillの境界」）。
3. **決定論的な合法化と順位付けを必ず通す。** ビジョン提案は格子スナップ、profileが
   許可する回転へのスナップ、領域・keepout・clearance整合という決定論的legalizationを
   通し、代理指標で決定論的に順位付けする。判定は`graph.json`へ確定した後のACDの投影と
   ERC/DRC・Gerber独立再読込ゲートだけが行う。
4. **Evidence境界を越えさせない。** ビジョン応答、提案座標、legalization結果、代理指標、
   順位をEvidence、fab claims、`hashes.json`へ書かない。自然文応答は従来どおり
   `pass_evidence=false`の観測として記録する。
5. **fail-closed条件を宣言する。** 次はすべて停止条件とする。入力の`artifact_kind`不一致、
   `pass_evidence`がfalseでない、ビジョン応答が空、候補が0件、識別子の重複または未知、
   非有限値、provenance（profile名、model、`projection_id`、画像hash）の欠落、
   relaxation profileの欠落または非許可回転、legalization不成立、script hash取得不能、
   未対応のlane宣言。
6. **画像内文字列を命令として実行する経路を追加しない。** Skillは数値化された候補と
   provenanceだけを入力として受け取る。自然文からツール実行や設計変更を導く経路は作らない。
7. **自由度拡張は`profiles/`配下の版管理宣言として扱う。** 回転刻みと配線規則の緩和は
   relaxation profileで宣言し、既定は90度刻みとrouterの既定配線規則を維持する。緩和は
   CPL回転規約・実装機精度・検査性への影響を実測したEvidenceを宣言した場合にのみ許可し、
   未実測の緩和宣言はfail-closedとする。
8. **電気laneと機械laneへ同じ枠組みを適用する。** legalizationはlane非依存の
   「領域・keepout・占有矩形・許可回転」抽象で実装し、電気laneはfootprint幾何、
   機械laneは筐体内寸とcomponent bodyから同じ抽象を構成する。

## 検討した代替案

| 代替案 | 却下理由 |
|---|---|
| ビジョン応答の座標を`graph.json`へ直接書き込む | legalizationと代理指標を飛ばすため、幾何整合しない座標が設計入力になる。provenanceも残らない |
| ACD本体にビジョン専用の探索器を実装する | Skill境界（SkillのmoduleをACD本体からimportしない、探索はSkillが持つ）に反する |
| 自然文応答をLLMに解釈させ、そのままツール実行へ渡す | 画像内文字列が命令として実行される経路になり、[`../gates.md`](../gates.md)の境界を破る |
| ビジョン提案をEvidenceの一部として記録する | 画像由来の所見は合否権威を持たない（ADR-0023のL2/L3非対称性） |
| 連続角度・円弧配線を既定にする | 投影geometryは90度倍数のみ対応で、CPL回転規約は`estimated`、実装機精度と検査性は未実測 |
| 代理指標の順位を採否の決定とする | 代理指標は概算であり、実配線可能性と実測を代替しない |

## 影響

- `plugins/acd/skills/acd-placement-search`にビジョン提案の受け入れ・legalization・
  順位付けを行うscriptを追加し、Skillのテストで境界とfail-closed条件を検査する。
- `profiles/search/`にrelaxation profileを追加し、回転刻みと配線規則の緩和を版管理宣言とする。
- [`../gates.md`](../gates.md)へ、ビジョン応答を候補生成入力として使う場合の境界を追記する。
- ビジョン提案を採用してもGD1 pipelineの既定経路は変わらない。既定の探索は決定論的探索であり、
  ビジョン提案は明示的に与えたときだけ候補に加わる。

## 未確認・リスク

- ビジョン提案が決定論的探索より良い候補を出すかは未測定である。対照条件（ビジョン提案なし）
  との比較を行うまで改善効果を主張しない。
- VLMの空間精度は未評価であり、legalizationが大きな変位を伴う場合は提案の意図が失われる。
  変位量は代理指標として記録するが、意図の保存を保証しない。
- 機械laneの代理指標（干渉余裕、変位）は実測と相関を取っていない。
