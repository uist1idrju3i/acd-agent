# ADR-0048: 製品テーマソングのL3成果物生成とStrudel非結合

> ステータス: Accepted
> 日付: 2026-09-06
> 関連: [`ADR-0023-deterministic-gate-authority.md`](ADR-0023-deterministic-gate-authority.md)、[`../research/README.md`](../research/README.md)、[`../operations.md`](../operations.md)

## コンテキスト

新規プロダクトのリリースにはテーマソングが付きものである。VibeBBの成果物として、
設計ごとに製品専用のジングルを新規作曲する機能を求められた。候補技術として
ライブコーディング環境のStrudel（TidalCyclesのJavaScript移植、AGPL-3.0-or-later）、
TidalCycles・FoxDot・Sardine・SuperCollider（GPL）、Sonic Pi、Gibber・Glicol（MIT）、
music21（BSD）、ACE-Step・YuE（Apache-2.0のGPU生成モデル）、MusicGen（重みCC-BY-NC）
を調査した。

本リポジトリはGPL/AGPLコードをACDへimport結合しない。またSkill成果物はL3観測であり、
合否権限を持たず設計入力へ逆流させない。GPU生成モデルは再現性と実行環境の要件を
満たさず、実行時のnpm依存追加はplugin配布とfail-closed検証を複雑にする。

## 決定

1. `acd-theme-song` Skillを追加し、Design Graphから製品専用ジングルを決定論的に
   作曲する。出力はStrudelパターン記法のテキスト（`theme-song.strudel.js`）と
   Standard MIDI File format 1（`theme-song.mid`）、およびprovenanceとする。
2. 作曲エンジンはPython標準ライブラリのみで実装し、seedは正規化graph JSONのhashと
   任意saltから導出する。同一graph・同一saltはbyte一致し、graph変更は楽曲を変える。
3. Strudelはimport・bundle・実行しない。生成するのはStrudelの公開パターン構文に従う
   テキストだけであり、再生はユーザーが<https://strudel.cc>へ貼り付けて行う。
   生成物はリポジトリと同一ライセンス（BSD-3-Clause）の独自出力である。
4. L2経路として、agentが提案したStrudelパターンを許可関数・許可音源・mini-notation
   文字・明示テンポ範囲・危険トークン不在・括弧整合で検査する
   `validate_theme_song_proposal.py`を置く。検査はパターンテキストの受理判定に限り、
   設計の合否には作用しない。不合格は理由を列挙して停止し、成果物を書かない。
5. 楽曲成果物は、Gerber等と同様に基板pipelineの投影成果物として出力する。
   `src/acd/pipeline/theme_song.py`がSkill CLIをsubprocessで2回実行してbyte一致を確認し、
   `theme-song/theme-song.mid`、`theme-song/theme-song.strudel.js`と
   `theme-song-projection.json`（`ThemeSongProjection`、`record_class="L3"`、
   `pass_evidence=False`、script sha256・graph hash・出力hash付き）を`out/`へ書き、
   `hashes.json`へ登録する。Evidence、fab claims、gate fields、製造提出用fab package
   （JLCPCB zip）へは追加せず、合否にも作用させない。
6. WAV書き出し、ESP32ブザー用データ、GPU生成モデルの採用は本ADRの対象外とし、
   必要になれば別ADRで受入条件を定義する。

## 影響

- Strudel／MIDIの生成物は`out/`以下に置き、commitしない。
- 生成Strudelは作曲器自身のvalidatorを通し、生成MIDIは独立再読込でnote-on／note-offの
  対応を確認してから書き出す。いずれの不一致もfail-closedとする。
- Skill scriptは`acd`をimportしないため、PEP 723メタデータとpackage契約の対象外である。
