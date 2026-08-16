# ADR-0001: uv workspaceによるmonorepo構成

> ステータス: Accepted
> 日付: 2026-08-11

## コンテキスト

ACDは設計グラフ契約、コアロジック、イベント、外部ツールadapter、実行ランタイムを
一貫して開発する必要がある。OpenHands SDKはsubmodule（`vendor/software-agent-sdk`）、
Agent Canvasソースはsubmodule（`vendor/openhands`）として取り込み済みであり、
いずれもソース自体は変更しない。

## 決定

- リポジトリ直下を`uv` workspaceのルートとし、`packages/*`をworkspace memberとする。
- パッケージは依存の少ない順に`acd-schema`、`acd-core`、`acd-events`、`acd-tools`、
  `acd-runtime`の5つに分割する。粒度は[`docs/architecture.md`](../architecture.md)を正とする。
- `openhands-sdk`はworkspace sourceとしてsubmoduleのパスを参照し、PyPIから取得しない。
- lint（ruff）、型検査（pyright strict）、テスト（pytest）、文書検証
  （`scripts/verify_docs.py`）の設定はルート`pyproject.toml`に一元化する。
- `schemas/`（機械可読契約の正）、`fixtures/`（tracked golden／negative fixture）、
  `plugins/acd/`（OpenHands plugin骨格）、`scripts/`をルート直下に置く。

## 影響

- ローカルとCIは同一コマンド（`uv sync` → `uv run ruff check` → `uv run pyright` →
  `uv run pytest` → `uv run python scripts/verify_docs.py`）で検証できる。
- SDKの版はsubmodule commitで固定され、SDK更新は明示的なsubmodule更新となる。
- パッケージ間の依存は`acd-schema`を底とする一方向に保つ。循環依存は導入しない。
