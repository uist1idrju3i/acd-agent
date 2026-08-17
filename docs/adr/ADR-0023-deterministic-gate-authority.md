# ADR-0023: 判定・操舵・観測の三層分離

> ステータス: Accepted
> 日付: 2026-08-19

## コンテキスト

Conversationとagent-serverを実運用経路にすると、critic score、LLM judge、metrics、
Skill出力を合否へ混入させる圧力が高まる。禁止事項の列挙だけでは、利用可能な範囲を
明確にできない。

## 検討した選択肢

- 案A: critic scoreを合否に使う。物理成果物の誤合格と自己証明を許すため却下する。
- 案B: LLM judgeの十分という判断でゲートを省略する。未実行をunknownとして扱う
  fail-closedの意味論を壊すため却下する。
- 案C: 判定、操舵、観測を分離し、非対称性規則を置く。これを採用する。

## 決定

- **L1判定**は決定論的ゲートと`Evidence.supports_pass(graph.revision)`だけが担う。
  合格を出せるのはL1だけである。
- **L2操舵**はcritic、`StuckDetector`、condenser、Skill、agent、reviewerの出力を
  反復の継続、打ち切り、修正対象の提示に使う。
- **L3観測**はmetrics、telemetry、event、laminarを予算、性能、監査に使う。
- **非対称性規則**として、L2とL3は不合格・停止側にだけ作用できる。合格側へ作用
  させてはならない。

未検証をfail-closedとする規則は合否claimに適用する。探索、実験、文書ステータス、
運搬層や観測層に判定用negative testを要求しない。ADRの過去決定を削除しないという
旧規定は撤回する。

## 維持する意味論

fail-closed、`graph.revision`を`rN`として扱うこと、判定の両辺を別出自にすること、
自己証明を禁止することは維持する。AGENTS、architecture、roadmap、ADR-0016はこの
三層語彙を使用する。
