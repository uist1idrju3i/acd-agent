# FEM fixture

`gd1-drop.json` declares a one-metre drop estimate for the GD1 enclosure.
`gd1-drop.dat` is a deliberately synthetic, minimal `.dat`-like parser fixture;
it is not a CalculiX run and must not be used as authoritative evidence.

The real `ccx` execution path is fail-closed to `unknown` when CalculiX is not
installed. The host used for this change does not provide `ccx`, so the
real-run regression test is skipped.
