# 運用・インストール

## 前提

- Linux環境
- Python 3.12以上
- `uv`
- KiCad CLI
- JavaとFreeRouting
- Docker（ゲート実行の正）

OpenHands Software Agent SDKは`vendor/software-agent-sdk`のsubmodule v1.44.1
（commit `9d143aac35c2dcec9cbb046ff9f35ac5eb072f6a`）をworkspace sourceとして使用する。
agent-serverはACDの対象外であり、採用する場合は新規ADRで受入条件を定義する。実行形は
`LocalConversation`とdigest固定server imageを使う`DockerWorkspace` runnerを基点とする。
host経路はprovisional専用であり、authoritative Evidenceを生成しない。

## fab profile registry

利用可能なfab profileは[`../profiles/fab-profile-registry.json`](../profiles/fab-profile-registry.json)
で管理する。registryの各項目はprofile ID、相対パス、fab名、process名を持ち、参照先の
profile本体にも同じID・metadataが必要である。新しいprofileを追加するときは、一次情報を
`sources`へ記録したprofile JSONを作成し、registryへ登録してから、ID一致、path実在、
fab・process metadata一致を検証する。出所のないcapability値を追加してはならない。

基板pipelineとsilkscreen resolverのprofile解決順序は次のとおり。

1. `--fab-profile`が指定された場合は明示パスを使用する。
2. `--fab-profile-id`が指定された場合は、そのIDをregistryで解決する。
3. どちらも無い場合はgraphの`fab.order_intent.fab_profile`をIDとしてregistryで解決する。

例:

```bash
uv run python scripts/run_gd1_pipeline.py --fab-profile-id jlcpcb-fr4-2l-1oz
uv run python scripts/resolve_gd1_silkscreen.py --fab-profile-id jlcpcb-fr4-2l-1oz
```

未知ID、path欠落、profile本体とのID不一致、registry metadata不一致はfail-closedで停止
する。明示パスを使う場合もgraphのprofile IDとの一致検査は省略しない。

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

`vendor/software-agent-sdk`がv1.44.1のcommitを指していることを確認する。

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

#### plugin更新時のキャッシュ確認

同じrepositoryを一度installした環境では、初回install時に指定したbranch以外の
リファレンスを指定してもキャッシュ済みのcommitがinstallされることを実機で確認した。
branch名でも40桁commit SHAでもgit URL形式でも同じであり、GUIは警告を出さない。

原因はSDKのキャッシュ実装（`openhands.sdk.git.cached_repo`）にある。キャッシュ先は
source URLのsha256だけで決まり（`get_cache_path`）、plugin manifestのversionは参照されない。
そのため`plugin.json`のversionを上げてもキャッシュは再利用される。キャッシュは
`git clone --depth 1 --branch <初回ref>`で作られるため`remote.origin.fetch`が
そのbranchだけを指し、更新時の`git fetch origin`では他のbranchやcommitを取得できない。
`_update_repository`はcheckout失敗を警告だけで飲み込み（`Using cached version.`）、
古いtreeをそのままinstallする。したがって初回に指定したbranchの先端を追う更新は成功し、
別branchや任意commitへの切り替えはキャッシュを消さない限り成功しない。

install直後にplugin詳細のリファレンスを`git ls-remote`の結果と照合し、
不一致であれば次を実行してからinstallし直す。

```bash
rm -rf ~/.openhands/plugins/installed/acd
rm -rf ~/.openhands/cache/extensions/acd-agent-*
```

削除後はOpenHandsを再起動する。リファレンスが一致しないまま動作確認へ進むと、
古い資材の挙動を新しい変更の観測結果として誤って扱う。

運用上は、リファレンスを省略するかbranch名を指定して`main`でinstallしておく。この場合の
更新は「更新」ボタンだけで済み、`update`が`ref=None`で再fetchして`origin/main`へ
resetするため`main`の先端に追従する。作業branchや特定commitで検証したい場合だけ、
上記のキャッシュ削除を伴うinstallし直しが必要になる。

この追従は実機で確認した。キャッシュ削除後にbranch名`main`でinstallし、その後`main`が
進んだ状態で「更新」を押すと、`POST /api/plugins/installed/acd/refresh`が200を返し、
plugin詳細のリファレンスが`git ls-remote origin refs/heads/main`と40桁一致する新しい
commitへ移り、再読込後も保持された。以前観測した「更新」のHTTP 500と「追加」のHTTP 409は
再現しなかった。500は完全SHA指定でinstallしたキャッシュ（detached HEAD相当）に限られる
可能性が高いが、その再現条件は未確認である。500が出た場合はキャッシュ削除からの
installし直しへ倒す。

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
   未解決シルクの候補評価を個別に実行する場合は、Skill scriptへworker数を明示できる。

   ```bash
   uv run --script plugins/acd/skills/acd-silkscreen-placement/scripts/silkscreen_search.py \
     --input silkscreen-input.json \
     --output silkscreen-output.json \
     --workers 4
   ```

   `--workers`の既定値は`min(os.cpu_count() or 1, 4)`であり、`--workers 1`はpoolを
   作らず完全逐次になる。text単位の候補数前パスと、1 text内のrotation×x-column列を
   共有context bundle付きchunkへまとめてProcessPoolExecutorで評価し、結果はチャンク内・
   チャンク間とも宣言順に戻す。main passは
   `dynamic_silk`が後続textの障害物になるため逐次である。worker数によって候補、
   rejection、fail-closed結果、output JSONのbyte列、hash、Evidence、provenance、
   summaryは変化しない。SkillはACD本体からimportせず、常にsubprocess境界で実行する。
   2コアVMのhost provisionalでは、同一の未解決6 text入力に対するSkill直接実行が
   `--workers 1`で49.075秒、`--workers 2`で29.245秒、`--workers 4`で29.722秒となり、
   各output JSON（63,900,205 bytes）はbyte一致した。
   `placement_search.py`はwarm状態で1.44秒（interpreter起動込み）、実処理がサブ秒
   だったため、今回の並列化対象に含めていない。
   基板pipelineの独立したPython stageは既定のCPU数（最大4）を使って実行する。筐体pipelineは
   `--pipeline-workers N`でworker数を指定でき、既定は`--pipeline-workers 1`（逐次）である。
   `--pipeline-workers N`を明示すればCAD stageの並列実行をopt-inできる。
   筐体pipelineでは、rationale／lane抽出／筐体投影を逐次実行した後、機械ゲートと
   shell・lid・assemblyのartifact測定を独立stageとして実行する。ゲート後の断面・干渉
   visual projectionも独立stageである。`--pipeline-workers N`はこれらのOCP/build123d
   処理を、pipeline全体で再利用するspawn contextの`ProcessPoolExecutor`で実行し、
   結果を宣言順またはprojection ID順に戻す。runner生成直後にworker数分のCAD module warm-up jobを
   Manager由来のBarrierで待ち合わせるため、逐次のrationale／lane抽出／筐体投影とOCP importを重ねられる。
   Linuxの既定forkで
   OCP状態を継承すると停止するため、CAD経路だけspawnを明示し、基板pipelineの既定contextは
   変更しない。warm-upのimport失敗やtimeoutは最適化の失敗として警告し、判定を変えずに
   通常経路を続行する。artifact測定とvisual projectionはこのrunnerへsubmitし、nested poolを作らない。
   筐体候補探索の`--jobs N`は候補fixtureと出力先を分離するが、既定runnerでは
   `pipeline-workers=1`のCAD経路をプロセス内lockで直列化し、OCP/build123dのnested並列と
   oversubscriptionを避ける。カスタムrunnerで内部CAD並列を有効にする場合は、候補側の`--jobs 1`
   を使い、共有native状態を同時に扱わない。
   逐次確認やデバッグには次を使う。

   ```bash
   uv run python scripts/run_gd1_enclosure_pipeline.py \
     --out out/gd1-enclosure \
     --pipeline-workers 1
   ```

   2コアVMで同一fixtureをhost実行した測定では、筐体pipelineのwall clockは
   `--pipeline-workers 1`で`8.309`秒、`--pipeline-workers 4`で`26.492`秒だった。
   4 workerのspawnと`build123d` warm-upだけを分離測定すると、runner生成は`0.001`秒、
   warm-up待ちは`4.870`秒（1 workerあたりの測定値）、shutdownは`0.915`秒だった。warm-upは逐次の
   rationale／lane抽出／筐体投影と重ねられるが、2コア環境ではCAD stageの並列処理と4 workerの
   CPU競合が支配的で、このfixtureでは再利用しても並列短縮を確認できなかった。そのため筐体
   経路の既定を逐次にし、CAD stage実処理がworker起動コストを上回る大規模設計や多コア環境では
   `--pipeline-workers N`を明示して並列化する。host実行はprovisionalでauthoritative Evidenceの
   合否根拠には使わない。
   GD1の基板・筐体・pytest subsetをまとめて検証する場合は、resolverのfixture書き換えを
   barrierとして先に完了させるlane orchestratorを使う。

   ```bash
   uv run python scripts/run_design_lanes.py
   uv run python scripts/run_design_lanes.py --jobs 1
   uv run python scripts/run_design_lanes.py --list
   ```

   `--jobs`の既定値は`min(os.cpu_count() or 1, 4)`である。`--jobs 1`はresolver、
   基板lane、筐体lane、FW lane、pytest subsetを宣言順に実行し、最初の失敗で停止する。
   それより大きい値ではresolverを単独実行した後、基板lane（`out/gd1`）、筐体lane
   （`out/gd1-enclosure`）、FW lane（`out/gd1-fw`）、pytest subsetを並列実行し、
   出力は宣言順に戻して失敗をすべて報告する。`--list`は各commandとbarrier属性をJSONで
   表示する。全実行のL3観測は`out/timing-record.json`へ保存し、各laneの直接実行も
   lane別`timing-record.json`を出力する。
   基板のDSN exportとFreeRouting SES生成物は、明示した`--cache-dir`へ入力hash単位で
   保存できる。例えば途中失敗後の再開は次のように実行する。

   ```bash
   uv run python scripts/run_design_lanes.py --resume --cache-dir out/.stage-cache
   ```

   `--resume`は有効な入力hash一致の生成物だけを復元し、判定、Evidence、timingを復元
   しない。cache hitでもDSN／SESのparse、routing connectivity、DRC、Gerber、その他の
   L1 gateは必ず再実行し、Evidenceも新規生成する。破損またはhash不一致のentryは
   無視して再生成する。cache reportはL3観測であり、合否authorityではない。
   `container-gates` jobも、digest固定imageのDockerWorkspace内で`uv sync && uv run
   python scripts/run_design_lanes.py`を実行し、完了後にhost側でauthoritative Evidenceを
   検証する。CPL／BOM chainは逐次のままだが、E-4のDSN／SES stage cacheは
   `--cache-dir`または`--resume`で明示的に利用できる。
   host provisionalでのlane全体の測定は、基板laneが`freerouting` executable不在で
   fail-closedとなったため完了していない。失敗までのwall clockは`--jobs 1`が
   15.902秒、既定並列が29.331秒であり、成功時の短縮比較には使わない。外部ツールを
   含むauthoritativeな測定はdigest固定imageのCI `container-gates`で行い、短縮しない
   場合もその実測値を記録する。
   並列実行のhash差分を逐次2回と比較するintegration testは既定ではskipされる。
   ロック済みcontainerで`ACD_PIPELINE_PARALLEL_TEST=1`、`kicad-cli`、`freerouting`を
   揃えた場合だけ有効になる。逐次A／逐次B／並列Cの3回を実行し、A/BとA/Cで
   差分となるhashキー集合が一致することを確認する。`refill_zones`が再生成する
   KiCad UUIDによる既存のrun-to-run差分を許容し、完全なhash一致は要求しない。
   会話から実行する場合も、ゲートの段階、使用したfixture、入力・出力Evidenceのパスを
   応答へ明記させる。

   なお、2コアVMのhost provisional測定では、GD1 fixtureのsilkscreenがpinnedのため
   通常のresolverから探索Skillは呼ばれず、resolve全体は12.0秒、Skill呼び出しは0回
   だった。未解決化した6 textでは、探索Skillの1回の呼び出しが47.77秒、resolve全体が
   63.29秒で、純Pythonの候補評価が支配項になった。worker=1/2/4の比較結果は同一入力
   のoutput byte列、候補・rejection順序、判定、fail-closed結果とともにhost
   provisionalとして記録し、authoritativeな判断はdigest固定containerのCIで行う。

### Local GUI APIの認証とトンネル越しの検証

Local GUIをSSHポート転送だけで参照する構成では、リモートでのコマンド実行はできず、
`http://127.0.0.1:8000/`のGUI操作だけが到達経路である。この状態で`/api/conversations`
などのAPIへ直接curlすると、GUIが保持する認証情報を伴わないため
`{"detail":"Unauthorized"}`が返る。トンネルの疎通確認とAPIの認証は別問題であり、
ルートへのHTTP 200をAPI到達性の根拠にしない。

APIをscriptから叩く場合は、GUIのブラウザsessionが実際に送信している認証情報を取得して
同じ資格情報で呼び出す。

1. ブラウザで`http://127.0.0.1:8000/`を開き、GUIへログインした状態にする。
2. devtoolsのNetworkタブでGUI自身が発行している`/api/...`リクエストを1件選び、
   その`Authorization`ヘッダまたはsession cookieを確認する。
3. 同じヘッダ・cookieを付けてcurlを実行し、認証が通ることを確認する。

   ```bash
   curl -sS -H "Authorization: $OPENHANDS_LOCAL_TOKEN" http://127.0.0.1:8000/api/conversations
   ```

4. 取得した値は環境変数などで一時的に保持し、リポジトリ、PR本文、コミット、ログ、
   実行記録へ書かない。持ち出す実行記録は`scripts/export_execution_records.py`の
   秘匿化経路を通す。

認証情報を取得できない場合、API経路での自動化は「未実行」であり、GUI操作による確認結果を
API検証の合格根拠へ昇格させない。未検証はfail-closedとして扱う。

### 発注前最終ゲートの再実行とcheck-only

発注前の判定には7.2の`OrderTotalResult` JSON、policy、判定時刻を渡す。
`OrderTotalResult`のJSONは`OrderTotalDocument`の契約として読み込み、coreの変換関数が
内訳hashを再計算して内容との一致を検証する。
既存Evidenceだけを検査する場合は、再実行しないことを明示するcheck-only経路を使う。

```bash
uv run python scripts/pre_order_gate.py \
  --order-total out/order-total.json \
  --evidence out/gd1/evidence-electrical.json \
  --evidence out/gd1-enclosure/evidence-mechanical.json \
  --evaluated-at 2026-08-14T00:00:00Z \
  --check-only
```

両laneを発注直前に再実行する場合だけ、digestを解決できるserver imageを明示する。
この経路は`DockerWorkspace`を通り、`docker/image-digests.json`のdigest lockを使う。

```bash
uv run python scripts/pre_order_gate.py \
  --order-total out/order-total.json \
  --evaluated-at 2026-08-14T00:00:00Z \
  --rerun-authoritative \
  --image ghcr.io/uist1idrju3i/acd-server@sha256:b5afc5daadf801f62d7bcb3f8229fe417e0e658b7ab1a660bf737f105f18c968
```

`--local-provisional`はこのCLIの選択肢ではなく、hostの`LocalWorkspace`結果は
authoritative Evidenceにならない。再実行しないcheck-onlyで現行revisionの両lane Evidenceが
見つからない場合も、ゲート未実行として停止する。このCLIはjournal書込み、送信、実発注を
行わない。

### quoteからorder-totalを生成する

見積record、発注範囲、基板製造プロファイルから、既存の決定論的集計を呼び出して
`OrderTotalDocument`を生成できる。各quote recordは対象revision、supplier、
counterparty、通貨、必須category、明細合計を満たし、OrderScopeとFabProfileDocument
のID・revision・通貨契約に一致していなければならない。`--quote-record`は複数回
指定する。

```bash
uv run python scripts/aggregate_order_total.py \
  --quote-record fixtures/contracts/valid/quote-order.json \
  --order-scope fixtures/contracts/valid/order-scope.json \
  --fab-profile profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json \
  --target-revision r12 \
  --evaluated-at 2026-08-14T00:00:00Z \
  --output out/order-total.json
```

集計が成功したら、生成されたJSONを既存の発注前ゲートへ渡す。parse失敗、missing、
revision・supplier・counterparty・通貨・category不一致、明細合計やbreakdown hashの
不一致はすべて非ゼロ終了で停止する。集計結果はL1合格権限やauthoritative Evidence
ではなく、発注可否は既存のpre-order gateだけが判定する。

### VibeBB設計loopの実行

会話から要件をgraphへ反映し、設計反復と発注可否を一つの決定論的loopで進める入口は
`/acd:vibebb-loop`である。要件差分は`--requirement`、新規fixtureのspecは
`--fixture-spec`でloopへ渡せる。単独の`acd_compile_requirement_change`と
`acd_build_design_fixture`も引き続き利用できる。loop本体は次の順序をコード側で固定する。

1. fixture生成（`--fixture-spec`指定時のみ）
2. 要件compile（`--requirement`指定時のみ）
3. 要件入口整合検査（常時）
4. silkscreen resolver（基板pipelineの前提となるbarrier）
5. 基板pipeline、筐体pipeline、FW pipeline（Skill CLI subprocess）
6. order-total集計（quote record、OrderScope、FabProfileDocument指定時のみ）
7. 発注可否のpre-order gate

コマンド実装へ順序と前提を移したため、各scriptをshellから個別に呼び出す必要はない。
出力先とartifact prefixはgraph_idから導出し、`golden-design-1`だけは既存の`gd1`
互換名を維持する。各段の失敗は後続段を実行せず、失敗段IDとそれまでの段結果を含む
`ok: false`、`fail_closed: true`のJSONと非ゼロ終了を返す。不在tool、ESP-IDFやQEMUの
検証不能、parse失敗、unknownも同じ扱いであり、「問題なし」へ置き換えない。

```bash
uv run python scripts/run_design_loop.py \
  --fixture fixtures/golden-design-1 \
  --out-root out \
  --order-total out/order-total.json \
  --policy plugins/acd/hooks/order-policy.json \
  --requirement out/requirement-update.json \
  --evaluated-at 2026-08-14T00:00:00Z
```

既存のorder-total documentを使う場合は`--order-total`を指定する。quoteからloop内で
生成する場合は、次のaggregation modeを使う。二つのmodeを同時に指定することはできず、
fab profileを含む全入力が揃わない場合もfail-closedになる。

```bash
uv run python scripts/run_design_loop.py \
  --fixture fixtures/golden-design-1 \
  --out-root out \
  --quote-record fixtures/contracts/valid/quote-order.json \
  --order-scope fixtures/contracts/valid/order-scope.json \
  --fab-profile profiles/jlcpcb/fab-profile-jlcpcb-fr4-2l-1oz.json \
  --policy plugins/acd/hooks/order-policy.json \
  --evaluated-at 2026-08-14T00:00:00Z
```

この場合、lane planから導出した`out/order-total.json`へ集計結果を書き、直後の
order-readinessがそのdocumentを読み込む。集計はL2の決定論的処理であり、合格判定や
authoritative Evidenceを生成しない。quote取得と実発注はこのloopの責務ではない。

### 契約registryとparts catalogの追加

トポロジtemplateは`contracts/topology-templates.json`へ追加する。`template_id`と
registryの`block_id`を対応させ、部品要求の`kind`、`value`、`package`、padのnet参照を
宣言する。共通railはdocument-levelの`shared_nets`へ宣言し、その他はtemplate-local
netとする。Pydantic検証はtemplate内の重複refdes／local net、shared netとの衝突、
未知block、未宣言net、template欠落をfail-closedにする。template間の重複は代替block
のため許可し、padは自templateのlocal netまたはshared netだけを参照できる。

部品entryは次のCLIでdry-run検証してからcatalogへ原子的に追加する。

```bash
uv run python scripts/register_part_catalog_entry.py \
  --entry fixtures/contracts/valid/part-entry.json \
  --catalog contracts/parts-catalog.json \
  --dry-run
uv run python scripts/register_part_catalog_entry.py \
  --entry fixtures/contracts/valid/part-entry.json \
  --catalog contracts/parts-catalog.json
```

entryには`part_number`、`kind`、`value`、`package`と、symbol／footprintの名前、
file、source、source_ref、`sha256:<64 hex>`を必須で宣言する。CLIは両fileを実際に
読み、宣言SHA-256と一致しない場合やfileが存在しない場合は非ゼロ終了でfail-closedに
する。既存`part_number`または同じ選択key（`kind`＋`value`＋`package`）との衝突は、
`select_part`の曖昧な結果を増やすため拒否する。既存entryのテキスト表現は保持し、
新規entryだけを追記する。dry-runはcatalog hashの変更予定を報告するが書き込まない。

同じ操作は会話経路の`acd_register_parts_catalog_entry`でも行える。これは入力
catalog／entryを資源宣言し、登録結果とcanonical catalog hashを観測するだけで、
L1合格やauthoritative Evidenceを生成しない。USB-Cを持たないfixtureや電池給電
fixtureの回帰例は、既存predicateだけを使う。充電・保護回路の妥当性はこの経路で
判定せず、規範的な電池契約はロードマップ16.2／16.3を待つ。

新規fixtureをspecから生成する場合は、`--fixture-spec`を追加する。fixtureに既存の
`graph.json`がある場合は上書きせずfail-closedで停止する。

cache・resume・lane並列を有効にする場合は、次のように指定する。

```bash
uv run python scripts/run_design_loop.py \
  --fixture fixtures/golden-design-1 \
  --out-root out \
  --order-total out/order-total.json \
  --policy plugins/acd/hooks/order-policy.json \
  --cache-dir out/.stage-cache \
  --resume \
  --jobs 3 \
  --evaluated-at 2026-08-14T00:00:00Z
```

`--resume`で`--cache-dir`を省略すると`out-root/.stage-cache`を使う。cacheは
入力hashが一致する決定論的なDSN／SES生成物だけを再利用し、判定、verdict、
Evidenceは毎回再実行する。`--jobs 1`はsilkscreen barrier後のlaneを逐次実行し、
CLIの既定値は`min(os.cpu_count() or 1, 3)`である。tool経路の`jobs`既定値は1で、
並列化は明示指定時だけ有効になる。timing recordとcache reportはL3観測であり、
記録失敗は結果へ理由を記録するが、合否を変更しない。

要件入口整合検査は`requirements.json`を必須入力としてparseし、graph ID、revision、
constrains node、node kind、graph-anchored requirement nodeのtext、functional block
registryを既存validatorで検査する。missing、parse失敗、不一致、unknownや未回答の
要件は推測せずfail-closedとし、silkscreen以降を実行しない。この常時stageはL1ゲートや
authoritative Evidenceの代替ではなく、合否を変更しないL3観測として分類しない。

board-pipelineのfail-closed却下後に候補探索をloopへ自動連結する場合は、探索を明示的に
有効化し、候補予算とround上限を正整数で指定する。

```bash
uv run python scripts/run_design_loop.py \
  --fixture fixtures/golden-design-1 \
  --out-root out \
  --order-total out/order-total.json \
  --policy plugins/acd/hooks/order-policy.json \
  --explore-board \
  --max-exploration-candidates 3 \
  --max-exploration-rounds 2 \
  --evaluated-at 2026-08-14T00:00:00Z
```

自動探索はboard-pipelineの却下後、全laneのjoin後に直列で実行する。候補が見つかった場合も
graphの妥当性、graph IDとrevisionの探索前との一致、正規化content hashの変化、
探索reportの`target_revision`とgraph revisionの一致を検査してからsilkscreenを含む
loop全体を再実行する。enclosure、FW、silkscreenの失敗では自動探索せず、探索の
`candidate_found` reportもL1合格Evidenceではない。`exhausted`、`stopped`、不正report、
graph検証失敗、
round上限到達は元のboard失敗理由を保持してfail-closedで停止する。自動連結を使わない場合や
診断次元を指定して手動評価する場合は`acd_explore_board_candidates`を使用する。

`acd_run_design_loop`も同じin-code orchestratorを呼び出す。gate、閾値、期待値、
revision一致、authoritative Evidenceの規則は変更しない。Skill出力、AI review、host上の
provisional実行、loopの成功観測は合格Evidenceではなく、実発注もこの入口では行わない。

### side-effect journalの読み出し

7.4のjournalは1行1entryのJSON Linesで、書込みCLIは提供しない。7.3の許可recordを使った
事前予定とproviderの事後結果が揃った発注だけを、次の読み取り専用CLIで再構成する。

```bash
uv run python scripts/side_effect_journal.py \
  --journal out/side-effect-journal.jsonl \
  --idempotency-key order-20260814
```

CLIはentry契約、entry自身のhash、直前entryとのhash連鎖、冪等key、事前・事後の許可hash、
製造data package hash、revision、時刻を検証する。事後結果が欠落したjournal、改変・削除・
並べ替えられた行、存在しない・読み出し不能なjournalは非ゼロ終了で停止する。この層はjournalの記録と
再構成だけを行い、送信・発注・新しい発注許可は作らない。

### 自働発注dry-run

7.5のCLIはdry-runが既定であり、7.3の許可record、journal、製造data package hash、
宛先、対象revision、allowlist済みcredential参照名、実行時刻を受け取る。

```bash
uv run python scripts/order_execution.py \
  --permit out/pre-order-gate.json \
  --journal out/side-effect-journal.jsonl \
  --idempotency-key order-20260814 \
  --package-hash sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  --destination supplier.example \
  --target-revision r1 \
  --credential-reference ACD_API_KEY \
  --occurred-at 2026-08-14T00:00:00Z \
  --command echo dry-run
```

出力payloadはpackage hash、宛先、対象revision、総額、許可hashだけから作られ、
secret値、Evidence内容、時刻を含めない。journalには`dry_run`のpre/post組を記録するが、
これは実発注完了として扱えない。`--real`は明示provider設定とcredential環境変数が無ければ
fail-closedで停止し、設定が揃っても実supplierへ送信せずprovider境界で非ゼロ終了する。
submission record（`record_class=L3`、`pass_evidence=false`、`content_sha256`）とjournalの
pre/post rejected組を残す。confirmation policyのskip、必須hook不在、
credential参照名のallowlist外、上限額override、冪等key再送、provider scriptの非ゼロ終了、
post記録失敗は停止条件である。実providerへの送信は本マイルストーンの範囲外であり、
credentialの値を引数・journal・ログ・stdoutへ渡してはならない。`--command`は必須で、
command未実行をsuccessとして記録する経路はない。command形式不正やsecret値の混入は
事前予定の追記前に拒否し、providerの`failure`とは区別する。

4. 出力ファイル名とFWプロジェクト名は入力graphの`graph_id`から導出する。GD1の
   `graph_id`は`golden-design-1`であり、prefixを固定名で仮定しない。`graph_id`から
   安全な名前を導出できない場合はfail-closedで停止する。EvidenceのclaimのsubjectはgraphのnodeIDを
   使い、固定名を埋め込まない。実行済みのGD1基板pipelineでは、回路図
   `out/gd1/golden-design-1.kicad_sch`、routed board
   `out/gd1/routed/golden-design-1.kicad_pcb`、Gerberの
   `out/gd1/gerbers/`、drillの`out/gd1/gerbers/golden-design-1.drl`、製造出力の
   `out/gd1/fab/`、電気Evidenceの`out/gd1/evidence-electrical.json`が生成される。
   シルク解決を個別に実行した場合は、回路図を含む中間成果物が
   `out/gd1-silkscreen-resolve/iteration-1/`に生成される。

   JLCPCBへ投入するファイルは、製造出力ディレクトリ内の
   `out/gd1/fab/golden-design-1-bom-jlcpcb.csv`と
   `out/gd1/fab/golden-design-1-cpl-jlcpcb.csv`の2つだけである。
   `out/gd1/golden-design-1.bom.csv`はDesign Graph由来の内部BOM投影であり、非実装部品も含み得るため、
   発注用ファイルとして投入してはならない。
   CPL回転の独立検証には、リポジトリ内の
   `evidence/gd1-cpl-orientation/`を使用する。このディレクトリ自体が無い場合は
   製造データ生成をfail-closedで停止し、個別部品のEvidence欠落は
   `order-readiness.json`の回転unknownとして記録する。

   基板pipelineは、ゲートの診断専用Evidenceを`out/gd1/gate-evidence/`へ常時保存する。
   `design-predicates.json`は全述語（`pass`、`fail`、`unknown`、`not_applicable`）の
   評価段階、measurement、subject、remediationを含む。measurementには
   `quantity`があり、例えば`pad_distance_mm`や`qualifying_capacitor_count`として
   `measured`の意味を明示する。remediationの`dimensions_source`はregistry由来か
   未知かを示し、未知の場合は変更次元を推測しない。`routing-connectivity.json`は
   SESから求めたnet単位のwire／via成分、連結成分ペアごとの代表的な未接続pad対、
   wireへ接続しないpadを含み、
   routerの`convergence_state`と観測結果の不一致も記録する。GND島のstitch via検査で
   欠落が発生した場合は`gnd-stitch-vias.json`へ構造化座標またはエラー理由を保存する。
   さらに`out/gd1/design-freedom-declaration.json`へ探索対象の設計自由度とregistry整合の
   hash-linked declarationを、`out/gd1/stitch-candidate-report.json`へ初回およびrefill
   反復の候補・除外理由・GND島未被覆測定を保存する。
   これらのファイルは`sort_keys`付きJSON、固定座標丸め、canonical JSON SHA-256で
   決定論的に生成される。SES欠落・parse失敗などで観測できない場合も
   `status: "unavailable"`と機械可読な理由を記録する。

   これらはL3の診断Evidenceであり、L1の合否権限を持たない。したがって、routerが
   `converged`と報告してconnectivity観測が未接続を示しても合否は変えず、逆にEvidenceの
   生成失敗で既存の合格を不合格へ変えない。既存の`assert_converged`、閾値、停止位置、
   authoritative Evidenceのcontainer実行条件は変更しない。

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
   uv run --with cmake==3.31.6 --script plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py \
     --fixture fixtures/golden-design-1 --out out/gd1-fw
   ```

   実行済みの出力は、FWプロジェクト
   `out/gd1-fw/acd_golden_design_1_fw/`、ビルド済みFW
   `out/gd1-fw/acd_golden_design_1_fw/build/acd_golden_design_1_fw.bin`、統合flash image
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

package refは契約ファイルと一緒に更新する。手動更新は、対象commitがローカルにあり
`HEAD`の祖先であることを確認したうえで、次を実行する。

```bash
uv run python scripts/update_skill_package_ref.py --ref <40桁commit SHA>
uv run python scripts/verify_skill_package_ref.py --check
```

updaterは`acd-package-ref.txt`、`acd`をimportする全Skill scriptと
`scripts/probe_pinned_acd_graph.py`のPEP 723ヘッダー、生成済み
`acd-package-contract.json`を同時に更新する。checkerはrefのlocal commit解決・祖先性、
schema tree、API surface、fixture kind coverage、script hashと契約driftを
fail-closedで検査する。既存の`verify_skill_metadata.py`は従来のmetadata契約を検査し、
checkerは`verify_all.py`のstandard stageにも含まれる。refはリリース後のcommitまたは
semver tagを指定し、scriptとref fileはpluginのリリースと一緒に更新する。
この自己解決経路はローカルSkill実行だけを扱い、ゲート実行の正であるdigest固定imageと
authoritative Evidenceの契約は変更しない。

`acd`本体のschemaまたはAPIを変更した場合、package refを更新しない限りSkill scriptは
古い`acd`で動き続ける。refが実装より古い状態では、FW pipelineがGD1 fixtureに対しても
`15 validation errors for DesignGraph`のように失敗することがある。既存の
`scripts/verify_skill_metadata.py`と`/acd:doctor`の`_package_ref_check`はref書式と
script metadataの一致を検査するが、ref自体の陳腐化は検出しない。詳細な観測と改善提案は
[`vibebb-gap-analysis.md`](vibebb-gap-analysis.md)のH節を参照する。
mainへのschema・API・fixture・Skill変更後は
`.github/workflows/update-skill-package-ref.yml`がcheckerを実行し、skew時だけ
merge commitへ再固定するPRを作成する。一致時は何もしないため、auto-PRのmergeによる
再trigger loopは発生しない。ただし`GITHUB_TOKEN`で作成したPRはGitHub ActionsのCIを
起動しないため、必要ならPRを更新する主体または手動runでCIを起動する。

locked tools imageは同じPEP 723 metadataを持つ全acd-importing scriptの依存をbuild時に
解決し、GD1のpinned-acd probeを実行してからofflineで再実行する。したがってimage内の
FW Skill laneは実行時のgit・ネットワークへ依存しない。imageの事前導入内容と容量差は
[`docker/README.md`](../docker/README.md)に記録する。

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

### リリース手順

リリース前に、対象タグの作成・push権限とrulesetを確認する。タグ作成はrulesetで
制限されることがあり、`GH013`で拒否された場合は権限を持つ担当者へ作成を依頼する。
リリースノートは変更のハイライトと実行例へのリンクだけを記載し、Release assetsは
添付しない。

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
hostの参考実行を明示する場合だけ、SDK公開入口の`LocalWorkspace`を使う
`--local-provisional`を指定する。この経路はprovisional結果だけを返し、
`ACD_IN_CONTAINER`または`ACD_CONTAINER_IMAGE_DIGEST`が設定された環境では起動せず停止する。

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

`publish-acd-tools.yml`はjob summaryへindex digestを記録し、同じdigest、image metadata、
workflow runを更新PRへ渡す。`publish-acd-server.yml`もderived digestとtagを同じ経路で
更新する。未publishのentryやplaceholder digestは作成せず、lockに記録されていないimageを
pullするfallbackも禁止する。lock fileと`docker/README.md`はpublish trigger
（`publish-acd-tools.yml`の`paths`）から除外しており、digest更新PR自体が再publishを起こして
lockと`latest`が食い違い続けることを防ぐ。build入力を変更した場合だけtools publishが走り、
成功後にserver publishが`workflow_run`で連鎖する。lockの検証は次のように行う。

```bash
TOOLS_REF="$(uv run python scripts/pull_locked_image.py --entry acd-tools)"
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

`publish-acd-server.yml`は`workflow_dispatch`またはtools publish成功後の`workflow_run`で起動し、
lockから解決したACD tools digestをbaseにしてSDKの`build.py`でagent-server imageをbuildし、
GHCRへpublishする。publish後はderived digestとtagをlock更新PRへ記録する。
現行のbase tools digestは、Semeru／OpenJ9 JREとbuild時生成SCCを同梱した
`sha256:901ffd495c4876d3c02ff9c3303c67a6ee0d2c54b39460bb370a2c8260bb602c`である。
lockに記録済みのserver image
`sha256:b5afc5daadf801f62d7bcb3f8229fe417e0e658b7ab1a660bf737f105f18c968`は、
現行base tools digestからderiveした値である。
toolsを再同梱した場合は`publish-acd-server.yml`を再`workflow_dispatch`してderived digestを
更新する。手動起動はlockからbase toolsを解決するため、この更新はlockへ新しいtools digestを
記録した後に行う。tools publish成功による`workflow_run`連鎖では、lock更新PRがmerge前で
lockが1世代前を指すため、`acd-tools:latest`の現digestを解決してbaseにする。digestが
解決できない場合はfail-closedで停止し、baseはjob summaryへ記録する。
baseとderivedは独立に記録し、
toolsとserverのdigestは同一とは扱わず、CIとrunnerはlock済みserver digestをpullして実行する。

`build.py`はimage tagを`SDK_SHA`→`GITHUB_SHA`→`git rev-parse HEAD`の優先順で決めるため、
`workflow_run`起動では`GITHUB_SHA`がworkflow定義側のcommitを指し、checkoutした
`workflow_run.head_sha`とtagが食い違う。2026-08-30のrun 33305827733と33305891477では
buildは成功したがalias stepが存在しないtagを参照し、
`ghcr.io/uist1idrju3i/acd-server:<head_sha>-latest-source: not found`で失敗して
server digest lock更新PRが生成されなかった。以後は`git rev-parse HEAD`で解決した
`SERVER_SHA`をbuild step（`SDK_SHA`）とalias／tag解決step双方へ渡し、
publishしたsourceとtagを一致させる。

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

### FreeRoutingの資源宣言

FreeRouting 2.3.0の`--help`と同梱公式文書
（`command_line_arguments.md`および`docs/settings.md`）では、`-mt`を省略した場合の
既定値が論理CPU数−1である。GD1基板pipelineはこの暗黙継承を採用し、`-mt`を
commandへ含めない（[`adr/ADR-0045-openj9-freerouting-runtime.md`](adr/ADR-0045-openj9-freerouting-runtime.md)）。
`scripts/run_gd1_pipeline.py --freerouting-threads N`で正のintを明示すれば従来どおり
固定できる。以前は`-mt 1`を常に明示していたが、`-mt 0/1/2/4`のSES SHA-256が一致する
実測に基づき、多コアVPSでCPUを使えるよう暗黙継承へ変更した。

Evidenceの機械非依存性は、実行環境のCPU数を記録しないことで保つ。暗黙継承時の
ToolEnvelopeの`measurement_conditions`は固定文字列
`"implicit router threads (cpu_count-1)"`であり、`routing_config.freerouting_threads`は
JSON `null`として残る。したがって`config_hash`は実行機のCPU数で変動しない。明示値を
渡した場合は従来どおり`max {N} router threads`を記録する。

routerの`-mp` pass budgetの単一既定値は`DEFAULT_ROUTER_MAX_PASSES = 100`である。
これはlock済み`acd-tools` container
（`ghcr.io/uist1idrju3i/acd-tools@sha256:d29bf726396b507014319ea8ba7c1e53200a37eb49930dfde6add8d8c69f396a`）
内のGD1 fixture測定を根拠とする。旧CLI既定の99999と明示100を比較した結果、
両方のSES SHA-256は
`808ee9658df69b3f6aeddb827caf885d6592dd0afa6e8a2b01579bce715897d9`で一致し、
`convergence_state=converged`、`PIPELINE PASSED`、layout
`identity_hash=sha256:6882a9acd3b8cc0c7ffb18072e2376923e7a22a5fb36bfc788746d793667923c`
も一致した。wall timeは旧既定93秒、100 passes 92秒だった。このため既定値を100へ
統一し、凍結済みexample内の既存`max 99999 passes`記録は変更しない。

外部ツールのtimeout既定値は`DEFAULT_TOOL_TIMEOUT_S = 600.0`秒である。timeout時は
`timed_out`を独立した収束状態としてenvelopeへ記録する。これは`unknown`とは異なるが、
どちらも`converged`ではないため合格を支えず、部分出力も成果物として扱わない。

2コアVM上のdigest固定image
`ghcr.io/uist1idrju3i/acd-tools@sha256:044a024c9f56e7ab9f60eef34431bd52a1d3dedb1861a2764263a0200f20e9a1`
で、`examples/sensor-node-20260820/board/gd1.dsn`を`-mp 10`で実行した測定では、
`-mt 0/1/2/4`のSES SHA-256がすべて
`45d620d0d86c05e860724fb1e0df49c6cda34b00c9dc921b552d2a0f071ddff0`で一致した。
wall timeはそれぞれ93.5/93.0/92.5秒で、差は測定誤差の範囲だった。Optimization stageは
約73.05秒の経過時間に対し約70.01 CPU秒であり、この規模のrouterは実質single-threaded
である。`-mt 4`を2コアcontainerへ渡すと2へcapするwarningが出る。この出力非依存性は
GD1 DSN・FreeRouting 2.3.0の事例であり、他の入力や版でSES SHA-256が一致しない場合は
`-mt`固定へ戻す。`feature_flags.multi_threading`の既定値はfalseで、実験的機能は
有効化しない。

### FreeRouting実行JREとJVMオプション

acd-tools imageのFreeRouting実行JREはIBM Semeru Open JRE 26.0.2.10
（Eclipse OpenJ9 0.61.0、2026-08-18公開）である。tarballはversionとSHA-256
（`0de86d8ed8d1a764cfa5839bef0283c562f30fd902a01ec406f01143e5bec1aa`）でpinし、
`/opt/jre`へ展開する。build時に`java -version`がEclipse OpenJ9とSemeru 26.0.2.10を
示すことを検査する。aptの`openjdk-26-jre-headless`（HotSpot）は同梱しない。

以前のcontainer-gatesでは、acd-server imageが`DISPLAY=:1`を設定している一方でX serverを
提供しないため、FreeRoutingがversion bannerを出力する前にAWTを初期化し、
`java.awt.AWTError: Can't connect to X11 window server using ':1' as the value of the DISPLAY
variable`で終了した。結果として`FreeroutingRunner.version()`が
`router version banner unparsable (fail-closed)`を返し、routing前に停止した。この事象は
mainのcontainer-gates（run
<https://github.com/uist1idrju3i/acd-agent/actions/runs/33302135950>、head
`a73a27335d4d7a03bba5f2030c5bea96fbd2db67`）で発生した。Semeru／OpenJ9
0.60.0と0.61.0の両imageで再現し、旧Ubuntu OpenJDK 26.0.1 imageでは再現しなかった。
FreeRouting jarと`/tmp/freerouting`の状態は比較imageで同一だった。wrapperは
`-Djava.awt.headless=true`を固定し、build時にも`DISPLAY=:99`でversion bannerが残ることを
検査することで、ambientなDISPLAYに依存しない。

wrapper [`docker/freerouting`](../docker/freerouting)が宣言する既定は次のとおりで、
env欄に記載したものだけenvで上書きできる。

| option | 既定 | env |
|--------|------|-----|
| 最大heap | `-Xmx2g` | `FREEROUTING_MAX_HEAP` |
| JVM tuning | `-Xtune:footprint` | `FREEROUTING_JVM_TUNING` |
| AWT | `-Djava.awt.headless=true` | なし |
| SCC | `-Xshareclasses:name=fr_scc,cacheDir=/opt/scc,readonly` | `FREEROUTING_SCC_NAME`／`FREEROUTING_SCC_DIR` |
| container検出 | `-XX:+UseContainerSupport` | なし |
| GCスレッド自動調整 | `-XX:+AdaptiveGCThreading` | なし |
| active processor count | 宣言しない | `FREEROUTING_ACTIVE_PROCESSORS` |

shared class cache（SCC）とAOTはimage build時に生成し、runtimeはreadonlyで再利用する。
コンテナではSCCが既定で無効化されるため明示有効化が必要で、build時生成にすることで
container再作成でもcacheが消えない。`nonfatal`は付けない。SCC不在時は`readonly`／
`readonly,fatal`のいずれでも`JVMSHRC226E`／`JVMSHRC336E`／`JVMSHRC337E`／
`JVMSHRC840E`で起動失敗し、終了statusが非0になるため、追加optionなしでfail-closedを
満たす。`-Xsoftmx`は設定しない。2コア環境では`-Xsoftmx1g`併用が僅かに速いが
（1.6秒、2%）、より大きな基板でheapを`-Xmx`まで伸ばせなくなる副作用を避ける。
JVMのCPU認識は制限しない。既定で1へ制限するとGC／JITとFreeRoutingのCPU検出まで
制限するため、`-XX:ActiveProcessorCount`は`FREEROUTING_ACTIVE_PROCESSORS`が明示された
場合だけ付与する。

2コアVM、digest固定image
`ghcr.io/uist1idrju3i/acd-tools@sha256:35313c1ddd1954122ad3f173ca557993e6ca0dc892c3f052521f83c8e4c5e36c`
へSemeru JREをmountし、同じGD1 DSNを`-mp 10`・`-mt`暗黙で実行した3回反復の平均は
次のとおりである。全構成でSES SHA-256は
`45d620d0d86c05e860724fb1e0df49c6cda34b00c9dc921b552d2a0f071ddff0`に一致した。

| 構成 | wall（平均/最小〜最大） | peak RSS | peak heap |
|------|------------------------|----------|-----------|
| HotSpot `-Xmx2g` `-mt 1`（baseline） | 98.3秒 / 96.4〜99.6 | 1139.9 MB | 425.9 MB |
| OpenJ9 `gencon` + SCC | 91.1秒 / 87.7〜95.9 | 622.9 MB | 330.1 MB |
| OpenJ9 `-Xtune:virtualized` + SCC | 94.2秒 / 88.5〜101.6 | 566.7 MB | 317.2 MB |
| OpenJ9 `-Xtune:footprint` + SCC | 77.3秒 / 76.1〜78.7 | 357.9 MB | 148.3 MB |
| OpenJ9 `-Xtune:footprint -Xsoftmx1g` + SCC | 75.7秒 / 74.6〜76.7 | 324.0 MB | 110.1 MB |

単発測定（n=1）では`gencon`（SCC無し）98.5秒、`-Xquickstart`+SCC 113.6秒、
`optthruput`+SCC 107.6秒、`balanced -Xnuma:none`+SCC 113.4秒／RSS 1333.6 MB、
`-Xtune:throughput`+SCC 104.0秒であり、いずれも`-Xtune:footprint`より遅い。出荷する
wrapperと同一のoption列での確認実行は76.2秒／RSS 344.9 MB／peak heap 99.9 MBで、
unrecognized option警告は無く、SES hashも一致した。baseline比でwallは約22%短縮、
peak RSSは約70%削減である。

多コア・大RAMのVPS相当環境は未測定である。この節の測定はすべて2コア・7GBのVMで
取得した。`-Xtune:footprint`はメモリ使用量最小化を優先する設定であるため、高性能VPSへ
移行する場合は`FREEROUTING_JVM_TUNING`の再評価が必要になり得る。CPU数・RAMの増加には
`-mt`暗黙継承、`UseContainerSupport`、`AdaptiveGCThreading`、`FREEROUTING_MAX_HEAP`で
追従する。

SDK `DockerWorkspace`にはCPU／memory resource
fieldがなく、現在のworkspace境界からcontainer資源を宣言できないため、
`tool_concurrency_limit`の既定1と、資源を宣言できない場合はSDK mutexで直列化する
既存契約を維持する。wrapper変更はimage変更なので、mainの`docker/**`変更で
`publish-acd-tools.yml`が実行される。build contextを決める`.dockerignore`も
同じtriggerに含める。SCC warm-upが`examples/sensor-node-20260820/board/gd1.dsn`を
COPYするため、`.dockerignore`はこの1ファイルだけを例外として残す。
過去の手動運用ではpublish job summaryのGHCR digestを確認してから
`docker/image-digests.json`へ転記していた。lockのdigestを推測・手書きしてはならない。
旧JRE移行のpublish済みimageについては、lockの両entryに`java`ツール版文字列として
`openjdk 26.0.2 2026-07-21 (IBM Semeru Runtime Open Edition 26.0.2.0, Eclipse OpenJ9 0.60.0)`を
記録している。この文字列はpublish済みimageをdigest指定でpullし、`java -version`の出力から
転記した値であり、他のツール版は旧JRE移行で変化しなかった。今回更新後のlock値は
publish後に`docker/image-digests.json`へ別変更として転記する。

toolchain更新（Semeru 26.0.2.10／OpenJ9 0.61.0、uv 0.12.7、ESP-IDF v6.1、KiCad 10.0.6、
CMake／Ninja同梱）後にpublishしたacd-tools image
`sha256:6bb87bd720117b6179f35da36e3fe417d35d6da243459be2da8e337883462930`については、
digest指定でpullして各ツールの版出力を実測し、lockの`acd_tools.tools`へ転記した。
`cmake`と`ninja`はこのimageから同梱されたためkeyを追加した。`java`は既存entryと同じ
1行形式へ整形しており、実測の生出力は
`openjdk version "26.0.2.1" 2026-08-18` / `IBM Semeru Runtime Open Edition 26.0.2.10 (build 26.0.2.1+1)` /
`Eclipse OpenJ9 VM 26.0.2.10 (build 26.0.2.1+1-openj9-0.61.0, ...)`である。
`acd_server.tools`はlockが指すdigestが更新前のimageのままなので変更しない。
過去のserver imageでは、publishとlock更新が済んだ時点で同じ手順で実測し、
別変更として転記していた。
現在のpublish workflowは、tools／serverのpublish完了後にdigest固定imageを
`scripts/measure_image_tools.py`で実測し、そのJSONを同じdigest lock更新PRへ渡す。
実測コマンドの失敗、版出力のparse失敗、digest非固定refはfail-closedで扱い、
tools欄を不完全なままlock PRを作成しない。過去の手動転記記録はhistoryとして残すが、
新しいpublishでは手動転記は不要である。

digest lock更新PRは作成直後にauto-mergeを有効化する。repositoryでauto-mergeが
利用できない場合はworkflow summaryへ手動mergeが必要であることを記録する。
ただし、PRのCI、特にlock済みserver imageを実行する`container-gates`は引き続き
合否を決めるゲートであり、auto-mergeは検証を置き換えない。

### FW pipelineのhost実行とToolEnvelopeの注記

FW pipelineをhostで参考実行する場合は、ESP-IDFとQEMUに加えて
`libslirp0`およびSDL2系共有ライブラリが必要である。QEMUをtarball等から配置した場合は、
`qemu-system-riscv32`のあるディレクトリをPATHへ追加してから実行し、次で解決できることを
確認する。ESP-IDF v6.1、Espressif QEMU 9.2.2、`libslirp0`、SDL2系ライブラリ、ccache、
CJKフォント、CMake 4.2.3、Ninja 1.13.2はacd-tools imageへ同梱しており、
container経路ではhost側の準備を必要としない（`IDF_PATH`、`IDF_TOOLS_PATH`、
`IDF_PYTHON_ENV_PATH`、`CCACHE_DIR`、`IDF_CCACHE_ENABLE`はimageで宣言する）。
以前のimage（ESP-IDF v6.0.2のimageを含む）はCMakeとNinjaのいずれも同梱しておらず、
container内のFW laneは`To use idf.py, either the 'ninja' or 'GNU make' build tool must be
available in the PATH`で失敗していた。同梱内容と検証項目は
[`docker/README.md`](../docker/README.md)を参照する。

hostのprovisional経路では、従来どおり`run_design_lanes.py`が
`uv run --with cmake==3.31.6`でCMakeを注入する。これはhost側の実行環境を補うためのもので、
container経路の自己完結したCMake／Ninja同梱を置き換えない。

KiCad公式PPAが10.0.5を配布しなくなり、次の環境では10.0.6だけが解決されるため、
GD1の現行library pinを10.0.5から10.0.6へ更新した。公式libraryのうち
`Device.kicad_sym`、`Regulator_Linear.kicad_sym`、`Switch.kicad_sym`の3ファイルの内容が
変わっていたため、pinは実ファイルをSHA-256計算して更新した。参照した15ファイルは
ホストとlocked `acd-server` containerの双方でhashを計算し、全件一致を確認している。
fixture全体の再生成は、mainから存在するsilkscreen resolverの不整合
（`mechanical.silk_text.dev_board`が有効な配置を得られないfail-closedエラー）のため
実行できなかった。この不具合はKiCad pin更新とは独立しており、歴史的な配置や生成物を
書き換えず、今回の変更ではgraphのlibrary pin属性だけを実ファイルから決定論的に更新した。

```bash
command -v qemu-system-riscv32
```

host経路はprovisional専用であり、合格側Evidenceの生成には使わない。authoritativeな
ゲート実行は、引き続きlock済みdigest固定server imageを`DockerWorkspace`で実行する。
実行例と生成物の構成は[`examples/sensor-node-20260820/`](../examples/sensor-node-20260820/)を
参照する。

`kicad-cli`のERC/DRCは違反件数に応じたexit codeを返すため、違反が検出された場合に
非ゼロとなりうる。したがってToolEnvelopeの`exit_code`をToolEnvelopeの`status`と
混同してはならず、exit codeだけを成功・失敗の根拠にしない。ERC/DRCのstatusは、
独立したparserと決定論的ゲートが検査した違反件数・種類、およびEvidence契約に従って
解釈する。exit codeの意味が不明な外部ツールはunknownとして扱い、既存のfail-closed
境界を維持する。

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
8.3ではGD1の各laneで、必須ゲート通過後にlane固有の視覚投影を
`out_dir/visual/`へ既定生成する（電気laneは回路図ビューと宣言銅層ごとの層別レイアウト
ビューを`visual-projections-electrical.json`へ、機械laneは断面・干渉ビューを
`visual-projections-mechanical.json`へL3観測として
記録する）。投影集合のidentity hashは`generated_at`を再現性の対象から除外するため、
同一入力・同一renderer版の再実行で時刻以外の内容を同一性として比較できる。機械laneでは
authoritativeな`enclosure-assembly.step`を`build123d`で断面・干渉SVGへ投影する。
断面のXY offsetは`wall_thickness_mm + standoff_height_mm / 2`をMechanicalLaneから
決定論的に導出して記録し、キャビティ床とcoplanarになる位置は使用しない。断面は
宣言したXY平面とこのoffsetを記録し、
干渉体積は機械ゲートの`measured_max_interference_volume_mm3`を転記してビューの
干渉領域有無と突合する。干渉領域がない場合はSVGへ空layerを後付けせず、
projection recordの`interference_region_present=false`と体積0で観測する。8.5では電気laneに限り、
同一revisionの
`ElectricalLane`／`BoardModel`とSVGを決定論的に照合し、
`visual-crosscheck-electrical.json`へL3観測として記録する。この照合は8.3のSVG投影生成直後、
`hashes.json`生成前に既定実行される。
8.3の層導出はgraphで宣言された`BoardView.layers`の層数をKiCadの銅層名へ決定論的に
対応させる。現在の対応表は2層（`F.Cu`／`B.Cu`）と4層（`F.Cu`／`In1.Cu`／`In2.Cu`／`B.Cu`）
に限り、0層、1層、奇数層、その他の未対応層数はfail-closedとする。
8.4では必要時に8.3の正規化前SVGをCairoSVG 2.9.0で幅1600pxへラスタライズし、
8.3の`visual-projections-electrical.json`を変更せず、
`visual-projections-electrical-raster.json`へPNG派生集合を書き出す。acd-tools imageには
libcairo2を固定し、container内でPNG派生可能であることをraster testで検証済みである。
PNG派生はAI受け渡し時のon-demand経路であり、合否権限を持たない投影を既定成果物へ増やさないため、
pipelineの既定出力には含めない。lock済みacd-server imageもCairo追加後のtools imageから
deriveしており、container経路でPNG派生できる。生成PNGのIHDRから
解像度を測定する。PNGは`png-identity-v1`（正規化なし、生PNG bytesのSHA-256）で記録し、
2回の生成hashが一致しない場合、入力SVGの正規化後hashがrecordと一致しない場合、または
CairoSVGのimport・版取得・libcairo依存が利用できない場合はfail-closedとする。
SDKへ渡す画像はworkspace内PNGだけをbase64の`data:image/png;base64,...` URLへ変換し、
HTTP(S)・`file:` URLは作成しない。`OH_INLINE_IMAGE_ALLOW_PRIVATE_HOSTS`がtruthyな環境では
画像経路を停止し、vision応答は`pass_evidence=false`のL3観測としてだけ保存する。

8.5の照合レポートは、投影集合のidentity hash、machine-readable入力の相対パスとhash、
投影集合全体の網羅性を記録するset item、投影ごとの照合項目、集約status、レビュー観点
チェックリスト、canonical hash、`generated_at`を記録する。set itemは投影recordへ複製しない。
identity hashは`generated_at`を除外するため、同一入力から同一の照合結果とチェック記録を
再生成できる。決定論的項目はSVGから直接読み取れる事実だけを`match`または`mismatch`とする。
SVGのwidth／height単位は`ElectricalLane.board.unit`と突き合わせ、KiCad SVGと対応付けられる
宣言単位は`mm`だけとする。viewBoxの原点・y軸は`ElectricalLane.board.origin`／`y_axis`と
突き合わせ、対応する宣言は`board_upper_left`／`down`だけとする。root寸法とviewBox寸法の
自己整合は確認するが、SVGのA4ページ範囲を基板実寸法と解釈しない。基板寸法はSVGから
決定論的に読めないため照合対象にしない。未対応の単位・原点・y軸宣言はfail-closedとする。
可読性、設計意図、注記の視認性、重なり・非表示要素による意味欠落、信号・電源系統の読み取り、
層別SVGの意味的な銅層identityは`observation_required`としてunknownのまま記録する。
unknownをmatchへ集約せず、mismatch・対象欠落・解析失敗・revision不一致はpipelineを停止する。
レポートは`pass_evidence=False`のL3観測であり、Evidence、fab claims、gate fields、
`hashes.json`、fab packageへ追加しない。

## 生成文書lane

`acd-product-docs` Skillは、Design Graph、記録済み視覚投影集合、生成済みFWピン投影
（`acd_pins.h`）から製品説明READMEと取扱説明書を決定論的に生成する。生成文書はL3観測
（提示物）であり、合否権限を持たず、投影を設計入力へ逆流させない。

```bash
uv run python plugins/acd/skills/acd-product-docs/scripts/generate_product_readme.py \
  --graph fixtures/golden-design-1/graph.json \
  --projections out/gd1/visual-projections-electrical.json \
                out/gd1/visual-projections-layout.json \
                out/gd1/visual-projections-system.json \
  --out-dir out/docs
uv run python plugins/acd/skills/acd-product-docs/scripts/generate_instruction_manual.py \
  --graph fixtures/golden-design-1/graph.json \
  --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
  --out-dir out/docs
```

出力先は`out/docs/`とし、`product-readme.md`と`instruction-manual.md`のほかに、
`<文書名>.provenance.json`へ入力の相対パスとcontent hash、template id、生成script
のhash、graph_id、対象revision、出力hash、生成時刻を記録する。記載値はすべて入力由来で、
推定値を書かない。文書本文に時刻を埋め込まないため、同一入力の再生成はbyte一致する。

不足・不整合はfail-closedとし、「問題なし」と解釈しない。契約違反のgraph、
対象revisionと異なる投影集合またはピン投影、`regeneration_check`が`reproduced`でない投影、
参照画像の欠落、投影集合の未宣言、`acd_pins.h`のmacro欠落は生成を停止する。
帰属表記は部品ごとのsymbol／footprintライブラリ出所と参照から生成し、
外部ライブラリのライセンス表示と帰属を保持する。

## 設計知識lane

`acd-design-knowledge` Skillは、Design Graph、設計根拠record、ゲート結果、Evidence、
生成文書、git履歴、会話ログを決定論的にindex化し、仕様、使い方、不具合対処、設計根拠、
経緯の質問へ出典付きで回答する。indexとtroubleshooting知識、回答、公開FAQはいずれも
`pass_evidence=false`のL3観測であり、合否権限を持たず、設計入力へ逆流させない。

```bash
uv run python plugins/acd/skills/acd-design-knowledge/scripts/build_knowledge_index.py \
  --graph fixtures/golden-design-1/graph.json \
  --rationale fixtures/golden-design-1/rationale.json \
  --documents out/docs \
  --evidence out/gd1 \
  --gate-results out/gd1 \
  --conversation-logs out/conversations \
  --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
  --audience internal \
  --out-dir out/knowledge
uv run python plugins/acd/skills/acd-design-knowledge/scripts/ask.py \
  --graph fixtures/golden-design-1/graph.json \
  --rationale fixtures/golden-design-1/rationale.json \
  --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
  --question "LEDが点滅しないときは何を確認するか"
uv run python plugins/acd/skills/acd-design-knowledge/scripts/generate_faq.py \
  --graph fixtures/golden-design-1/graph.json \
  --rationale fixtures/golden-design-1/rationale.json \
  --pins-header out/gd1-fw/acd_golden_design_1_fw/main/acd_pins.h \
  --out-dir out/docs
```

`build_knowledge_index.py`は`knowledge-index.json`と`troubleshooting-knowledge.json`を
出力し、source種別、相対参照、hash、状態を記録する。読めない、宣言されていない、
parseできないsourceは`unknown`として記録し、存在しないことを「問題なし」と解釈しない。
troubleshooting知識はgraphの電源系統とFWピン投影（`acd_pins.h`）から導出し、QAと
公開FAQで同じ導出結果を共有する。ピン投影が無い場合、該当項目は`unknown`のまま残す。

`ask.py`は回答できた場合に出典付きの根拠文を返して終了コード0、導出できない場合は
`unknown`と理由を返して終了コード2とする。推測で回答しない。経緯の質問はgit履歴、
commitごとのgraph revision、内部会話ログ、ECO recordを出典として引用する。

`--audience public`および`generate_faq.py`は会話ログをindexから除外し、除外した
source種別をprovenanceの`excluded_source_kinds`へ明記する。FAQは`out/docs/faq.md`と
`faq.md.provenance.json`へ出力し、本文へ時刻を埋め込まないため同一入力の再生成は
本文がbyte一致する。

## 検証

検証段階とコマンド列は`uv run python scripts/verify_all.py --list`で確認できる
`verify_all.py`を正とする。文書のみ、通常、フルの段階を次で実行する。

### 実行例の取り込み

実行例を取り込む場合は、成果物を所定のパスへ配置した後、対象Markdownを`git add`して
Git追跡対象に加えてから`uv run python scripts/verify_all.py --stage docs`を実行する。
`verify_docs.py`はgit追跡済みMarkdownだけを検査し、`examples/*/conversation/`配下の
会話ログなどbyte-exact生成artifactは検査対象外とする。人間が保守するREADME、report、
docsのMarkdownは引き続き検査対象であり、リンク、fence、見出し、用語の検査を弱めない。
実行例の取り込み時は、同一設計の再実行か新規設計かを設計入力と生成物で確認し、
その結果を記録する。判定基準と要件を変えた場合の設計動作の確認手順は
[`design-requirement-variation.md`](design-requirement-variation.md)を参照する。

```bash
uv run python scripts/verify_all.py --stage docs
uv run python scripts/verify_all.py --stage standard
uv run python scripts/verify_all.py --stage full
```

barrier付きコマンドは単独実行し、barrierのない連続コマンドを独立バッチとして並列実行
する。standardとfullの`uv sync`はbarrierとして先頭に置かれ、docs stageは文書検証の
3コマンドを環境同期なしで並列実行する。既定の並列度は
`min(os.cpu_count() or 1, 4)`で、`--jobs N`で上書きできる。`--jobs 1`はコマンドを宣言順に
逐次実行して最初の失敗で停止し、子プロセスの出力を直接流す（pytest自体の
`-n auto`は`--jobs`と独立に有効なまま）。`--jobs N`（N > 1）はバッチの開始行を
出してから起動済みコマンドを最後まで実行し、出力を宣言順に戻して失敗したコマンドを
すべて報告する。どちらも失敗時は非零終了する。コマンドとbarrier属性は
`uv run python scripts/verify_all.py --list`で機械可読に確認できる。

pytestは既定で`-n auto --dist loadgroup`を使うため、`uv run pytest`は自動worker数で
テストを実行する。単体デバッグなどで無効化する場合は`uv run pytest -n 0`を使う。
固定パス、cwd、環境変数、installed plugin storeの共有による衝突を避け、独立化できない
共有状態だけを`pytest.mark.xdist_group`で同一workerへ固定する。判定内容を緩めず、
並列・逐次の収集件数と正規化hashが一致することを検証する。

`full`には`pytest plugins`、silkscreen resolver、基板・筐体pipeline、外部ツールprobeを
含む。authoritative container gateはCI固有の`container-gates` jobで実行するため、
`verify_all.py`には含めない。

2コアVMで同一入力を測定した結果は、pytestの逐次（`-n 0`）195.13秒、
自動並列（`-n auto`）108.73秒だった。`verify_all.py --stage standard`
は`--jobs 1` 141.21秒、既定並列 126.66秒だった。
測定は各条件1回で、外部ツールを含まないstandard段階の比較である。

mainのCI run `32909530356`をbaselineとして、`verify`は262秒（うちStandard verification
222秒）、`skills`は102秒、`pinned-acd-probe`は28秒、`container-gates`は451秒
（locked agent-server imageのpull 178秒、決定論的gateの実行245秒）だった。
`.md`ファイルだけの変更では`changes` jobがcode変更なしと判定し、重い4 jobを
conditional skipして`docs-verify`だけを実行するfast pathを使う。skipされたjobは
conditional skipとして必須checkを満たすが、`container-gates`は通常の変更で引き続き
合否を決めるゲートである。

`container-gates`ではcheckout直後にlock済みserver imageのdigest固定refをbackgroundで
warm pullし、setup-uv、workspace sync、digest解決と重ね合わせる。その後のauthoritative
pullとdigest検証、決定論的gateの順序およびfail-closed挙動は変更しない。warm pullの
失敗は無視してauthoritative経路へ任せる。fast pathとwarm pullによる短縮幅は、merge後の
CI runを実測して別途記録する。

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

policy付き適用を行う場合は次を使う。whitelist外、bounds/tolerance外、graph／revision不一致、
malformed proposalは検証不能として停止する。`--dry-run`ではhashとL3 recordだけを生成し、
通常実行ではpolicyのinput pathsを一括stagingして失敗時に全ファイルをrollbackする。

```bash
uv run python scripts/apply_input_feedback.py \
  --proposal out/input-feedback-proposal.json \
  --policy fixtures/feedback/apply-policy.json \
  --repo-root . \
  --record out/input-feedback-application.json \
  --dry-run
```

見積取得は`QuoteProvider`境界を通るfixture providerを使用する。`scripts/fetch_quote.py`で
provider設定を選び、期限切れ・malformed・未知providerは検証不能として停止する。実supplier
adapterはこの境界へ追加する後続作業である。

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

- SDKは`vendor/software-agent-sdk`のv1.44.1、commit
  `9d143aac35c2dcec9cbb046ff9f35ac5eb072f6a`に固定する。更新前にpinned checkoutの
  API、上流release tag、CHANGELOGまたは一次リリース情報を確認する。
- v1.42.1からv1.43.1への更新では、Agent Pluginsのmanifest loaderとclosed
  `plugin.json` schema、structured task outcome preset、shell semanticsの
  defense-in-depth、LLM provider connection/runtime metadata、cleanup LLM profile、
  `AgentSettingsBase.from_persisted()`、profile validate endpointが追加された。
  ACDはagent-serverを引き続き非対象とし、structured outcome、shell semantics、
  provider/runtime metadata、cleanup profile、provider connectionsは採用しない。
  これらで既存のfail-closed hook/security policy、L1の決定論的判定、authoritative
  Evidenceの規則を置換・緩和しない。Agent Pluginsのmanifest loaderもSDKの公開追加
  surfaceとして記録するが、既存のACD plugin format採用範囲を拡大しない。
- 同更新で、resume時のclient tool再登録、Conversation errorのstructured event、
  active LLM profile解決、terminal executable prefix重複防止、browser-useの自動
  Chromium install削除、v1 skills migration修正が行われた。ACDの既存利用箇所では
  公開APIのimportとsignatureに互換性問題はなく、追加された既定動作は既存の安全境界を
  変更しない。
- v1.43.1からv1.44.1への更新では、別LLM profile`oracle`へ第二意見を照会する`ask_oracle`
  toolがtoolsへ追加され、structured builtin tool specのremote解決、`AsyncExecutor.close()`の
  上限時間、subscription LLMでのcondenser有効化、workspace git cloneのprovider host尊重、
  conversationごとのbrowser `user_data_dir`分離が修正された。ACDは`ask_oracle`を不採用とし、
  非決定論的な助言経路を合否・Evidenceへ関与させない。browserの`user_data_dir`分離は明示
  有効時のSingletonLock衝突を避ける既定改善であり、既存のL2探索補助の境界を変更しない。
- 同更新のagent-server側変更（ACP providerのbuild argとlayer分離、conversation単位の
  lifecycle lock、streaming deltaの配信範囲修正、crash recovery、canvas extension manifest、
  ACP agentへのworkspace project skills注入禁止）はACDの対象外であり、採用しない。
- Python依存は`pyproject.toml`とlockを正とし、既定値・公開API・破壊的変更を確認して
  `docs/openhands-sdk-capabilities.json`の採否へ反映する。Markdown表は
  `scripts/verify_sdk_capabilities.py`で生成し、採否enumと代表APIの検査を通す。
- KiCad CLI、Java、FreeRouting等の外部ツールは`command -v`と
  `uv run python scripts/probe_tools.py`で版と能力を記録する。版不明、未実行、
  出力不整合はゲートを緩めずfail-closedとする。
- SDKのdev workspace経路からDockerWorkspaceへ移行する際はimage digest、Dockerfile、外部ツール版を同時に記録し、
  ホスト実行の結果を合格側Evidenceへ昇格しない。
- container toolchainの今回更新では、Semeru 26.0.2.10（OpenJ9 0.61.0、新機能追加なし）、
  uv 0.12.7、ESP-IDF v6.1（GD1 FWが使うGPIO／I2C／FreeRTOS APIは破壊的変更の対象外）、
  KiCad 10.0.6（PPA追従、pinしない）、CMake 4.2.3、Ninja 1.13.2へ更新した。
  以前のimage（ESP-IDF v6.0.2のimageを含む）はCMakeとNinjaを欠き、
  `To use idf.py, either the 'ninja' or 'GNU make' build tool must be available in the PATH`
  でcontainer FW laneが失敗していたため、今回imageへ同梱した。host provisional経路は
  `uv run --with cmake==3.31.6`によるCMake注入を維持する。FreeRouting 2.3.0と
  QEMU 9.2.2は据え置きである。lock値`docker/image-digests.json`はpublish後に別変更で更新する。
- KiCad 10.0.5は公式PPAから配布されなくなったため、現行環境を10.0.6へ追従させた。
  公式libraryでは`Device.kicad_sym`、`Regulator_Linear.kicad_sym`、
  `Switch.kicad_sym`の3ファイルの内容が変わり、実ファイルから再計算したpinを
  `graph.json`とparts catalogへ反映した。ホストとlocked containerで参照15ファイルの
  hashは全件一致した。fixture generator全体はmain由来のsilkscreen resolver不整合で
  再生成できなかったため、今回の変更はlibrary pin属性に限定し、歴史的記録は変更していない。

版と能力は次で記録する。

```bash
uv run python scripts/probe_tools.py
```

Docker workspace経路（ゲート実行の正）:

```bash
SERVER_REF="$(uv run python scripts/pull_locked_image.py --entry acd-server \
  --record out/container/pull-acd-server.json)"
uv run python scripts/run_in_workspace.py --image "$SERVER_REF"
```

`scripts/pull_locked_image.py`はlock済みdigestのpull入口の正である。`docker/image-digests.json`の
lock entryだけを受け付け、`image@sha256:...`のimmutable referenceでpullし、pull後に
localのdigestがlock値と一致することを`docker image inspect`で確認する。全体timeout
（既定900s）、有限回のbackoff retry（既定3回）、docker版・attempt・timeout・取得時刻を含む
provenanceの`--record`出力を持つ。pull失敗、retry上限到達、digest不一致、docker CLI
timeout、lock未設定はいずれもexit=2でfail-closedとし、Evidenceを生成しない。

container実行のtimeout境界は`run_in_workspace.py`の引数で明示する。既定値は
`--health-check-timeout 300`、`--command-timeout 3600`、`--docker-cli-timeout 300`、
`--memory-limit 8g`、`--platform linux/amd64`である。ACDは`DockerWorkspace`のlifecycleが
呼ぶdocker CLI（`docker version`、`docker run`、`docker inspect`、`docker logs`、
`docker stop`）へ同じdocker CLI timeoutとmemory上限（`--memory`／`--memory-swap`）を与え、
`resolve_image_digest()`の`docker image inspect`にも明示timeoutを与える。container起動が
失敗した場合は観測したcontainerを`docker stop`で後始末し、停止できないcontainer IDを
エラーへ含める。`WorkspaceResult`は失敗種別（`timeout`、`transport`、`command`）を保持し、
runnerは失敗種別を出力して非ゼロ終了する。retryはdigest固定pullとfile downloadに限り、
gate実行とEvidence生成は再試行しない。

`--graph`で指定したDesign Graphから、未指定のcommandとdownload pathを導出する。
graphのmissing、parse failure、または不正な`graph_id`ではGD1へfallbackせず停止する。
commandを明示する場合もdownload path未指定なら同じgraph-derived defaultsを使うため、
graphを特定できない運用ではdownload pathを明示する。

生成物の既定pathとFW boot logはgraph_id由来であり、GD1 fixtureだけが互換値
（`out/gd1-*`および`ACD GD1 fw boot target_revision=%s`）を明示属性または
compatibility aliasで再現する。boot log messageのC string literal安全条件を含む
FW boot-log導出規則の規範は[`architecture.md`](architecture.md)に集約し、
coreとSkillは独立実装する。

imageへ同梱したACD本体・pipeline scripts・fixtureだけで実行する場合は`--source bundled`を
使う。この経路はリポジトリをマウントせず、image内`/opt/acd`のprebake済み環境で実行する。

```bash
uv run python scripts/run_in_workspace.py --image "$SERVER_REF" --source bundled \
  "uv run python scripts/run_gd1_enclosure_pipeline.py --out out/gd1-enclosure"
```

`--source bundled`は実行前に`/opt/acd`の`pyproject.toml`、`uv.lock`、`src/acd`、
`scripts`、`fixtures`、prebake済み`.venv`を検査し、欠落があればコマンドを実行せず停止する。
同梱資材を持つimageがpublishされてlockへ記録されるまで、既定は`--source mounted`のままとする。

server imageがlockに未設定、image digestを解決できない、または経路がunknownの場合、
runnerはコマンドを実行せず非ゼロ終了する。
runnerは`ACD_CONTAINER_IMAGE_DIGEST`と`ACD_IN_CONTAINER`をcontainerへforwardする。
hostのToolEnvelopeは`execution_context="host"`、containerのToolEnvelopeは型付き
`container_image_digest`を持つ。`evidence/`へ昇格するCLIは
`supports_authoritative_pass()`を要求する。

host provisional経路（合格側Evidenceへ昇格しない参考実行）:

```bash
uv run python scripts/run_in_workspace.py --local-provisional --repo "$PWD" \
  "uv run python scripts/run_gd1_pipeline.py --out out/gd1-host"
```

この経路は`LocalWorkspace(working_dir=...)`を使用し、結果はhost/provisional型で返す。
`--image`との併用、container markerまたはdigest環境変数がある状態は拒否する。

外部ツールが無い、版が不明、または出力を独立再読込できない場合、pipelineは
fail-closedで停止する。ゲートの仕様とprobeの責務は[`gates.md`](gates.md)を参照する。

## plugin

OpenHands SDKから`plugins/acd`をpluginとして読み込む。pluginには10 Skill、5
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

hook遮断と確認mode拒否はSDKの`UserRejectObservation`として現れる。振り返りのために
event列を直読しなくて済むよう、`run_acd_goal(..., rejection_summary_path=...)`は
goal終了時（中断時も含む）に遮断理由を自動集計し、
`acd.openhands.session.rejection_summary`が`hook_rejection_summary`成果物として書き出す。
集計は`source`（`hook`／`user`／`unknown`）、tool名、遮断理由でgroup化し、件数と
`action_id`を決定論的に並べる。pinned SDKのliteral外のsourceは落とさず`unknown`として
数え、遮断のあった実行が「遮断なし」に見えないようにする。要約は
`pass_evidence=false`のL3観測であり、遮断を解除せず、合否へ影響しない。

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

## graph単体検証の正規経路

graph単体の妥当性検証は`scripts/validate_graph.py`だけを正規入口とする。過去に案内された
`scripts/validate_design_graph.py`は存在せず、参照してはならない。

```bash
uv run python scripts/validate_graph.py --fixture fixtures/golden-design-1
```

この入口はgraphのparse、requirement documentの検証、rationale coverage、laneごとの
決定論的preflight（必須node・属性の宣言欠落集約）をまとめて実行する。parse失敗、
入力欠落、宣言欠落はすべてfail-closedであり、成功扱いにしない。preflightは診断であって
L1ゲート判定ではなく、検証成功は設計成功を意味しない。合否権限は引き続きlaneの決定論的
ゲートとrevision一致のauthoritative Evidenceだけが持つ。laneを限定する場合は`--lane`を
繰り返し指定する。

## laneのCLI引数

lane入口は`--fixture`（`graph.json`を含む設計入力ディレクトリ）と`--out`（lane出力先）に
統一する。`scripts/run_design_lanes.py --list`が出力する各laneコマンドは、そのまま単体
実行できる。

| 入口 | 用途 |
|---|---|
| `scripts/resolve_gd1_silkscreen.py` | シルク解決lane |
| `scripts/run_gd1_pipeline.py` | 基板lane |
| `scripts/run_gd1_enclosure_pipeline.py` | 筐体lane |
| `plugins/acd/skills/acd-firmware-esp32c3/scripts/run_fw_pipeline.py` | FW lane |
| `scripts/validate_graph.py` | graph単体検証 |

旧引数（`--graph`、`--graph-dir`、`--fixture-dir`、`--out-dir`、`--output`）は受け付けず、
置き換え先を示す明示エラーで停止する。`scripts/run_in_workspace.py`はlane入口ではなく
workspace実行wrapperであり、既定コマンドとEvidenceパスの導出に使うgraphファイルを
`--graph`で受け取る点が異なる。

## out-rootのhost／container分離

container実行のEvidenceは`out/container/`配下へdownloadし、host実行の`out/`と共有しない。
root実行containerとhost実行が同一out-rootを共用すると`Permission denied`が発生し、
設計起因のfail-closedと区別できなくなるためである。CIの`container-gates`は
`out/container/gd1/evidence-electrical.json`と
`out/container/gd1-enclosure/evidence-mechanical.json`を検証する。

`scripts/run_in_workspace.py`は失敗時に`failure classification`を出力する。`permission`と
`environment`は環境起因であり、ゲート判定が得られていない状態としてfail-closedに留まる。
`design`は設計起因の失敗、`unknown`は出力が無く分類できない失敗である。いずれも合格側へ
昇格しない。

## pipelineログの要約

`scripts/run_design_lanes.py`はJSON要約へ失敗コマンドのログ末尾だけを載せる。完全な
ログは`<out-root>/lane-logs/command-NN.log`へ書き出し、要約には省略行数と保存先を含める。
末尾行数は`--log-tail-lines`、完全なログの埋め込みは`--full-logs`で指定する。要約はL3観測
であり、コマンドの判定を変更しない。

## 実行記録の持ち出し

実機実行記録を外部公開する場合は、公開可能な最小集合だけを収集する入口を使う。

```bash
uv run python scripts/export_execution_records.py out/records --out out/public/records.json
```

許可fieldのallowlistだけを残し、それ以外のfieldは落とす。残ったテキストからは
エンドポイント、ホスト名、IPアドレス、`/home/<user>`等のパス、アカウント名を既定で
秘匿化する。秘匿化後も漏洩パターンが残る場合は出力せずエラーで停止する（fail-closed）。
秘匿化漏れの検出は`tests/core/test_execution_export.py`と
`scripts/tests/test_export_execution_records.py`のnegative testで固定する。

## トラブル時

- `uv sync`が失敗する場合はsubmoduleが初期化されているか確認する。
- 外部ツールが見つからない場合は`probe_tools.py`の結果を確認する。
- graphやfixtureが不正な場合は入力を修正し、エラーを成功扱いにしない。
- 秘密情報をログ、fixture、graph、commitへ書かない。
