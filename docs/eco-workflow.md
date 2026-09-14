# ECOワークフローとrevisionライフサイクル

## 目的

ECO（Engineering Change Order）は、Design Graphへ恒久的な設計変更を反映し、
revisionを進めるためのL1契約である。ワークアラウンドは製造済み個体への暫定的な
逸脱であり、設計入力の正を変更しない。ワークアラウンド状態は
`rN+WA-001`のように識別するが、恒久revisionではない。

## ライフサイクル

1. **draft**: 不具合、要求、陳腐化、コストなどの変更理由と対象を整理する。
2. **ECO record**: `ECO-001`のようなID、変更理由、影響node、影響lane、再検証要件、
   水平展開の処置を`EcoRecord`へ宣言する。
3. **to_revision graphのcommit**: `from_revision`のgraphを直接上書きせず、変更後の
   graphを`to_revision`（通常は`rN+1`）として保存する。ECOのfrom/toには
   `+WA-`付きrevisionを指定しない。
4. **gate rerun**: graph diffから実際の変更nodeとlaneを比較し、必要なゲートを
   `to_revision`へ再実行する。各結果は対応するevidenceファイルへ記録する。
5. **horizontal disposition**: 13.1で列挙した各水平展開対象について、
   `fixed_in_eco`、`not_affected`、または別ECOへの`deferred`を記録する。
6. **close gate**: graph ID、revision、impact、lane、evidence、水平展開を決定論的に
   検査し、すべてが整合した場合だけ`closable`とする。

### laneと最低限の再検証

| 影響lane | 最低限のゲート | evidenceファイル |
|---|---|---|
| electrical | `erc`, `design_predicates`, `drc` | `erc.json`, `design_predicates.json`, `drc.json` |
| mechanical | `mechanical_preflight`, `mechanical_interference` | `mechanical_preflight.json`, `mechanical_interference.json` |
| firmware | `firmware_evidence` | `firmware_evidence.json` |

Evidenceは`<evidence-dir>/<gate>.json`から読み込み、`target_revision`とgate名が
要求と一致し、statusが`pass`または`not_applicable`であることを確認する。欠落、
破損、読めないファイル、revision不一致、未知statusはunknownとしてcloseを止める。

## ワークアラウンドとの関係

ワークアラウンドrevision（例: `r1+WA-001`）は、対象個体に適用した逸脱の識別子で
あり、Design Graphの恒久revisionへ昇格しない。graphへの本修正はECOとして起票し、
恒久revision `rN+1`を生成する。ECOの`retires_workaround_ids`は現段階では記録用の
hookであり、廃止判定は個体台帳とECO close結果を組み合わせて行う。

## ワークアラウンドの個体追跡と廃止

`WorkaroundLedger`は、ワークアラウンドを適用した対象をロットまたはシリアル単位で
記録する。シリアルが列挙されている場合、ロットの適用recordだけではそのシリアルを
適用済みとみなさない。作業後検査が`pass`のrecordだけが`applied_verified`であり、
`not_recorded`と`fail`はそれぞれ未検証・失敗としてopenのまま残る。

| 状態 | 廃止判定上の扱い |
|---|---|
| `unmodified` | ワークアラウンド未適用。open |
| `applied_verified` | 対象個体への適用と作業後検査を確認済み |
| `applied_unverified` | 作業後検査が未記録。open |
| `applied_failed` | 作業後検査が失敗。open |
| `scrapped` | 個体を廃棄したrecordがあり、openから除外 |
| `upgraded` | `resolved_revision`への更新を記録した場合だけopenから除外 |

ワークアラウンドの廃止条件は次の論理積である。

```text
ECO closable ∧ same defects ∧ no open units
```

ここで`ECO closable`は対象ECOの`eco-check.json`が`closable`で、recordに記録した
sha256・ECO ID・解決revisionと一致することを含む。`same defects`は、ECOの
`kind=defect`理由がreworkの全不具合IDを覆うことをいう。未適用個体、作業後検査が
未記録または失敗の個体、解決revisionと異なる更新、列挙範囲外の処置は廃止を許可しない。
個体が不明なスコープの場合も、対象を列挙できないためunknownとして停止する。

## fail-closedの運用

from/to graphのgraph IDまたはrevisionが不一致、graph diffがunknown、impact nodeや
laneが不一致、最低限ゲートの宣言が不足、evidenceが未実行・unknown・fail、または
水平展開の検索・処置が未完了の場合、ECOはcloseしない。`deferred`は同じ
`EcoDocument`内の別ECOを参照しなければならず、自分自身への参照は拒否する。
close結果は観測文書ではなく決定論的L1 gate結果として保存するが、ECO recordやgraphへ
close結果を書き戻さない。
