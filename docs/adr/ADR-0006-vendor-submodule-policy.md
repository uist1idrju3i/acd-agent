# ADR-0006: SDK vendor submoduleの更新方針

> ステータス: Accepted
> 日付: 2026-08-11

## 決定

`vendor/software-agent-sdk`はタグ由来のcommit SHAへ固定する。SDK v1.42.1は
`167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497`であり、ACDから実行時にimportする箇所は
44箇所あるため、submoduleを単なる文書用vendorとして扱わない。

更新時は一次情報（公式release、tag、commit、変更履歴）を確認し、使用APIと破壊的変更を
記録する。次に`uv lock`を実行し、lint、型検査、テスト、文書検証を行う。最後に
`docs/dependency-notes.md`と本書、`AGENTS.md`の版表記を同じ変更で更新する。

Dockerfileとprobeで固定する外部ツール版は運用上のpinとして扱い、別の版pin manifestを
追加しない。submoduleソース自体は変更せず、更新は明示的なcommit移動だけで行う。

## 影響

SDK APIの採否は[`openhands-sdk-capabilities.md`](../openhands-sdk-capabilities.md)へ記録する。
submodule更新に伴い、実行時import、`uv.lock`、生成物、文書の整合を一つの変更として
検証する。`vendor/openhands/`はSDK submoduleではなく、追跡・追加しない。
