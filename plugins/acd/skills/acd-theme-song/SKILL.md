---
name: acd-theme-song
description: Compose a product theme song (jingle) for a design graph as a Standard MIDI File. The agent writes a theme song proposal JSON (key, tempo, tracks, notes, drums); the Skill validates it strictly and renders MIDI, falling back to a deterministic graph-derived song when no proposal exists.
version: 0.2.0
license: BSD-3-Clause
triggers:
  - theme song
  - jingle
  - midi
  - テーマソング
  - ジングル
  - 作曲
---

# ACD theme song

Every product release deserves a theme song. This Skill turns a design graph
into a short jingle written as a Standard MIDI File (`theme-song.mid`). The
song is an L3 artifact: it presents the design, cannot approve it, never flows
back into design inputs, and is not Evidence.

The GD1 board pipeline (`src/acd/pipeline/theme_song.py`) runs this CLI as a
subprocess in its projection stage, checks that two runs reproduce identical
bytes, and ships `theme-song/theme-song.mid` and `theme-song-projection.json`
as projection deliverables alongside the Gerbers, registered in `hashes.json`
but never in Evidence or the fab package.

| Script | Purpose |
| --- | --- |
| `theme_song.py` | Composition library: graph summary, deterministic composer, proposal validator, MIDI writer/reader, provenance. |
| `compose_theme_song.py` | CLI. Renders an agent proposal (`--proposal`) or the deterministic song; writes `.mid` and provenance. |

## Composing as an agent (the expected path)

You, the agent, compose the song. The Skill does not call a model; it validates
what you write and renders it. Work in three steps:

1. Read the design graph (`graph_id`, `revision`, requirements, components,
   nets, firmware states) and decide what the product should sound like: mood,
   key, tempo, motif, arrangement. Write that reasoning into `rationale`.
2. Optionally start from the deterministic draft to get the contract filled in:

   ```bash
   uv run python plugins/acd/skills/acd-theme-song/scripts/compose_theme_song.py \
       --graph fixtures/golden-design-1/graph.json \
       --out-dir out/theme-song-draft \
       --proposal-out out/theme-song-draft/theme-song.proposal.json
   ```

   Edit the notes, tracks, tempo and title freely; only the contract below is
   enforced.
3. Render and check the proposal. Rejections list every reason and write no
   artifact; fix the proposal and rerun.

   ```bash
   uv run python plugins/acd/skills/acd-theme-song/scripts/compose_theme_song.py \
       --graph fixtures/golden-design-1/graph.json \
       --proposal out/theme-song-draft/theme-song.proposal.json \
       --out-dir out/theme-song
   ```

To adopt the song for a design, save the accepted proposal as
`theme-song.json` next to that design's `graph.json` (for example
`fixtures/golden-design-1/theme-song.json`). The board pipeline renders that
file (`source: agent_proposal`) and records its hash in the projection; when
the file is absent it falls back to the deterministic composer
(`source: deterministic`). The proposal is a design input in git like any other
fixture, so changing it changes the projection hash.

### Proposal contract (`theme_song_proposal` 0.1)

```json
{
  "artifact_kind": "theme_song_proposal",
  "schema_version": "0.1",
  "pass_evidence": false,
  "graph_id": "golden-design-1",
  "target_revision": "r1",
  "title": "Golden Design Fanfare",
  "rationale": "Why this music represents the product.",
  "bpm": 120,
  "bars": 16,
  "key": "c major",
  "tracks": [
    {"name": "Melody", "channel": 0, "program": 80,
     "notes": [{"bar": 0, "step": 0, "length": 2, "pitch": "c5", "velocity": 96}]}
  ],
  "drums": [{"bar": 0, "step": 0, "sound": "bd"}]
}
```

- `graph_id` and `target_revision` must equal the graph's; `pass_evidence`
  must be `false`.
- `bpm` 92..140; `bars` a multiple of 4 in 4..64; `key` non-empty text.
- 1..8 tracks with unique names (`[A-Za-z0-9 _-]`, up to 32 chars), unique
  MIDI `channel` 0..15 excluding 9 (drums), `program` 0..127.
- Each note: `bar` in `0..bars-1`, `step` 0..15 (16 steps per bar), `length`
  1..64 steps ending within the song, `pitch` as a MIDI number 0..127 or a
  name such as `f#4`/`bb3`, `velocity` 1..127. No track may repeat the same
  pitch at the same step. At least 8 notes in total; at most 4096 events.
- Drums use channel 9 and the General MIDI names `bd sd hh oh cp rim lt mt
  ht cr rd`.

Acceptance judges the proposal text only; it never approves the design.

## Deterministic fallback

Without `--proposal` the song is derived from the graph:

- Seed `sha256(canonical_graph_json_hash + "\0" + salt)`; identical graph and
  salt give byte-identical MIDI, any graph change changes the song.
- Mode (major/minor), key, tempo (92..140 bpm) and chord progression come from
  the requirement, component, net and firmware-state counts; the motif from
  `graph_id`. Sections: intro, verse, lift (transposed a semitone), outro.
  Rhythms are Euclidean patterns.

```bash
uv run python plugins/acd/skills/acd-theme-song/scripts/compose_theme_song.py \
    --graph fixtures/golden-design-1/graph.json --out-dir out/theme-song --salt v2 --bars 32
uv run pytest plugins/acd/skills/acd-theme-song -q
```

Open `theme-song.mid` in any DAW or MIDI player.

## MIDI, provenance and fail-closed behaviour

The MIDI is format 1, 480 ticks per beat, one track per proposal track plus a
drum track on channel 9. The composer re-reads its own bytes to confirm every
note-on has a note-off before writing.

`theme-song.provenance.json` records `pass_evidence: false`, `source`
(`deterministic` or `agent_proposal`), `composer_id`, the graph
`graph_id`/`revision`, canonical and file hashes of the graph, the proposal
path and hash when used, the generator script hash, the MIDI hash, the
composition parameters and the licence (`BSD-3-Clause`).

Generation stops instead of producing a song when the graph is not a JSON
object, `graph_id`/`revision`/`nodes` are missing, a node lacks `id`/`kind`,
the bar count is invalid, the proposal violates the contract, or the MIDI
self-check fails. Only the Python standard library is used.
