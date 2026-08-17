# ADR-0021: 設計根拠recordの保持

> ステータス: Accepted
> 日付: 2026-08-17
> 関連: [`ADR-0007-llm-guided-physical-design.md`](ADR-0007-llm-guided-physical-design.md)、[`ADR-0009-openhands-delegation-and-skills.md`](ADR-0009-openhands-delegation-and-skills.md)、[`ADR-0011-search-results-as-design-input.md`](ADR-0011-search-results-as-design-input.md)

## 決定

安全または製造影響を持つ属性だけをrationale必須範囲とする。他の属性は警告として
扱い、未分類属性はfail-closedで停止する。

設計判断の理由を型付きrecordとして`rationale.json`に保持し、設計グラフ全体の
網羅性を決定論的ゲートで判定する。`rationale.json`は設計入力と同じ変更で更新し、
配置やシルクのSkill由来値にはSkill名とscript hashを記録する。graphに要求nodeが
存在する場合は`driving_requirements`で参照し、要求が文書にだけ存在する場合は
`driving_requirement_refs`に文書パスと要求IDを記録する。

## 背景

部品、配置、配線幅、筐体寸法、FWピン割当の採用理由が設計入力と別の会話や記憶に
散在すると、後から判断を再現できない。rationaleは採用判断とその理由、却下した
代替案、要求、出所を保持するが、合否を決定する権威ではない。文書だけの要求を
node参照として偽らないため、docレベル参照を型付きで保持する。

## 却下した選択肢

- **graph属性へ理由を散在させ続ける:** 個別属性の説明はできるが、判断単位、
  代替案、出所、網羅性を共通形式で検査できないため却下した。
- **会話ログだけに保持する:** 会話は参照にはなるが、保存・検索・要約・分岐により
  権威性と再現性を保証できないため却下した。
- **ADRだけに記録する:** ADRは大きなアーキテクチャ判断には適するが、各graph nodeと
  attrの網羅性を機械的に検査する粒度には向かないため却下した。

## RationaleとEvidence

Rationaleは「なぜこの設計判断を採用したか」を説明する。Evidenceはツール、入力、
出力、版、hash、測定条件により検証結果を支持する。RationaleはEvidenceの代替では
なく、合否の受入権限を持たない。合否は契約と決定論的ゲートが判定する。

## Staleの扱い

graphの値またはrevisionが変わりsubject hashが一致しなくなったrecordはstaleとして
fail-closedにする。fixture生成は既定では停止し、理由の再記述を要求する。明示的な
`--refresh-rationale-hashes`だけがhashとtarget revisionを更新でき、justificationは
書き換えない。

## HooksとSkill

設計入力編集後の`PostToolUse` hookは不足を警告し、`Stop` hookはexit code 2で不足、
parse失敗、staleをブロックする。`acd-design-rationale` Skillはrecordの作成を補助
するが、Skill出力は合否権限を持たない。会話永続ログはconversation event reference
として参照できるだけで、権威ではない。

## 未解決事項

- 複数設計revisionをまたぐrecordの保管・廃棄方針。
- 要求文書の改訂とdriving requirementの自動差分。
- 人間によるrecordレビューの表示と承認ワークフロー。
