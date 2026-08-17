# ADR-0006: vendor submoduleの対象と固定方針

> ステータス: Accepted
> 日付: 2026-08-13

## コンテキスト

ACDはOpenHandsのソースを参照する一方、外部プロセスとして実行するツールや
ライセンス上の制約があるコードも扱う。依存物を一律に`vendor/`へ置くと、CIの
取得・ビルドコスト、ライセンス境界、実行時の再現性を混同するため、submoduleの
適用範囲と版固定方法を明確にする必要がある。

## 決定

- `vendor/`のgit submoduleは、ACDが直接importまたは資材として参照する、
  permissiveライセンスで、サイズが実用的なソースに限定する。
- submoduleはタグ由来のcommit SHAで固定する。
- `vendor/software-agent-sdk`（v1.42.1）をsubmoduleとして固定する。
- OpenHands Agent CanvasはACDの実行基盤でも参照資材でもないため、submoduleにしない。

## 根拠

次の3分類で依存物の扱いを決める。

### 分類A: submodule固定が適切

ACDがソースを直接参照・import・資材配布するpermissiveなものはsubmoduleに固定する。
ACDが直接参照するsoftware-agent-sdkだけが該当する。

### 分類B: submoduleにせず、版pin＋probeで固定する

kicad-cli、FreeCAD、ngspice、freerouting JAR、ESP-IDFなど、外部プロセスとして
呼び出すbinaryはsubmoduleにしない。ソースツリーが巨大でCIでのビルドが非現実的であり、
決定論の要件は実行したbinaryの版を記録することで満たすためである。これは
`packages/acd-tools`のprobeと同じ考え方である。分類Bの版pin manifest自体は本ADRの
範囲外（未決定・今後の課題）とし、ここでは実装しない。

### 分類C: vendorに置かない

GPL/AGPLコードをACDへimport結合し得るもの（kiutils、PySpice、boardsmithなど）は
`vendor/`に置かない。これは`AGENTS.md`の「GPL/AGPLコードをACDへimport結合しない」
という方針に従う。

## 影響

- submoduleのポインタとcommit SHAにより、参照するソースの再現性を確保する。
- OpenHandsの公開Skillsは外部URLを参照し、submoduleにはしない。
- submoduleはポインタであり再配布ではない。ただし将来binaryを同梱・配布する場合は、
  ライセンス義務が別途発生する。詳細は[`research/prior-art.md`](../research/prior-art.md)の
  「ライセンス境界まとめ」を参照する。
- `vendor/`の取得はCIのcloneコストに影響するため、submoduleは直接参照するSDKに
  限定する。公開Skills repositoryはcloneせず、必要時に外部参照する。

## H3更新

旧版ではAgent Canvasをsubmodule化していたが、ACDの実行・ビルド・テストに使わず、
参照価値もないため削除した。OpenHands/extensionsも同じ理由でsubmoduleに追加しない。
