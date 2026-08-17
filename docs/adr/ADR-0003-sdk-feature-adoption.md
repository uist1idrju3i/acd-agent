# ADR-0003: SDK機能採用方針

> ステータス: Superseded
> 日付: 2026-08-11

## 結論

本ADRの初期Phase 0分類は、現行のSDK採否を表さないため廃止する。現行の採用範囲、
採用候補、不採用の分類は[`openhands-sdk-capabilities.md`](../openhands-sdk-capabilities.md)
を正とする。

決定論的ゲートの判定権限とOpenHands専用拡張の境界は、
[`ADR-0023`](ADR-0023-deterministic-gate-authority.md)および
[`ADR-0024`](ADR-0024-openhands-only-scope.md)で定める。

## 経緯

初期検討ではEventLog、TestLLM、DockerWorkspace、subagent、criticなどを段階導入として
記録した。その後、SDK v1.42.1の実装確認とACD側の実装により、Conversation、hooks、critic、
plugin、TestLLM、Docker workspaceなどの採用範囲が具体化した。旧分類を現行仕様として
併記すると境界を誤読させるため、現行の機能表へ集約する。

## 影響

SDK機能を追加・変更するときは、まずcapabilities文書と関連ADRを更新する。本ADRの
旧Phase 0分類を根拠に、現行の実装状態や採否を推測してはならない。
