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

## 落とし穴: installed plugin store が pytest に混ざる

`~/.openhands/plugins/installed/acd/` が存在すると SDK の ambient plugin 読み込みが
テスト中の会話へも効く。古い store（ADR-0039 前の `skills:` 付き AgentDefinition）が
残っていると `ValueError: Skill 'acd-contracts' not found ...` で会話生成が落ちる。
store を最新 ref へ入れ替えるか、HOME を分離して実行する:

```bash
mkdir -p /tmp/isohome && ln -s ~/.local ~/.cache ~/.pyenv /tmp/isohome/ 2>/dev/null
env HOME=/tmp/isohome uv run python scripts/verify_all.py --stage standard
```

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
