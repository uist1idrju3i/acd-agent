# ADR-0040: plugin hookのplugin root解決方式

> ステータス: Accepted
> 日付: 2026-08-19

## コンテキスト

pinned SDK v1.43.1の`openhands.sdk.hooks.executor.HookExecutor.execute()`は、
command hookへ`OPENHANDS_PROJECT_DIR`（`working_dir`）、`OPENHANDS_SESSION_ID`、
`OPENHANDS_EVENT_TYPE`、`OPENHANDS_TOOL_NAME`だけを渡し、`shell=True`かつ
`cwd=working_dir`で実行する。plugin rootを示す環境変数は存在せず、
`load_hooks()`はhooks.jsonのcommand文字列をそのまま採用するため、SDKがplugin root
へのパス展開を行うこともない。

ACDのhook commandは`${ACD_PLUGIN_ROOT:-$OPENHANDS_PROJECT_DIR/plugins/acd}`規約を
使っていた。明示経路（開発checkout）ではworkspaceがリポジトリなので解決できるが、
ADR-0036のambient install経路では`working_dir`が会話workspace
（`/home/openhands/workspace/project/<conversation-id>`）であり、plugin資材は
`~/.openhands/plugins/installed/acd/`にある。したがってfallbackが存在しないパスを指し、

```text
python3: can't open file '<workspace>/plugins/acd/hooks/scripts/session_start.py'
```

でexit code 2、SessionStartとPreToolUseがblockedとなり、terminalとfile_editorが
すべて拒否された。実機Local GUIで`/acd:doctor`がこの理由により実行不能であることを
確認した。利用者環境で`ACD_PLUGIN_ROOT`を手動設定する回避策は、ADR-0027の単一配布
形態と利用者環境の手動変更禁止に反する。

## 決定

hook commandはPOSIX shellでplugin rootを自己解決する。候補は次の順で、
`hooks/scripts`ディレクトリが実在する最初のものを採用する。

1. `$ACD_PLUGIN_ROOT`（明示的な上書き）
2. `$OPENHANDS_PROJECT_DIR/plugins/acd`（明示経路の開発checkout）
3. `$HOME/.openhands/plugins/installed/acd`（ambient install経路のplugin store）

どの候補も解決できない場合は、標準エラーへ理由を出力してexit code 2で終了する。
SDKはexit code 2をblockedとして扱うため、解決不能はfail-closedのままになる。

`plugins/acd/agents/acd-*.md`のhook宣言は`hooks.json`と同一文字列を保ち、
`acd.openhands.safety.validate_acd_agent_hooks()`の既存driftチェックで担保する。

回帰防止として次を追加する。

- install doctorのrequired check「hook plugin root resolution」が、すべてのplugin
  hook commandに3候補が含まれることを検査する。requiredのため`unknown`も
  fail-closedとする。
- `plugins/acd/hooks/tests/test_hooks.py`が、workspaceにplugin treeが無い環境で
  installed plugin storeから起動できること、および候補がすべて欠落した環境で
  exit code 2になることを確認する。

install doctorのhook invocability checkは、従来の「commandが`${`で始まるか」という
判定ではなく、`.py`参照の直前にinterpreterがあるかで直接実行を判定する。

rationale coverage hook（Stop・PostToolUse）はACD checkoutの
`scripts/check_rationale.py`をworkspace相対で直接実行していたため、ambient install経路の
会話workspaceではscript不在でexit code 2となりStopが常にblockedになった。
`--if-present`はscript内部の分岐であり、Pythonがfile openに失敗する段では作用しない。
したがってrationale hookもplugin同梱script
`plugins/acd/hooks/scripts/check_rationale.py`へ移し、上記の3候補解決を通す。同梱script
は次の意味論を持つ。

- rationale入力（`fixtures/golden-design-1/graph.json`と`rationale.json`）が無い場合は
  not applicableとしてexit code 0。従来の`--if-present`と同じ。
- 入力があるがworkspaceに`scripts/check_rationale.py`が無い場合は、warn-onlyでなければ
  denyでexit code 2としてfail-closedにする。
- 入力とvalidatorが揃う場合はworkspaceのvalidatorを`uv run --project <workspace>`で実行し、
  その終了コードを返す。warn-only（PostToolUse）は従来どおりblockしない。

## 影響

- ambient install経路でSessionStart・PreToolUse・PostToolUse・Stopのplugin hookが
  実行され、`/acd:doctor`と`/acd:gates`がGUIから到達可能になる。
- 明示経路の挙動は変わらない。`ACD_PLUGIN_ROOT`による上書きも従来どおり有効。
- hook policyの停止側の権限は変更しない。解決不能・script不在は引き続きblockedであり、
  合格側へ作用しない。
- SDKがplugin rootをhook環境変数として渡すようになった場合は、候補列の縮小を
  新規ADRで判断する。

## 検証

- `uv run pytest plugins`でhook解決の正常系・installed store経路・fail-closed系を
  確認する。
- install doctorのnegative testで、workspaceのみを指すcommandがrequired checkで
  失敗することを確認する。
- prompt manifestを再生成し、`scripts/verify_agent_prompts.py --check`のdriftを解消する。
- `uv run python scripts/verify_all.py --stage standard`を通す。
