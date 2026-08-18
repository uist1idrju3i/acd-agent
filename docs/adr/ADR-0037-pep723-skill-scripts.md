# ADR-0037: PEP 723によるSkill scriptの依存自己解決

> ステータス: Accepted
> 日付: 2026-08-18

## コンテキスト

ADR-0035／ADR-0036により、pluginはGUI（Local GUI）または`install_plugin()`で
インストールできるが、Skill scriptのうち`acd`パッケージをimportするものは、
実行環境へ事前に`uv pip install "git+https://github.com/uist1idrju3i/acd-agent@<ref>"`
を実行しておく必要があった。plugin installはSkill資材をコピーするだけで
Python環境へは何も導入しないため、ローカル実行（LocalConversation、ホストの
workspace）ではこの事前installを忘れると`ModuleNotFoundError`で失敗する。

PEP 723（inline script metadata）を使うと、script先頭のメタデータブロックに
依存を宣言でき、`uv run --script`が実行時に専用環境を自動作成して依存を解決する。
これによりplugin installだけでSkill scriptが実行可能になる。

## 決定

`acd`をimportするSkill script（`plugins/acd/skills/*/scripts/*.py`）へ
PEP 723メタデータを付与し、事前の`uv pip install`を不要にする。

1. 対象scriptの先頭へ次のブロックを付与する。

   ```python
   # /// script
   # requires-python = ">=3.12"
   # dependencies = [
   #     "acd @ git+https://github.com/uist1idrju3i/acd-agent@<pinned ref>",
   # ]
   # ///
   ```

2. pinned refの単一の正は`plugins/acd/skills/acd-package-ref.txt`（1行、
   40桁commit SHAまたは`v<semver>` tagのみ。ADR-0035の`validate_pinned_ref()`と
   同じ規則）とする。全対象scriptのメタデータはこのrefと一致しなければならない。

3. 対象SkillのSKILL.mdの実行例は`uv run --script <path>`形式とする。
   PEP 723メタデータは`uv run python <path>`では読まれないためである。

4. driftは`scripts/verify_skill_metadata.py`で機械検査する。検査内容は、
   - `acd`をimportする全scriptがPEP 723ブロックを持つこと、
   - dependency文字列がref fileのrefと完全一致すること、
   - refが40桁SHAまたは`v<semver>` tagであること、
   - `requires-python`が`pyproject.toml`と一致すること、
   - 対象SkillのSKILL.mdが対象scriptを`uv run --script`形式で案内していること。
     判定不能・parse失敗はfail-closedとする。
5. 本検査を`scripts/verify_all.py`のstandard stage（fullへ継承）へ追加する。

## 影響

- plugin install（GUI）だけでSkill scriptが実行可能になり、
  `uv pip install`は開発checkout用途を除き不要になる（ADR-0035の手順1は
  ローカルSkill実行の前提としては任意となる。ADR-0035自体は配布経路の
  定義として有効なまま）。
- `uv run --script`は隔離環境でpinned refのgit版`acd`を使う。開発checkoutの
  ローカル変更を使う場合は従来どおり`uv run python <path>`（project環境）を
  使う。CI・pytestはscriptをmoduleとしてimportするため影響を受けない。
- 初回実行時はネットワークアクセスとgit取得・依存build（`cadquery-ocp`等の
  大型依存を含む）が発生する。オフライン環境では初回実行が失敗する
  （fail-closed）。2回目以降はuvのcacheが使われる。
- refはリリース（mainへのmerge）後に存在するcommitを指す必要があるため、
  `acd`本体を変更した場合のref更新は後続の変更で行う。更新手順は
  `docs/operations.md`に記す。ref file・script metadata・SKILL.mdの整合は
  verify経路でdriftとして検出される。
- ゲート実行の正はdigest固定server image（ADR-0026／ADR-0028）のままであり、
  本ADRはローカルSkill実行の導入経路だけを扱う。ホスト実行が合格側Evidenceを
  生成しない契約は変更しない。

## 検証

- `scripts/verify_skill_metadata.py`の検査をpositive／negative双方でテストする
  （ref不一致、ブロック欠落、可変ref、SKILL.md形式逸脱が不合格になること）。
- `uv run python scripts/verify_all.py --stage standard`が新検査を含めて通ること。
