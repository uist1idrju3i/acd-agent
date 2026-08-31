# Golden Design #1 ライブラリpin

本ディレクトリのシンボル・footprintは
[espressif/kicad-libraries](https://github.com/espressif/kicad-libraries)
から取得した抜粋である。

- 取得元URL: `https://github.com/espressif/kicad-libraries`
- 取得commit: `dd76561812ab300351234ba6e0ec1295641796f0`
- 取得日: 2026-08-11 UTC
- ライセンス: Creative Commons CC-BY-SA 4.0（KiCadライブラリ例外付き）。
  原文は取得元リポジトリの`LICENSE.md`を参照する。
- 内容:
  - `Espressif.kicad_sym`: `ESP32-C3-MINI-1`シンボルのみを抜粋した最小ライブラリ。
  - `Espressif.pretty/ESP32-C3-MINI-1.kicad_mod`: 対応するfootprint（無改変）。

KiCad公式ライブラリ由来の部品（抵抗、コンデンサ、USB-C、AMS1117、SHT4x等）は
本ディレクトリへ複製せず、kicadパッケージ（10.0.6）同梱の
`/usr/share/kicad/symbols`・`/usr/share/kicad/footprints`をファイルhash付きで
pinして参照する（`graph.json`の各`electrical.component`ノード属性）。
