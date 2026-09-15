# dual-beacon-tag provisional ルータ測定記録

このディレクトリは、2026-09-14に行ったdual-beacon-tagのL3 provisional
測定記録である。実行はhostから固定tools imageを起動する経路で行い、
host単独のauthoritative実行ではない。

ルータ探索へ到達させるため、合成CPL orientation recordをscratch fixtureへ
一時的に供給した。合成recordは測定済みのCPL provenanceではなく、
authoritative Evidenceでもない。この記録からL1の合格やend-to-end acceptanceを
主張してはならない。

30 x 22 mm / 2-layerの設計は、28候補を3 roundで評価しても全候補が
`not_converged`となり、最終unroutedは21、plateauは5、open netは10件だった。
40 x 30 mmのvariantでは`placement-0003`が0 unrouted、connectivity、DRC、
independent reloadを通過したが、合成archiveのparse gapによりcandidate評価で
rejectされた。したがって14.22はend-to-end合格を実証していない。

実測結果はrouter探索と診断の再現用であり、設計入力・CPL producer・container
実行経路・筐体干渉・FW coverageの未解決事項を置き換えない。
