---
name: testing-acd-plugin-install
description: ACD plugin (plugins/acd) のGUI install経路とinstall doctorを実環境で検証する手順。OpenHands SDK install_pluginの落とし穴、installed plugin storeがtest suiteへ与える副作用、fail-closed検証のやり方を含む。
---

# ACD plugin install / doctor の実環境検証

## GUI install（Local GUIのPlugins画面と同じ経路）

`vendor/software-agent-sdk` のSDKをそのまま使う。ブラウザGUIは不要。

```bash
uv run python -c "
from openhands.sdk.plugin.installed import install_plugin, list_installed_plugins
i = install_plugin(source='github:uist1idrju3i/acd-agent', ref='<branch|tag|SHA>',
                   repo_path='plugins/acd', force=True)
print(i.resolved_ref, i.install_path)
print([p.name for p in list_installed_plugins()])"
```

- 正しい install 先は `~/.openhands/plugins/installed/acd/`。
- `repo_path` を省略すると repo 全体が
  `~/.openhands/plugins/installed/acd-agent-<hash>/` へ入り、ACD資材は読み込まれない。
  この壊れたレイアウトの再現にそのまま使える（doctorのinstall locationテストに有用）。
- ローカルパスをsourceにする場合 `repo_path` は使えない
  （`ExtensionFetchError: repo_path is not supported for local extension sources`）。
  ローカル tree を使いたいときは `plugins/acd` を直接 source に渡すか、コピーを作る。

### 落とし穴: ref cache が古い commit を返し得る

`~/.openhands/cache/extensions/` に同じ repo が残っていると、別の `ref` を指定しても
`resolved_ref` が前回の commit のままになることがある。install 後は必ず
`resolved_ref` を `git ls-remote origin <ref>` と突き合わせ、必要なら
`~/.openhands/cache/extensions/` の該当ディレクトリを消してから再実行する。

#### Local GUI では stale cache が無警告で成立し、ref 指定では回避できない

実機 Local GUI の Plugins 画面で観測した挙動（PR #122 検証時）。
**アンインストール → 再インストールしても cache は再取得されない。**

- remote に実在する branch 名を「リファレンス」へ入れても、解決 ref は
  cache 済みの旧 commit のままになる。
- **完全な 40 桁 commit SHA を入れても同じ旧 commit のままになる。**
  つまり「存在しない ref だから fallback した」わけではなく、
  cache が fetch しないため要求 ref が事実上無視される。
- エラー toast も警告も出ず、インストールは成功したように見える。

原因は SDK 側の cache 実装（`openhands.sdk.git.cached_repo`）にある。cache 先は
source URL の sha256 だけで決まり（`get_cache_path`）、plugin manifest の version は
参照されないため `plugin.json` の version を上げても cache は再利用される。cache は
`git clone --depth 1 --branch <初回 ref>` で作られるので `remote.origin.fetch` が
その branch だけを指し、更新時の素の `git fetch origin` では他の branch や commit を
取得できない。`_update_repository` は checkout 失敗を warning
（`Using cached version.`）で飲み込み、古い tree をそのまま install する。
したがって **初回 install の branch 先端を追う更新は成功し**、別 branch や任意 commit への
切り替えは cache を消さない限り成功しない。`main` で install しておけば以後は
「更新」ボタン（`update` は `ref=None` で fetch → `origin/main` へ reset）で追従できる。
これは実機で実測済み: cache purge 後に branch 名 `main` で install した状態で
「更新」を押すと `POST /api/plugins/installed/acd/refresh` が 200 を返し、
解決 ref が新しい main 先端（`git ls-remote` と 40 桁一致）へ移り、再読込後も保持された。
以前観測した「更新」の HTTP 500 と「追加」の HTTP 409 は再現しなかったので、
500 は完全 SHA 指定 cache に限られる可能性が高い（未確認）。

GUI 操作の HTTP status を証拠にしたいときは、クリック前に `window.fetch` と
`XMLHttpRequest.prototype.open` をラップしておき console から status を回収する。
toast は消えるため、status を直接読むほうが確実。

したがって GUI で新しい commit を検証するには、次を検証開始前の前提条件として扱う。

1. `git ls-remote origin <ref>` で remote 側の commit を先に確定させる。
2. install 後に必ず詳細モーダルの「リファレンス」チップを読み、1 と一致するか照合する。
   一致しなければ、それ以降の `/acd:doctor` `/acd:gates` 結果は
   **その commit の証拠にならない**ので実行しない（LLM 課金の無駄を避ける）。
3. 一致しない場合はサーバ側で cache を消す必要がある
   （`~/.openhands/cache/skills/` の該当 clone と
   `~/.openhands/plugins/installed/acd` を削除し、サーバを再起動する）。
   port-forward 専用のトンネル経由では実施できないため、
   サーバ所有者へ依頼する前提でテスト計画を立てる。

チップの hex は等幅小フォントで screenshot からの目視誤読が起きやすい。
`browser` の DOM ダンプに対して `リファレンス[0-9a-f]{7,40}` を grep すると確実に読める。

#### cache purge 後は素直に最新 commit を取得できる

サーバ所有者が `~/.openhands/plugins/installed/acd` と
`~/.openhands/cache/extensions/acd-agent-*` を削除して OpenHands を再起動した後は、
`github:<owner>/<repo>` + `ref` + `path` の指定で解決 ref が remote の HEAD に一致した
（`main` 指定で `git ls-remote origin refs/heads/main` と完全一致を確認）。
purge 後の初回 install だけが確実に新しい commit を掴める窓なので、
その 1 回で doctor と gates を続けて回す計画にすると再依頼を減らせる。

また、検証対象の branch はテスト中に merge されて削除されることがある。
検証開始直前に `git ls-remote origin refs/heads/<branch>` を実行し、
空なら `main` へ切り替えて `git merge-base --is-ancestor <fix-commit> FETCH_HEAD` で
修正 commit が含まれることを確認してから進める。

#### stale cache の機構と、branch 名で install すべき理由（SDK コード根拠）

`vendor/software-agent-sdk` を読むと挙動の理由が説明できるので、
GUI が指定 ref を無視したときは実装バグではなく以下の設計制約を疑う。

- `openhands/sdk/extensions/fetch.py` の `get_cache_path` は
  `sha256(source_url)[:16]` と repo 名だけで cache directory を決め、
  **ref を cache key に含めない**。よって同じ source URL で ref を変えても
  同一 cache directory が再利用される。
- `openhands/sdk/git/cached_repo.py` の `GitHelper.clone` は既定 `depth=1` で
  `--branch <初回ref>` を付ける。shallow clone は指定 branch の tip しか持たないため、
  後から別 commit を checkout すると失敗しうる（docstring 自身が警告している）。
- 失敗しても `_try_fetch` / `_try_checkout_and_reset` が
  `Failed to checkout <ref>: ... Using cached version.` の warning で例外を飲み込むため、
  **install は成功したように見えて古い tree が入る**。これが無警告 stale の正体。
- update 経路は branch 上なら `_try_reset_to_origin(repo_path, current_branch, git)`、
  detached HEAD なら default branch へ recover する。

したがって「GUI の『更新』ボタンで main 先端へ追従させたい」場合、
初回 install のリファレンスは **完全 SHA ではなく branch 名 `main`** にする。
完全 SHA で install すると cache clone が detached HEAD になり update の意味が変わる。

なお解決 ref の表示は要求 ref の反射ではなく
`resolved_ref = git_helper.get_head_commit(repo_cache_path)`（実 HEAD commit）なので、
詳細モーダルの「リファレンス」チップは stale 判定の signal として信頼できる。
plugin 詳細モーダルの下部には `更新` / `アンインストール` / `会話を開始` / `閉じる` があり、
ref 照合だけを行う回は `会話を開始` を押さないこと（LLM 課金が発生する）。
会話を作っていないことは、サイドバーの会話一覧件数が検証前後で不変であることで確認する。

## 落とし穴: installed plugin store が pytest に混ざる

`~/.openhands/plugins/installed/acd/` が存在すると SDK の ambient plugin 読み込みが
テスト中の会話へも効く。古い store（ADR-0039 前の `skills:` 付き AgentDefinition）が
残っていると `ValueError: Skill 'acd-contracts' not found ...` で会話生成が落ちる。
store を最新 ref へ入れ替えるか、HOME を分離して実行する:

```bash
mkdir -p /tmp/isohome && ln -s ~/.local ~/.cache ~/.pyenv /tmp/isohome/ 2>/dev/null
env HOME=/tmp/isohome uv run python scripts/verify_all.py --stage standard
```

## 落とし穴: ambient install の hook script パス解決（ADR-0040 以前の不具合）

SDK の `HookExecutor` は plugin root を環境変数で渡さず、`OPENHANDS_PROJECT_DIR` は
会話 workspace（`.../workspace/project/<conv_id>/`）を指す。ADR-0040 以前の hook command
は `python3 ${ACD_PLUGIN_ROOT:-$OPENHANDS_PROJECT_DIR/plugins/acd}/hooks/scripts/<name>.py`
という形で、GUI ambient install（`~/.openhands/plugins/installed/acd/`）では script が
存在しないパスを指した。結果は

```text
python3: can't open file '.../workspace/project/<conv_id>/plugins/acd/hooks/scripts/session_start.py': [Errno 2] No such file or directory
```

で exit code 2 となり、hook は fail-closed で `SessionStart` と
`PreToolUse(terminal)` / `PreToolUse(file_editor)` を全て block する。
この状態では `/acd:doctor` も `/acd:gates` も command body には到達するが
**ツールを1つも実行できず**、install doctor JSON を得られない。

現行の hook command は POSIX shell で plugin root を自己解決する（`$ACD_PLUGIN_ROOT` →
`$OPENHANDS_PROJECT_DIR/plugins/acd` → `$HOME/.openhands/plugins/installed/acd` の順で
`hooks/scripts` が実在する最初のもの、どれも無ければ exit 2）。

GUI で `/acd:*` を検証する前に、会話冒頭の `🚫フック: SessionStart blocked`
バッジの有無を必ず確認する。出ていたら plugin root が解決できておらず、
それ以降の doctor/gates 結果は「未取得」として扱う。

## 落とし穴: Stop hook の workspace 相対 script（plugin root 解決の対象外）

Stop / PostToolUse の rationale hook は、以前 `uv run python
scripts/check_rationale.py --if-present` のように **plugin root を解決しない workspace
相対 command** だった。plugin 同梱 script ではなく ACD repo checkout 側の `scripts/` を
前提にしているため、GUI ambient install の空 workspace では次で fail-closed になった。

```text
[Stop hook feedback] .../bin/python: can't open file '.../workspace/project/<conv_id>/scripts/check_rationale.py': [Errno 2] No such file or directory
```

`SessionStart` / `PreToolUse` が `ok` でも Stop 段でだけ block されるため、
agent が「script を探す」ループに入り LLM 呼び出しが膨らむ。GUI 検証では
Stop hook のバッジも個別に確認し、ループを検知したら手動停止して課金を抑える。
`--if-present` は script 内部の分岐なので、script 不在は救済されない。

現在は rationale hook も plugin 同梱 script
`plugins/acd/hooks/scripts/check_rationale.py` を 3 候補解決で起動するため、
install doctor の `hook plugin root resolution` check がすべての hook command を評価する。
workspace 相対の外部 script 参照を新たに追加すると doctor の評価対象外になり
`ok` のまま block が起きうるので、hook は必ず plugin 同梱 script から起動する。

実機 GUI で修正を確認する際の合否判定は、会話の DOM 全文を落として
`SessionStart\s*blocked` / `PreToolUse.{0,40}blocked` / `PostToolUse.{0,40}blocked` /
`Stop\s*blocked` / `can't open file` / `acd plugin root unresolved` /
`No such file or directory` を negative check として grep し、
`SessionStart ok` / `PreToolUse ok` / `PostToolUse ok` / `Stop ok` の出現数を
positive check として数えるのが確実（バッジは折り畳まれて screenshot に写らないことがある）。
`Stop ok` は agent の応答が完全に終わってから描画されるので、
途中で手動停止すると Stop hook の証拠が取れない。空 workspace の `/acd:gates` は
設計ファイルを探索するため 5〜7 分かかる場合があり、完走させる余裕を見ておく。

## install doctor の検証

実行は隔離環境を使わず `python3 <path>` で直接行う（`uv run --script` は利用者環境を
誤認するため使わない）。plugin root は `Path(__file__).resolve().parents[3]`。

```bash
python3 plugins/acd/skills/acd-install-doctor/scripts/install_doctor.py                     # 開発checkout
python3 ~/.openhands/plugins/installed/acd/skills/acd-install-doctor/scripts/install_doctor.py  # GUI install
```

- `status`: `ok` / `degraded` / `failed`、exit code は `failed` のときだけ 1。
- required check の `fail`/`unknown` は fail-closed で `failed`。
- optional（docker到達性、hook invocability）の失敗は `degraded`（exit 0）。
  ホスト EDA ツール（`kicad-cli`/`freerouting`）の不在は status を下げない。
- commit 済み hook script は executable bit / shebang を持たないため、健全な環境でも
  `degraded` が期待値になり得る。実資材の permission は書き換えないこと。

### fail-closed を確かめる（必ず一時コピーに対して行う）

`cp -a ~/.openhands/plugins/installed/acd /tmp/<case>/acd` してから壊す。有効な例:
`.plugin/plugin.json` の `name` 改変、`agents/prompt-manifest.json` の `asset_hash` /
`canonical_hash` の1文字改変や削除、manifest への無害キー追加（canonical hash不一致）、
`skills/acd-package-ref.txt` を別 ref へ、`agents/` や `commands/` を空に、
`hooks/hooks.json` を不正JSONに、prompt-manifest 未登録の `agents/acd-*.md` 追加。
環境側は `env -i PATH=<最小dir>` で `uv` を外す（PATH最小化で python が 3.10 に落ちて
判定が混ざるので、python3.12 の symlink を張った専用 PATH dir を作る）。
docker 不到達は `DOCKER_HOST=tcp://127.0.0.1:1` で再現できる。
hook invocability は shebang のみ／exec bit のみ欠けたコピーで両方 fail することを確認する。

終了後は一時コピーと余分な store エントリを削除し、`<store>/acd` を正しい
`repo_path` 付き install に戻し、`git status --short` と
`ls -l plugins/acd/hooks/scripts` で working tree 無変更を確認する。

## Devin Secrets Needed

なし（public repo の匿名 clone とローカルツールのみで完結する）。

## ambient installed plugin をGUI越しに最新へ更新する（実機VPSで確認）

GUIの「プラグイン」ボタンは会話へ追加する公開plugin一覧であり、ambient install
（`~/.openhands/plugins/installed/acd`）の更新導線ではない。tunnel越しでも
agent-serverのinstall APIを直接叩けば正規経路で更新できる。

```bash
curl -sS -X POST http://127.0.0.1:8000/api/plugins/install \
  -H 'content-type: application/json' \
  -d '{"source":"github:uist1idrju3i/acd-agent","ref":"main","repo_path":"plugins/acd","force":true}'
```

- 更新後は `resolved_ref` を `git ls-remote origin main` と40桁照合する。
- store配下のファイルを手で書き換えてはならない（検証の証拠にならない）。

## doctor JSON全文はevent logから取るのが確実

GUIの折り畳みを展開せずに、会話のevent JSONを直接grepする。

```bash
sudo grep -l "workspace firmware prerequisites" \
  /home/openhands/.openhands/agent-canvas/dev_conversations/<conv-id>/events/event-*.json
```

## 既存成果物を壊さないための workspace 分離

`/acd:init` は `--workspace <名前>` を受けるので、検証では既存の `acd-workspace` を
避けて別名（例 `acd-workspace-verify`）を使い、既存workspaceのmtimeが変化しないことを
確認する。GUI右パネルのファイルツリーは新規workspaceを即時表示しないことがあるため、
実体の有無は read-only の `sudo ls` で確認する。

## 期待digestは作業ツリーではなく origin/main から取る

`docker/image-digests.json` は作業ツリー側が古いことがある。検証対象revisionの期待値は
`git show origin/main:docker/image-digests.json` から取得する。
