# 運用・インストール

## 前提

- Linux環境
- Python 3.12以上
- `uv`
- KiCad CLI
- JavaとFreeRouting
- Docker（ゲート実行の正）

OpenHands Software Agent SDKは`vendor/software-agent-sdk`のsubmodule v1.42.1
（commit `167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497`）をworkspace sourceとして使用する。
agent-serverはACDの対象外であり、採用する場合は新規ADRで受入条件を定義する。実行形は
`LocalConversation`とdigest固定server imageを使う`DockerWorkspace` runnerを基点とする。
host経路はprovisional専用であり、authoritative Evidenceを生成しない。

## cloneと依存関係

```bash
git clone --recurse-submodules <repository-url>
cd acd-agent
uv sync
```

submoduleの確認:

```bash
git submodule status
```

`vendor/software-agent-sdk`がv1.42.1のcommitを指していることを確認する。

## OpenHandsへのインストール（SDK標準ルート）

配布版をOpenHands環境へ導入する場合は、repositoryをcloneせず、pluginを
installed plugin storeへインストールするだけでSkillを実行できる。Skill scriptは
PEP 723のメタデータから`acd`を初回実行時に自己解決するため、ネットワーク接続と
大きな依存パッケージのダウンロードが必要になる。

```bash
# 開発checkout用、または任意の事前インストール:
uv pip install "git+https://github.com/uist1idrju3i/acd-agent@<tag or SHA>"
```

次に、SDK標準の`Plugin.fetch()`／`PluginSource`でplugin資材を取得する。refは
40桁commit SHAまたは`v<semver>` tagに限定される。

```python
from openhands.sdk.plugin import Plugin
from acd.openhands.distribution import acd_plugin_source

source = acd_plugin_source("<40桁SHA または v<semver> tag>")
plugin = Plugin.load(Plugin.fetch(
    source.source, ref=source.ref, repo_path=source.repo_path))
```

開発時の編集・submodule確認では、従来どおり「cloneと依存関係」に記載した
`git clone --recurse-submodules`と`uv sync`の経路を使用する。配布経路を短縮しても、
ゲート実行の正はlock記録済みdigest固定server imageであり、`DockerWorkspace`を
通したauthoritative Evidenceの契約は変わらない。

## OpenHandsへのインストール（installed plugin自動読み込み）

ADR-0035のpackage導入後、SDK標準のinstalled plugin storeへpluginをinstallする。

```bash
uv pip install "git+https://github.com/uist1idrju3i/acd-agent@<tag or SHA>"
```

```python
from openhands.sdk.plugin.installed import install_plugin

install_plugin(
    "github:uist1idrju3i/acd-agent",
    ref="<tag or SHA>",
    repo_path="plugins/acd",
)
```

同じ処理は、次のcopy-pastableなコマンドでも実行できる。

```bash
python -c "from openhands.sdk.plugin.installed import install_plugin; print(install_plugin('github:uist1idrju3i/acd-agent', ref='<tag or SHA>', repo_path='plugins/acd'))"
```

install後に起動する`LocalConversation`は、SDKのambient自動読み込みでinstalled pluginを
取得する。不変ref（tagまたは40桁SHA）を推奨するが、この経路では強制しない。開発・CIや
provenanceを厳密に固定する用途では、ADR-0035の明示`Plugin.fetch()`経路を使用する。
この経路を選択しても、ゲート実行の正はlock記録済みdigest固定server imageを
`DockerWorkspace(server_image=...)`で実行する契約から変わらない。
同じinstalled plugin storeへは、後述のAgent Canvas GUIからもinstallできる。
将来catalogへacdを登録した後は、これらの手動操作は不要となり、catalog経由の
インストールへ置き換わる（「将来のGUI掲載（marketplaceカタログ）」参照）。

### Agent Canvas GUIからのインストール

OpenHandsのLocal GUI（Agent Canvas）は「カスタマイズ → Plugins → プラグインを追加」
ダイアログを持ち、入力値はSDKの`install_plugin(source, ref, repo_path)`へそのまま渡る
（[公式ドキュメント](https://docs.openhands.dev/overview/plugins#local-gui)）。
ACDは次の値でinstallできる。

| 項目 | 入力値 |
| --- | --- |
| ソース | `github:uist1idrju3i/acd-agent` |
| リファレンス（任意） | branch名、tag、または40桁commit SHA |
| パス | `plugins/acd` |

パスは必須である。省略するとplugin rootがリポジトリ直下になり、
`plugins/acd/.plugin/plugin.json`は読まれず、SDKがディレクトリ名からmanifestを推論する。
その場合、Skill・AgentDefinition・command・hooksは0件のままでもinstall自体は成功し得る。
インストール直後にplugin詳細ダイアログでplugin名が`acd`であること（`acd-agent-<hash>`では
ないこと）と、Skillが読み込まれていることを確認する。この確認を完了してから、次節の
Local GUIからの動作確認手順へ進む。

リファレンスを省略するとdefault branchの先頭を取得する。再現性が必要な場合は
不変ref（tagまたは40桁commit SHA）を指定する。短縮SHAはSDKのfetchが
`git clone --branch`で解決するため使用できない。install後の挙動と契約は
上記のambient自動読み込み経路（ADR-0036）と同一である。Skill scriptの`acd`
依存はPEP 723で自己解決されるため、hostのpip installとは独立している。
digest固定server image（Docker image）はplugin installでは取得されず、ゲート実行時に
`DockerWorkspace(server_image=...)`が初回pullする。

### Local GUIからの動作確認手順

インストール直後に、まず自己診断入口を実行する。doctorはplugin資材と実行環境を
観測するが合否権限を持たない。required checkの`failed`はインストール資材または
install locationの不整合として扱い、`repo_path: plugins/acd`を省略した場合は指定のsource
とpathで再インストールする。prompt manifestのcanonical hashと資材hashも検証する。その後、既存のplugin名`acd`と
Skill読み込み確認を行い、Local GUIの会話から決定論的な投影・出力を確認する。
GUIでの操作は、既存のCLI入口を会話から呼び出す形に限定する。

1. `/acd:doctor`を実行する。GUI installでは
   `~/.openhands/plugins/installed/acd/skills/acd-install-doctor/scripts/install_doctor.py`、
   開発checkoutでは
   `plugins/acd/skills/acd-install-doctor/scripts/install_doctor.py`を使用する。
   JSONの`status`、required check、plugin rootをそのまま確認する。hookはinterpreter経由で
   起動されるため、commit済みscriptの実行可能権限・shebang不足はstatusを下げない。
   Dockerが到達不能な場合は`degraded`となる。ホストEDAツールの不在はhost executionの
   観測情報として記録されるだけでstatusを下げず、
   doctorのL3観測をauthoritative Evidenceやゲート合格へ昇格させない。

2. plugin詳細の名前が`acd`であり、Skillが読み込まれていることを確認する。これは
   doctorのmanifest／Skill資材検査をGUIのロード結果でも確認する手順であり、
   doctorだけでSDKのロード成功を推定しない。

3. 基板・筐体のゲートは`/acd:gates` commandを実行する。`plugins/acd/commands/gates.md`
   の引数契約に合わせ、必要に応じてfixtureと出力先を指定する。

   ```text
   /acd:gates --fixture fixtures/golden-design-1 --out out/gd1
   ```

   基板pipelineの前提として、シルク配置を解決する場合は
   `scripts/resolve_gd1_silkscreen.py`を先に実行する。resolverはcontextの
   mask開口、既存／固定シルク、同じ面のbody/courtyard、最近傍部品帰属を候補段階で
   検査するが、最終合否はauthoritative projectionと独立測定ゲートが判定する。基板pipelineは
   `scripts/run_gd1_pipeline.py`、筐体pipelineは
   `scripts/run_gd1_enclosure_pipeline.py --out out/gd1-enclosure`がCLI入口である。
   会話から実行する場合も、ゲートの段階、使用したfixture、入力・出力Evidenceのパスを
   応答へ明記させる。

4. 実行済みのGD1基板pipelineでは、回路図
   `out/gd1/gd1.kicad_sch`、routed board
   `out/gd1/routed/gd1.kicad_pcb`、Gerberの
   `out/gd1/gerbers/`、drillの`out/gd1/gerbers/gd1.drl`、製造出力の
   `out/gd1/fab/`、電気Evidenceの`out/gd1/evidence-electrical.json`が生成される。
   シルク解決を個別に実行した場合は、回路図を含む中間成果物が
   `out/gd1-silkscreen-resolve/iteration-1/`に生成される。

   JLCPCBへ投入するファイルは、製造出力ディレクトリ内の
   `out/gd1/fab/gd1-bom-jlcpcb.csv`と
   `out/gd1/fab/gd1-cpl-jlcpcb.csv`の2つだけである。
   `out/gd1/gd1.bom.csv`はDesign Graph由来の内部BOM投影であり、非実装部品も含み得るため、
   発注用ファイルとして投入してはならない。
   CPL回転の独立検証には、リポジトリ内の
   `evidence/gd1-cpl-orientation/`を使用する。このディレクトリ自体が無い場合は
   製造データ生成をfail-closedで停止し、個別部品のEvidence欠落は
   `order-readiness.json`の回転unknownとして記録する。

5. 実行済みのGD1筐体pipelineでは、部品別STEPとして
   `out/gd1-enclosure/enclosure-shell.step`と
   `out/gd1-enclosure/enclosure-lid.step`、組立確認専用の統合STEPとして
   `out/gd1-enclosure/enclosure-assembly.step`、2オブジェクトを保持する
   `out/gd1-enclosure/enclosure.3mf`、全構成物の正規化hash一覧
   `out/gd1-enclosure/enclosure-artifacts.json`、および
   `out/gd1-enclosure/evidence-mechanical.json`が生成される。部品STEPはshellまたは
   lidの単独ソリッドだけを含み、統合STEPは組立確認用であり、製造部品ファイルの
   代用にはしない。構成物一覧が欠落または期待ファイルと不一致の場合はfail-closedで停止する。

6. FW Skillは会話に`firmware`、`ESP32-C3`、`ESP-IDF`、`QEMU`、`GPIO`のいずれかを
   含めて起動し、次の入口を実行させる。

   ```bash
   uv run --script plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py \
     --fixture fixtures/golden-design-1 --out out/gd1-fw
   ```

   実行済みの出力は、FWプロジェクト
   `out/gd1-fw/acd_gd1_fw/`、ビルド済みFW
   `out/gd1-fw/acd_gd1_fw/build/acd_gd1_fw.bin`、統合flash image
   `out/gd1-fw/flash.bin`、QEMUの仮想シリアルログ
   `out/gd1-fw/qemu-serial.log`、結果の
   `out/gd1-fw/summary.json`である。ESP-IDFと
   `qemu-system-riscv32`が利用できない環境ではこの手順を実行できず、推測した成果物パスを
   成功結果として記録してはならない。

7. これらのhost実行はprovisional専用であり、合格側Evidenceにはならない。authoritative
   Evidenceは、lock済みdigest固定server imageを`DockerWorkspace(server_image=...)`で
   実行した経路だけが生成する。digest不明、container marker欠落、Evidenceのrevision不一致、
   `status`不正、unknown、または実行経路不明はfail-closedとする。FWのQEMUログも仮想検証で
   あり、GD1実機の`measured` EvidenceやLED実測の代替にはならない。

### Skill script依存の自己解決（PEP 723）

`acd`をimportするSkill scriptは先頭のPEP 723メタデータにpackage URLを持ち、
`uv run --script <path>`が専用環境を作成してpinned refから依存を解決する。初回は
ネットワーク接続が必要で、大型依存の取得に時間がかかるため、オフライン環境では
初回実行が失敗する。開発checkoutのローカル変更を使う場合は`uv run python <path>`を
使用する。

package refを更新する場合は、`plugins/acd/skills/acd-package-ref.txt`を編集し、
7つの対象scriptのPEP 723ヘッダーを同じrefへ更新する。その後、
`uv run python scripts/verify_skill_metadata.py`で整合性を検証する。refはリリース後の
commitまたはsemver tagを指定し、scriptとref fileはpluginのリリースと一緒に更新する。
この自己解決経路はローカルSkill実行だけを扱い、ゲート実行の正であるdigest固定imageと
authoritative Evidenceの契約は変更しない。

### アップデート

pluginの更新は2通りある。SDKの`update_plugin()`は、記録済みのsourceを`ref=None`
（default branchの先頭）で再取得して上書きする。GUIの「更新」ボタンはこの経路を使うため、
アンインストールは不要で、有効・無効の状態も維持される。更新ボタンではrefを指定できない。

```bash
python -c "from openhands.sdk.plugin.installed import update_plugin; print(update_plugin('acd'))"
```

特定のtagまたは40桁SHAへ更新する場合は、`install_plugin(..., force=True)`で
上書きinstallする。GUIではいったんアンインストールし、新しいrefで再度インストールする。

```bash
python -c "from openhands.sdk.plugin.installed import install_plugin; print(install_plugin('github:uist1idrju3i/acd-agent', ref='<new tag or SHA>', repo_path='plugins/acd', force=True))"
```

Skill scriptのpackage refは`plugins/acd/skills/acd-package-ref.txt`で管理され、
pluginの更新に含めて変更する。plugin refの更新はhostのpip installとは独立している。
開発checkout用、または任意の事前インストールとしては、次のコマンドを利用できる。

```bash
uv pip install --force-reinstall "git+https://github.com/uist1idrju3i/acd-agent@<new tag or SHA>"
```

pluginとscriptのpackage refはリリース時に整合させる。versionが分かれると、
Skillが呼ぶscriptと`acd` moduleの契約がずれるためである。

### 将来のGUI掲載（marketplaceカタログ）

OpenHands Enterpriseには、catalog repositoryをMarketplace Source URI
（例: `github://owner/plugin-directory@ref`）で参照するexperimentalなPlugin Marketplace
GUIがある。`plugins/acd/.plugin/plugin.json`は、GUIの詳細画面が表示するname、version、
description、authorを含むSDK manifestとしてcatalog掲載に対応できる。

掲載時は、catalog repositoryへ次のようなentryを登録する。これは配布側の作業であり、
ACD本体のコード変更は必要ない。

```json
{
  "name": "acd",
  "source": {
    "source": "github",
    "repo": "uist1idrju3i/acd-agent",
    "path": "plugins/acd",
    "ref": "<tag or SHA>"
  }
}
```

このentryは`github:uist1idrju3i/acd-agent`の`plugins/acd`を不変refで指し、
GUIからのinstallをSDK installed-plugin経路へ接続する。

Dockerでゲートを実行する場合は、`docker/image-digests.json`のlockからserver imageを解決し、
`DockerWorkspace(server_image=...)`へ渡す。server digestが未記録、空、または解決不能なら
runnerは起動せずfail-closedで停止する。host経路は参考実行であり、合格側Evidenceを生成しない。

CIでは`container-gates` jobがlock済みserver imageをpullし、SDKの
`DockerWorkspace`を経由する`scripts/run_in_workspace.py`でresolver、基板pipeline、
筐体pipelineを実行する。agent-serverの`/workspace`を占有させるため、host repositoryは
`/acd-src:ro`へmountし、container内の`/workspace/acd`へ複製する。container内で生成された
`out/gd1/evidence-electrical.json`と`out/gd1-enclosure/evidence-mechanical.json`は、
SDKの`RemoteWorkspace.file_download()`でhostへ取り出してから
`verify_authoritative_evidence.py`へ渡す。revision不一致、host実行、digest不在、
unknown、parse失敗、file不在はすべて非ゼロ終了となる。

runnerは実行対象であるderived server imageのcontent addressを
`ACD_CONTAINER_IMAGE_DIGEST`へforwardする。これによりEvidenceのdigestは実際に
pipelineを実行したserver imageのidentityを表す。base tools digestとは別の値であり、
両者を同一とは扱わない。

`publish-acd-tools.yml`のjob summaryに表示されたindex digestを、image refとともに
`docker/image-digests.json`へ転記する。未publishのentryやplaceholder digestは作成せず、
lockに記録されていないimageをpullするfallbackも禁止する。lockの検証は次のように行う。

```bash
TOOLS_REF="$(uv run python scripts/print_locked_image.py --entry acd-tools)"
docker pull "$TOOLS_REF"
docker run --rm \
  -v "$PWD:/acd-src:ro" \
  -w /tmp \
  "$TOOLS_REF" \
  sh -c 'cp -r /acd-src /tmp/acd && cd /tmp/acd && uv sync && uv run python scripts/probe_tools.py'
```

probe結果の既知版がlockの`tools`と一致することを確認し、版不明、pull失敗、
parse失敗はfail-closedとする。FreeRoutingとuvはDockerfileでSHA-256を検証している一方、
KiCad、ngspice、Java、Pythonはbuild時のAPT／PPA解決に依存する。したがって再buildを
同一性の根拠にせず、publish済みimage digestをidentity authorityとして扱う。

`publish-acd-server.yml`は`workflow_dispatch`専用で、lockから解決したACD tools
digestをbaseにしてSDKの`build.py`でagent-server imageをbuildし、GHCRへpublishする。
初回実行で得たbaseとderivedは独立に記録し、base
`sha256:e64405a15e69991063c688a80b4f215bdc3dbfb8b4fb480b3ef3484f017e1395`とderived
`sha256:a18a56564b7c713b45052ab8c296b59ffcd7fc221f4ed1d0564f4c934b853def`を同一とは扱わない。
derived digestは`docker/image-digests.json`の`acd_server`へ転記済みであり、CIとrunnerは
このserver digestをpullして実行する。

browser_useは`build_acd_conversation(enable_browser=True)`を明示したL2探索時だけ使用する。
Chromiumが利用できない場合は例外で停止し、browser由来の観測はEvidenceへ昇格させない。
EasyEDA APIの決定論的取得経路は維持し、設計入力へ確定する資材は既存経路で再取得して
hashを記録する。SDKのworkflowはfail-closed境界を保てないため不採用（将来再検討）とし、
agent-server系能力は対象外とし、採用判断は新規ADRの起票後に行う。

## 外部ツール

環境に次の実行ファイルが必要である。

```bash
command -v kicad-cli
command -v java
command -v freerouting
```

### KiCad SVG視覚投影の一次確認

KiCad CLI 10.0.5の`sch export svg`と`pcb export svg`は、SVGの`<title>`要素へ
出力ファイル名と秒精度のISO 8601生成時刻を埋め込む。このため同一入力でも生バイト列は
決定的ではないことを一次確認した。8.2では、`<title>`要素が想定形で1個だけ存在する場合に
要素全体を固定文字列へ置換する`kicad-svg-title-v1`正規化規則を採用した。要素の不在、
複数、想定形との不一致、SVGルートのwidth／height単位またはviewBoxの測定不能は
fail-closedとする。正規化後hashは再生成時にも照合し、renderer版は`kicad-cli version`
から取得する。実物fixtureは`kicad-cli version`が10.0.5の環境で、
`kicad-cli pcb export svg --layers F.Cu -o fixtures/visual_projection/kicad/gd1-front-copper.svg out/gd1-silkscreen-resolve/iteration-1/gd1.kicad_pcb`
と、出力先だけを`gd1-front-copper-reproduced.svg`へ変えた同じコマンドを実行して生成した。
出力ファイル名が`<title>`へ入るため、この名前差が生バイト列の非決定性の由来になる。
回路図SVGはKiCadがsheet名をファイル名にして出力するため、単一sheetの期待出力を投影パスへ
renameする。複数sheetによる複数SVG出力は未対応で、追加されたSVGを検出した時点でfail-closedとする。
8.3ではGD1電気laneに限り、必須ゲート通過後に回路図ビューと宣言銅層ごとの層別レイアウト
ビューを`out_dir/visual/`へ既定生成し、`visual-projections-electrical.json`へL3観測として
記録する。投影集合のidentity hashは`generated_at`を再現性の対象から除外するため、同一入力・
同一renderer版の再実行で時刻以外の内容を同一性として比較できる。機械laneの断面・干渉ビューは
renderer未実装のため後続フェーズで扱う。8.5では電気laneに限り、同一revisionの
`ElectricalLane`／`BoardModel`とSVGを決定論的に照合し、
`visual-crosscheck-electrical.json`へL3観測として記録する。この照合は8.3のSVG投影生成直後、
`hashes.json`生成前に既定実行される。
8.3の層導出はgraphで宣言された`BoardView.layers`の層数をKiCadの銅層名へ決定論的に
対応させる。現在の対応表は2層（`F.Cu`／`B.Cu`）と4層（`F.Cu`／`In1.Cu`／`In2.Cu`／`B.Cu`）
に限り、0層、1層、奇数層、その他の未対応層数はfail-closedとする。
8.4では必要時に8.3の正規化前SVGをCairoSVG 2.9.0で幅1600pxへラスタライズし、
8.3の`visual-projections-electrical.json`を変更せず、
`visual-projections-electrical-raster.json`へPNG派生集合を書き出す。PNG派生は
pipelineの既定出力ではなくon-demandのAI受け渡し経路である。acd-tools imageのlibcairo2存在は
未検証で、image再publishとdigest更新までcontainer側で保証できないためである。生成PNGのIHDRから
解像度を測定する。PNGは`png-identity-v1`（正規化なし、生PNG bytesのSHA-256）で記録し、
2回の生成hashが一致しない場合、入力SVGの正規化後hashがrecordと一致しない場合、または
CairoSVGのimport・版取得・libcairo依存が利用できない場合はfail-closedとする。
SDKへ渡す画像はworkspace内PNGだけをbase64の`data:image/png;base64,...` URLへ変換し、
HTTP(S)・`file:` URLは作成しない。`OH_INLINE_IMAGE_ALLOW_PRIVATE_HOSTS`がtruthyな環境では
画像経路を停止し、vision応答は`pass_evidence=false`のL3観測としてだけ保存する。

8.5の照合レポートは、投影集合のidentity hash、machine-readable入力の相対パスとhash、
投影ごとの照合項目、集約status、レビュー観点チェックリスト、canonical hash、
`generated_at`を記録する。identity hashは`generated_at`を除外するため、同一入力から
同一の照合結果とチェック記録を再生成できる。決定論的項目はSVGから直接読み取れる
事実だけを`match`または`mismatch`とし、可読性、設計意図、注記の視認性、重なり・非表示
要素による意味欠落、信号・電源系統の読み取り、層別SVGの意味的な銅層identityは
`observation_required`としてunknownのまま記録する。unknownをmatchへ集約せず、
mismatch・対象欠落・解析失敗・revision不一致はpipelineを停止する。
レポートは`pass_evidence=False`のL3観測であり、Evidence、fab claims、gate fields、
`hashes.json`、fab packageへ追加しない。

## 検証

検証段階とコマンド列は`uv run python scripts/verify_all.py --list`で確認できる
`verify_all.py`を正とする。文書のみ、通常、フルの段階を次で実行する。

```bash
uv run python scripts/verify_all.py --stage docs
uv run python scripts/verify_all.py --stage standard
uv run python scripts/verify_all.py --stage full
```

`full`には`pytest plugins`、silkscreen resolver、基板・筐体pipeline、外部ツールprobeを
含む。authoritative container gateはCI固有の`container-gates` jobで実行するため、
`verify_all.py`には含めない。

GD1基板pipelineはERC、routing、SES import、DRC、fabrication出力、独立再読込、
silkscreen可読性ゲートまで通過する。外部ツールや入力が不正な場合は、ゲートを
緩めずfail-closedとして状態をそのまま記録する。

`verify_authoritative_evidence.py`はLLMやSDKの判定を使わず、
`Evidence.supports_authoritative_pass()`とその構成要素だけを検査する。引数なし、
parse失敗、file不在、revision不一致、status不正、host実行、digest不在、unknown混入は
成功扱いにしない。

## 製造・組立受領の取り込み

送付manifestとfabまたは実装業者の受領recordを決定論的に突合する。manifest自身の
canonical JSON SHA-256を受領recordの`manifest_reference.manifest_hash`と比較し、
成果物の相対pathとcontent hash、対象revision、manifestの`unknowns`を検査する。
成果物の同一性に関係する構造不備、`status: "fail"`、不一致、受領record契約違反は
非ゼロ終了となる。manifestの`unknowns`は価格・納期などの追跡情報としてsortedキーを
reportへ記録するが、それ自体では突合を停止しない。出力Evidenceは合格側へ昇格しない。

```bash
uv run python scripts/ingest_receipt.py \
  --manifest fixtures/contracts/valid/fab-package-receipt.json \
  --receipt fixtures/contracts/valid/receipt.json \
  --evidence out/receipt-evidence.json \
  --report out/receipt-reconciliation.json
```

同一のmanifestとreceiptを再実行した場合、reportとEvidenceは同じバイト列になる。
受領recordの`recorded_by`は記録者 provenance としてEvidenceの測定機器operatorへ引き継がれる。
入力のJSON parse失敗、契約違反、manifest構造不備でもCLIはexit code 2を返し、
`status="unknown"`のreportを可能な限り出力する。
出力Evidenceは`execution_context="host"`で、`PhysicalEvidence.supports_authoritative_pass()`
は常に`False`である。

## FW書き込みと機能測定の取り込み

`FunctionalRunRecord`へESP-IDF版、toolchain版、project commit、build成果物、4種類の
生ログ、測定機器、期待条件、時刻を宣言し、次のCLIで決定論的に取り込む。

```bash
uv run python scripts/ingest_functional_run.py \
  --run fixtures/functional/valid/run.json \
  --logs-dir fixtures/functional/valid/logs \
  --evidence-dir out/functional-evidence \
  --report out/functional-report.json
```

CLIは宣言された全ファイルのSHA-256を実体へ先に照合し、`idf.py build`相当の
`ESP-IDF v...`、`Project build complete.`、`.bin`サイズ行、`esptool.py`相当の
`Chip is ...`、書き込み行と`Hash of data verified.`行の件数、`Hard resetting`完了、
LED captureの時系列・周波数・duty、`I (12345) gd1: temp=25.31C rh=48.20%`形式の
serial logの温湿度・周期を独立parserで検査する。buildの版行やflashの必須行が無い、
形式不正、parse不能、ファイル読取不能は`unknown`、版不一致、chip不一致、verify数不足、
値域外、周期外れは`fail`となる。全checkがpassなら全体もpass、unknownが1件でもあれば
全体unknown、それ以外のfailは全体failとする。4件すべてがpassしたときだけexit code 0、
それ以外はexit code 2でreportを出力する。

reportの入力hashはrecordと参照ファイルの実体hashから決定し、Evidenceの時刻はrecordの
宣言時刻から導出する。同一入力は同一report・Evidenceを生成する。生成Evidenceは
`measurement_class="measured"`かつ`execution_context="host"`であり、決定論的ゲートの
authoritative合格へ昇格しない。

## 測定結果の入力反映proposal

5.1〜5.3の実機Evidenceを、明示的な反映policyと現行のgraph／rationaleへ照合し、
入力更新の候補だけを生成する。入力ファイル、policy、Evidence、rationaleは変更せず、
proposalを入力へ自動適用しない。

```bash
uv run python scripts/propose_input_feedback.py \
  --graph fixtures/golden-design-1/graph.json \
  --rationale fixtures/golden-design-1/rationale.json \
  --policy fixtures/feedback/policy.json \
  --evidence fixtures/feedback/valid/led_frequency.json \
  --evidence fixtures/feedback/valid/matched_artifact_count.json \
  --proposal out/input-feedback-proposal.json
```

policyはgraph id、revision、measurement name、対象node／属性、`set_value`または
`reconfirm`、許容差、decision kindを宣言する。stale／virtual／invalid Evidence、
未分類属性、対象不在、measurement不在、重複rule id、graph／revision不一致は
fail-closedとなり、CLIはtracebackを出さずexit code 2と`status="unknown"`のproposalを
可能な限り出力する。正常なproposal生成はexit code 0であり、`rationale_required`が
残っていても人のレビューが必要なため、自動適用可能を意味しない。

適用を行う場合は人または別の明示的工程が入力graphを更新し、
`validate_applied_feedback`でproposalに宣言されたnode／属性以外の差分がないことを
検査する。提案生成と適用後検証はいずれも入力を書き換えない。

## Role prompt manifest

role別promptは`plugins/acd/agents/acd-*.md`から`PromptSection`へ読み込まれ、
資材bytesと抽出本文のhashを`plugins/acd/agents/prompt-manifest.json`へ固定する。
manifestの整合性は次で確認する。

```bash
uv run python scripts/verify_agent_prompts.py --check
```

`--check`はagent資材とmanifestを一切書き換えない。資材の欠落、parse失敗、hash drift、
manifest不正はfail-closedとなり、reportを標準出力へ出してexit code 2を返す。
drift reportの`unregistered_roles`は資材に存在するがmanifestへ未登録のrole、
`missing_roles`はmanifestにあるが資材から欠落したroleを表す。
manifestを現在の資材から決定論的に生成する場合だけ`--write`を使う。

```bash
uv run python scripts/verify_agent_prompts.py --write
```

## Model routing policy

主agent、judge、condenserのmodel、SDK `usage_id`、profile識別子は
`plugins/acd/model-policy.json`で宣言する。この資材は秘密情報を持たず、整合性は次で
確認する。

```bash
uv run python scripts/verify_model_policy.py --check
```

`--check`はpolicyを書き換えず、parse失敗、`unknown`、canonical hash不一致、
role不整合はreportを標準出力へ出してexit code 2を返す。現在のpolicyを書き出す場合だけ
`--write`を使う。routing観測は非EvidenceのL2/L3 metadataであり、合否判定には使わない。
`model-policy.json`のmodel識別子は運用側が差し替える宣言例であり、ACDが記載された
vendor modelを既定採用するものではない。コード側でこの資材を暗黙に読み込むことはなく、
呼び出し側がpolicyを明示的に渡した場合だけroutingへ適用される。

## Agent settings・profile・credential

role別のprofile名、参照するLLM profile名、credentialのSecretRegistry参照名は
`plugins/acd/agent-settings.json`で宣言する。この資材は秘密情報を持たず、credentialは
参照名だけを保持して値を保存しない。整合性は次で確認する。

```bash
uv run python scripts/verify_agent_settings.py --check
```

`--check`は資材を書き換えず、parse失敗、`unknown`設定、canonical hash不一致、
`model-policy.json`とのprofile drift、allowlist外のcredential参照名は
`status="unknown"`のreportを標準出力へ出してexit code 2を返す。現在の資材へcanonical
hashを固定する場合だけ`--write`を使う。profileはSDKの`OpenHandsAgentProfile`として
検証し、credential参照名がprofile側へ混入した場合も拒否する。settings報告は
`pass_evidence=false`固定の非EvidenceなL3観測であり、合否判定には使わない。
`build_acd_conversation`へ`agent_settings`を明示的に渡した場合だけ、routing profileを
この資材から導出し、driftとallowlist違反でfail-closedに停止する。

## Observation store

metrics、stats、goal結果、routing観測のL3 metadataはSDK `FileStore`を経由して保存する。
Evidenceと設計入力の保存経路は対象外であり、FileStoreへ移譲しない。

既存の`Path`引数を使うwriterは、Pathの親ディレクトリをrootとする`LocalFileStore`を
内部で使用する。`FileStore`を明示する場合のpathはstore rootからの相対pathだけを許可し、
空path、絶対path、`..`によるroot脱出、rootを準備できない場合はfail-closedで拒否する。
payloadは`pass_evidence=false`固定の型付き観測だけを受け付ける。

## 永続memoryとevent view

`.openhands/memory/MEMORY.md`の永続memoryは既定で無効であり、
`build_acd_conversation(enable_persistent_memory=True)`を明示した場合だけSDKの
`load_memory`経路で読み込む。memory本文は保存せず、観測はindex path、文字数、
context hashだけを`pass_evidence=false`固定で記録する。allowlist対象のsecret値が
memoryへ混入した場合、読込失敗、index不在はfail-closedで停止する。

event viewは原EventLogと照合する表示専用のprojectionであり、表示するeventごとに
event id、event種別、内容hashだけを記録する。整合性は次で確認する。

```bash
uv run python scripts/verify_context_view.py --check
```

`--check`は資材を書き換えず、canonical hash不一致、EventLog不一致、EventLogに存在しない
view entry、EventLog読込失敗は`status="unknown"`のreportを標準出力へ出してexit code 2を
返す。tracked projectionを再生成する場合だけ`--write`を使う。memory観測とview projectionは
gate criticのEvidence経路で明示的に拒否し、合否判定には使わない。

## 依存・版・破壊的変更の記録

依存、submodule、外部ツールを更新した場合は、使用API、既定値、破壊的変更、
採否を本節へ追記する。現行の基準は次のとおりである。

- SDKは`vendor/software-agent-sdk`のv1.42.1、commit
  `167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497`に固定する。更新前にpinned checkoutの
  API、上流release tag、CHANGELOGまたは一次リリース情報を確認する。
- Python依存は`pyproject.toml`とlockを正とし、既定値・公開API・破壊的変更を確認して
  `docs/openhands-sdk-capabilities.json`の採否へ反映する。Markdown表は
  `scripts/verify_sdk_capabilities.py`で生成し、採否enumと代表APIの検査を通す。
- KiCad CLI、Java、FreeRouting等の外部ツールは`command -v`と
  `uv run python scripts/probe_tools.py`で版と能力を記録する。版不明、未実行、
  出力不整合はゲートを緩めずfail-closedとする。
- SDKのdev workspace経路からDockerWorkspaceへ移行する際はimage digest、Dockerfile、外部ツール版を同時に記録し、
  ホスト実行の結果を合格側Evidenceへ昇格しない。

版と能力は次で記録する。

```bash
uv run python scripts/probe_tools.py
```

Docker workspace経路（ゲート実行の正）:

```bash
SERVER_REF="$(uv run python scripts/print_locked_image.py --entry acd-server)"
docker pull "$SERVER_REF"
uv run python scripts/run_in_workspace.py --image "$SERVER_REF"
```

server imageがlockに未設定、image digestを解決できない、または経路がunknownの場合、
runnerはコマンドを実行せず非ゼロ終了する。
runnerは`ACD_CONTAINER_IMAGE_DIGEST`と`ACD_IN_CONTAINER`をcontainerへforwardする。
hostのToolEnvelopeは`execution_context="host"`、containerのToolEnvelopeは型付き
`container_image_digest`を持つ。`evidence/`へ昇格するCLIは
`supports_authoritative_pass()`を要求する。

外部ツールが無い、版が不明、または出力を独立再読込できない場合、pipelineは
fail-closedで停止する。ゲートの仕様とprobeの責務は[`gates.md`](gates.md)を参照する。

## plugin

OpenHands SDKから`plugins/acd`をpluginとして読み込む。pluginには8 Skill、5
AgentDefinition、`/acd:gates` command、SDK ToolDefinition、hooksが含まれる。
決定論的なACD入口は`acd.openhands.tools.definitions`の`register_acd_tools()`からSDKへ登録する。
Conversationの安全設定は`EnsembleSecurityAnalyzer`、`ConfirmRisky`、allowlist付き
`SecretRegistry`、ローカルSkill loader、`StuckDetector`を使用する。ACD analyzerと
Pattern analyzerのensembleは具体的riskの最大値を採用し、全て`UNKNOWN`なら
`UNKNOWN`、`propagate_unknown=True`なら任意の`UNKNOWN`を伝播する。これらはL2であり、
hostの参考実行をauthoritative Evidenceへ変えることはない。

Skill loaderはpinned SDKの
`load_skills_from_dir(skill_dir: str | Path) -> tuple[dict[str, Skill], dict[str, Skill], dict[str, Skill]]`
を使う。SDKは個別エラーを警告して継続する実装だが、ACD wrapperは各`SKILL.md`を
SDK `Skill.load()`で事前検証し、ロード数も照合して壊れた・欠落した資材をfail-closedにする。
public/user/marketplace自動読み込みは無効である。pinned SDKの`SecretValue`注釈には
callableの説明もあるが、実装の`_wrap_secret()`は`str | SecretSource`以外を拒否する。
そのためACDは環境変数をlazy `SecretSource`でラップする。secretの値はログ、
ToolEnvelope、Evidenceへ出さず、SDK registryのmaskingだけを出力境界に使う。

Goal loopはSDK `GoalController`をACD側のdriverから再利用する。SIGINTは
`LocalConversation.interrupt()`へ結線し、goalの中断結果は`status="interrupted"`として
記録する。`goal_result`と`conversation_stats`は`pass_evidence=false`の観測成果物であり、
judgeのcomplete評決や統計値を合否へ使わない。

lane並列は`tool_concurrency_limit`で設定し、既定値は1（直列）とする。2以上を指定する
場合は、ACD toolの`declared_resources()`が返す資源keyを経由して共有入力・出力を
直列化する。資源宣言やpath解決に失敗したtoolは宣言不能としてtool単位のmutexへ
fail-closedに倒す。task/delegateはhook付きAgentDefinitionに限定し、sub-agentの結果を
Evidenceへ昇格しない。workflowは任意scriptがhook境界を外れるため不採用（将来再検討）とする。

外部利用者が配布版を読み込む場合は、branch名ではなく不変refを指定する。
commit SHAは40桁で、release tagは`v<semver>`形式にする。

```python
from acd.openhands.distribution.plugin import acd_plugin_source

plugin = acd_plugin_source("v1.2.3")
```

`ref=None`、branch名、短縮SHA、空文字、不正なtagはfail-closedで拒否される。
開発checkoutでは`build_acd_conversation()`の既定local pathを使用できる。

## トラブル時

- `uv sync`が失敗する場合はsubmoduleが初期化されているか確認する。
- 外部ツールが見つからない場合は`probe_tools.py`の結果を確認する。
- graphやfixtureが不正な場合は入力を修正し、エラーを成功扱いにしない。
- 秘密情報をログ、fixture、graph、commitへ書かない。
