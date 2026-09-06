# Golden Design #1 ライブラリpin

## Espressif

- 取得元URL: `https://github.com/espressif/kicad-libraries`
- 取得commit: `dd76561812ab300351234ba6e0ec1295641796f0`
- 取得日: 2026-08-11 UTC
- ライセンス: Creative Commons CC-BY-SA 4.0（KiCadライブラリ例外付き）。
  原文は取得元リポジトリの`LICENSE.md`を参照する。
- 内容:
  - `Espressif.kicad_sym`: `ESP32-C3-MINI-1`シンボルのみを抜粋した最小ライブラリ。
  - `Espressif.pretty/ESP32-C3-MINI-1.kicad_mod`: 対応するfootprint（無改変）。

## CERN KiCad Libraries

- 取得元URL: `https://gitlab.com/ohwr/cern-kicad-libs`
- 取得commit: `9f654ec4b274ca67960426e157a73103918d462b`
- 取得日: 2026-09-06
- ライセンス: CERN-OHL-P-2.0（permissive variant、Copyright 2024-2025 CERN）。
  ライセンス本文は`LICENSES/CERN-OHL-P-2.0.txt`に保存する。
- シンボルはKiCad 9生成ライブラリから無改変で抜粋し、upstreamと同じく
  `Footprint` propertyを空のまま保持する。ACDではcatalogでfootprintを対応付ける。
  upstreamが想定するdatabase-library利用に必要な3D modelとdatasheetは含めない。
- 抽出は`extract_cern_library_parts.py --spec libraries/CERN.parts.json
  --source <checkout>`で再現し、`--check`でdriftを検出する。

KiCad公式ライブラリ由来の部品（抵抗、コンデンサ、USB-C、AMS1117、SHT4x等）は
本ディレクトリへ複製せず、kicadパッケージ（10.0.6）同梱の
`/usr/share/kicad/symbols`・`/usr/share/kicad/footprints`をファイルhash付きで
pinして参照する（`graph.json`の各`electrical.component`ノード属性）。
