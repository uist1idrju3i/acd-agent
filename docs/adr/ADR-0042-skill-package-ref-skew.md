# ADR-0042: Skill package refのskew検出と事前導入

> ステータス: Accepted
> 日付: 2026-08-23
> 関連: [`ADR-0037-pep723-skill-scripts.md`](ADR-0037-pep723-skill-scripts.md)、[`ADR-0038-acd-install-doctor.md`](ADR-0038-acd-install-doctor.md)、[`../operations.md`](../operations.md)

## コンテキスト

PEP 723のSkill scriptは、`acd-package-ref.txt`に記録したgit refの`acd`を
`uv run --script`で解決する。refの形式とmetadataだけを検査すると、実装より古い
refでも合格してしまい、schema/APIのskewが実行時の`DesignGraph`検証まで遅延する。
この状態では、fixtureで使用するfirmwareのnode kindをpinned packageが持たない
ことをCIの標準検証で発見できない。

## 決定

1. `plugins/acd/skills/acd-package-contract.json`を、ref、schema tree SHA、
   pinned schemaからASTで抽出したnode/edge kind、fixtureのkind、全ての
   ACD-importing scriptのSHA-256とAST-derived API symbolを含むcanonical contractとする。
2. `scripts/verify_skill_package_ref.py`をCIのfail-closed checkerとする。local commitへの
   解決、HEADへのancestor、schema tree一致、pinned API surface、fixture kind coverage、
   metadata、contract driftを検査する。git履歴がshallow、refが未解決、情報が不明な場合も
   不合格とする。`--write`はcontractを再生成する。
3. `scripts/update_skill_package_ref.py`はref file、全scriptのPEP 723 dependency、
   contractを一括更新する。更新対象にはrepositoryのGD1 probeも含め、同じ入力で再実行しても
   変更を作らない。
4. `/acd:doctor`はgitや`acd`をimportせず、インストール済みpluginだけからcontractの存在、
   parse、ref一致、script hash、import symbolのsubset、fixture kind coverageを判定する。
   欠落・parse不能・不一致はskipせずfailとし、結果には件数を含める。
5. `scripts/probe_pinned_acd_graph.py`はGD1の`graph.json`をpinned `DesignGraph`で検証し、
   firmware Skillの`extract_firmware_lane`まで実行する。CIはこのprobeを独立jobで実行する。
6. tools imageは全scriptのPEP 723 metadata blockが一致することを確認してからprobeを実行し、
   uv cacheを保持する。onlineでwarmした後にoffline probeを実行し、実行時のnetwork依存を
   fail-closedで検証する。cache容量はimageの運用コストとして記録する。
7. mainへのschema、fixture、Skill資材のpush後はautomationがcheckerを実行する。skewが
   無ければ終了し、skewがあれば`${GITHUB_SHA}`で更新した日本語PRを作る。更新PRが
   mainへmergeされた際もcheckerが一致を確認して終了するため、再triggerの無限ループを
   作らない。`GITHUB_TOKEN`で作成したPRはCIをtriggerしないため、必要な場合は通常の
   token経路で再実行する。

## 運用上の二段階pin

refはHEADのancestorでなければならないため、schema/API変更を含むPRの途中で未pushの
作業treeや将来のmerge commitを指してはならない。まずPR branchへpush済みのcommitへ
pinしてcheckerを通し、merge後にpost-merge automationが実際のmerge commitへ再pinする。
この二段階で、PR中の検証可能性とmerge後の実装・Skill packageの一致を両立する。

## 境界

本ADRはSkillの依存解決とskew検出だけを定める。L1の決定論的gate、revision一致の
authoritative Evidence、threshold、SkillをACD本体からimportしない境界、host実行を
authoritative Evidenceへ昇格しない境界は変更しない。
