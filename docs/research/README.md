# 研究結論

> 詳細な調査資料はgit履歴に残し、ここではACDの決定に影響した結論だけを保持する。

## prior art

信頼性を担保するには生成と判定を分離し、独立再読込とfail-closedを組み合わせる必要がある。
この結論をL1決定論的ゲート、L2操舵、L3観測の三層境界とEvidence契約へ反映した。

## reliability practices

自動ゲート、AIレビュー、工程出口を相互補完させ、AIレビューに合否権限を与えない。
unknownや未実行は停止側へ倒し、`Evidence.supports_pass(revision)`を唯一のpass authorityとした。

## qc tools

Q7/N7は観察と修正計画の手法であり、代理指標や自然文所見を合否根拠にしない。
投影レビューは入力から再生成し、投影編集を正へ逆流させない。

## tool selection

KiCad、FreeRouting、CADなどの外部ツールは版・入力・出力を独立に確認し、能力不明を
fail-closedとする。SDKの汎用tool採否はACDゲートの決定権を変更しない。

## ecad domain notes

電気設計はnet、pin、stackup、座標、製造出力を別々の投影と再読込で確認する。
ERC/DRC、routing、Gerber/drill、BOM/CPLの契約をACD固有の決定論的責務として保持した。

## ai physical design

LLMは要求分解、候補生成、観察、修正案に使い、配置・配線候補は幾何合法化とゲートで
確認する。代理スコアや探索agentの出力だけで合格にしない。

## algorithmic music (theme song)

Strudel（TidalCyclesのJS移植、AGPL-3.0-or-later）、TidalCycles・FoxDot・Sardine・
SuperCollider・ChucK（GPL）、Sonic Pi、Gibber・Glicol（MIT）、music21（BSD）、
mido／pretty_midi、ACE-Step・YuE（Apache-2.0 GPU生成モデル）、MusicGen（重みCC-BY-NC）、
Stable Audio Open（Community License）を比較した。GPL/AGPLのimport結合禁止、再現性、
標準ライブラリ完結を満たすのは「Strudelパターン構文のテキスト生成 + 自前MIDI書き出し」
だけであり、Strudelは結合せず公開構文だけを使う。LLM提案は許可関数・許可音源・
危険トークンのwhitelist検査で受理判定し、幻覚関数名・未知sample名を停止側へ倒す
（ADR-0048）。
