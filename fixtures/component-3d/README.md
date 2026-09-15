# component-3d synthetic fixture

このSTEPはKiCad CLIがないホストでも部品3D連携の決定論的テストを行うための
build123d生成fixtureである。基板プレートと、GD1のU1/J1位置に置いた2つの
component solidを含む。実KiCadモデルやauthoritative Evidenceの代替ではない。

再生成:

```bash
uv run python scripts/make_component_3d_fixture.py \
  --out fixtures/component-3d/gd1-components.step
```
