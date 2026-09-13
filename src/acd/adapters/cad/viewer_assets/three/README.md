# three.js（vendor同梱）

統合3Dモデル投影のHTMLビューア（`acd.adapters.cad.assembly_viewer`）が埋め込む
three.jsの資材である。外部CDNへ依存しないため、必要なmoduleだけをnpm packageから
無変更で複製している。

- 取得元: npm `three` package（<https://www.npmjs.com/package/three>、
  upstream <https://github.com/mrdoob/three.js>）
- 版: `VERSION`に記録（`0.186.0` = r186）
- ライセンス: MIT（`LICENSE`、Copyright 2010-2026 Three.js Authors）
- 複製したファイル:
  - `build/three.module.js` → `three.module.js`
  - `build/three.core.js` → `three.core.js`
  - `examples/jsm/controls/OrbitControls.js` → `OrbitControls.js`
  - `examples/jsm/loaders/GLTFLoader.js` → `GLTFLoader.js`
  - `examples/jsm/utils/BufferGeometryUtils.js` → `BufferGeometryUtils.js`
  - `examples/jsm/utils/SkeletonUtils.js` → `SkeletonUtils.js`

ファイル本体は改変しない。相対import（`./three.core.js`等）はHTML生成時にimport mapの
bare specifierへ書き換えて`data:` URLとして埋め込む。更新時は`VERSION`と本書の版、
`docs/operations.md`の依存記録を同じ変更で更新する。
