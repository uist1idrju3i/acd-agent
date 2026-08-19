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
