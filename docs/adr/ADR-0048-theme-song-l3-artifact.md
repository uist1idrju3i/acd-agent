# ADR-0048: 製品テーマソングのMIDI投影とLLM作曲提案の検証レンダリング

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
一方で、作曲そのものはLLM agentが主体的に行い、決定論的な自動作曲を単なる
下書き・fallbackに留めることが求められた。

## 決定

1. `acd-theme-song` Skillを追加する。出力はStandard MIDI File format 1
   （`theme-song.mid`）とprovenanceだけとし、Strudelパターン等の再生環境依存形式は
   生成しない。Strudelはimport・bundle・実行せず、調査対象として記録するに留める。
2. 作曲の主体はLLM agentである。agentはDesign Graphを読み、調・テンポ・題名・
   トラック（channel/program）・音符列（bar/step/length/pitch/velocity）・ドラムを
   `theme_song_proposal` JSON（`graph_id`・`target_revision`・`pass_evidence=false`・
   `rationale`付き）として提案する。Skillは提案を範囲・識別子・時間軸・重複・件数で
   厳密に検査し、受理した提案だけを決定論的にMIDIへレンダリングする。不合格は理由を
   列挙して停止し、成果物を書かない。受理判定は提案テキストの契約適合に限り、
   設計の合否には作用しない。
3. 提案が無い場合のfallbackとして、Python標準ライブラリのみの決定論的composerを置く。
   seedは正規化graph JSONのhashと任意saltから導出し、同一graph・同一saltはbyte一致、
   graph変更は楽曲を変える。composerは提案契約で下書き（`--proposal-out`）を出力でき、
   agentはそれを編集して提案へ仕上げてよい。
4. 採用した提案は設計ディレクトリの`theme-song.json`（`graph.json`の隣）へ置き、
   git管理の設計入力とする。基板pipelineの`src/acd/pipeline/theme_song.py`はそれが
   あればSkill CLIへ`--proposal`で渡し（`source="agent_proposal"`）、無ければ決定論
   composerを使う（`source="deterministic"`）。いずれもsubprocessで2回実行して
   MIDIのbyte一致を確認し、`theme-song/theme-song.mid`と`theme-song-projection.json`
   （`ThemeSongProjection`、`record_class="L3"`、`pass_evidence=False`、script sha256・
   graph hash・提案hash・出力hash付き）を`out/`へ書き、`hashes.json`へ登録する。
   Evidence、fab claims、gate fields、製造提出用fab package（JLCPCB zip）へは追加せず、
   合否にも作用させない。
5. WAV書き出し、ESP32ブザー用データ、GPU生成モデルの採用は本ADRの対象外とし、
   必要になれば別ADRで受入条件を定義する。

## 影響

- MIDIの生成物は`out/`以下に置き、commitしない。採用した提案`theme-song.json`は
  fixtureとしてcommitする。
- 生成MIDIは独立再読込でnote-on／note-offの対応を確認してから書き出す。不一致は
  fail-closedとする。
- 提案の検査規則（bpm 92..140、bars 4..64の4倍数、track 1..8、channel 9はドラム専用、
  8音以上4096イベント以下、既知ドラム名のみ等）はSkill側で固定し、成功のために
  緩めない。
- Skill scriptは`acd`をimportしないため、PEP 723メタデータとpackage契約の対象外である。
