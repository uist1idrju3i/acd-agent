# ADR-0044: 探索対象とする設計自由度の宣言およびstitch候補Evidence

> ステータス: Accepted
> 日付: 2026-08-23
> 関連: [`ADR-0023-deterministic-gate-authority.md`](ADR-0023-deterministic-gate-authority.md)、[`ADR-0043-functional-block-contract-registry.md`](ADR-0043-functional-block-contract-registry.md)、[`../operations.md`](../operations.md)

## コンテキスト

物理設計の候補探索を将来追加するためには、何を変更可能な自由度として扱うかと、
現在固定されている値の出所を明示する必要がある。値の出所や境界を持たない自由度を
探索へ渡すと、設計入力と投影の境界を曖昧にし、決定論的ゲートの権威を迂回し得る。

また、stitch via候補は初回呼び出し時だけでなく、GND島の未被覆を除外するrefill反復
でも変化する。候補と除外理由を保存しない場合、後続の解析が生成済み基板を再解析する
必要があり、候補選択の再現性を検証できない。

## 決定

1. `contracts/design-freedom-declaration.json`を9次元の設計自由度宣言の正とする。
   各次元はlane、型、現在値の出所、bound basis、gate authority、探索可否を持ち、
   宣言ID集合はschemaで完全一致させる。
2. 宣言は既存のgraph属性またはfab profileにある値を再掲する場合だけ数値境界を持つ。
   境界を宣言しない場合は、該当する決定論的ゲートが権威であることを`bound_basis`へ
   記録する。根拠のない境界や、categorical次元の単位は許可しない。
3. functional-block registryの`allowed_change_dimensions`は、宣言済みで探索有効な
   次元だけを参照できる。未知または探索無効の参照はfail-closedで停止する。
4. 基板pipelineは宣言とregistryの整合を設計predicate段階の前に検査し、宣言と
   `searchable_dimensions`を`design-freedom-declaration.json`へ保存する。このartifact
   はL3の追跡情報であり、L1の合否を決定しない。
5. `inject_stitch_vias`は常に候補reportを返す。候補を座標順に保存し、選択状態、除外
   理由、allowed-points override、選択座標を含める。pipelineは初回とrefill反復を
   反復番号付きで`stitch-candidate-report.json`へ保存し、GND島の未被覆測定は既存の
   pruning evidenceから再利用する。DFM reportは従来のbounded summaryを保持する。
6. 本ADRはL1 gateのthreshold、判定、停止位置、authoritative Evidenceの条件を変更
   しない。候補reportと設計自由度artifactの書き込み失敗は、観測を欠落させないため
   fail-closedで伝播させる。

## 未決定事項

銅層数の探索はfab profile registryと基板projectionの連携が必要であり、機械datumの
探索はB-6の単一datum化が必要である。これらは本セッションの範囲外として宣言上は
無効化し、後続セッションで解決する。
