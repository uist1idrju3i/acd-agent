# ADR-0004: 部品カタログとライブラリ出所方針

> ステータス: Accepted
> 日付: 2026-08-11

## コンテキスト

部品、footprint、3D model、シンボルはERC/DRCだけでは正しさを検証できず、
出所不明のライブラリ記述は合格根拠にできない（`AGENTS.md`の不変条件）。
Phase 1でKiCadライブラリを参照する前に出所方針を確定する。

## 決定

- 部品カタログは設計グラフの`electrical.component`ノードの属性として、
  MPN、メーカー、出所URL、取得時点、ライセンスを保持する。
- ライブラリ（シンボル、footprint、3D model）は取得元URLとcommit（または
  版とhash）をpinし、解決した実パスと取得時点をEvidenceに記録する。
- pinのないライブラリ参照、出所不明のfootprint、hash未記録の3D modelは
  `unknown`としてfail-closedで扱い、照合Evidenceなしに合格根拠にしない。
- ライブラリ記述と実部品の照合（datasheet照合、ピン配列検証）は独立した
  Evidenceとして記録し、ライブラリ更新時はstale化して再照合する。
- KiCad公式ライブラリを既定の第一候補とし、ライセンス
  （KiCad libraries: CC-BY-SA 4.0ほか）は[`docs/research/README.md`](../research/README.md)の
  ライセンス境界に従って利用形態を確認する。

## 影響

- Phase 1のKiCad投影は、pinされたライブラリ参照だけを解決できる。
- 部品・ライブラリ出所のスキーマ詳細（catalog契約）はPhase 1で
  `schemas/`に追加し、本ADRを正として設計する。

ADR-0008により、契約の正は`schemas/`からPydanticモデルへ移行した。
