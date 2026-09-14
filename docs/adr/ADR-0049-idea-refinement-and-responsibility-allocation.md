# ADR-0049: アイデア洗練record・対話履歴・責務割当の契約

> ステータス: Accepted
> 日付: 2026-09-13
> 関連: [`ADR-0021-design-rationale-records.md`](ADR-0021-design-rationale-records.md)、[`ADR-0023-deterministic-gate-authority.md`](ADR-0023-deterministic-gate-authority.md)、[`../roadmap.md`](../roadmap.md)（マイルストーン21）

## コンテキスト

マイルストーン21は、会話で持ち込まれたものづくりアイデアを設計入力へ落とせる
水準まで洗練し、洗練後の機能群を機構・機械・電気・FW・PC側ソフト・サーバ・
スマホアプリのどこへ配置するかを決める上流段階を扱う。アイデアは一度の生成で
確定せず、利用者との対話の往復で洗練される。L1判定は決定論的ゲートと
authoritative Evidenceだけが担い、L2は操舵・停止側、L3は観測に限るという
三層分離（ADR-0023）をこの段階でも緩めない。

## 決定

1. `IdeaRecord`（`src/acd/schema/idea.py`）をgit管理の設計入力とする。
   配置は`fixtures/<design>/idea/idea.json`、設計が未着手の段階では独立した
   ideaディレクトリとする。各項目は`confirmed`（利用者同意済み）か`open`
   （未決）の2値とし、`confirmed`には値・`confirmed_at`・少なくとも1つの
   `user_statement`出所を必須とする。`user_statement`以外の出所は項目を
   confirmedへ昇格できない。`success_criteria`・`functions`の未宣言は
   unknownであり、`open_items`へsentinelとして残り、promotionを妨げる。
2. 対話履歴`IdeaDialogueHistory`はターンごとの追記専用とし、
   `idea-dialogue.json`としてrecordの隣に保存する。`turn_no`は連続した
   追番で、改変・挿入は契約違反とする。履歴は内部知識源に留め、公開文書へは
   含めない（マイルストーン12.4と同じ規則）。中断・再開は同じ`open_items`
   から継続する。
3. 進捗は`IdeaProgress`のL3観測（`record_class="L3"`、`pass_evidence=false`）
   とし、`confirmed_count`・`open_count`・`blocking_unknowns`を報告するが、
   進捗率や件数は合格根拠にも承認にもならない。
4. 洗練SKILL（21.2、別PRで実装）はL2操舵とする。未決論点を優先度順に少数ずつ
   質問し、各質問へ選択肢・トレードオフ・推奨案とその出所を付ける。推測で
   項目を埋めず、利用者の同意した回答だけを`confirmed`としてrecordへ追記する。
5. 粗見積（21.4、別PRで実装）は推定であることを明示し、confirmed済みの数値
   制約とのみ比較する。矛盾は停止側の論点として報告し、合格側へ作用させない。
6. promotion（21.5、別PRで実装）がマイルストーン14.5のRequirementDocumentへ
   変換する条件は、`open_items`が空であること、およびpromoteされる各要件に
   rationale recordが付くこととする。
7. 責務割当（21.6・21.7、別PRで実装）は、`design.responsibility`という新規
   node kindのgraph nodeとして割当を宣言し、属性は`function_id`・`domain`・
   `criteria`とする。`domain`は`REQUIRED_RATIONALE_ATTRS`へ分類する。
   配置先の能力宣言と分野間interface宣言はgraph.jsonの隣の
   `responsibility.json`へ置く。決定論的ゲートは未割当機能・能力宣言との矛盾・
   片側だけのinterface・unknownでfail-closedに停止し、gate evidenceを出力する
   が、割当そのものへauthoritative Evidenceは生成しない。
8. 投影（21.8、別PRで実装）は`out/docs`の文書laneへ`write_document`の
   provenance付きで生成する。L3提示であり、合否権限を持たない。

項目2〜8は後続PRが実装する契約である。

## 影響

- `idea.json`と`idea-dialogue.json`は設計入力としてcommitし、対話履歴の
  公開文書への混入を禁じる。
- `IdeaField`のconfirmed昇格条件はスキーマvalidatorで固定し、成功のために
  緩めない。
- 責務割当の宣言はgraph nodeの新規kindとして扱い、`domain`属性は
  rationale必須属性として分類する。未知・未宣言はunknownとしてfail-closedにする。
