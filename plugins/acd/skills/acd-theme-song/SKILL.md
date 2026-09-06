---
name: acd-theme-song
description: Compose a deterministic product theme song (jingle) for a design graph as Strudel pattern text and a Standard MIDI File, and validate agent-proposed Strudel patterns against an allowed surface.
version: 0.1.0
license: BSD-3-Clause
triggers:
  - theme song
  - jingle
  - strudel
  - midi
  - テーマソング
  - ジングル
  - 作曲
---

# ACD theme song

Every product release deserves a theme song. This Skill composes a short
jingle for a design graph and writes it as Strudel pattern text
(`theme-song.strudel.js`) and a Standard MIDI File (`theme-song.mid`). The
song is an L3 artifact: it presents the design, cannot approve it, never flows
back into design inputs, and is not Evidence.

The GD1 board pipeline (`src/acd/pipeline/theme_song.py`) runs this CLI as a
subprocess in its projection stage, checks that two runs reproduce identical
bytes, and ships `theme-song/theme-song.mid`, `theme-song/theme-song.strudel.js`
and `theme-song-projection.json` as projection deliverables alongside the
Gerbers, registered in `hashes.json` but never in Evidence or the fab package.

| Script | Purpose |
| --- | --- |
| `theme_song.py` | Composition library: graph summary, seed, score, Strudel renderer, MIDI writer, validator, provenance. |
| `compose_theme_song.py` | Deterministic composer CLI (L3). Writes `.strudel.js`, `.mid` and provenance. |
| `validate_theme_song_proposal.py` | L2 path: checks an agent-proposed Strudel pattern and records it only when accepted. |

## Usage

```bash
# Deterministic jingle for the golden design (16 bars by default).
uv run python plugins/acd/skills/acd-theme-song/scripts/compose_theme_song.py \
    --graph fixtures/golden-design-1/graph.json \
    --out-dir out/theme-song

# Variation with the same graph: mix a salt into the seed.
uv run python plugins/acd/skills/acd-theme-song/scripts/compose_theme_song.py \
    --graph fixtures/golden-design-1/graph.json \
    --out-dir out/theme-song-v2 --salt v2 --bars 32

# Agent-proposed Strudel pattern (L2). Rejected proposals write nothing.
uv run python plugins/acd/skills/acd-theme-song/scripts/validate_theme_song_proposal.py \
    --graph fixtures/golden-design-1/graph.json \
    --proposal out/theme-song/proposal.strudel.js \
    --out-dir out/theme-song

# Skill tests (kept separate from the ACD test suite).
uv run pytest plugins/acd/skills/acd-theme-song -q
```

Play the result by pasting `theme-song.strudel.js` into <https://strudel.cc>,
or open `theme-song.mid` in any DAW or MIDI player.

## How the song is derived

- The seed is `sha256(canonical_graph_json_hash + "\0" + salt)`. The same
  graph and salt produce byte-identical `.strudel.js` and `.mid`; any graph
  change changes the song.
- Mode (major/minor), key, tempo (92..140 bpm) and chord progression come from
  the graph structure (requirement, component, net and firmware-state counts).
  The melodic motif is derived from the `graph_id`.
- Sections: intro (bass and kick), verse, lift (melody transposed a semitone),
  outro on the tonic. Rhythms are Euclidean patterns.
- The Strudel output uses only a small documented surface (`setcps`, `stack`,
  `note`, `s`, `gain`, `lpf`, `room`, ...) and built-in sounds
  (`triangle`, `sawtooth`, `square`, `bd`, `sd`, `hh`). The MIDI output is
  format 1, 480 ticks per beat, with melody, chord, bass and drum tracks. The
  composer re-reads its own MIDI to confirm every note-on has a note-off.

## Provenance and fail-closed behaviour

Both scripts write `<artifact>.provenance.json` with `pass_evidence: false`,
the graph `graph_id`/`revision`, the canonical input hash, the generator script
hash, every artifact hash, the composition parameters (or proposal hash) and
the licence (`BSD-3-Clause`, same as the repository).

Generation stops instead of producing a song when the graph is not a JSON
object, `graph_id`/`revision`/`nodes` are missing, a node lacks `id`/`kind`,
the bar count is not a multiple of 4 within 4..64, or the self-check of the
generated Strudel/MIDI fails.

A proposal is rejected (all reasons listed) when it contains executable or
external-access tokens (`import`, `require`, `fetch`, `eval`, `samples`,
`${`, ...), calls a function outside the allowed surface, uses a sound outside
the allowed list, lacks `setcps(...)` or sets a tempo outside 92..140 bpm, has
unbalanced delimiters, uses mini-notation characters outside the whitelist, or
produces no `note`/`n`/`s` events. Acceptance is a pattern-text check only; it
does not approve the design.

## Licence boundary

Strudel (<https://strudel.cc>, AGPL-3.0-or-later) is not imported, bundled or
executed by this Skill. The Skill generates text in Strudel's public pattern
syntax, which the user pastes into the Strudel REPL. The generated artifacts
are original output of this repository and carry the repository licence.
