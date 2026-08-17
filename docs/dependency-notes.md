# 依存関係ノート

> ステータス: Accepted
> 対象: OpenHands Software Agent SDK v1.42.1

## 対応表

| 依存 | ACD側の利用 | 版・固定 | 一次情報 |
|---|---|---|---|
| OpenHands SDK | Tool、hooks、critic、Conversation、plugin、workspace | submodule v1.42.1 / `167c1f924ac8a8acbeb0432bf9b1fcf77d5c2497` | [release](https://github.com/OpenHands/software-agent-sdk/releases/tag/v1.42.1) |
| OpenHands agent-server | Conversation運搬、REST、WebSocket | v1.42.1 | `vendor/software-agent-sdk/openhands-agent-server/` |
| KiCad | ERC、DRC、出力、測定 | 10系へ移行予定。現行Dockerfileは9系 | [KiCad 10](https://docs.kicad.org/10.0/) |
| FreeRouting | routing | 2.1.0、SHA-256確認 | [release](https://github.com/freerouting/freerouting) |
| Docker | ゲート隔離 | digest固定を次フェーズで正とする | `DockerWorkspace` source |

## SDK更新契約

SDK更新時は公式releaseとtag由来commitを確認し、公開APIと破壊的変更を棚卸しする。続いて
`uv lock`、全検証、capabilities、AGENTS、ADR、ここを同じ変更で更新する。SDKの採否は
[`openhands-sdk-capabilities.md`](openhands-sdk-capabilities.md)、submodule方針は
[`ADR-0006`](adr/ADR-0006-vendor-submodule-policy.md)を参照する。

## 重要な実装事実

`DockerWorkspace`の`server_image`は`str | None`で、`get_image()`が値をそのままDocker runへ
渡す。digest形式を受け取れる構造はあるが、SDK自身のdigest検証は確認できない。
agent-serverのhooksはworkspace設定を返す`POST /api/hooks`であり、server直接APIへの自動適用は
未確認である。delegateは`spawn`と`delegate`、workflowは`async def main(wf)`と安全なAPIだけを
提供し、決定論的ゲートの判定器ではない。
