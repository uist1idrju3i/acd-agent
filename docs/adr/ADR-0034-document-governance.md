# ADR-0034: 文書統治とSDK能力カタログ

> ステータス: Accepted
> 日付: 2026-08-18

## コンテキスト

SDK能力の採否、ADRの履歴、agent-serverの対象範囲が複数の手管理文書へ分散すると、
実装と文書のdriftを検出できず、Supersededな決定が現行方針として読まれる危険がある。
特に、判定側のfail-closedを文書都合で緩めると、L1のpass authorityを損なう。

## 決定

- SDK能力カタログは`docs/openhands-sdk-capabilities.json`を単一の正とする。
  `docs/openhands-sdk-capabilities.md`の表はJSONから生成し、
  `scripts/verify_sdk_capabilities.py --check`をCIで実行してdriftを拒否する。
  手管理表を廃止する理由は、pinned SDKの公開モジュールをASTで全列挙し、未claim、
  duplicate claim、stale claim、代表API欠落を機械的にfail-closedへできるためである。
- `agent-server`はOpenHands専用拡張の対象外とする。将来採用する場合は、認証、
  権限、Evidence境界、実機受入条件を定義する新規ADRを起票してから検討する。
- Superseded ADRは、統合先を示す`> ステータス: Superseded by ADR-XXXX`の1行pointer
  だけを残す。統合元の本文は物理削除し、履歴全文を保持しない。決定内容が必要な場合は
  統合先ADRを自己完結して読める本文にする。
- `docs/README.md`の「Accepted ADR一覧」を現行Accepted文書の単一の索引とする。
  Superseded pointerや実ファイルのない項目を一覧へ含めない。
- rationale coverageの未分類`unclassified`はfail-closedを維持し、緩めない。これは
  設計判断の根拠が未分類のままL1判定へ混入することを防ぐためである。手管理の緩和要求は
  SDK能力カタログの機械生成・drift検証で解消済みであり、判定側のfail-closed契約とは
  別問題として扱う。

## 影響

採否データ、Accepted ADR、Superseded履歴の現行参照先が明確になる。文書の追加・統合時は
`docs/README.md`、ADR本文、生成カタログ、`verify_docs.py`および各drift検査を同じ変更で
更新する必要がある。
