# ACD project memory

## コードベース
- 決定論的ゲートは `src/acd/pipeline/` にあり、合否はL1だけが確定する。
- L3観測は `AcdObservationStore` を通して書き出す。

## 好み
- 既存fixtureを再利用し、閾値は緩めない。
