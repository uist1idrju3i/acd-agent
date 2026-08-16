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
- 今回、OpenHands Agent Canvasの本体ソースを`vendor/openhands`として追加し、
  MITライセンスのv1.13.0（`4f465f3ccada5271a3bbe4a0148941b0c40d243b`）に固定する。
  既存の`vendor/software-agent-sdk`（v1.41.0）もこの方針に含める。

## 根拠

次の3分類で依存物の扱いを決める。

### 分類A: submodule固定が適切

ACDがソースを直接参照・import・資材配布するpermissiveなものはsubmoduleに固定する。
既存のsoftware-agent-sdkと、今回追加するopenhands/Agent Canvasが該当する。

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
- `vendor/openhands`はMITライセンスであり、ライセンス境界を確認したうえで参照する。
- submoduleはポインタであり再配布ではない。ただし将来binaryを同梱・配布する場合は、
  ライセンス義務が別途発生する。詳細は[`prior-art.md`](../prior-art.md)の
  「ライセンス境界まとめ」を参照する。
- `vendor/`の取得はCIのcloneコストに影響するため、サイズが大きいsubmoduleには
  shallow clone設定を付ける。`vendor/openhands`は作業ツリー18M、Git object database
  400Mの実測であり、`.gitmodules`に`shallow = true`を設定した。
