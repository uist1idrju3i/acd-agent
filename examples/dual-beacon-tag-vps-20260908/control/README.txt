Pristine-main control runs at 5bf2c90652f9ba5479cae97983446a652fac55ba
(digest-locked server image ghcr.io/uist1idrju3i/acd-server@sha256:fb236ff5b53dabead1a6f8bd8e32aa6d1e42f140f527d95d2bd72d2ca01a3b9e).

control-a / control-b  : fixture-as-committed (stale graph.json copy left in
                         fixtures/dual-beacon-tag by the agent; net.button, no BOOT net)
control-a2 / control-b2: fixture-effective (the fixture the agent's last loop
                         actually ran: out/dual-beacon-tag-fixture graph regenerated
                         from spec.json at 09:39, net.boot wired to pin.u1.23,
                         plus the 09:38 spec.json)

Commands (cwd = pristine worktree; exit codes in parentheses):

control-a (exit 1):
  uv run python scripts/run_in_workspace.py --image ghcr.io/uist1idrju3i/acd-server@sha256:fb236ff5b53dabead1a6f8bd8e32aa6d1e42f140f527d95d2bd72d2ca01a3b9e \
    --repo <worktree> --memory-limit 6g --command-timeout 1800 --download-root out/control-a \
    "uv sync && uv run python scripts/run_design_loop.py --fixture fixtures/dual-beacon-tag --design-only --out-root out/control-a"

control-b (exit 1): same with --download-root out/control-b and loop command
  "... --design-only --explore-board --max-exploration-candidates 2 --max-exploration-rounds 1 --out-root out/control-b"

control-a2 (exit 1): same as control-a with out/control-a2.
control-b2 (exit 1): same as control-b with out/control-b2.

Verifier (host, per run): uv run python scripts/verify_authoritative_evidence.py \
  --revision-from fixtures/dual-beacon-tag/graph.json --out-root out/container/<run> \
  --require-lane electrical --require-lane mechanical --require-lane firmware
  -> all four: exit 1, "FAIL: no Evidence files supplied" (loop fail-closed
     before any evidence stage).

control-c (exit 1): fixture regeneration from the agent's final spec.json on pristine
  main (no graph reuse):
  "uv sync && uv run python scripts/run_design_loop.py --fixture fixtures/dual-beacon-tag \
    --fixture-spec fixtures/dual-beacon-tag/spec.json --fixture-overwrite --design-only --out-root out/control-c"
  -> failed_stage fixture-generation, "FixtureBuilderError: parts catalog has no matching part".
     The agent's graph.json carries parts_catalog_sha256 sha256:c1371cf3... (the agent-edited
     contracts/parts-catalog.json with KT-0603G / KT-0603A / Conn_01x04_Pin entries); the
     pristine catalog is sha256:fda21feb.... control-a2 / control-b2 reused that graph, so
     their reach depends on the agent's contract edit, not on pristine main alone.
