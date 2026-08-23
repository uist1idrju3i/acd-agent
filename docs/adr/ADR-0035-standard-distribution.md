# ADR-0035: SDK標準機構による配布とインストール

> ステータス: Accepted
> 日付: 2026-08-18

## コンテキスト

これまでのインストールは`git clone --recurse-submodules`と`uv sync`を前提とし、
利用者のOpenHands環境へACDを導入する手順が重かった。pinned SDK v1.43.1は拡張の
標準配布機構として、`PluginSource`／`Plugin.fetch()`によるgit取得（resolved commit
SHAへのピン留めと`~/.openhands/cache/plugins/`へのキャッシュ）を提供する。また
`openhands-sdk`、`openhands-tools`、`openhands-workspace`のv1.43.1はPyPIへ公開済み
である。ACD側には既に`acd_plugin_source(ref)`と`validate_pinned_ref()`（40桁SHAまたは
`v<semver>` tagのみ許可）が存在する。

## 決定

インストール経路をSDK標準機構へ寄せ、利用者操作を次の2段へ縮める。

1. Pythonパッケージ`acd`をgit経由で導入する（clone不要）。

   ```bash
   uv pip install "git+https://github.com/uist1idrju3i/acd-agent@<tag or SHA>"
   ```

2. pluginはSDKの`Plugin.fetch()`／`PluginSource`で取得する。refは
   `validate_pinned_ref()`が許可する不変refに限る。

   ```python
   from openhands.sdk.plugin import Plugin
   from acd.openhands.distribution import acd_plugin_source

   source = acd_plugin_source("<40桁SHA または v<semver> tag>")
   plugin = Plugin.load(Plugin.fetch(
       source.source, ref=source.ref, repo_path=source.repo_path))
   ```

これを成立させるため、次を実施する。

- `pyproject.toml`の`[project.dependencies]`で`openhands-sdk==1.43.1`、
  `openhands-tools==1.43.1`、`openhands-workspace==1.43.1`をPyPI版へピン留めする。
  開発checkoutでは`[tool.uv.sources]`のvendored submodule pathが引き続き優先され、
  submoduleが開発時の正であることは変わらない。pip/uvのgit installでは
  `tool.uv.sources`が適用されないため、PyPIのpinned版で解決される。
- wheelへ`docker/image-digests.json`をbuild時にpackage dataとして同梱する
  （`acd/openhands/image-digests.json`）。lockの正はrepositoryのtracked fileであり、
  wheel内のコピーはbuild時点の投影である。gitへ複製ファイルを追加しない。
- `acd.openhands.image_lock`へ既定lock解決を追加する。repository checkoutの
  `docker/image-digests.json`が与えられない場合、packaged copyを
  `importlib.resources`で読む。どちらも解決できない場合はfail-closedで停止する。
  検証規則（digest形式、placeholder拒否、未設定entry拒否）は変更しない。
- console script `acd-locked-image`を追加し、installed環境からもlock記録済みの
  `image@digest`を取得できるようにする（`scripts/print_locked_image.py`と同じ
  失敗時exit code 2の契約）。

## 影響

- ゲート実行の正は従来どおりlock記録済みのdigest固定server image
  （`DockerWorkspace(server_image=...)`）であり、authoritative Evidence契約
  （ADR-0026／ADR-0028）は変更しない。本ADRは配布・インストール経路だけを扱う。
- plugin refの可変ref（branch名、短縮SHA、空文字）は引き続き拒否される。
  fetchのresolved SHAはconversation persistenceの再現に使われる。
- SDK submodule版とPyPI pinの版は同一（v1.43.1）でなければならない。submodule更新時は
  `pyproject.toml`のpinを同じ変更で更新する。
- wheel内lockはbuild時点のsnapshotである。lock更新後に配布物を使う場合は
  再installが必要であり、runnerのdigest検証がfail-closedの最終防衛線となる。

## 検証

- packaged lockの解決と、lock欠落・不正時のfail-closedをテストする。
- `uv build`で生成したwheelに`acd/openhands/image-digests.json`が含まれ、
  tracked lockと同一内容であることを検査する。
- `validate_pinned_ref`の既存negative test（branch名、短縮SHA、`ref=None`）を維持する。
