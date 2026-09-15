---
description: 不具合recordからワークアラウンド候補を立案し、完成案を救済可能性gateで再検証する。
argument-hint: "<graph> <defects> <defect-id>"
allowed-tools:
  - terminal
---

# ACD ワークアラウンド

`/acd:workaround`は、13.1の不具合record、13.2の追加工差分contract、
13.3の救済可能性gateをつなぐL2の操舵・観測経路です。Skill、agent、reviewerは
合否権限を持たず、出力JSONは観測結果として報告します。制約付き救済は合格では
ありません。

次の順序を守ります。

1. `propose_workaround.py`でgraphとdefectsを読み、対象defectについてfreshな
   defect-record checkを実行する。blockedなら候補を立案せず、候補0件で停止する。
2. eligibleなら、`firmware_only`、`rework_only`、`combined`の3戦略を確認する。
   適用可能なanchorが無い戦略も`not_applicable`として残す。
3. agentは候補setの`proposed` templateだけを完成させる。候補setに無いanchor、
   node、方針を発明しない。`WA-000`は完成`rework.json`へ持ち込まず、実在する
   workaround IDへ置き換える。
4. DFA assessmentには判断のbasis（参照した資料・確認結果）を必ず記載する。
5. `check_workaround.py`で対象candidate、完成したrework、DFA、必要なapprovalと
   revision一致したERC/DRC Evidenceを渡す。内部では既存の`evaluate_salvage()`を
   呼び出し、派生graphを出力する。
6. `workaround-evaluation.json`のverdict、gate runs、rejection reasons、
   alternativesを観測結果として報告する。salvageableだけが終了code 0であり、
   constrained_salvageは終了code 1の不合格観測である。

Skillの候補・評価はauthoritative L1 Evidenceではなく、設計入力へ逆流させません。
